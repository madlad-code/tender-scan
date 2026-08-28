"""Takvolymsextraktion — pinning down one framework agreement's ceiling.

The whole product reduces to one number, `utnyttjandegrad = avropat / takvolym`.
This module produces the denominator, and it is the harder half: the numerator
is arithmetic on invoice rows, while the ceiling has to be dug out of a notice
whose publisher may have stated it two or three times, inconsistently.

Three things this module refuses to do, all of them because the spec says the
error would be invisible:

* It never lets an *estimated* value stand in for a ceiling. When only an
  estimate is published, `cap_value_sek` is NULL and the estimate lives in its
  own column. A report can say "no ceiling published"; it cannot survive
  quietly dividing by a forecast.
* It never silently reconciles disagreeing published figures. Every choice is
  recorded in `raw_excerpt` with both numbers, and the doubt is carried by
  `cap_confidence` so the manual review queue can pick it up.
* It never hardcodes a currency rate. Conversion goes through `fx.py` at the
  notice's own issue date, or the cap stays NULL.

Measured against 137 real Swedish CPV-72 framework notices; `frameworks
validate` reprints those numbers from the cached corpus at any time.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from tender_scan import money
from tender_scan.eforms import Amount, NoticeGraph
from tender_scan.fx import FxError, FxRates
from tender_scan.orgnr import normalize_orgnr
from tender_scan.records import FrameworkAgreement

CAP_SOURCE_EFORMS = "eforms_field"
CAP_SOURCE_REGEX = "document_regex"
CAP_SOURCE_MANUAL = "manual"

REVIEW_THRESHOLD = 0.7

BASIS_NOTICE_OVERALL = "notice-overall-maximum"
BASIS_NOTICE_FRAMEWORK = "notice-framework-maximum"
BASIS_LOT_SUM = "lot-maximum-sum"

# Base confidences. A structured eForms field is a number the buyer entered in a
# form field labelled "maximum value"; a regex over prose is an inference.
CONF_STRUCTURED = 0.95
CONF_STRUCTURED_PARTIAL = 0.80  # a lot sum missing some lots is a lower bound
CONF_AGREEMENT = 0.98  # two independent fields stating the same number
CONF_LOT_SUM_WINS = 0.75
CONF_NOTICE_WINS = 0.80
CONF_REGEX_CAP = 0.60

# Multiplicative penalties, applied after selection.
PENALTY_APPROXIMATE_EXCEEDS = 0.8
PENALTY_EQUALS_ESTIMATE = 0.9

AGREEMENT_TOLERANCE = Decimal("0.01")  # 1 %


@dataclass(frozen=True, slots=True)
class CapCandidate:
    amount: Decimal
    currency: str | None
    source: str
    basis: str
    confidence: float
    excerpt: str


# -- formatting --------------------------------------------------------------


def format_amount(value: Decimal, currency: str | None) -> str:
    """`4000000` -> `4 000 000 SEK`, for excerpts a human has to read."""
    quantized = value.quantize(Decimal(1)) if value == value.to_integral_value() else value
    grouped = f"{quantized:,}".replace(",", "\x20")  # plain space, not NBSP
    return f"{grouped} {currency or 'SEK'}"


# -- candidates --------------------------------------------------------------


def _framework_lot_ids(graph: NoticeGraph) -> set[str]:
    return {
        lot_id for lot_id, lot in graph.lots.items() if lot.framework_type not in (None, "none")
    }


def _lot_ceilings(graph: NoticeGraph) -> tuple[dict[str, Amount], set[str]]:
    """Per-lot ceilings, and the lot ids that contributed one.

    A lot can publish its ceiling in two places — `LotResult`'s
    `MaximumValueAmount` and the lot project's `FrameworkMaximumAmount`. They
    are the same business term (BT-271) reached by two routes, so a lot that
    carries both must be counted once or the sum doubles.
    """
    ceilings: dict[str, Amount] = {}
    for result in graph.lot_results:
        if result.lot_id is not None and result.max_value is not None:
            ceilings[result.lot_id] = result.max_value
    for lot_id, lot in graph.lots.items():
        if lot_id not in ceilings and lot.framework_maximum is not None:
            ceilings[lot_id] = lot.framework_maximum
    return ceilings, set(ceilings)


def _notice_candidate(amount: Amount | None, basis: str, label: str) -> CapCandidate | None:
    if amount is None or amount.value <= 0:
        return None  # a published 0 is "not stated", never a ceiling of nothing
    return CapCandidate(
        amount=amount.value,
        currency=amount.currency,
        source=CAP_SOURCE_EFORMS,
        basis=basis,
        confidence=CONF_STRUCTURED,
        excerpt=f"{label} = {format_amount(amount.value, amount.currency)}",
    )


def _lot_sum_candidate(graph: NoticeGraph) -> CapCandidate | None:
    ceilings, contributing = _lot_ceilings(graph)
    positive = {lot_id: a for lot_id, a in ceilings.items() if a.value > 0}
    if not positive:
        return None

    currencies = {a.currency for a in positive.values()}
    if len(currencies) > 1:
        # Summing across currencies would need a per-lot conversion this
        # candidate has no date for. Drop it rather than add SEK to EUR.
        return None
    currency = currencies.pop()

    total = sum((a.value for a in positive.values()), Decimal(0))
    framework_lots = _framework_lot_ids(graph)
    missing = framework_lots - contributing
    parts = ", ".join(
        f"{lot_id} {format_amount(a.value, a.currency)}" for lot_id, a in sorted(positive.items())
    )
    if missing:
        excerpt = (
            f"Summa av publicerade lot-tak ({parts}) = {format_amount(total, currency)}. "
            f"Undre gräns: {len(missing)} av {len(framework_lots)} ramavtalsdelar "
            f"({', '.join(sorted(missing))}) saknar publicerat tak."
        )
        confidence = CONF_STRUCTURED_PARTIAL
    else:
        excerpt = f"Summa av publicerade lot-tak ({parts}) = {format_amount(total, currency)}"
        confidence = CONF_STRUCTURED
    return CapCandidate(
        amount=total,
        currency=currency,
        source=CAP_SOURCE_EFORMS,
        basis=BASIS_LOT_SUM,
        confidence=confidence,
        excerpt=excerpt,
    )


def cap_candidates(graph: NoticeGraph, text: str | None = None) -> list[CapCandidate]:
    """Every ceiling the notice offers, structured first, regex only as a fallback."""
    candidates: list[CapCandidate] = []
    overall = _notice_candidate(
        graph.overall_maximum, BASIS_NOTICE_OVERALL, "BT-118 OverallMaximumFrameworkContractsAmount"
    )
    if overall is not None:
        candidates.append(overall)
    framework = _notice_candidate(
        graph.framework_maximum, BASIS_NOTICE_FRAMEWORK, "BT-271 FrameworkMaximumAmount"
    )
    if framework is not None:
        candidates.append(framework)
    lot_sum = _lot_sum_candidate(graph)
    if lot_sum is not None:
        candidates.append(lot_sum)

    if candidates or not text:
        return candidates

    for match in money.find_caps(text):
        if match.amount <= 0:
            continue
        candidates.append(
            CapCandidate(
                amount=match.amount,
                currency=match.currency,
                source=CAP_SOURCE_REGEX,
                basis=match.pattern,
                confidence=min(match.confidence, CONF_REGEX_CAP),
                excerpt=f'Textträff "{match.pattern}": {match.excerpt}',
            )
        )
    return candidates


# -- selection ---------------------------------------------------------------


def _agree(left: Decimal, right: Decimal) -> bool:
    """Within 1 % of the larger of the two."""
    larger = max(abs(left), abs(right))
    return larger == 0 or abs(left - right) / larger <= AGREEMENT_TOLERANCE


def _merge_notice_level(items: list[CapCandidate]) -> CapCandidate | None:
    """Reconcile BT-118 against BT-271 when a notice publishes both."""
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    first, second = items[0], items[1]
    both = f"{first.excerpt}; {second.excerpt}"
    if _agree(first.amount, second.amount):
        return replace(first, confidence=CONF_AGREEMENT, excerpt=f"{both} (samstämmiga)")
    # They disagree and neither is provably the total. Take the larger: a
    # ceiling is an upper bound, and choosing the smaller of two published
    # upper bounds is what produces a utilisation rate above 100 %. Both
    # figures go in the excerpt so a reviewer can overrule this.
    larger = first if first.amount >= second.amount else second
    picked = format_amount(larger.amount, larger.currency)
    return replace(
        larger,
        confidence=CONF_NOTICE_WINS,
        excerpt=f"{both} — motstridiga, valde det högre ({picked})",
    )


def choose_cap(candidates: list[CapCandidate]) -> CapCandidate | None:
    """One ceiling, chosen by a documented rule, with the doubt in the confidence."""
    structured = [c for c in candidates if c.source == CAP_SOURCE_EFORMS]
    if not structured:
        regex = [c for c in candidates if c.source == CAP_SOURCE_REGEX]
        if not regex:
            return None
        return max(regex, key=lambda c: (c.confidence, c.amount))

    notice = _merge_notice_level(
        [c for c in structured if c.basis in (BASIS_NOTICE_OVERALL, BASIS_NOTICE_FRAMEWORK)]
    )
    lot_sum = next((c for c in structured if c.basis == BASIS_LOT_SUM), None)
    if notice is None:
        return lot_sum
    if lot_sum is None:
        return notice
    if lot_sum.currency != notice.currency:
        return notice  # incomparable without a conversion date; keep the stated total

    both = f"{notice.excerpt}; {lot_sum.excerpt}"
    if _agree(notice.amount, lot_sum.amount):
        return replace(notice, confidence=CONF_AGREEMENT, excerpt=f"{both} (samstämmiga)")
    if lot_sum.amount > notice.amount:
        # The lots alone add up to more than the notice-level figure, so that
        # figure is provably not the total for the agreement (15840-2026).
        return replace(
            lot_sum,
            confidence=CONF_LOT_SUM_WINS,
            excerpt=f"{both} — lot-summan överstiger notisnivån, valde lot-summan",
        )
    # The notice-level figure is larger, which is what happens when some lots
    # published no ceiling: the sum is then an incomplete lower bound.
    return replace(
        notice,
        confidence=CONF_NOTICE_WINS,
        excerpt=f"{both} — lot-summan är ofullständig, valde notisnivån",
    )


# -- conversion and dates ----------------------------------------------------


def _issue_date(graph: NoticeGraph) -> date | None:
    try:
        return date.fromisoformat(graph.issue_date) if graph.issue_date else None
    except ValueError:
        return None


def _to_sek(
    value: Decimal | None, currency: str | None, fx: FxRates | None, on: date | None
) -> tuple[int | None, str | None]:
    """Integer SEK, plus a note when the conversion could not be made."""
    if value is None:
        return None, None
    code = (currency or "SEK").upper()
    if code == "SEK":
        return money.to_int_sek(value), None
    if fx is None or on is None:
        return None, (
            f"Beloppet är i {code} och kunde inte omräknas "
            f"({'ingen växelkurskälla' if fx is None else 'saknat publiceringsdatum'})."
        )
    try:
        return fx.to_sek(value, code, on), None
    except FxError as exc:
        return None, f"Växelkurs saknas för {code}: {exc}"


def _months_between(start: str | None, end: str | None) -> int | None:
    """Whole months, rounded down. None when either date is missing or unusable."""
    if not start or not end:
        return None
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return None
    if last < first:
        return None
    months = (last.year - first.year) * 12 + (last.month - first.month)
    if last.day < first.day:
        months -= 1
    return max(months, 0)


def _period(graph: NoticeGraph) -> tuple[str | None, str | None]:
    starts = sorted(lot.period_start for lot in graph.lots.values() if lot.period_start)
    ends = sorted(lot.period_end for lot in graph.lots.values() if lot.period_end)
    return (starts[0] if starts else None, ends[-1] if ends else None)


# -- the record --------------------------------------------------------------


def _penalties(graph: NoticeGraph, chosen: CapCandidate) -> tuple[float, list[str]]:
    confidence = chosen.confidence
    notes: list[str] = []
    approximate = graph.overall_approximate
    if approximate is not None and approximate.value > chosen.amount:
        confidence *= PENALTY_APPROXIMATE_EXCEEDS
        notes.append(
            f"Prognosen ({format_amount(approximate.value, approximate.currency)}) "
            f"överstiger valt tak ({format_amount(chosen.amount, chosen.currency)})."
        )
    estimated = graph.estimated_overall
    if estimated is not None and estimated.value == chosen.amount:
        confidence *= PENALTY_EQUALS_ESTIMATE
        notes.append(
            "Taket är identiskt med uppskattat värde — fälten kan ha fyllts i med samma siffra."
        )
    return round(confidence, 4), notes


def extract_framework(
    graph: NoticeGraph,
    *,
    fx: FxRates | None = None,
    text: str | None = None,
) -> FrameworkAgreement:
    """One notice into one `framework_agreements` row.

    A notice that is not a framework still produces a row, with
    `is_framework = False` and a NULL cap: a recorded negative beats a silent
    omission when the corpus is later re-counted.
    """
    on = _issue_date(graph)
    buyer = graph.buyer
    start, end = _period(graph)

    estimated_sek, estimated_note = _to_sek(
        graph.estimated_overall.value if graph.estimated_overall else None,
        graph.estimated_overall.currency if graph.estimated_overall else None,
        fx,
        on,
    )

    chosen = choose_cap(cap_candidates(graph, text=text)) if graph.is_framework() else None
    cap_sek: int | None = None
    cap_source: str | None = None
    cap_confidence: float | None = None
    excerpt_parts: list[str] = []

    if chosen is not None:
        cap_confidence, notes = _penalties(graph, chosen)
        cap_sek, conversion_note = _to_sek(chosen.amount, chosen.currency, fx, on)
        excerpt_parts = [chosen.excerpt, *notes]
        if conversion_note is not None:
            excerpt_parts.append(conversion_note)
            cap_confidence = None  # no stored cap, so no confidence to report
        else:
            cap_source = chosen.source
    elif graph.is_framework():
        excerpt_parts = ["Inget publicerat tak i notisen."]
    if estimated_note is not None:
        excerpt_parts.append(f"Uppskattat värde: {estimated_note}")

    return FrameworkAgreement(
        notice_id=graph.notice_id,
        buyer_name=buyer.name if buyer else None,
        buyer_orgnr=normalize_orgnr(buyer.company_id) if buyer else None,
        title=graph.title,
        is_framework=graph.is_framework(),
        cap_value_sek=cap_sek,
        estimated_value_sek=estimated_sek,
        cap_source=cap_source,
        cap_confidence=cap_confidence,
        start_date=start,
        end_date=end,
        max_duration_months=_months_between(start, end),
        cpv_main=graph.cpv_main,
        raw_excerpt=" ".join(excerpt_parts) or None,
    )


def needs_review(fw: FrameworkAgreement) -> bool:
    """True when a human still has to look at this row.

    A cap with no confidence counts as needing review: the extractor always
    records one alongside a cap, so a NULL there means the row came from
    somewhere else and is unexplained.
    """
    if fw.cap_value_sek is None:
        return True
    return fw.cap_confidence is None or fw.cap_confidence < REVIEW_THRESHOLD


# -- corpus validation -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationReport:
    notices: int
    frameworks: int
    with_cap: int
    per_source: dict[str, tuple[int, float]]  # source -> (count, mean confidence)
    needing_review: int
    skipped: list[tuple[str, str]]  # (notice_id, reason)

    def render(self) -> str:
        lines = [
            f"Notiser lästa:            {self.notices}",
            f"Varav ramavtal:           {self.frameworks}",
            f"Ramavtal med takvolym:    {self.with_cap} av {self.frameworks}"
            + (
                f" ({self.with_cap / self.frameworks:.1%})"
                if self.frameworks
                else " (inga ramavtal i urvalet)"
            ),
            f"I manuell granskningskö:  {self.needing_review}",
            "",
            "Per cap_source:",
        ]
        if not self.per_source:
            lines.append("  (ingen)")
        for source, (count, mean) in sorted(self.per_source.items()):
            lines.append(f"  {source:16} {count:4}  medelkonfidens {mean:.2f}")
        if self.skipped:
            lines.append("")
            lines.append(f"Överhoppade ({len(self.skipped)}):")
            lines.extend(f"  {notice_id}: {reason}" for notice_id, reason in self.skipped)
        return "\n".join(lines)


def validate(
    rows: Iterable[FrameworkAgreement], skipped: list[tuple[str, str]]
) -> ValidationReport:
    """Aggregate extracted rows into the hit-rate report the spec asks for."""
    rows = list(rows)
    frameworks = [row for row in rows if row.is_framework]
    with_cap = [row for row in frameworks if row.cap_value_sek is not None]
    per_source: dict[str, tuple[int, float]] = {}
    for source in {row.cap_source for row in with_cap if row.cap_source}:
        matching = [row for row in with_cap if row.cap_source == source]
        confidences = [row.cap_confidence for row in matching if row.cap_confidence is not None]
        mean = sum(confidences) / len(confidences) if confidences else 0.0
        per_source[source] = (len(matching), mean)
    return ValidationReport(
        notices=len(rows),
        frameworks=len(frameworks),
        with_cap=len(with_cap),
        per_source=per_source,
        needing_review=sum(1 for row in frameworks if needs_review(row)),
        skipped=skipped,
    )
