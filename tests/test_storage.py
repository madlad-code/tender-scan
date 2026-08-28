import json
import sqlite3
from pathlib import Path

from tender_scan.models import Lot, Notice, parse_notice
from tender_scan.records import AwardWinner, FrameworkAgreement, SupplierPayment
from tender_scan.storage import SCHEMA_VERSION, Storage, payment_row_hash


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


# -- schema version 3: the utilization tables -------------------------------

_V3_TABLES = (
    "framework_agreements",
    "award_winners",
    "supplier_payments",
    "foia_requests",
    "fx_rates",
)


def _tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    return names


def _raw_notice_rows(path) -> list[tuple]:
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT * FROM notices ORDER BY id").fetchall()
    conn.close()
    return rows


def _make_v2_db(path, notices) -> None:
    """A genuine v2 database: rows written by the real writer, then the v3
    tables dropped and user_version rolled back."""
    with Storage(path) as storage:
        for notice in notices:
            storage.upsert(notice)
    conn = sqlite3.connect(path)
    for table in _V3_TABLES:
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    Path(str(path) + ".bak").unlink(missing_ok=True)


def test_fresh_db_has_every_v3_table(tmp_path):
    db = tmp_path / "fresh.db"
    with Storage(db):
        pass

    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    conn.close()
    assert set(_V3_TABLES) <= _tables(db)


def test_v2_migration_keeps_every_notice_row_byte_for_byte(tmp_path):
    db = tmp_path / "v2.db"
    _make_v2_db(
        db,
        [
            make_notice(),
            make_notice(id="451000-2026", title="Annan upphandling", deadline=None),
            make_notice(id="452000-2026", estimated_value=None, currency=None, lots=()),
        ],
    )
    before = _raw_notice_rows(db)

    with Storage(db) as storage:
        assert storage.count() == 3

    assert _raw_notice_rows(db) == before
    assert set(_V3_TABLES) <= _tables(db)


def test_v2_migration_writes_backup(tmp_path):
    db = tmp_path / "v2.db"
    _make_v2_db(db, [make_notice()])
    assert not (tmp_path / "v2.db.bak").exists()

    with Storage(db):
        pass

    assert (tmp_path / "v2.db.bak").exists()


def test_v1_database_reaches_v3_in_one_open(tmp_path):
    db = tmp_path / "legacy.db"
    raw = {
        "publication-number": "104-2026",
        "deadline-receipt-tender-date-lot": ["2026-08-20Z"],
        "estimated-value-lot": ["3000000"],
        "estimated-value-cur-lot": ["SEK"],
    }
    _make_legacy_db(db, [_legacy_row(raw, "2026-08-20Z", "3000000 SEK")])

    with Storage(db) as storage:
        notice = storage.list_notices()[0]

    # The v1 -> v2 conversion still happened, and v3 came along in the same open.
    assert notice.estimated_value == 3000000.0
    assert notice.currency == "SEK"
    assert notice.deadline == "2026-08-20T00:00:00Z"
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    conn.close()
    assert set(_V3_TABLES) <= _tables(db)
    assert (tmp_path / "legacy.db.bak").exists()


def test_opening_a_v3_db_twice_changes_nothing(tmp_path):
    db = tmp_path / "v3.db"
    with Storage(db) as storage:
        storage.upsert(make_notice())
        storage.upsert_framework(make_framework())
        storage.insert_payments([make_payment()])

    def snapshot():
        conn = sqlite3.connect(db)
        schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        data = {
            table: conn.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("notices", *_V3_TABLES)
        }
        conn.close()
        return schema, data

    before = snapshot()
    with Storage(db):
        pass

    assert snapshot() == before
    assert not (tmp_path / "v3.db.bak").exists()


# -- framework agreements ---------------------------------------------------


def make_framework(**overrides) -> FrameworkAgreement:
    defaults = dict(
        notice_id="1884-2026",
        buyer_name="Statens institutionsstyrelse",
        buyer_orgnr="202100-4508",
        title="Ramavtal konsulttjänster",
        is_framework=True,
        cap_value_sek=3_000_000,
        estimated_value_sek=1_500_000,
        cap_source="eforms_field",
        cap_confidence=1.0,
        start_date="2026-01-01",
        end_date="2028-01-01",
        max_duration_months=24,
        cpv_main="72000000",
        raw_excerpt=None,
        updated_at="2026-08-27T10:00:00Z",
    )
    return FrameworkAgreement(**{**defaults, **overrides})


def test_upsert_framework_roundtrips(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.upsert_framework(make_framework())
        stored = storage.get_framework("1884-2026")

    assert stored == make_framework()


def test_get_framework_returns_none_when_absent(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        assert storage.get_framework("nope-2026") is None


def test_upsert_framework_is_idempotent(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.upsert_framework(make_framework())
        storage.upsert_framework(make_framework(cap_value_sek=4_000_000, cap_source="manual"))

        frameworks = storage.list_frameworks()

    assert len(frameworks) == 1
    assert frameworks[0].cap_value_sek == 4_000_000
    assert frameworks[0].cap_source == "manual"


def test_upsert_framework_stamps_updated_at_when_missing(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.upsert_framework(make_framework(updated_at=None))
        stored = storage.get_framework("1884-2026")

    assert stored is not None
    assert stored.updated_at is not None and stored.updated_at.endswith("Z")


def test_list_frameworks_needs_review_boundary_and_null_cap(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.upsert_framework(make_framework(notice_id="a-2026", cap_confidence=0.7))
        storage.upsert_framework(make_framework(notice_id="b-2026", cap_confidence=0.69))
        storage.upsert_framework(
            make_framework(notice_id="c-2026", cap_confidence=0.95, cap_value_sek=None)
        )
        storage.upsert_framework(make_framework(notice_id="d-2026", cap_confidence=1.0))

        all_ids = [fw.notice_id for fw in storage.list_frameworks()]
        review_ids = [fw.notice_id for fw in storage.list_frameworks(needs_review=True)]

    assert all_ids == ["a-2026", "b-2026", "c-2026", "d-2026"]
    assert review_ids == ["b-2026", "c-2026"]  # 0.7 exactly is not under review


def test_a_cap_with_no_confidence_is_in_the_review_queue(tmp_path):
    """An unexplained cap is exactly what a human has to look at."""
    with Storage(tmp_path / "test.db") as storage:
        storage.upsert_framework(make_framework(notice_id="e-2026", cap_confidence=None))
        review_ids = [fw.notice_id for fw in storage.list_frameworks(needs_review=True)]
    assert review_ids == ["e-2026"]


# -- award winners ----------------------------------------------------------


def make_winner(**overrides) -> AwardWinner:
    defaults = dict(
        notice_id="1884-2026",
        supplier_name="Konsultbolaget AB",
        supplier_orgnr="556224-8012",
        lot_id="LOT-0001",
        rank=1,
        awarded_value_sek=1_500_000,
        match_confidence=1.0,
        updated_at="2026-08-27T10:00:00Z",
    )
    return AwardWinner(**{**defaults, **overrides})


def test_replace_winners_roundtrips(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.replace_winners("1884-2026", [make_winner()])
        winners = storage.list_winners("1884-2026")

    assert winners == [make_winner()]


def test_replace_winners_drops_suppliers_that_vanished_from_a_rescan(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.replace_winners(
            "1884-2026",
            [make_winner(), make_winner(supplier_name="Andra Bolaget AB", rank=2)],
        )
        assert len(storage.list_winners("1884-2026")) == 2

        storage.replace_winners("1884-2026", [make_winner()])
        names = [w.supplier_name for w in storage.list_winners("1884-2026")]

    assert names == ["Konsultbolaget AB"]


def test_replace_winners_leaves_other_notices_alone(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.replace_winners("1884-2026", [make_winner()])
        storage.replace_winners(
            "15840-2026", [make_winner(notice_id="15840-2026", supplier_name="Tredje AB")]
        )

        storage.replace_winners("1884-2026", [])

        assert storage.list_winners("1884-2026") == []
        other = storage.list_winners("15840-2026")
        assert [w.supplier_name for w in other] == ["Tredje AB"]
        assert len(storage.list_winners()) == 1


def test_list_winners_without_notice_id_returns_all(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.replace_winners("1884-2026", [make_winner(lot_id="LOT-0002")])
        storage.replace_winners("15840-2026", [make_winner(notice_id="15840-2026")])

        ids = [(w.notice_id, w.lot_id) for w in storage.list_winners()]

    assert ids == [("15840-2026", "LOT-0001"), ("1884-2026", "LOT-0002")]


# -- supplier payments ------------------------------------------------------


def make_payment(**overrides) -> SupplierPayment:
    defaults = dict(
        payer_org="Statens institutionsstyrelse",
        supplier_name="Konsultbolaget AB",
        supplier_orgnr="556224-8012",
        amount_sek=1_200_000,
        period_year=2026,
        period_month=3,
        source="open_data",
        source_url="https://example.se/leverantorsreskontra.csv",
        row_hash=None,
        ingested_at=None,
    )
    return SupplierPayment(**{**defaults, **overrides})


def _payment_rows(storage) -> list[tuple]:
    return storage.connection().execute("SELECT * FROM supplier_payments").fetchall()


def test_insert_payments_returns_rows_added(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        added = storage.insert_payments([make_payment(), make_payment(period_month=4)])

    assert added == 2


def test_insert_payments_is_idempotent(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        payments = [make_payment(), make_payment(period_month=4)]
        storage.insert_payments(payments)
        before = _payment_rows(storage)

        assert storage.insert_payments(payments) == 0
        assert _payment_rows(storage) == before


def test_insert_payments_adds_only_the_new_rows(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.insert_payments([make_payment()])

        added = storage.insert_payments([make_payment(), make_payment(amount_sek=999)])

        assert added == 1
        assert len(_payment_rows(storage)) == 2


def test_insert_payments_collapses_the_same_row_spelled_differently(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        storage.insert_payments([make_payment()])

        added = storage.insert_payments(
            [make_payment(supplier_orgnr="5562248012", payer_org="  Statens institutionsstyrelse ")]
        )

    assert added == 0


def test_insert_payments_with_nothing_to_insert(tmp_path):
    with Storage(tmp_path / "test.db") as storage:
        assert storage.insert_payments([]) == 0


# -- payment_row_hash -------------------------------------------------------


def test_payment_row_hash_ignores_argument_order(tmp_path):
    first = payment_row_hash(
        payer_org="Region Skåne",
        supplier_name="Konsultbolaget AB",
        supplier_orgnr="556224-8012",
        amount_sek=1_200_000,
        period_year=2026,
        period_month=3,
        source_url="https://example.se/x.csv",
    )
    second = payment_row_hash(
        source_url="https://example.se/x.csv",
        period_month=3,
        period_year=2026,
        amount_sek=1_200_000,
        supplier_orgnr="556224-8012",
        supplier_name="Konsultbolaget AB",
        payer_org="Region Skåne",
    )
    assert first == second


def test_payment_row_hash_ignores_whitespace_and_orgnr_spelling():
    canonical = payment_row_hash(
        payer_org="Region Skåne",
        supplier_name="Konsultbolaget AB",
        supplier_orgnr="556224-8012",
        amount_sek=1_200_000,
        period_year=2026,
        period_month=3,
        source_url="https://example.se/x.csv",
    )
    messy = payment_row_hash(
        payer_org="  region   skåne\n",
        supplier_name=" KONSULTBOLAGET  AB ",
        supplier_orgnr=" 5562248012 ",
        amount_sek=1_200_000,
        period_year=2026,
        period_month=3,
        source_url=" https://example.se/x.csv ",
    )
    assert messy == canonical


def test_payment_row_hash_separates_different_amounts():
    def hash_for(amount: int) -> str:
        return payment_row_hash(
            payer_org="Region Skåne",
            supplier_name="Konsultbolaget AB",
            supplier_orgnr="556224-8012",
            amount_sek=amount,
            period_year=2026,
            period_month=3,
            source_url="https://example.se/x.csv",
        )

    assert hash_for(1_200_000) != hash_for(1_200_001)


def test_payment_row_hash_separates_periods_and_payers():
    base = dict(
        payer_org="Region Skåne",
        supplier_name="Konsultbolaget AB",
        supplier_orgnr="556224-8012",
        amount_sek=1_200_000,
        period_year=2026,
        period_month=3,
        source_url=None,
    )
    reference = payment_row_hash(**base)

    assert payment_row_hash(**{**base, "period_month": 4}) != reference
    assert payment_row_hash(**{**base, "period_month": None}) != reference
    assert payment_row_hash(**{**base, "period_year": 2025}) != reference
    assert payment_row_hash(**{**base, "payer_org": "Region Halland"}) != reference


def test_payment_row_hash_falls_back_to_the_name_without_a_valid_orgnr():
    named = payment_row_hash(
        payer_org="Region Skåne",
        supplier_name="Konsultbolaget AB",
        supplier_orgnr=None,
        amount_sek=1_200_000,
        period_year=2026,
        period_month=3,
    )
    # A value that fails the Luhn check is not an orgnr, so it is ignored.
    bad_orgnr = payment_row_hash(
        payer_org="Region Skåne",
        supplier_name="Konsultbolaget AB",
        supplier_orgnr="556224-8013",
        amount_sek=1_200_000,
        period_year=2026,
        period_month=3,
    )
    assert bad_orgnr == named
