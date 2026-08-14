import json
import sqlite3

from tender_scan.models import Lot, Notice, parse_notice
from tender_scan.storage import SCHEMA_VERSION, Storage


def make_notice(**overrides) -> Notice:
    defaults = dict(
        id="450106-2026",
        title="Digitalt systemstöd",
        buyer="Statens institutionsstyrelse",
        cpv="72000000",
        deadline="2026-08-26T22:00:00Z",
        estimated_value=18000000.0,
        currency="SEK",
        lots=(Lot(estimated_value=18000000.0, currency="SEK"),),
        url="https://ted.europa.eu/en/notice/-/detail/450106-2026",
        raw={"publication-number": "450106-2026"},
    )
    return Notice(**{**defaults, **overrides})


def test_upsert_and_list(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.upsert(make_notice())
        notices = storage.list_notices()

    assert len(notices) == 1
    stored = notices[0]
    assert stored == make_notice()


def test_upsert_is_idempotent(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.upsert(make_notice())
        storage.upsert(make_notice(title="Updated title"))

        assert storage.count() == 1
        assert storage.list_notices()[0].title == "Updated title"


def test_list_orders_by_deadline_nulls_last(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.upsert(make_notice(id="b-2026", deadline=None))
        storage.upsert(make_notice(id="c-2026", deadline="2026-08-31T22:00:00Z"))
        storage.upsert(make_notice(id="a-2026", deadline="2026-08-14T22:00:00Z"))

        ids = [n.id for n in storage.list_notices()]

    assert ids == ["a-2026", "c-2026", "b-2026"]


def test_roundtrip_from_fixture(tmp_path, search_response):
    with Storage(tmp_path / "test.db") as storage:
        for raw in search_response["notices"]:
            storage.upsert(parse_notice(raw))

        assert storage.count() == 5
        stored = {n.id: n for n in storage.list_notices()}

    notice = stored["450106-2026"]
    assert notice.estimated_value == 18000000.0
    assert notice.currency == "SEK"
    assert notice.lots == (Lot(estimated_value=18000000.0, currency="SEK"),)
    assert notice.raw["publication-number"] == "450106-2026"


def test_persists_across_connections(tmp_path):
    db = tmp_path / "test.db"
    with Storage(db) as storage:
        storage.upsert(make_notice())
    with Storage(db) as storage:
        assert storage.count() == 1


# -- migration from the legacy v1 schema ------------------------------------

_LEGACY_SCHEMA = """
CREATE TABLE notices (
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


def _make_legacy_db(path, rows) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_SCHEMA)
    conn.executemany(
        "INSERT INTO notices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _legacy_row(raw: dict, deadline: str | None, value: str | None) -> tuple:
    return (
        raw["publication-number"],
        "Titel",
        "Köpare",
        "72000000",
        deadline,
        value,
        "https://ted.europa.eu/x",
        json.dumps(raw),
    )


def test_migration_reparses_raw_json(tmp_path):
    db = tmp_path / "legacy.db"
    raw = {
        "publication-number": "100-2026",
        "deadline-receipt-tender-date-lot": ["2026-08-20Z"],
        "estimated-value-lot": ["3000000", "1000000"],
        "estimated-value-cur-lot": ["SEK", "SEK"],
    }
    _make_legacy_db(db, [_legacy_row(raw, "2026-08-20Z", "3000000 SEK")])

    with Storage(db) as storage:
        notice = storage.list_notices()[0]

    assert notice.deadline == "2026-08-20T00:00:00Z"
    assert notice.estimated_value == 4000000.0  # all lots, not just the first
    assert notice.currency == "SEK"
    assert notice.lots == (Lot(3000000.0, "SEK"), Lot(1000000.0, "SEK"))


def test_migration_falls_back_to_columns_without_raw_fields(tmp_path):
    db = tmp_path / "legacy.db"
    # Raw JSON without publication-number: re-parse fails, columns are used.
    row = (
        "101-2026",
        "Titel",
        "Köpare",
        "72000000",
        "2026-09-03+02:00",
        "18000000 SEK",
        "https://ted.europa.eu/x",
        json.dumps({}),
    )
    _make_legacy_db(db, [row])

    with Storage(db) as storage:
        notice = storage.list_notices()[0]

    assert notice.id == "101-2026"
    assert notice.deadline == "2026-09-02T22:00:00Z"
    assert notice.estimated_value == 18000000.0
    assert notice.currency == "SEK"


def test_migration_sets_schema_version_and_writes_backup(tmp_path):
    db = tmp_path / "legacy.db"
    raw = {"publication-number": "102-2026"}
    _make_legacy_db(db, [_legacy_row(raw, None, None)])

    with Storage(db) as storage:
        assert storage.count() == 1

    assert (tmp_path / "legacy.db.bak").exists()
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    columns = {r[1] for r in conn.execute("PRAGMA table_info(notices)")}
    conn.close()
    assert {"estimated_value", "currency", "lots_json"} <= columns


def test_migration_is_not_rerun_on_reopen(tmp_path):
    db = tmp_path / "legacy.db"
    raw = {"publication-number": "103-2026"}
    _make_legacy_db(db, [_legacy_row(raw, None, None)])

    with Storage(db):
        pass
    (tmp_path / "legacy.db.bak").unlink()  # remove backup; reopen must not recreate it
    with Storage(db) as storage:
        assert storage.count() == 1
    assert not (tmp_path / "legacy.db.bak").exists()


def test_fresh_db_gets_current_schema_version(tmp_path):
    db = tmp_path / "fresh.db"
    with Storage(db):
        pass
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
    assert not (tmp_path / "fresh.db.bak").exists()
