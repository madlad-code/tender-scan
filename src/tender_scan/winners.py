"""M2 — leverantörsregister: every supplier awarded a place on a framework.

A framework agreement is usually won by several suppliers per lot — five to
fifteen is ordinary — and which of them actually receives the call-offs is
decided by the rangordning. Taking only the first winner, or attaching a rank
that was never published, would produce a prospect list that looks right and
is wrong.

## Why this reads the notice XML and not the search API

The TED search API returns winners as flat arrays with no lot linkage.
Across the 518-notice Swedish CPV-72 corpus, `winner-name` and
`winner-identifier` have different lengths in 310 notices — 60 % — with one
real notice carrying three identifiers and a single name. Pairing them by
index would silently attribute contracts to the wrong company. Every field
here therefore comes from the resolved eForms graph.

## Two published values that mean the opposite of what they look like

* `LotTender/LegalMonetaryTotal/PayableAmount` is frequently `0`. That means
  the buyer published no value, not that the contract is worth nothing.
  Stored as NULL, because a 0 would poison every sum downstream.
* `ValueKnownIndicator` sits under `SubcontractingTerm` and refers to the
  *subcontracting* value. It says nothing about `PayableAmount` and must not
  gate it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from tender_scan.eforms import LotTender, NoticeGraph, Organization
from tender_scan.fx import FxError, FxRates
from tender_scan.orgnr import normalize_orgnr
from tender_scan.records import AwardWinner

FUZZY_THRESHOLD = 0.90

# Confidence for an orgnr taken straight from the notice's own CompanyID.
EXACT_CONFIDENCE = 1.0

# Company forms, stripped before names are compared. Kept in one place: a
# second copy that drifts is how "Advania Sverige AB" stops matching
# "Advania Sverige".
_COMPANY_FORMS = (
    "aktiebolag",
    "ab publ",
    "ab",
    "handelsbolag",
    "hb",
    "kommanditbolag",
    "kb",
    "ekonomisk forening",
    "ekonomisk förening",
    "ek for",
    "ideell forening",
    "as",
    "a/s",
    "oy",
    "gmbh",
    "ltd",
    "limited",
    "inc",
    "bv",
    "b.v.",
    "nv",
    "plc",
)
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_company_name(name: str | None) -> str:
    """Casefold, drop punctuation and the company form, collapse whitespace.

    The single place name normalisation happens, for both fuzzy matching here
    and payment-to-winner matching in M4.
    """
    if not name:
        return ""
    text = _PUNCTUATION.sub(" ", name.casefold())
    text = _WHITESPACE.sub(" ", text).strip()
    # "(publ)" has already lost its parentheses; strip the forms from the end,
    # repeatedly, so "Advania Sverige AB (publ)" reduces the same as "AB".
    changed = True
    while changed:
        changed = False
        for form in _COMPANY_FORMS:
            if text.endswith(" " + form):
                text = text[: -len(form) - 1].strip()
                changed = True
    return text


# -- orgnr resolution --------------------------------------------------------


def fuzzy_match_orgnr(
    name: str | None,
    known: Mapping[str, str],
    threshold: float = FUZZY_THRESHOLD,
) -> tuple[str | None, float | None]:
    """Best orgnr for a supplier name among names whose orgnr is already known.

    Returns `(None, None)` below the threshold rather than the closest guess.
    The spec's rule is "gissa aldrig tyst": a near miss stored as a match would
    attach one company's call-offs to another and never announce itself.
    """
    target = normalize_company_name(name)
    if not target or not known:
        return None, None
    best_orgnr: str | None = None
    best_ratio = 0.0
    for candidate_name, candidate_orgnr in known.items():
        candidate = normalize_company_name(candidate_name)
        if not candidate:
            continue
        ratio = SequenceMatcher(None, target, candidate).ratio()
        if ratio > best_ratio:
            best_orgnr, best_ratio = candidate_orgnr, ratio
    if best_orgnr is None or best_ratio < threshold:
        return None, None
    return best_orgnr, round(best_ratio, 4)


def resolve_orgnr(
    org: Organization,
    known: Mapping[str, str] | None = None,
) -> tuple[str | None, float | None]:
    """The supplier's orgnr and how sure we are of it.

    Confidence is 1.0 for an orgnr the notice itself published, the similarity
    ratio for a fuzzy name match, and None when neither worked — in which case
    the orgnr is None too, never a best guess.
    """
    exact = normalize_orgnr(org.company_id)
    if exact is not None:
        return exact, EXACT_CONFIDENCE
    if known:
        return fuzzy_match_orgnr(org.name, known)
    return None, None


# -- extraction --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WinnerMatch:
    winner: AwardWinner
    org_id: str | None  # the ORG-nnnn the row came from, for traceability
    contract_ids: tuple[str, ...]


@dataclass(slots=True)
class _Accumulator:
    org: Organization
    lot_id: str
    tenders: dict[str, LotTender] = field(default_factory=dict)
    contracts: set[str] = field(default_factory=set)

    def award_date(self, graph: NoticeGraph) -> str | None:
        """The latest AwardDate among the contracts that settled these tenders."""
        dates = [
            contract.award_date
            for contract_id in self.contracts
            if (contract := graph.settled_contracts.get(contract_id)) is not None
            and contract.award_date
        ]
        return max(dates) if dates else None


def _issue_date(graph: NoticeGraph) -> date | None:
    try:
        return date.fromisoformat(graph.issue_date) if graph.issue_date else None
    except ValueError:
        return None


def _awarded_value(
    tenders: dict[str, LotTender], fx: FxRates | None, on: date | None
) -> int | None:
    """Sum of the distinct tenders' published values, or None when none published.

    Tenders are keyed by id before they get here, so a tender reached through
    both a SettledContract and a bare LotResult stub is counted once. A
    published 0 is dropped, not summed: it means "value not disclosed".
    """
    total: int | None = None
    for tender in tenders.values():
        amount = tender.payable_amount
        if amount is None or amount.value <= 0:
            continue
        currency = (amount.currency or "SEK").upper()
        if currency == "SEK":
            value = int(amount.value.quantize(Decimal(1)))
        elif fx is not None and on is not None:
            try:
                value = fx.to_sek(amount.value, currency, on)
            except FxError:
                continue  # an unconvertible amount is left out, never guessed
        else:
            continue
        total = value if total is None else total + value
    return total


def _rank(tenders: dict[str, LotTender]) -> int | None:
    """The best published rank. Never synthesised from list position."""
    ranks = [t.rank for t in tenders.values() if t.rank is not None]
    return min(ranks) if ranks else None


def extract_winner_matches(
    graph: NoticeGraph,
    *,
    fx: FxRates | None = None,
    known: Mapping[str, str] | None = None,
) -> list[WinnerMatch]:
    """One row per (supplier, lot), with the ORG id and contracts it came from."""
    accumulators: dict[tuple[str, str], _Accumulator] = {}
    for result in graph.lot_results:
        for tender_id, contract_id in graph.tenders_of(result):
            tender = graph.lot_tenders.get(tender_id)
            if tender is None:
                continue
            lot_id = result.lot_id or tender.lot_id
            if lot_id is None:
                continue
            if tender.lot_id is not None and tender.lot_id != lot_id:
                continue  # one contract can settle tenders across several lots
            org_id = graph.tendering_parties.get(tender.tendering_party_id or "")
            org = graph.organizations.get(org_id or "")
            if org is None or not org.name:
                continue
            key = (lot_id, org.org_id)
            accumulator = accumulators.setdefault(key, _Accumulator(org, lot_id))
            accumulator.tenders[tender_id] = tender
            if contract_id is not None:
                accumulator.contracts.add(contract_id)

    on = _issue_date(graph)
    matches: list[WinnerMatch] = []
    seen: set[tuple[str, str]] = set()
    for (lot_id, _), accumulator in sorted(accumulators.items()):
        name = accumulator.org.name or ""
        if (name, lot_id) in seen:
            # Two ORG entries with the same name on one lot would collide on the
            # table's primary key. Keep the first and let the second go.
            continue
        seen.add((name, lot_id))
        supplier_orgnr, confidence = resolve_orgnr(accumulator.org, known)
        matches.append(
            WinnerMatch(
                winner=AwardWinner(
                    notice_id=graph.notice_id,
                    supplier_name=name,
                    supplier_orgnr=supplier_orgnr,
                    lot_id=lot_id,
                    rank=_rank(accumulator.tenders),
                    awarded_value_sek=_awarded_value(accumulator.tenders, fx, on),
                    match_confidence=confidence,
                    award_date=accumulator.award_date(graph),
                ),
                org_id=accumulator.org.org_id,
                contract_ids=tuple(sorted(accumulator.contracts)),
            )
        )
    return matches


def extract_winners(
    graph: NoticeGraph,
    *,
    fx: FxRates | None = None,
    known: Mapping[str, str] | None = None,
) -> list[AwardWinner]:
    """Every supplier awarded a place on this notice, one row per lot."""
    return [match.winner for match in extract_winner_matches(graph, fx=fx, known=known)]


# -- corpus summary ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WinnerSummary:
    notices: int
    rows: int
    with_orgnr: int
    fuzzy_matched: int
    with_rank: int
    with_value: int
    skipped: list[tuple[str, str]]

    def render(self) -> str:
        lines = [
            f"Notiser lästa:            {self.notices}",
            f"Leverantörsrader:         {self.rows}",
            f"Med giltigt orgnr:        {self.with_orgnr} av {self.rows}",
            f"Varav namnmatchade:       {self.fuzzy_matched}",
            f"Med publicerad rangordning: {self.with_rank} av {self.rows}",
            f"Med publicerat värde:     {self.with_value} av {self.rows}",
        ]
        if self.skipped:
            lines.append(f"Överhoppade ({len(self.skipped)}):")
            lines.extend(f"  {notice_id}: {reason}" for notice_id, reason in self.skipped)
        return "\n".join(lines)


def summarize(
    rows: list[AwardWinner], notices: int, skipped: list[tuple[str, str]]
) -> WinnerSummary:
    return WinnerSummary(
        notices=notices,
        rows=len(rows),
        with_orgnr=sum(1 for row in rows if row.supplier_orgnr),
        fuzzy_matched=sum(
            1
            for row in rows
            if row.supplier_orgnr
            and row.match_confidence is not None
            and row.match_confidence < EXACT_CONFIDENCE
        ),
        with_rank=sum(1 for row in rows if row.rank is not None),
        with_value=sum(1 for row in rows if row.awarded_value_sek is not None),
        skipped=skipped,
    )
