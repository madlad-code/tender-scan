"""SQLite storage for procurement notices.

Schema versions (PRAGMA user_version):
  0/1 — legacy: estimated_value stored as TEXT ("18000000 SEK"), deadlines in
        TED's mixed zone formats ("2026-08-20Z" vs "2026-09-03+02:00").
  2   — estimated_value REAL + currency TEXT, deadlines normalized to UTC
        ISO-8601, per-lot values in lots_json.
  3   — utilization tables next to `notices`, which is left exactly as it was:
        framework_agreements, award_winners, supplier_payments, foia_requests
        and fx_rates. Purely additive, so the migration only creates tables.
  5   — award_winners.award_date, so a prospect list can be sorted by when a
        supplier was last awarded a place rather than by a proxy.
  4   — buyer identity, which is what keeps an unrelated payment out of a
        framework's observed spend:
          * supplier_payments.payer_orgnr — attribution by organisationsnummer
            rather than by display name;
          * framework_buyers — every buyer a notice names, since 7 of the 137
            cached notices name between 2 and 16, and that count is the honest
            denominator for the coverage ratio;
          * framework_agreements.buyer_is_cpb — set when the buyer is a known
            central purchasing body, whose entitled organisations TED does not
            publish, so coverage has no denominator at all.

Legacy databases are migrated automatically on open (a `<db>.bak` copy of the
file is written first). Rows are re-parsed from their stored raw JSON, so the
migration applies the exact same parsing rules as a fresh scan.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tender_scan.models import Lot, Notice, normalize_deadline, parse_lots, parse_notice
from tender_scan.orgnr import normalize_orgnr
from tender_scan.records import (
    AwardWinner,
    FoiaRequest,
    FrameworkAgreement,
    MunicipalContract,
    SupplierPayment,
)

# The database lives under data/, which is gitignored. The old default was
# "tender_scan.db" relative to the working directory, which meant a command run
# from the repo root silently created an empty database beside the code and
# reported zero rows instead of failing — the worst possible way to be wrong.
DEFAULT_DB_PATH = "data/tender_scan.db"

SCHEMA_VERSION = 5

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS notices (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    buyer           TEXT,
    cpv             TEXT,
    deadline        TEXT,
    estimated_value REAL,
    currency        TEXT,
    lots_json       TEXT NOT NULL DEFAULT '[]',
    url             TEXT,
    raw_json        TEXT NOT NULL
);
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS framework_agreements (
    notice_id            TEXT PRIMARY KEY,
    buyer_name           TEXT,
    buyer_orgnr          TEXT,
    title                TEXT,
    is_framework         INTEGER NOT NULL DEFAULT 0,
    cap_value_sek        INTEGER,
    estimated_value_sek  INTEGER,
    cap_source           TEXT,      -- 'eforms_field' | 'document_regex' | 'manual'
    cap_confidence       REAL,
    start_date           TEXT,
    end_date             TEXT,
    max_duration_months  INTEGER,
    cpv_main             TEXT,
    buyer_is_cpb         INTEGER NOT NULL DEFAULT 0,
    raw_excerpt          TEXT,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS award_winners (
    notice_id         TEXT NOT NULL,
    supplier_name     TEXT NOT NULL,
    supplier_orgnr    TEXT,
    lot_id            TEXT NOT NULL,
    rank              INTEGER,
    awarded_value_sek INTEGER,
    match_confidence  REAL,
    award_date        TEXT,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (notice_id, supplier_name, lot_id)
);

CREATE TABLE IF NOT EXISTS supplier_payments (
    payer_org      TEXT NOT NULL,
    payer_orgnr    TEXT,
    supplier_name  TEXT NOT NULL,
    supplier_orgnr TEXT,
    amount_sek     INTEGER NOT NULL,
    period_year    INTEGER NOT NULL,
    period_month   INTEGER,
    source         TEXT NOT NULL,   -- 'open_data' | 'foia' | 'annual_report'
    source_url     TEXT,
    row_hash       TEXT NOT NULL,
    ingested_at    TEXT NOT NULL,
    -- What the money bought and which unit spent it, where the ledger says so.
    -- Also added by _add_missing_columns for databases that predate them; both
    -- paths are needed, and a fresh database that only had the ALTER would have
    -- worked on this machine and failed on every new clone.
    account        TEXT,
    cost_centre    TEXT,
    PRIMARY KEY (row_hash)
);

CREATE TABLE IF NOT EXISTS framework_buyers (
    notice_id   TEXT NOT NULL,
    buyer_orgnr TEXT NOT NULL,
    buyer_name  TEXT,
    PRIMARY KEY (notice_id, buyer_orgnr)
);

CREATE TABLE IF NOT EXISTS foia_requests (
    id                    INTEGER PRIMARY KEY,
    target_org            TEXT NOT NULL,
    target_email          TEXT,
    framework_notice_id   TEXT,
    sent_at               TEXT,
    reminder_1_at         TEXT,
    reminder_2_at         TEXT,
    decision_requested_at TEXT,
    status                TEXT NOT NULL,
    response_received_at  TEXT,
    response_file_path    TEXT,
    notes                 TEXT
);

CREATE TABLE IF NOT EXISTS fx_rates (
    currency     TEXT NOT NULL,
    rate_date    TEXT NOT NULL,
    sek_per_unit TEXT NOT NULL,
    source       TEXT,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (currency, rate_date)
);

CREATE TABLE IF NOT EXISTS municipal_contracts (
    buyer_org      TEXT NOT NULL,
    buyer_orgnr    TEXT,
    contract_ref   TEXT,
    title          TEXT,
    category       TEXT,
    supplier_name  TEXT NOT NULL,
    supplier_orgnr TEXT,
    start_date     TEXT,
    end_date       TEXT,
    rank           INTEGER,
    cap_value_sek  INTEGER,
    source         TEXT NOT NULL,   -- 'foia' | 'open_data'
    source_file    TEXT,
    row_hash       TEXT NOT NULL,
    ingested_at    TEXT NOT NULL,
    PRIMARY KEY (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_award_winners_orgnr ON award_winners (supplier_orgnr);
CREATE INDEX IF NOT EXISTS idx_payments_orgnr ON supplier_payments (supplier_orgnr);
CREATE INDEX IF NOT EXISTS idx_payments_payer ON supplier_payments (payer_org);
CREATE INDEX IF NOT EXISTS idx_payments_payer_orgnr ON supplier_payments (payer_orgnr);
CREATE INDEX IF NOT EXISTS idx_contracts_buyer ON municipal_contracts (buyer_org);
CREATE INDEX IF NOT EXISTS idx_contracts_orgnr ON municipal_contracts (supplier_orgnr);
"""

_SCHEMA = _SCHEMA_V2 + _SCHEMA_V3

# A cap this weakly evidenced is shown to a human before it is published.
REVIEW_CONFIDENCE = 0.7

# Legacy estimated_value text, e.g. "18000000 SEK" or "2500000.5".
_LEGACY_VALUE = re.compile(r"^\s*(?P<amount>\d+(?:\.\d+)?)\s*(?P<currency>[A-Z]{3})?\s*$")

_FRAMEWORK_COLUMNS = (
    "notice_id",
    "buyer_name",
    "buyer_orgnr",
    "title",
    "is_framework",
    "cap_value_sek",
    "estimated_value_sek",
    "cap_source",
    "cap_confidence",
    "start_date",
    "end_date",
    "max_duration_months",
    "cpv_main",
    "buyer_is_cpb",
    "raw_excerpt",
    "updated_at",
)

_WINNER_COLUMNS = (
    "notice_id",
    "supplier_name",
    "supplier_orgnr",
    "lot_id",
    "rank",
    "awarded_value_sek",
    "match_confidence",
    "award_date",
    "updated_at",
)

_FOIA_COLUMNS = (
    "target_org",
    "target_email",
    "framework_notice_id",
    "sent_at",
    "reminder_1_at",
    "reminder_2_at",
    "decision_requested_at",
    "status",
    "response_received_at",
    "response_file_path",
    "notes",
)

_CONTRACT_COLUMNS = (
    "buyer_org",
    "buyer_orgnr",
    "contract_ref",
    "title",
    "category",
    "supplier_name",
    "supplier_orgnr",
    "start_date",
    "end_date",
    "rank",
    "cap_value_sek",
    "source",
    "source_file",
    "row_hash",
    "ingested_at",
)

_PAYMENT_COLUMNS = (
    "payer_org",
    "payer_orgnr",
    "supplier_name",
    "supplier_orgnr",
    "amount_sek",
    "period_year",
    "period_month",
    "source",
    "source_url",
    "row_hash",
    "ingested_at",
    "account",
    "cost_centre",
)


class Storage:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or os.environ.get("TENDER_SCAN_DB", DEFAULT_DB_PATH))
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._migrate_if_needed()
        # Columns first, then the schema script: it creates an index on
        # supplier_payments.payer_orgnr, which fails outright on a database
        # whose table predates that column.
        self._add_missing_columns()
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def connection(self) -> sqlite3.Connection:
        """The raw handle, for modules that own their own tables (fx.py) and for views."""
        return self._conn

    # -- migration ---------------------------------------------------------

    def _migrate_if_needed(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        table = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'notices'"
        ).fetchone()
        if table is None:
            return  # fresh database: schema is created right after
        self._backup_file()
        if version < 2:
            self._migrate_v1_to_v2()
        # v2 -> v3 adds tables only; the CREATE TABLE IF NOT EXISTS run in
        # __init__ is the whole migration, and `notices` is never touched.

    def _add_missing_columns(self) -> None:
        """Add columns that `CREATE TABLE IF NOT EXISTS` cannot add to a table
        that already exists.

        Run on every open rather than gated on the version number: a database
        stamped with the current version by an older build of that version
        would otherwise never gain them, and `PRAGMA table_info` is cheap and
        idempotent. Existing payment rows keep a NULL payer_orgnr rather than
        having one inferred from their payer_org text — reload the source to
        fill them in, since a guessed buyer identity is exactly what this
        column exists to prevent.
        """
        for table, column, ddl in (
            ("supplier_payments", "payer_orgnr", "TEXT"),
            ("framework_agreements", "buyer_is_cpb", "INTEGER NOT NULL DEFAULT 0"),
            ("award_winners", "award_date", "TEXT"),
            # Huddinge's ledger names the account and the cost centre behind
            # every line. Borås and Bjurholm do not, so both stay NULL there.
            # They join the aggregation key, which makes Huddinge's grain
            # finer without changing anyone else's: a query that sums by
            # supplier and month returns exactly what it returned before.
            ("supplier_payments", "account", "TEXT"),
            ("supplier_payments", "cost_centre", "TEXT"),
        ):
            columns = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if columns and column not in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        self._conn.commit()

    def _backup_file(self) -> None:
        source = Path(self.db_path)
        if source.is_file():
            shutil.copy2(source, source.with_name(source.name + ".bak"))

    def _migrate_v1_to_v2(self) -> None:
        old_rows = self._conn.execute("SELECT * FROM notices").fetchall()
        self._conn.execute("ALTER TABLE notices RENAME TO notices_legacy")
        self._conn.executescript(_SCHEMA_V2)
        for row in old_rows:
            self.upsert(_migrate_row(row))
        self._conn.execute("DROP TABLE notices_legacy")
        self._conn.commit()

    # -- CRUD --------------------------------------------------------------

    def upsert(self, notice: Notice) -> None:
        self._conn.execute(
            """
            INSERT INTO notices
                (id, title, buyer, cpv, deadline, estimated_value, currency,
                 lots_json, url, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                buyer = excluded.buyer,
                cpv = excluded.cpv,
                deadline = excluded.deadline,
                estimated_value = excluded.estimated_value,
                currency = excluded.currency,
                lots_json = excluded.lots_json,
                url = excluded.url,
                raw_json = excluded.raw_json
            """,
            (
                notice.id,
                notice.title,
                notice.buyer,
                notice.cpv,
                notice.deadline,
                notice.estimated_value,
                notice.currency,
                json.dumps(
                    [
                        {"estimated_value": lot.estimated_value, "currency": lot.currency}
                        for lot in notice.lots
                    ]
                ),
                notice.url,
                json.dumps(notice.raw, ensure_ascii=False),
            ),
        )
        self._conn.commit()

    def list_notices(self) -> list[Notice]:
        rows = self._conn.execute(
            "SELECT * FROM notices ORDER BY deadline IS NULL, deadline, id"
        ).fetchall()
        return [
            Notice(
                id=row["id"],
                title=row["title"],
                buyer=row["buyer"],
                cpv=row["cpv"],
                deadline=row["deadline"],
                estimated_value=row["estimated_value"],
                currency=row["currency"],
                lots=tuple(
                    Lot(estimated_value=lot["estimated_value"], currency=lot["currency"])
                    for lot in json.loads(row["lots_json"])
                ),
                url=row["url"],
                raw=json.loads(row["raw_json"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]

    # -- framework agreements ----------------------------------------------

    def upsert_framework(self, fw: FrameworkAgreement) -> None:
        columns = ", ".join(_FRAMEWORK_COLUMNS)
        placeholders = ", ".join("?" for _ in _FRAMEWORK_COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _FRAMEWORK_COLUMNS[1:])
        self._conn.execute(
            f"INSERT INTO framework_agreements ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(notice_id) DO UPDATE SET {updates}",
            _framework_values(fw),
        )
        self._conn.commit()

    def get_framework(self, notice_id: str) -> FrameworkAgreement | None:
        row = self._conn.execute(
            "SELECT * FROM framework_agreements WHERE notice_id = ?", (notice_id,)
        ).fetchone()
        return _framework_from_row(row) if row is not None else None

    def list_frameworks(self, needs_review: bool = False) -> list[FrameworkAgreement]:
        """All framework rows, or only the ones a human still has to look at.

        A row needs review when the cap is missing outright, when it was
        extracted with weak evidence, or when it carries no confidence at all.
        The last case matters: the extractor always records a confidence
        alongside a cap, so a NULL there means the row came from somewhere
        else and is unexplained. `frameworks.needs_review` applies the same
        rule in Python, and a test asserts the two agree.
        """
        query = "SELECT * FROM framework_agreements"
        params: tuple[Any, ...] = ()
        if needs_review:
            query += " WHERE COALESCE(cap_confidence, -1) < ? OR cap_value_sek IS NULL"
            params = (REVIEW_CONFIDENCE,)
        query += " ORDER BY notice_id"
        return [_framework_from_row(row) for row in self._conn.execute(query, params)]

    def replace_framework_buyers(
        self, notice_id: str, buyers: Iterable[tuple[str, str | None]]
    ) -> None:
        """Make the stored buyers of one notice exactly `buyers` — (orgnr, name)."""
        with self._conn:
            self._conn.execute("DELETE FROM framework_buyers WHERE notice_id = ?", (notice_id,))
            self._conn.executemany(
                "INSERT OR IGNORE INTO framework_buyers (notice_id, buyer_orgnr, buyer_name) "
                "VALUES (?, ?, ?)",
                [(notice_id, orgnr, name) for orgnr, name in buyers if orgnr],
            )

    def list_framework_buyers(self, notice_id: str) -> list[tuple[str, str | None]]:
        return [
            (row["buyer_orgnr"], row["buyer_name"])
            for row in self._conn.execute(
                "SELECT buyer_orgnr, buyer_name FROM framework_buyers "
                "WHERE notice_id = ? ORDER BY buyer_orgnr",
                (notice_id,),
            )
        ]

    # -- award winners -----------------------------------------------------

    def replace_winners(self, notice_id: str, winners: Iterable[AwardWinner]) -> None:
        """Make the stored winners of one notice exactly `winners`.

        A re-scan may drop a supplier (a corrected notice, a better parse), so
        this is delete-then-insert rather than upsert. Both statements run in
        one transaction: a failure must not leave the notice with no winners.
        """
        columns = ", ".join(_WINNER_COLUMNS)
        placeholders = ", ".join("?" for _ in _WINNER_COLUMNS)
        with self._conn:
            self._conn.execute("DELETE FROM award_winners WHERE notice_id = ?", (notice_id,))
            self._conn.executemany(
                f"INSERT INTO award_winners ({columns}) VALUES ({placeholders})",
                [_winner_values(w) for w in winners],
            )

    def list_winners(self, notice_id: str | None = None) -> list[AwardWinner]:
        query = "SELECT * FROM award_winners"
        params: tuple[Any, ...] = ()
        if notice_id is not None:
            query += " WHERE notice_id = ?"
            params = (notice_id,)
        query += " ORDER BY notice_id, lot_id, supplier_name"
        return [_winner_from_row(row) for row in self._conn.execute(query, params)]

    # -- foia requests ------------------------------------------------------

    def insert_foia(self, request: FoiaRequest) -> int:
        """Log a new request and return its id."""
        columns = ", ".join(_FOIA_COLUMNS)
        placeholders = ", ".join("?" for _ in _FOIA_COLUMNS)
        with self._conn:
            cursor = self._conn.execute(
                f"INSERT INTO foia_requests ({columns}) VALUES ({placeholders})",
                _foia_values(request),
            )
        return int(cursor.lastrowid or 0)

    def update_foia(self, request_id: int, **fields: object) -> None:
        """Update named columns of one request. Unknown columns are rejected."""
        unknown = set(fields) - set(_FOIA_COLUMNS)
        if unknown:
            raise ValueError(f"unknown foia_requests columns: {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{column} = ?" for column in fields)
        with self._conn:
            self._conn.execute(
                f"UPDATE foia_requests SET {assignments} WHERE id = ?",
                (*fields.values(), request_id),
            )

    def get_foia(self, request_id: int) -> FoiaRequest | None:
        row = self._conn.execute(
            "SELECT * FROM foia_requests WHERE id = ?", (request_id,)
        ).fetchone()
        return _foia_from_row(row) if row is not None else None

    def list_foia(self, status: str | None = None) -> list[FoiaRequest]:
        query = "SELECT * FROM foia_requests"
        params: tuple[Any, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY id"
        return [_foia_from_row(row) for row in self._conn.execute(query, params)]

    # -- supplier payments -------------------------------------------------

    def insert_payments(self, payments: Iterable[SupplierPayment]) -> int:
        """Add payment rows that are not already stored; returns how many were added.

        Re-running a loader over the same source file inserts nothing, because
        `row_hash` is the primary key and identical rows collide on it.
        """
        rows = [_payment_values(p) for p in payments]
        if not rows:
            return 0
        columns = ", ".join(_PAYMENT_COLUMNS)
        placeholders = ", ".join("?" for _ in _PAYMENT_COLUMNS)
        before = self._conn.total_changes
        with self._conn:
            self._conn.executemany(
                f"INSERT OR IGNORE INTO supplier_payments ({columns}) VALUES ({placeholders})",
                rows,
            )
        return self._conn.total_changes - before

    def insert_contracts(self, contracts: Iterable[MunicipalContract]) -> int:
        """Add catalogue rows that are not already stored; returns how many were added.

        Same idempotency contract as `insert_payments`: `row_hash` is the
        primary key, so re-reading the same delivered file adds nothing.
        """
        rows = [_contract_values(c) for c in contracts]
        if not rows:
            return 0
        columns = ", ".join(_CONTRACT_COLUMNS)
        placeholders = ", ".join("?" for _ in _CONTRACT_COLUMNS)
        before = self._conn.total_changes
        with self._conn:
            self._conn.executemany(
                f"INSERT OR IGNORE INTO municipal_contracts ({columns}) VALUES ({placeholders})",
                rows,
            )
        return self._conn.total_changes - before

    def list_contract_buyers(self) -> list[str]:
        """Every municipality whose catalogue is stored, alphabetically."""
        return [
            row[0]
            for row in self._conn.execute(
                "SELECT DISTINCT buyer_org FROM municipal_contracts ORDER BY buyer_org"
            )
        ]


# -- row identity ------------------------------------------------------------


def payment_row_hash(
    payer_org: str,
    supplier_name: str,
    supplier_orgnr: str | None,
    amount_sek: int,
    period_year: int,
    period_month: int | None,
    source_url: str | None = None,
    account: str | None = None,
    cost_centre: str | None = None,
) -> str:
    """The stable identity of one payment row, so re-ingesting a file is a no-op.

    sha256 over these six values joined by U+001F:

        payer_org | supplier_orgnr or supplier_name | amount_sek |
        period_year | period_month | source_url

    Text is case-folded with its whitespace collapsed, and the supplier is
    keyed on the canonical `NNNNNN-NNNN` orgnr whenever the value validates —
    falling back to the name, since an orgnr that fails Luhn is not one. So
    the same payment hashes identically no matter what order the columns came
    in, how it was padded, or whether the orgnr was hyphenated. A different
    amount, period or payer does not.

    Keep this definition frozen: changing it re-ingests every historical row.
    """
    parts = (
        _norm_text(payer_org),
        normalize_orgnr(supplier_orgnr) or _norm_text(supplier_name),
        str(int(amount_sek)),
        str(int(period_year)),
        "" if period_month is None else str(int(period_month)),
        _norm_text(source_url),
    )
    # Appended only when the ledger carries them, so every row hashed before
    # these columns existed still hashes to the same value and no historical
    # row is re-ingested. Where they do exist they must be in the hash: one
    # supplier can be paid the same amount in the same month against two
    # different accounts, and without them the second row would silently
    # collide with the first and be dropped.
    if account is not None or cost_centre is not None:
        parts = (*parts, _norm_text(account), _norm_text(cost_centre))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def contract_row_hash(
    buyer_org: str,
    contract_ref: str | None,
    supplier_name: str,
    supplier_orgnr: str | None,
    start_date: str | None,
    end_date: str | None,
) -> str:
    """The stable identity of one catalogue row.

    Keyed on the contract reference plus the supplier plus the term, because a
    ranked framework repeats one reference across its suppliers and a renewed
    contract repeats reference *and* supplier with a new end date. Dropping
    either would silently collapse rows that are genuinely different places.
    """
    parts = (
        _norm_text(buyer_org),
        _norm_text(contract_ref),
        normalize_orgnr(supplier_orgnr) or _norm_text(supplier_name),
        _norm_text(start_date),
        _norm_text(end_date),
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _contract_values(contract: MunicipalContract) -> tuple[Any, ...]:
    row_hash = contract.row_hash or contract_row_hash(
        contract.buyer_org,
        contract.contract_ref,
        contract.supplier_name,
        contract.supplier_orgnr,
        contract.start_date,
        contract.end_date,
    )
    return (
        contract.buyer_org,
        contract.buyer_orgnr,
        contract.contract_ref,
        contract.title,
        contract.category,
        contract.supplier_name,
        normalize_orgnr(contract.supplier_orgnr) or contract.supplier_orgnr,
        contract.start_date,
        contract.end_date,
        contract.rank,
        contract.cap_value_sek,
        contract.source,
        contract.source_file,
        row_hash,
        contract.ingested_at or _utc_now(),
    )


def _norm_text(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- record <-> row ----------------------------------------------------------


def _framework_values(fw: FrameworkAgreement) -> tuple[Any, ...]:
    return (
        fw.notice_id,
        fw.buyer_name,
        fw.buyer_orgnr,
        fw.title,
        int(fw.is_framework),
        fw.cap_value_sek,
        fw.estimated_value_sek,
        fw.cap_source,
        fw.cap_confidence,
        fw.start_date,
        fw.end_date,
        fw.max_duration_months,
        fw.cpv_main,
        int(fw.buyer_is_cpb),
        fw.raw_excerpt,
        fw.updated_at or _utc_now(),
    )


def _framework_from_row(row: sqlite3.Row) -> FrameworkAgreement:
    return FrameworkAgreement(
        notice_id=row["notice_id"],
        buyer_name=row["buyer_name"],
        buyer_orgnr=row["buyer_orgnr"],
        title=row["title"],
        is_framework=bool(row["is_framework"]),
        cap_value_sek=row["cap_value_sek"],
        estimated_value_sek=row["estimated_value_sek"],
        cap_source=row["cap_source"],
        cap_confidence=row["cap_confidence"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        max_duration_months=row["max_duration_months"],
        cpv_main=row["cpv_main"],
        buyer_is_cpb=bool(row["buyer_is_cpb"]),
        raw_excerpt=row["raw_excerpt"],
        updated_at=row["updated_at"],
    )


def _winner_values(winner: AwardWinner) -> tuple[Any, ...]:
    return (
        winner.notice_id,
        winner.supplier_name,
        winner.supplier_orgnr,
        winner.lot_id,
        winner.rank,
        winner.awarded_value_sek,
        winner.match_confidence,
        winner.award_date,
        winner.updated_at or _utc_now(),
    )


def _winner_from_row(row: sqlite3.Row) -> AwardWinner:
    return AwardWinner(
        notice_id=row["notice_id"],
        supplier_name=row["supplier_name"],
        supplier_orgnr=row["supplier_orgnr"],
        lot_id=row["lot_id"],
        rank=row["rank"],
        awarded_value_sek=row["awarded_value_sek"],
        match_confidence=row["match_confidence"],
        award_date=row["award_date"],
        updated_at=row["updated_at"],
    )


def _foia_values(request: FoiaRequest) -> tuple[Any, ...]:
    return (
        request.target_org,
        request.target_email,
        request.framework_notice_id,
        request.sent_at,
        request.reminder_1_at,
        request.reminder_2_at,
        request.decision_requested_at,
        request.status,
        request.response_received_at,
        request.response_file_path,
        request.notes,
    )


def _foia_from_row(row: sqlite3.Row) -> FoiaRequest:
    return FoiaRequest(
        id=row["id"],
        target_org=row["target_org"],
        target_email=row["target_email"],
        framework_notice_id=row["framework_notice_id"],
        status=row["status"],
        sent_at=row["sent_at"],
        reminder_1_at=row["reminder_1_at"],
        reminder_2_at=row["reminder_2_at"],
        decision_requested_at=row["decision_requested_at"],
        response_received_at=row["response_received_at"],
        response_file_path=row["response_file_path"],
        notes=row["notes"],
    )


def _payment_values(payment: SupplierPayment) -> tuple[Any, ...]:
    row_hash = payment.row_hash or payment_row_hash(
        payer_org=payment.payer_org,
        supplier_name=payment.supplier_name,
        supplier_orgnr=payment.supplier_orgnr,
        amount_sek=payment.amount_sek,
        period_year=payment.period_year,
        period_month=payment.period_month,
        source_url=payment.source_url,
        account=payment.account,
        cost_centre=payment.cost_centre,
    )
    return (
        payment.payer_org,
        payment.payer_orgnr,
        payment.supplier_name,
        payment.supplier_orgnr,
        payment.amount_sek,
        payment.period_year,
        payment.period_month,
        payment.source,
        payment.source_url,
        row_hash,
        payment.ingested_at or _utc_now(),
        payment.account,
        payment.cost_centre,
    )


def _migrate_row(row: sqlite3.Row) -> Notice:
    """Convert one legacy row to the current model.

    Prefers re-parsing the stored raw JSON (same code path as a live scan);
    falls back to converting the legacy columns directly if the raw payload
    is missing the expected fields.
    """
    raw: dict[str, Any] = json.loads(row["raw_json"])
    try:
        return parse_notice(raw)
    except (KeyError, TypeError, ValueError):
        estimated_value, currency = _split_legacy_value(row["estimated_value"])
        lots = parse_lots(
            [estimated_value] if estimated_value is not None else [], [currency] if currency else []
        )
        return Notice(
            id=row["id"],
            title=row["title"],
            buyer=row["buyer"],
            cpv=row["cpv"],
            deadline=normalize_deadline(row["deadline"]),
            estimated_value=estimated_value,
            currency=currency,
            lots=lots,
            url=row["url"],
            raw=raw,
        )


def _split_legacy_value(text: str | None) -> tuple[float | None, str | None]:
    """Split a legacy value string like '18000000 SEK' into (18000000.0, 'SEK')."""
    if not text:
        return None, None
    match = _LEGACY_VALUE.match(text)
    if not match:
        return None, None
    return float(match.group("amount")), match.group("currency")
