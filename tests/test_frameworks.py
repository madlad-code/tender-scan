"""M1 — takvolymsextraktion.

Every expectation here is a fact about a real published notice, not about what
the code happens to do. Where two published figures disagree, the test asserts
that both survive into `raw_excerpt`: a reviewer has to be able to see the
conflict that the confidence score is warning about.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tender_scan.eforms import Amount, NoticeGraph, notice_text, parse_graph
from tender_scan.frameworks import (
    BASIS_LOT_SUM,
    BASIS_NOTICE_FRAMEWORK,
    BASIS_NOTICE_OVERALL,
    CAP_SOURCE_EFORMS,
    CAP_SOURCE_REGEX,
    REVIEW_THRESHOLD,
    CapCandidate,
    cap_candidates,
    choose_cap,
    extract_framework,
    format_amount,
    needs_review,
    validate,
)
from tender_scan.fx import FxRates
from tender_scan.records import FrameworkAgreement
from tender_scan.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"


def graph_of(notice_id: str) -> NoticeGraph:
    return parse_graph((FIXTURES / f"eforms_{notice_id}.xml").read_bytes(), notice_id)


def _replace(record, **changes):
    """dataclasses.replace, spelled out so the intent of each synthetic case is visible."""
    return replace(record, **changes)


# -- the three fixtures the spec names ---------------------------------------


def test_1884_takes_the_notice_level_ceiling() -> None:
    """Overall 3 000 000; the only lot publishes 1 500 000, so the sum is incomplete."""
    fw = extract_framework(graph_of("1884-2026"))
    assert fw.is_framework is True
    assert fw.cap_value_sek == 3_000_000
    assert fw.cap_source == CAP_SOURCE_EFORMS
    assert fw.estimated_value_sek == 3_000_000
    assert "3 000 000 SEK" in fw.raw_excerpt
    assert "1 500 000 SEK" in fw.raw_excerpt


def test_15840_prefers_the_lot_sum_over_a_smaller_notice_level_figure() -> None:
    """8M at notice level, 8+8+14 = 30M across the lots. 8M is provably not the total."""
    fw = extract_framework(graph_of("15840-2026"))
    assert fw.cap_value_sek == 30_000_000
    assert fw.cap_confidence == pytest.approx(0.75)
    assert "8 000 000 SEK" in fw.raw_excerpt
    assert "30 000 000 SEK" in fw.raw_excerpt


def test_15840_has_no_lot_period_and_reports_none_rather_than_zero() -> None:
    fw = extract_framework(graph_of("15840-2026"))
    assert fw.start_date is None
    assert fw.end_date is None
    assert fw.max_duration_months is None


def test_8020_publishes_no_ceiling_at_all() -> None:
    """The estimate must never be promoted into the cap column."""
    fw = extract_framework(graph_of("8020-2026"))
    assert fw.is_framework is True
    assert fw.cap_value_sek is None
    assert fw.cap_source is None
    assert fw.cap_confidence is None
    assert fw.estimated_value_sek is not None
    assert needs_review(fw) is True
    assert "Inget publicerat tak" in fw.raw_excerpt


def test_8020_records_the_lot_period() -> None:
    fw = extract_framework(graph_of("8020-2026"))
    assert fw.start_date == "2025-08-26"
    assert fw.end_date == "2027-08-25"
    assert fw.max_duration_months == 23  # one day short of 24


def test_431354_reconciles_two_disagreeing_notice_level_fields() -> None:
    """BT-118 says 4M, BT-271 says 8M. Neither is provably the total."""
    fw = extract_framework(graph_of("431354-2026"))
    assert fw.cap_value_sek == 8_000_000
    assert fw.cap_confidence == pytest.approx(0.8)
    assert "BT-118" in fw.raw_excerpt
    assert "BT-271" in fw.raw_excerpt
    assert "motstridiga" in fw.raw_excerpt


def test_470310_two_fields_agreeing_raise_confidence() -> None:
    fw = extract_framework(graph_of("470310-2026"))
    assert fw.cap_value_sek == 200_000_000
    assert fw.cap_confidence == pytest.approx(0.98)
    assert "samstämmiga" in fw.raw_excerpt


# -- candidates and selection ------------------------------------------------


def test_all_three_structured_candidates_are_offered(eforms_431354: bytes) -> None:
    candidates = cap_candidates(parse_graph(eforms_431354, "431354-2026"))
    bases = {c.basis for c in candidates}
    assert bases == {BASIS_NOTICE_OVERALL, BASIS_NOTICE_FRAMEWORK, BASIS_LOT_SUM}
    assert all(c.source == CAP_SOURCE_EFORMS for c in candidates)


def test_a_lot_publishing_the_ceiling_twice_is_counted_once(eforms_431354: bytes) -> None:
    """LotResult MaximumValueAmount and the lot's FrameworkMaximumAmount are one term."""
    candidates = cap_candidates(parse_graph(eforms_431354, "431354-2026"))
    lot_sum = next(c for c in candidates if c.basis == BASIS_LOT_SUM)
    assert lot_sum.amount == Decimal("4000000")


def test_a_zero_ceiling_is_discarded_not_stored_as_zero() -> None:
    """A published 0 means "not stated", never a framework worth nothing."""
    graph = graph_of("1884-2026")
    zeroed = _replace(graph, overall_maximum=Amount(Decimal(0), "SEK"), lot_results=(), lots={})
    assert cap_candidates(zeroed) == []


def test_choose_cap_returns_none_without_candidates() -> None:
    assert choose_cap([]) is None


def test_regex_candidates_are_only_consulted_without_a_structured_one() -> None:
    graph = graph_of("1884-2026")
    text = "Takvolymen för avtalet är 99 000 000 kr."
    assert all(c.source == CAP_SOURCE_EFORMS for c in cap_candidates(graph, text=text))


def test_regex_fallback_when_the_notice_publishes_no_field() -> None:
    graph = graph_of("8020-2026")
    fw = extract_framework(graph, text="Takvolymen för avtalet är 4,5 mkr.")
    assert fw.cap_value_sek == 4_500_000
    assert fw.cap_source == CAP_SOURCE_REGEX
    assert fw.cap_confidence is not None and fw.cap_confidence <= 0.6
    assert needs_review(fw) is True


def test_regex_fallback_ignores_an_estimated_value_in_the_prose() -> None:
    fw = extract_framework(graph_of("8020-2026"), text="Uppskattat värde 24 000 000 kr.")
    assert fw.cap_value_sek is None


def test_the_larger_of_two_equally_confident_regex_hits_wins() -> None:
    candidates = [
        CapCandidate(Decimal("140000000"), None, CAP_SOURCE_REGEX, "takvolym", 0.60, "a"),
        CapCandidate(Decimal("1200000000"), None, CAP_SOURCE_REGEX, "takvolym", 0.60, "b"),
    ]
    chosen = choose_cap(candidates)
    assert chosen is not None and chosen.amount == Decimal("1200000000")


# -- penalties ---------------------------------------------------------------


def test_a_forecast_above_the_chosen_ceiling_costs_confidence() -> None:
    """15840: approximate 24M is below the chosen 30M, so no penalty applies."""
    fw = extract_framework(graph_of("15840-2026"))
    assert fw.cap_confidence == pytest.approx(0.75)
    assert "överstiger valt tak" not in (fw.raw_excerpt or "")


def test_a_cap_equal_to_the_estimate_costs_confidence() -> None:
    fw = extract_framework(graph_of("1884-2026"))
    assert fw.cap_value_sek == fw.estimated_value_sek
    assert fw.cap_confidence == pytest.approx(0.8 * 0.9)
    assert "identiskt med uppskattat värde" in fw.raw_excerpt


# -- non-frameworks ----------------------------------------------------------


def test_a_non_framework_notice_yields_a_recorded_negative(eforms_xml: bytes) -> None:
    """Every cached corpus notice is a framework, so this one is made into a plain
    award by setting the lot's framework code to `none` — the value the eForms
    codelist uses for an ordinary contract."""
    graph = parse_graph(eforms_xml, "214151-2026")
    plain = _replace(
        graph,
        lots={k: _replace(lot, framework_type="none") for k, lot in graph.lots.items()},
    )
    fw = extract_framework(plain)
    assert fw.is_framework is False
    assert fw.cap_value_sek is None
    assert fw.cap_source is None
    assert fw.cap_confidence is None


# -- currency ----------------------------------------------------------------


def eur_graph() -> NoticeGraph:
    """1884-2026 with its ceiling restated in euro on 2026-07-01."""
    graph = graph_of("1884-2026")
    return _replace(
        graph,
        overall_maximum=Amount(Decimal("1000000"), "EUR"),
        overall_approximate=None,
        estimated_overall=None,
        issue_date="2026-07-01",
        lot_results=(),
    )


def test_a_foreign_currency_without_a_rate_source_stores_no_cap() -> None:
    """Better a NULL than an unconverted number sitting in a SEK column."""
    fw = extract_framework(eur_graph(), fx=None)
    assert fw.cap_value_sek is None
    assert fw.cap_confidence is None
    assert "EUR" in fw.raw_excerpt
    assert "kunde inte omräknas" in fw.raw_excerpt


def test_a_foreign_currency_converts_at_the_notices_own_issue_date(ecb_csv: str) -> None:
    conn = sqlite3.connect(":memory:")
    calls: list[tuple[str, date, date]] = []

    def fake_fetch(currency: str, start: date, end: date) -> str:
        calls.append((currency, start, end))
        return ecb_csv

    fx = FxRates(conn, fetch=fake_fetch)
    fw = extract_framework(eur_graph(), fx=fx)
    assert fw.cap_value_sek is not None and fw.cap_value_sek > 1_000_000
    assert fw.cap_source == CAP_SOURCE_EFORMS
    # The window is centred on 2026-07-01, the notice's IssueDate, not on today.
    assert calls and calls[0][1] <= date(2026, 7, 1) <= calls[0][2]


# -- needs_review ------------------------------------------------------------


def framework_row(**kwargs: object) -> FrameworkAgreement:
    base = {"notice_id": "1-2026", "cap_value_sek": 1_000, "cap_confidence": 0.9}
    return FrameworkAgreement(**{**base, **kwargs})  # type: ignore[arg-type]


def test_needs_review_boundary_is_exclusive() -> None:
    assert needs_review(framework_row(cap_confidence=REVIEW_THRESHOLD)) is False
    assert needs_review(framework_row(cap_confidence=0.699)) is True


def test_a_missing_cap_always_needs_review() -> None:
    assert needs_review(framework_row(cap_value_sek=None, cap_confidence=0.99)) is True


def test_a_cap_without_a_confidence_needs_review() -> None:
    """An unexplained cap is exactly what a human has to look at."""
    assert needs_review(framework_row(cap_confidence=None)) is True


# -- formatting --------------------------------------------------------------


def test_format_amount_groups_thousands_for_a_human_reader() -> None:
    assert format_amount(Decimal("4000000"), "SEK") == "4 000 000 SEK"
    assert format_amount(Decimal("4000000"), None) == "4 000 000 SEK"
    assert format_amount(Decimal("1000000"), "EUR") == "1 000 000 EUR"


# -- storage round trip ------------------------------------------------------


def test_extract_and_store_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    rows = [extract_framework(graph_of(n)) for n in ("1884-2026", "15840-2026", "8020-2026")]
    for _ in range(2):
        with Storage(db) as storage:
            for row in rows:
                storage.upsert_framework(row)
    with Storage(db) as storage:
        stored = storage.list_frameworks()
        queue = storage.list_frameworks(needs_review=True)
    by_id = {row.notice_id: row for row in stored}
    assert len(stored) == 3
    assert set(by_id) == {"1884-2026", "15840-2026", "8020-2026"}
    assert by_id["1884-2026"].cap_value_sek == 3_000_000
    assert by_id["15840-2026"].cap_value_sek == 30_000_000
    assert {row.notice_id for row in queue} == {"8020-2026"}


def test_the_python_and_sql_review_queues_agree(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    rows = [
        framework_row(notice_id="a-2026", cap_confidence=0.99),
        framework_row(notice_id="b-2026", cap_confidence=0.5),
        framework_row(notice_id="c-2026", cap_value_sek=None, cap_confidence=None),
        framework_row(notice_id="d-2026", cap_confidence=None),
    ]
    with Storage(db) as storage:
        for row in rows:
            storage.upsert_framework(row)
        sql_queue = {row.notice_id for row in storage.list_frameworks(needs_review=True)}
    assert sql_queue == {row.notice_id for row in rows if needs_review(row)}
    assert sql_queue == {"b-2026", "c-2026", "d-2026"}


# -- validation report -------------------------------------------------------


def test_validate_counts_the_denominator_not_only_the_percentage() -> None:
    rows = [extract_framework(graph_of(n)) for n in ("1884-2026", "15840-2026", "8020-2026")]
    report = validate(rows, skipped=[("9-2026", "unreadable")])
    assert report.notices == 3
    assert report.frameworks == 3
    assert report.with_cap == 2
    assert report.needing_review == 1
    assert report.per_source[CAP_SOURCE_EFORMS][0] == 2
    rendered = report.render()
    assert "2 av 3" in rendered
    assert "9-2026: unreadable" in rendered


def test_validate_reports_no_frameworks_without_dividing_by_zero() -> None:
    assert "inga ramavtal" in validate([], skipped=[]).render()


# -- prose extraction --------------------------------------------------------


def test_notice_text_collects_prose_and_survives_a_broken_document() -> None:
    text = notice_text((FIXTURES / "eforms_8020-2026.xml").read_bytes())
    assert isinstance(text, str)
    assert notice_text(b"not xml at all") == ""
