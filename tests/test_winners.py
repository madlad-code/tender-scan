"""M2 — leverantörsregister.

The mis-join this module exists to prevent is silent: a winner attached to the
wrong lot, or an orgnr guessed from a similar name, produces a prospect list
that looks entirely plausible. So the tests assert the *negative* cases as hard
as the positive ones.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from tender_scan.eforms import Amount, NoticeGraph, Organization, parse_graph
from tender_scan.fx import FxRates
from tender_scan.records import AwardWinner
from tender_scan.storage import Storage
from tender_scan.winners import (
    EXACT_CONFIDENCE,
    extract_winner_matches,
    extract_winners,
    fuzzy_match_orgnr,
    normalize_company_name,
    resolve_orgnr,
    summarize,
)

FIXTURES = Path(__file__).parent / "fixtures"


def graph_of(notice_id: str) -> NoticeGraph:
    return parse_graph((FIXTURES / f"eforms_{notice_id}.xml").read_bytes(), notice_id)


# -- the winner graph --------------------------------------------------------


def test_all_winners_of_a_lot_are_taken_not_only_the_first() -> None:
    winners = extract_winners(graph_of("1884-2026"))
    assert {w.supplier_name for w in winners} == {"AFRY Sweden AB", "PlantVision AB"}
    assert all(w.lot_id == "LOT-0000" for w in winners)
    assert all(w.supplier_orgnr is not None for w in winners)
    assert all(len(w.supplier_orgnr) == 11 for w in winners)  # NNNNNN-NNNN


def test_winners_land_on_the_right_lot_and_do_not_leak_between_lots() -> None:
    """15840-2026 has three lots. A length check would not catch a mis-join."""
    winners = extract_winners(graph_of("15840-2026"))
    by_lot = {w.lot_id: w.supplier_name for w in winners}
    assert set(by_lot) == {"LOT-0001", "LOT-0002", "LOT-0003"}
    assert len(winners) == 3  # one row per lot, not one row per lot per tender


def test_a_supplier_on_several_lots_gets_one_row_per_lot() -> None:
    winners = extract_winners(graph_of("15840-2026"))
    assert len({w.supplier_name for w in winners}) == 1
    assert len(winners) == 3


def test_the_org_id_and_contracts_are_kept_for_traceability() -> None:
    matches = extract_winner_matches(graph_of("1884-2026"))
    assert all(m.org_id and m.org_id.startswith("ORG-") for m in matches)
    assert any(m.contract_ids for m in matches)


# -- rank --------------------------------------------------------------------


def test_a_published_rank_is_read_as_an_integer() -> None:
    winners = extract_winners(graph_of("470310-2026"))
    ranked = {w.supplier_name: w.rank for w in winners}
    assert ranked["Telia Cygate AB"] == 1


def test_rank_is_none_when_the_notice_publishes_no_ranking() -> None:
    """1884-2026 carries no RankCode; a position-derived rank would be a fabrication."""
    assert all(w.rank is None for w in extract_winners(graph_of("1884-2026")))


# -- awarded value -----------------------------------------------------------


def test_a_payable_amount_of_zero_means_undisclosed_not_zero() -> None:
    """Atea's tender in 470310-2026 publishes PayableAmount 0."""
    winners = {w.supplier_name: w for w in extract_winners(graph_of("470310-2026"))}
    assert winners["Atea Sverige AB"].awarded_value_sek is None
    assert winners["Telia Cygate AB"].awarded_value_sek == 160_000_000


def test_an_absent_payable_amount_is_none() -> None:
    assert all(w.awarded_value_sek is None for w in extract_winners(graph_of("1884-2026")))


def test_a_foreign_currency_value_needs_a_rate_source(ecb_csv: str) -> None:
    graph = graph_of("431354-2026")
    tenders = {
        tid: replace(t, payable_amount=Amount(Decimal("1000"), "EUR"))
        for tid, t in graph.lot_tenders.items()
    }
    eur = replace(graph, lot_tenders=tenders, issue_date="2026-07-01")

    assert extract_winners(eur)[0].awarded_value_sek is None

    fx = FxRates(sqlite3.connect(":memory:"), fetch=lambda c, s, e: ecb_csv)
    converted = extract_winners(eur, fx=fx)[0].awarded_value_sek
    assert converted is not None and converted > 1_000


# -- orgnr resolution --------------------------------------------------------


def org(name: str, company_id: str | None) -> Organization:
    return Organization(
        org_id="ORG-0001", name=name, company_id=company_id, country="SWE", city="Lund"
    )


def test_a_company_id_without_a_scheme_attribute_still_resolves() -> None:
    """8020-2026's CompanyID carries no schemeID; requiring one would drop it."""
    winner = extract_winners(graph_of("8020-2026"))[0]
    assert winner.supplier_orgnr == "559052-2248"
    assert winner.match_confidence == EXACT_CONFIDENCE


def test_an_id_that_fails_luhn_resolves_to_none_never_to_a_close_orgnr() -> None:
    resolved, confidence = resolve_orgnr(org("Utländskt Bolag", "1234567890"))
    assert resolved is None
    assert confidence is None


def test_a_foreign_id_is_not_fuzzy_matched_into_a_swedish_orgnr() -> None:
    known = {"Advania Sverige AB": "556190-4074"}
    resolved, confidence = resolve_orgnr(org("Nordic Semiconductor ASA", "NO123456"), known)
    assert resolved is None
    assert confidence is None


def test_fuzzy_matching_accepts_a_company_form_difference() -> None:
    known = {"Advania Sverige": "556190-4074"}
    resolved, confidence = fuzzy_match_orgnr("Advania Sverige AB", known)
    assert resolved == "556190-4074"
    assert confidence is not None and confidence >= 0.90


def test_fuzzy_matching_rejects_a_different_company_with_a_similar_name() -> None:
    known = {"Advinia Service AB": "556000-0001"}
    resolved, confidence = fuzzy_match_orgnr("Advania Sverige AB", known)
    assert resolved is None
    assert confidence is None


def test_fuzzy_matching_returns_nothing_without_a_known_set() -> None:
    assert fuzzy_match_orgnr("Advania Sverige AB", {}) == (None, None)
    assert fuzzy_match_orgnr(None, {"a": "1"}) == (None, None)


def test_a_notice_orgnr_beats_a_fuzzy_match() -> None:
    known = {"AFRY Sweden AB": "556000-0001"}
    resolved, confidence = resolve_orgnr(org("AFRY Sweden AB", "5562248012"), known)
    assert resolved == "556224-8012"
    assert confidence == EXACT_CONFIDENCE


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Advania Sverige AB", "advania sverige"),
        ("Advania Sverige AB (publ)", "advania sverige"),
        ("ATEA SVERIGE AB", "atea sverige"),
        ("Föreningen Ekonomisk Förening", "föreningen"),
        ("Knowit  Solutions   AB", "knowit solutions"),
        ("", ""),
        (None, ""),
    ],
)
def test_company_name_normalization(raw: str | None, normalized: str) -> None:
    assert normalize_company_name(raw) == normalized


# -- storage round trip ------------------------------------------------------


def test_replace_winners_drops_a_removed_supplier_and_leaves_others_alone(
    tmp_path: Path,
) -> None:
    db = tmp_path / "t.sqlite3"
    first = extract_winners(graph_of("1884-2026"))
    other = extract_winners(graph_of("8020-2026"))
    with Storage(db) as storage:
        storage.replace_winners("1884-2026", first)
        storage.replace_winners("8020-2026", other)
        storage.replace_winners("1884-2026", first[:1])
        remaining = {w.supplier_name for w in storage.list_winners("1884-2026")}
        untouched = storage.list_winners("8020-2026")
    assert remaining == {first[0].supplier_name}
    assert len(untouched) == len(other)


def test_extraction_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    rows = extract_winners(graph_of("15840-2026"))
    for _ in range(2):
        with Storage(db) as storage:
            storage.replace_winners("15840-2026", rows)
    with Storage(db) as storage:
        stored = storage.list_winners("15840-2026")
    assert len(stored) == 3
    assert [(w.lot_id, w.supplier_name) for w in stored] == [
        (w.lot_id, w.supplier_name) for w in sorted(rows, key=lambda w: (w.lot_id, w.supplier_name))
    ]


# -- summary -----------------------------------------------------------------


def test_summary_counts_fuzzy_matches_separately_from_exact_ones() -> None:
    rows = [
        AwardWinner("1-2026", "A AB", "556224-8012", "LOT-0000", rank=1, match_confidence=1.0),
        AwardWinner("1-2026", "B AB", "556336-5989", "LOT-0000", match_confidence=0.94),
        AwardWinner("1-2026", "C AB", None, "LOT-0000"),
    ]
    summary = summarize(rows, notices=1, skipped=[("9-2026", "unreadable")])
    assert summary.with_orgnr == 2
    assert summary.fuzzy_matched == 1
    assert summary.with_rank == 1
    assert summary.with_value == 0
    assert "9-2026: unreadable" in summary.render()


# -- no network --------------------------------------------------------------


def test_extraction_never_reaches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("extraction must not open a socket")

    monkeypatch.setattr("socket.socket", explode)
    assert extract_winners(graph_of("1884-2026"))
