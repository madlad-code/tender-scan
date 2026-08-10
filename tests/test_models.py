from tender_scan.models import parse_notice


def test_parse_full_notice(search_response):
    # Notice 450106-2026 in the recorded fixture has deadline and value.
    raw = next(n for n in search_response["notices"] if n["publication-number"] == "450106-2026")
    notice = parse_notice(raw)

    assert notice.id == "450106-2026"
    assert notice.title
    assert notice.buyer
    assert "72000000" in notice.cpv
    assert notice.deadline == "2026-08-27+02:00"
    assert notice.estimated_value == "18000000 SEK"
    assert notice.url and notice.url.startswith("https://ted.europa.eu/")
    assert notice.raw == raw


def test_parse_minimal_notice():
    notice = parse_notice({"publication-number": "1-2026"})
    assert notice.id == "1-2026"
    assert notice.title is None
    assert notice.buyer is None
    assert notice.cpv is None
    assert notice.deadline is None
    assert notice.estimated_value is None
    assert notice.url is None


def test_parse_prefers_english_title():
    raw = {
        "publication-number": "2-2026",
        "notice-title": {"swe": "Svensk titel", "eng": "English title"},
    }
    assert parse_notice(raw).title == "English title"


def test_parse_falls_back_to_swedish_title():
    raw = {
        "publication-number": "3-2026",
        "notice-title": {"hun": "Magyar cím", "swe": "Svensk titel"},
    }
    assert parse_notice(raw).title == "Svensk titel"


def test_parse_dedupes_cpv_codes():
    raw = {
        "publication-number": "4-2026",
        "classification-cpv": ["48510000", "48510000", "72000000"],
    }
    assert parse_notice(raw).cpv == "48510000,72000000"


def test_parse_joins_multiple_buyers():
    raw = {
        "publication-number": "5-2026",
        "buyer-name": {"swe": ["Kommun A", "Bolag B"]},
    }
    assert parse_notice(raw).buyer == "Kommun A; Bolag B"
