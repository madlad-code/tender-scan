from tender_scan.models import Notice, parse_notice
from tender_scan.storage import Storage


def make_notice(**overrides) -> Notice:
    defaults = dict(
        id="450106-2026",
        title="Digitalt systemstöd",
        buyer="Statens institutionsstyrelse",
        cpv="72000000",
        deadline="2026-08-27+02:00",
        estimated_value="18000000 SEK",
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
        storage.upsert(make_notice(id="c-2026", deadline="2026-09-01+02:00"))
        storage.upsert(make_notice(id="a-2026", deadline="2026-08-15+02:00"))

        ids = [n.id for n in storage.list_notices()]

    assert ids == ["a-2026", "c-2026", "b-2026"]


def test_roundtrip_from_fixture(tmp_path, search_response):
    with Storage(tmp_path / "test.db") as storage:
        for raw in search_response["notices"]:
            storage.upsert(parse_notice(raw))

        assert storage.count() == 5
        stored = {n.id: n for n in storage.list_notices()}

    notice = stored["450106-2026"]
    assert notice.estimated_value == "18000000 SEK"
    assert notice.raw["publication-number"] == "450106-2026"


def test_persists_across_connections(tmp_path):
    db = tmp_path / "test.db"
    with Storage(db) as storage:
        storage.upsert(make_notice())
    with Storage(db) as storage:
        assert storage.count() == 1
