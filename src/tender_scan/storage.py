"""SQLite storage for procurement notices.

Schema versions (PRAGMA user_version):
  0/1 — legacy: estimated_value stored as TEXT ("18000000 SEK"), deadlines in
        TED's mixed zone formats ("2026-08-20Z" vs "2026-09-03+02:00").
  2   — estimated_value REAL + currency TEXT, deadlines normalized to UTC
        ISO-8601, per-lot values in lots_json.
  3   — utilization tables next to `notices`, which is left exactly as it was:
        framework_agreements, award_winners, supplier_payments, foia_requests
        and fx_rates. Purely additive, so the migration only creates tables.

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
from tender_scan.records import AwardWinner, FrameworkAgreement, SupplierPayment

DEFAULT_DB_PATH = "tender_scan.db"

SCHEMA_VERSION = 3

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
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (notice_id, supplier_name, lot_id)
);

CREATE TABLE IF NOT EXISTS supplier_payments (
    payer_org      TEXT NOT NULL,
    supplier_name  TEXT NOT NULL,
    supplier_orgnr TEXT,
    amount_sek     INTEGER NOT NULL,
    period_year    INTEGER NOT NULL,
    period_month   INTEGER,
    source         TEXT NOT NULL,   -- 'open_data' | 'foia' | 'annual_report'
    source_url     TEXT,
    row_hash       TEXT NOT NULL,
    ingested_at    TEXT NOT NULL,
    PRIMARY KEY (row_hash)
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

CREATE INDEX IF NOT EXISTS idx_award_winners_orgnr ON award_winners (supplier_orgnr);
CREATE INDEX IF NOT EXISTS idx_payments_orgnr ON supplier_payments (supplier_orgnr);
CREATE INDEX IF NOT EXISTS idx_payments_payer ON supplier_payments (payer_org);
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
    "updated_at",
)

_PAYMENT_COLUMNS = (
    "payer_org",
    "supplier_name",
    "supplier_orgnr",
    "amount_sek",
    "period_year",
    "period_month",
    "source",
    "source_url",
    "row_hash",
    "ingested_at",
)


class Storage:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or os.environ.get("TENDER_SCAN_DB", DEFAULT_DB_PATH))
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._migrate_if_needed()
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

        A row needs review when the cap is missing outright or when it was
        extracted with weak evidence. A NULL confidence next to a present cap
        is not flagged: that combination means the cap came from an eForms
        field, where there is nothing to be unsure about.
        """
        query = "SELECT * FROM framework_agreements"
        params: tuple[Any, ...] = ()
        if needs_review:
            query += " WHERE cap_confidence < ? OR cap_value_sek IS NULL"
            params = (REVIEW_CONFIDENCE,)
        query += " ORDER BY notice_id"
        return [_framework_from_row(row) for row in self._conn.execute(query, params)]

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


# -- row identity ------------------------------------------------------------


def payment_row_hash(
    payer_org: str,
    supplier_name: str,
    supplier_orgnr: str | None,
    amount_sek: int,
    period_year: int,
    period_month: int | None,
    source_url: str | None = None,
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
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


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
        updated_at=row["updated_at"],
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
    )
    return (
        payment.payer_org,
        payment.supplier_name,
        payment.supplier_orgnr,
        payment.amount_sek,
        payment.period_year,
        payment.period_month,
        payment.source,
        payment.source_url,
        row_hash,
        payment.ingested_at or _utc_now(),
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
