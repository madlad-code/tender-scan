"""SQLite storage for procurement notices."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from tender_scan.models import Notice

DEFAULT_DB_PATH = "tender_scan.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    buyer           TEXT,
    cpv             TEXT,
    deadline        TEXT,
    estimated_value TEXT,
    url             TEXT,
    raw_json        TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or os.environ.get("TENDER_SCAN_DB", DEFAULT_DB_PATH))
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upsert(self, notice: Notice) -> None:
        self._conn.execute(
            """
            INSERT INTO notices (id, title, buyer, cpv, deadline, estimated_value, url, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                buyer = excluded.buyer,
                cpv = excluded.cpv,
                deadline = excluded.deadline,
                estimated_value = excluded.estimated_value,
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
                url=row["url"],
                raw=json.loads(row["raw_json"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
