"""SQLite storage for procurement notices.

Schema versions (PRAGMA user_version):
  0/1 — legacy: estimated_value stored as TEXT ("18000000 SEK"), deadlines in
        TED's mixed zone formats ("2026-08-20Z" vs "2026-09-03+02:00").
  2   — estimated_value REAL + currency TEXT, deadlines normalized to UTC
        ISO-8601, per-lot values in lots_json.

Legacy databases are migrated automatically on open (a `<db>.bak` copy of the
file is written first). Rows are re-parsed from their stored raw JSON, so the
migration applies the exact same parsing rules as a fresh scan.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from tender_scan.models import Lot, Notice, normalize_deadline, parse_lots, parse_notice

DEFAULT_DB_PATH = "tender_scan.db"

SCHEMA_VERSION = 2

_SCHEMA = """
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

# Legacy estimated_value text, e.g. "18000000 SEK" or "2500000.5".
_LEGACY_VALUE = re.compile(r"^\s*(?P<amount>\d+(?:\.\d+)?)\s*(?P<currency>[A-Z]{3})?\s*$")


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
        self._migrate_v1_to_v2()

    def _backup_file(self) -> None:
        source = Path(self.db_path)
        if source.is_file():
            shutil.copy2(source, source.with_name(source.name + ".bak"))

    def _migrate_v1_to_v2(self) -> None:
        old_rows = self._conn.execute("SELECT * FROM notices").fetchall()
        self._conn.execute("ALTER TABLE notices RENAME TO notices_legacy")
        self._conn.executescript(_SCHEMA)
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
                    [{"estimated_value": lot.estimated_value, "currency": lot.currency}
                     for lot in notice.lots]
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
        lots = parse_lots([estimated_value] if estimated_value is not None else [],
                          [currency] if currency else [])
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
