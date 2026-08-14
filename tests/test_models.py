from tender_scan.models import (
    Lot,
    format_estimated_value,
    normalize_deadline,
    parse_lots,
    parse_notice,
    total_estimated_value,
)


def test_parse_full_notice(search_response):
    # Notice 450106-2026 in the recorded fixture has deadline and value.
    raw = next(n for n in search_response["notices"] if n["publication-number"] == "450106-2026")
    notice = parse_notice(raw)

    assert notice.id == "450106-2026"
    assert notice.title
    assert notice.buyer
    assert "72000000" in notice.cpv
    # "2026-08-27+02:00" = midnight CEST, normalized to UTC.
    assert notice.deadline == "2026-08-26T22:00:00Z"
    assert notice.estimated_value == 18000000.0
    assert notice.currency == "SEK"
    assert notice.lots == (Lot(estimated_value=18000000.0, currency="SEK"),)
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
    assert notice.currency is None
    assert notice.lots == ()
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


# -- deadline normalization -------------------------------------------------


def test_normalize_deadline_utc_date():
    assert normalize_deadline("2026-08-20Z") == "2026-08-20T00:00:00Z"


def test_normalize_deadline_offset_date():
    # Midnight CEST is 22:00 the previous day in UTC.
    assert normalize_deadline("2026-09-03+02:00") == "2026-09-02T22:00:00Z"


def test_normalize_deadline_bare_date_assumed_utc():
    assert normalize_deadline("2026-08-20") == "2026-08-20T00:00:00Z"


def test_normalize_deadline_full_datetime():
    assert normalize_deadline("2026-08-20T12:30:00+02:00") == "2026-08-20T10:30:00Z"
    assert normalize_deadline("2026-08-20T12:30:00Z") == "2026-08-20T12:30:00Z"


def test_normalize_deadline_invalid_or_empty():
    assert normalize_deadline(None) is None
    assert normalize_deadline("") is None
    assert normalize_deadline("not-a-date") is None


def test_mixed_zone_deadlines_sort_correctly():
    # As raw strings, "2026-08-20Z" > "2026-08-19+02:00" is not guaranteed by
    # string comparison across formats. Normalized, they compare correctly.
    early = normalize_deadline("2026-08-20Z")
    late = normalize_deadline("2026-09-03+02:00")
    assert early < late


def test_parse_picks_earliest_deadline_across_formats():
    raw = {
        "publication-number": "6-2026",
        # 2026-08-20T00:00Z vs 2026-08-19T22:00Z (= 2026-08-20+02:00): the
        # offset date is actually earlier in UTC.
        "deadline-receipt-tender-date-lot": ["2026-08-20Z", "2026-08-20+02:00"],
    }
    assert parse_notice(raw).deadline == "2026-08-19T22:00:00Z"


# -- lots -------------------------------------------------------------------


def test_parse_lots_pairs_when_lengths_match():
    lots = parse_lots(["1000", "2000"], ["SEK", "EUR"])
    assert lots == (Lot(1000.0, "SEK"), Lot(2000.0, "EUR"))


def test_parse_lots_broadcasts_single_currency():
    lots = parse_lots(["1000", "2000", "3000"], ["SEK"])
    assert lots == (Lot(1000.0, "SEK"), Lot(2000.0, "SEK"), Lot(3000.0, "SEK"))


def test_parse_lots_leaves_currency_unknown_on_mismatch():
    lots = parse_lots(["1000", "2000", "3000"], ["SEK", "EUR"])
    assert all(lot.currency is None for lot in lots)
    assert [lot.estimated_value for lot in lots] == [1000.0, 2000.0, 3000.0]


def test_parse_lots_no_currencies():
    assert parse_lots(["500"], []) == (Lot(500.0, None),)


def test_parse_notice_takes_all_lots():
    raw = {
        "publication-number": "7-2026",
        "estimated-value-lot": ["1000000", "2500000"],
        "estimated-value-cur-lot": ["SEK", "SEK"],
    }
    notice = parse_notice(raw)
    assert notice.lots == (Lot(1000000.0, "SEK"), Lot(2500000.0, "SEK"))
    assert notice.estimated_value == 3500000.0
    assert notice.currency == "SEK"


def test_total_estimated_value_mixed_currencies_is_none():
    lots = (Lot(1000.0, "SEK"), Lot(2000.0, "EUR"))
    assert total_estimated_value(lots) == (None, None)


def test_format_estimated_value():
    assert format_estimated_value(18000000.0, "SEK") == "18000000 SEK"
    assert format_estimated_value(1500.5, "EUR") == "1500.5 EUR"
    assert format_estimated_value(500.0, None) == "500"
    assert format_estimated_value(None, "SEK") is None
