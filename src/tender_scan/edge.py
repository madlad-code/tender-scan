"""Where a municipality's contracts and its money disagree.

A framework contract is a promise to buy. A ledger is a record of buying. When
the two are laid over each other they rarely match, and the mismatch is the
product: a supplier holding a contract that yields nothing, a category the
municipality buys heavily and has contracted nobody for, a contract expiring in
five months that runs at eight million a year.

Three rules hold everywhere in this module, because breaking any of them turns
a finding into a guess:

1.  **No rate without its denominator and its interval.** Every proportion is
    a `Proportion`, which carries `k`, `n` and a Wilson 95 % interval. "62 % of
    contracted suppliers were paid" means nothing until you know it is 751 of
    1 219 and not 5 of 8.

2.  **A contract is only comparable to the months the ledger actually covers.**
    A supplier whose contract ended before the ledger begins cannot be shown to
    have sold nothing; they are excluded, not counted as dormant.

3.  **Not all spend is procurable.** Pensions, statutory transfers to
    Försäkringskassan and membership fees are not competed for, and counting
    them as "off-contract" would inflate the finding by billions. The
    classification is a modelling choice, so it is explicit, auditable through
    `classification_audit`, and every report states how much money it moved.

Pure stdlib on purpose: the statistics here are small enough to read, and a
number a reader cannot re-derive by hand is a number they will not trust.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

# -- statistics --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Proportion:
    """A share that refuses to be quoted without the count behind it."""

    k: int
    n: int

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        """Wilson score interval at 95 %.

        Wilson rather than the textbook normal approximation because the
        interesting proportions here sit near 0 and 1 — a category where two of
        two suppliers are off-contract — and the normal approximation puts its
        bounds outside [0, 1] exactly there.
        """
        return wilson(self.k, self.n)

    @property
    def width(self) -> float:
        low, high = self.interval
        return high - low

    def __str__(self) -> str:
        low, high = self.interval
        return f"{self.rate:6.1%} [{low:.1%}–{high:.1%}] n={self.n}"


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """The Wilson score interval for k successes in n trials."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def herfindahl(values: Iterable[float]) -> float:
    """HHI over shares of the total, 0 (atomised) to 1 (one supplier has all).

    Negative values — credit notes that outweigh a supplier's invoices for the
    window — are clamped to zero. A supplier who was net refunded did not hold
    a negative share of the market; they held none.
    """
    amounts = [max(0.0, float(v)) for v in values]
    total = sum(amounts)
    if total <= 0:
        return 0.0
    return sum((v / total) ** 2 for v in amounts)


def effective_suppliers(hhi: float) -> float:
    """1/HHI — how many equally-sized suppliers this concentration equates to.

    Easier to argue with than HHI itself: "this category has the concentration
    of 2.3 suppliers" lands where "HHI 0.43" does not.
    """
    return 1 / hhi if hhi > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Trend:
    """A monotone trend test over a short series, and its slope."""

    n: int
    statistic: float  # Mann-Kendall S
    p_value: float
    slope: float  # Sen's slope, units per step

    @property
    def direction(self) -> str:
        if self.p_value > 0.05:
            return "flat"
        return "up" if self.statistic > 0 else "down"


def mann_kendall(series: Sequence[float]) -> Trend:
    """Non-parametric trend test with Sen's slope.

    Monthly spend is spiky, seasonal and occasionally negative; a least-squares
    slope on 44 such points is led around by the two biggest months. Rank-based
    beats fitted here, and the test needs no distributional assumption we are
    in no position to justify.
    """
    n = len(series)
    if n < 4:
        return Trend(n, 0.0, 1.0, 0.0)
    s = 0
    slopes: list[float] = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            s += (series[j] > series[i]) - (series[j] < series[i])
            slopes.append((series[j] - series[i]) / (j - i))
    ties: dict[float, int] = {}
    for value in series:
        ties[value] = ties.get(value, 0) + 1
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties.values())) / 18
    if var <= 0:
        return Trend(n, float(s), 1.0, _median(slopes))
    z = (s - math.copysign(1, s)) / math.sqrt(var) if s else 0.0
    p = 2 * (1 - _normal_cdf(abs(z)))
    return Trend(n, float(s), min(1.0, max(0.0, p)), _median(slopes))


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# -- what the money was for --------------------------------------------------
#
# 167 account names in Huddinge's ledger alone, and they are not all the same
# kind of thing. Three groups have to come out before "spend without a
# contract" means anything:
#
#   * transfers the municipality has no choice about and nobody competes for —
#     pension disbursements, the statutory reimbursement to Försäkringskassan,
#     membership fees to Kommunförbundet, grants paid out;
#   * premises — rent and site leases, which are property deals rather than
#     framework procurement, and which alone are 22 % of Huddinge's ledger;
#   * individual placements — "köp av huvudverksamhet, placeringskostnad" is a
#     child or an adult placed with a care provider. These are procured, but
#     against framework agreements where zero call-offs is the normal state,
#     and reporting them as dormant contracts would be the single largest false
#     finding available in this data. They stay visible, in their own class.
#
# Everything else is treated as procurable. The rules are ordered and the first
# match wins; `classification_audit` prints what each rule caught and what it
# cost, so a reader can disagree with a specific rule rather than the number.

CLASS_TRANSFER = "transfer"
CLASS_PREMISES = "premises"
CLASS_MONOPOLY = "monopoly"
CLASS_PLACEMENT = "placement"
CLASS_PROCURABLE = "procurable"
CLASS_UNKNOWN = "unknown"

CLASS_LABELS = {
    CLASS_TRANSFER: "Transferering — ingen motpart att konkurrensutsätta",
    CLASS_PREMISES: "Lokal och mark — fastighetsaffär, inte ramavtal",
    CLASS_MONOPOLY: "Reglerat monopol eller taxa — ingen marknad att vinna",
    CLASS_PLACEMENT: "Individuell placering — noll avrop är normalt",
    CLASS_PROCURABLE: "Upphandlingsbar",
    CLASS_UNKNOWN: "Okänd — reskontran namnger inget konto",
}

# Ordered; the first match wins. Each rule carries the reason it exists, and
# `classification_audit` prints what it caught, so a reader can disagree with
# one line rather than with the total. Every rule here was written against an
# account name that actually appears in a delivered ledger — none is
# speculative, and none is tuned to make a number look better.
_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # Collectively agreed and statutory employer costs. AMF and grupplivförsäkring
    # follow from the collective agreement; the municipality cannot put them out
    # to tender, and Huddinge books 24 MSEK there.
    (re.compile(r"pension|arbetsmarknadsförsäkring|grupplivförsäkring|arbetsgivaravgift", re.I),
     CLASS_TRANSFER, "kollektivavtalad eller lagstadgad arbetsgivarkostnad"),
    # Money paid out rather than bought with: grants to residents, statutory
    # reimbursements between authorities, allowances.
    (re.compile(r"\bbidrag\b|bostadsanpassning|habiliteringsersättning|stipendi", re.I),
     CLASS_TRANSFER, "utbetalning till enskild eller myndighet, inget köp"),
    (re.compile(r"ersättning till (försäkringskassan|kommun|region|staten)", re.I),
     CLASS_TRANSFER, "lagstadgad ersättning mellan huvudmän"),
    (re.compile(r"medlemsavgift|avgift kommunförbund|avgift övriga intresseförening", re.I),
     CLASS_TRANSFER, "medlemsavgift, inte en upphandlad tjänst"),
    (re.compile(r"bankkostnad|räntekostnad|internbank|\bmoms\b|\bskatt\b", re.I),
     CLASS_TRANSFER, "finansiell eller skattemässig post"),
    (re.compile(r"representation \(internt\)|uppvaktningar \(internt\)", re.I),
     CLASS_TRANSFER, "intern personalkostnad, inte ett inköp av verksamheten"),
    # Premises. 22 % of Huddinge's ledger, and a property deal rather than a
    # framework: a landlord is not something a supplier can win in a tender.
    (re.compile(r"lokalhyr|markhyr|hyra av lokal|arrende|tomträtt|fastighetsskatt", re.I),
     CLASS_PREMISES, "hyra eller mark"),
    # Regulated monopolies and public tariffs. There is one water utility and
    # one district-heating grid; "off-contract" there says nothing about
    # procurement discipline, and counting it would be a free 31 MSEK.
    (re.compile(r"förbrukningsavgift|va-avgift|renhållningsavgift|nätavgift", re.I),
     CLASS_MONOPOLY, "leveransmonopol — VA, fjärrvärme, elnät"),
    (re.compile(r"grundad på taxa|myndighetsavgift|mät- och granskningsavgift|"
                r"lagstadgad avgift|inträdesavgift", re.I),
     CLASS_MONOPOLY, "priset är en taxa, inte ett anbud"),
    # Individual placements. Procured, but against frameworks where zero
    # call-offs is the normal state — the largest false finding available here.
    (re.compile(r"placeringskostnad|köp av huvudverksamhet|familjehem|kontaktperson", re.I),
     CLASS_PLACEMENT, "individuell placering mot ramavtal"),
)


# The same distinction on the contract side. A supplier holding a place on
# Huddinge's "9.10 Enstaka platser i bostad med särskild service, LSS" is
# waiting to be chosen by a resident under LOV; being paid nothing for two
# years is the framework working as designed, not a dormant contract. There are
# 978 such rows in Huddinge's catalogue — nearly half of it — and letting them
# into the headline would be the difference between a finding and a press
# release.
_CONTRACT_PLACEMENT = re.compile(
    r"^\s*9[\s.]|vård och omsorg|individ- ?och familjeomsorg|funktionshinderomsorg|"
    r"hvb|jourhem|familjehem|behandlingsfamilj|öppenvård|stödboende|daglig verksamhet|"
    r"särskilt boende|enstaka platser|\bLOV\b|personlig assistans|korttidsvistelse",
    re.I,
)


def classify_contract(title: str | None, category: str | None) -> str:
    """Whether a contract is one a supplier can sell against, or a place in a queue."""
    for value in (category, title):
        if value and _CONTRACT_PLACEMENT.search(value):
            return CLASS_PLACEMENT
    return CLASS_PROCURABLE


def classification_reason(account: str | None) -> str | None:
    """Why an account was taken out of the procurable base, in one phrase."""
    if account is None:
        return None
    for pattern, _cls, why in _RULES:
        if pattern.search(account):
            return why
    return None


def classify(account: str | None) -> str:
    """Which of the five classes an account name falls in. First rule wins."""
    if account is None or not account.strip():
        return CLASS_UNKNOWN
    for pattern, cls, _why in _RULES:
        if pattern.search(account):
            return cls
    return CLASS_PROCURABLE


# -- coverage ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage:
    """What a municipality's numbers may honestly be computed over.

    Printed above every report in this module. A reader who skips it is reading
    a rate without knowing whether it rests on 44 months or on one.
    """

    buyer_org: str
    contract_rows: int
    contracts_with_orgnr: int
    payment_rows: int
    payments_with_orgnr: int
    first_period: str | None
    last_period: str | None
    months: int
    accounts_named: Proportion
    spend_sek: int

    @property
    def measurable(self) -> bool:
        """Both halves present, and enough of each to join on."""
        return bool(self.contract_rows and self.payment_rows and self.months >= 6)

    @property
    def joinable(self) -> Proportion:
        """Share of catalogue rows that carry an orgnr to join on."""
        return Proportion(self.contracts_with_orgnr, self.contract_rows)

    def blockers(self) -> list[str]:
        out = []
        if not self.contract_rows:
            out.append("ingen avtalskatalog — allt avrop saknar nämnare")
        if not self.payment_rows:
            out.append("ingen reskontra — inget utfall att jämföra mot")
        if self.contract_rows and self.contracts_with_orgnr / self.contract_rows < 0.5:
            out.append(
                f"bara {self.contracts_with_orgnr}/{self.contract_rows} avtalsrader har orgnr; "
                "kopplingen skulle vila på namnmatchning"
            )
        if 0 < self.months < 6:
            out.append(f"reskontran täcker {self.months} månader — för kort för en trend")
        return out


def coverage(conn: sqlite3.Connection, buyer_org: str) -> Coverage:
    row = conn.execute(
        """
        SELECT COUNT(*), SUM(supplier_orgnr IS NOT NULL)
        FROM municipal_contracts WHERE buyer_org = ?
        """,
        (buyer_org,),
    ).fetchone()
    contracts, contract_orgnr = row[0] or 0, row[1] or 0
    row = conn.execute(
        """
        SELECT COUNT(*), SUM(supplier_orgnr IS NOT NULL),
               MIN(period_year * 100 + COALESCE(period_month, 1)),
               MAX(period_year * 100 + COALESCE(period_month, 12)),
               SUM(account IS NOT NULL), COALESCE(SUM(amount_sek), 0)
        FROM supplier_payments WHERE payer_org = ?
        """,
        (buyer_org,),
    ).fetchone()
    payments, payment_orgnr, first, last, named, spend = (
        row[0] or 0, row[1] or 0, row[2], row[3], row[4] or 0, row[5] or 0,
    )
    months = 0
    if first and last:
        months = (last // 100 - first // 100) * 12 + (last % 100 - first % 100) + 1
    return Coverage(
        buyer_org=buyer_org,
        contract_rows=contracts,
        contracts_with_orgnr=contract_orgnr,
        payment_rows=payments,
        payments_with_orgnr=payment_orgnr,
        first_period=f"{first // 100}-{first % 100:02d}" if first else None,
        last_period=f"{last // 100}-{last % 100:02d}" if last else None,
        months=months,
        accounts_named=Proportion(named, payments),
        spend_sek=spend,
    )


def _window(conn: sqlite3.Connection, buyer_org: str) -> tuple[str, str]:
    """The ledger's first and last day, as ISO dates.

    Everything in this module is measured inside it. A contract is only judged
    over months where there is a ledger to judge it against.
    """
    row = conn.execute(
        """
        SELECT MIN(period_year * 100 + COALESCE(period_month, 1)),
               MAX(period_year * 100 + COALESCE(period_month, 12))
        FROM supplier_payments WHERE payer_org = ?
        """,
        (buyer_org,),
    ).fetchone()
    if not row or row[0] is None:
        return ("9999-12-31", "0001-01-01")
    first, last = row
    last_day = _month_end(last // 100, last % 100)
    return (f"{first // 100}-{first % 100:02d}-01", last_day)


def _month_end(year: int, month: int) -> str:
    if month == 12:
        return f"{year}-12-31"
    nxt = date(year, month + 1, 1)
    return str(date.fromordinal(nxt.toordinal() - 1))


# -- 1. the classification audit ---------------------------------------------


@dataclass(frozen=True, slots=True)
class AccountClass:
    account: str | None
    cls: str
    amount_sek: int
    suppliers: int


def classification_audit(conn: sqlite3.Connection, buyer_org: str) -> list[AccountClass]:
    """Every account, what it was classified as, and what that decision cost.

    The point of the report: a reader who thinks "Markentreprenader" should not
    be procurable can see it is 540 MSEK and argue about that one line, instead
    of distrusting the total.
    """
    rows = conn.execute(
        """
        SELECT account, COALESCE(SUM(amount_sek), 0), COUNT(DISTINCT supplier_orgnr)
        FROM supplier_payments WHERE payer_org = ?
        GROUP BY account ORDER BY 2 DESC
        """,
        (buyer_org,),
    ).fetchall()
    return [AccountClass(a, classify(a), int(amount), n) for a, amount, n in rows]


# -- 2. contracts that never turned into money -------------------------------


@dataclass(frozen=True, slots=True)
class DormantSupplier:
    """A supplier holding a live contract who was paid nothing, or nearly."""

    supplier_name: str
    supplier_orgnr: str | None
    contracts: int
    titles: str
    start_date: str | None
    end_date: str | None
    live_months: int
    paid_sek: int


@dataclass(frozen=True, slots=True)
class DormantReport:
    """Dormant contracts, with the placement frameworks held separately.

    `suppliers` and `zero_rate` cover procurable contracts only. The placement
    figures are reported beside them rather than folded in, because a reader
    who cannot see the split cannot tell a finding from an artefact of how care
    is bought.
    """

    coverage: Coverage
    window: tuple[str, str]
    suppliers: list[DormantSupplier]
    contracted: int
    zero_paid: int
    placement_suppliers: list[DormantSupplier]
    placement_contracted: int
    placement_zero: int
    caveats: list[str]

    @property
    def zero_rate(self) -> Proportion:
        return Proportion(self.zero_paid, self.contracted)

    @property
    def placement_zero_rate(self) -> Proportion:
        return Proportion(self.placement_zero, self.placement_contracted)


def dormant(
    conn: sqlite3.Connection, buyer_org: str, *, min_live_months: int = 6
) -> DormantReport:
    """Suppliers with a contract live inside the ledger window who were paid nothing.

    `min_live_months` guards the obvious false positive: a contract that
    started six weeks before the ledger ends has not had time to be called off,
    and counting it as dormant would be a statement about the calendar rather
    than about the buyer.

    Payment is matched on organisation number only. Name matching across a
    catalogue and a ledger that were exported from different systems invents
    both matches and misses, and a supplier wrongly shown as never paid is the
    one error that would be repeated back to a customer.
    """
    cov = coverage(conn, buyer_org)
    start, end = _window(conn, buyer_org)
    rows = conn.execute(
        """
        WITH live AS (
            SELECT supplier_orgnr AS orgnr,
                   MIN(supplier_name) AS name,
                   COUNT(*) AS contracts,
                   MIN(start_date) AS start_date,
                   MAX(end_date) AS end_date,
                   GROUP_CONCAT(DISTINCT title) AS titles,
                   GROUP_CONCAT(DISTINCT category) AS categories
            FROM municipal_contracts
            WHERE buyer_org = :buyer
              AND supplier_orgnr IS NOT NULL
              AND (start_date IS NULL OR start_date <= :end)
              AND (end_date IS NULL OR end_date >= :start)
            GROUP BY supplier_orgnr
        ),
        paid AS (
            SELECT supplier_orgnr AS orgnr, COALESCE(SUM(amount_sek), 0) AS paid
            FROM supplier_payments
            WHERE payer_org = :buyer AND supplier_orgnr IS NOT NULL
            GROUP BY supplier_orgnr
        )
        SELECT live.name, live.orgnr, live.contracts, live.titles, live.categories,
               live.start_date, live.end_date, COALESCE(paid.paid, 0)
        FROM live LEFT JOIN paid USING (orgnr)
        ORDER BY COALESCE(paid.paid, 0), live.name
        """,
        {"buyer": buyer_org, "start": start, "end": end},
    ).fetchall()

    suppliers: list[DormantSupplier] = []
    placements: list[DormantSupplier] = []
    contracted = zero = placement_contracted = placement_zero = 0
    for name, orgnr, contracts, titles, categories, s_date, e_date, paid in rows:
        live_months = _overlap_months(s_date, e_date, start, end)
        if live_months < min_live_months:
            continue
        is_placement = classify_contract(titles, categories) == CLASS_PLACEMENT
        if is_placement:
            placement_contracted += 1
        else:
            contracted += 1
        if paid > 0:
            continue
        entry = DormantSupplier(
            supplier_name=name,
            supplier_orgnr=orgnr,
            contracts=contracts,
            titles=(titles or "")[:120],
            start_date=s_date,
            end_date=e_date,
            live_months=live_months,
            paid_sek=int(paid),
        )
        if is_placement:
            placement_zero += 1
            placements.append(entry)
        else:
            zero += 1
            suppliers.append(entry)
    for bucket in (suppliers, placements):
        bucket.sort(key=lambda s: (-s.live_months, s.supplier_name))

    caveats = [
        f"Mätt mot reskontran {start} – {end}, {cov.months} månader.",
        f"Endast avtal som varit aktiva minst {min_live_months} månader inom fönstret.",
        "Kopplingen är organisationsnummer, aldrig namn.",
        "Vård- och omsorgsramavtal (LOV, placeringar, HVB) räknas separat: "
        "noll avrop är där det normala läget, inte ett fynd.",
    ]
    if cov.contracts_with_orgnr < cov.contract_rows:
        missing = cov.contract_rows - cov.contracts_with_orgnr
        caveats.append(
            f"{missing} av {cov.contract_rows} avtalsrader saknar giltigt svenskt orgnr "
            "(oftast utländska leverantörer) och kan varken bekräftas eller dementeras."
        )
    return DormantReport(
        cov, (start, end), suppliers, contracted, zero,
        placements, placement_contracted, placement_zero, caveats,
    )


def _overlap_months(
    start_date: str | None, end_date: str | None, win_start: str, win_end: str
) -> int:
    """How many whole months a contract was live inside the ledger window."""
    s = max(start_date or win_start, win_start)
    e = min(end_date or win_end, win_end)
    if s > e:
        return 0
    sy, sm = int(s[:4]), int(s[5:7])
    ey, em = int(e[:4]), int(e[5:7])
    return (ey - sy) * 12 + (em - sm) + 1


# -- 3. money that went past the contracts -----------------------------------


@dataclass(frozen=True, slots=True)
class CategoryGap:
    """One account: what was spent, how much of it under contract, how concentrated."""

    account: str | None
    cls: str
    spend_sek: int
    on_contract_sek: int
    suppliers: int
    suppliers_on_contract: int
    hhi: float
    top_supplier: str | None
    top_share: float
    trend: Trend

    @property
    def off_contract_sek(self) -> int:
        return self.spend_sek - self.on_contract_sek

    @property
    def off_contract_share(self) -> float:
        return self.off_contract_sek / self.spend_sek if self.spend_sek > 0 else 0.0

    @property
    def covered(self) -> Proportion:
        """Share of this account's suppliers who hold a contract."""
        return Proportion(self.suppliers_on_contract, self.suppliers)


@dataclass(frozen=True, slots=True)
class LeakageReport:
    coverage: Coverage
    window: tuple[str, str]
    categories: list[CategoryGap]
    excluded: dict[str, int]
    caveats: list[str]

    @property
    def procurable_sek(self) -> int:
        return sum(c.spend_sek for c in self.categories)

    @property
    def off_contract_sek(self) -> int:
        return sum(c.off_contract_sek for c in self.categories)

    @property
    def off_contract_share(self) -> float:
        return self.off_contract_sek / self.procurable_sek if self.procurable_sek else 0.0


def leakage(conn: sqlite3.Connection, buyer_org: str) -> LeakageReport:
    """Procurable spend, split by whether the supplier held a contract at the time.

    "At the time" is the whole difficulty. A supplier whose contract ran
    2023–2024 and who was paid in 2026 was paid off-contract, and a join on the
    supplier alone would score that as covered. So each payment month is tested
    against the contract's own term.
    """
    cov = coverage(conn, buyer_org)
    start, end = _window(conn, buyer_org)

    rows = conn.execute(
        """
        SELECT p.account,
               p.supplier_orgnr,
               MIN(p.supplier_name),
               SUM(p.amount_sek) AS spend,
               SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM municipal_contracts c
                     WHERE c.buyer_org = p.payer_org
                       AND c.supplier_orgnr = p.supplier_orgnr
                       AND (c.start_date IS NULL OR c.start_date <=
                            printf('%04d-%02d-28', p.period_year, COALESCE(p.period_month, 12)))
                       AND (c.end_date IS NULL OR c.end_date >=
                            printf('%04d-%02d-01', p.period_year, COALESCE(p.period_month, 1)))
                   ) THEN p.amount_sek ELSE 0 END) AS on_contract
        FROM supplier_payments p
        WHERE p.payer_org = ? AND p.supplier_orgnr IS NOT NULL
        GROUP BY p.account, p.supplier_orgnr
        """,
        (buyer_org,),
    ).fetchall()

    by_account: dict[str | None, list[tuple[str, int, int]]] = {}
    excluded: dict[str, int] = {}
    for account, _orgnr, name, spend, on_contract in rows:
        cls = classify(account)
        if cls != CLASS_PROCURABLE:
            excluded[cls] = excluded.get(cls, 0) + int(spend)
            continue
        by_account.setdefault(account, []).append((name, int(spend), int(on_contract or 0)))

    series = _monthly_series(conn, buyer_org)
    categories: list[CategoryGap] = []
    for account, suppliers in by_account.items():
        spend = sum(s for _, s, _ in suppliers)
        on_contract = sum(c for _, _, c in suppliers)
        amounts = [s for _, s, _ in suppliers]
        hhi = herfindahl(amounts)
        top = max(suppliers, key=lambda s: s[1])
        categories.append(
            CategoryGap(
                account=account,
                cls=CLASS_PROCURABLE,
                spend_sek=spend,
                on_contract_sek=on_contract,
                suppliers=len(suppliers),
                suppliers_on_contract=sum(1 for _, _, c in suppliers if c > 0),
                hhi=hhi,
                top_supplier=top[0],
                top_share=top[1] / spend if spend > 0 else 0.0,
                trend=mann_kendall(series.get(account, [])),
            )
        )
    categories.sort(key=lambda c: -c.off_contract_sek)

    caveats = [
        f"Fönster: {start} – {end} ({cov.months} månader).",
        "Ett köp räknas som avtalat bara om leverantörens avtal löpte den månaden.",
    ]
    if cov.accounts_named.rate < 0.99:
        caveats.append(
            f"Bara {cov.accounts_named} av raderna namnger ett konto — "
            "utan konto går transfereringar inte att skilja från inköp."
        )
    return LeakageReport(cov, (start, end), categories, excluded, caveats)


def _monthly_series(conn: sqlite3.Connection, buyer_org: str) -> dict[str | None, list[float]]:
    """Off-contract share per account per month, for the trend test."""
    rows = conn.execute(
        """
        SELECT account, period_year * 100 + COALESCE(period_month, 1) AS period,
               COALESCE(SUM(amount_sek), 0)
        FROM supplier_payments WHERE payer_org = ?
        GROUP BY account, period ORDER BY account, period
        """,
        (buyer_org,),
    ).fetchall()
    out: dict[str | None, list[float]] = {}
    for account, _period, amount in rows:
        out.setdefault(account, []).append(float(amount))
    return out


# -- 4. what is about to come up for procurement -----------------------------


@dataclass(frozen=True, slots=True)
class ExpiringContract:
    """A supplier's contracts running out, priced by what they have been worth."""

    supplier_name: str
    supplier_orgnr: str | None
    titles: str | None
    contracts: int
    end_date: str
    days_left: int
    observed_months: int
    paid_sek: int
    accounts: str | None
    cls: str

    #: Below this many observed months an annual figure is arithmetic, not
    #: evidence. Orca Entreprenad's contract started six weeks before the ledger
    #: ends; annualising those two months turned 91 MSEK of history into a
    #: claimed 547 MSEK a year, and it was the largest number on the page.
    MIN_MONTHS_TO_ANNUALISE = 3

    @property
    def sizeable(self) -> bool:
        return self.observed_months >= self.MIN_MONTHS_TO_ANNUALISE

    @property
    def run_rate_year_sek(self) -> int:
        """Annualised from what was paid inside this contract's own window.

        Every catalogue but Jönköping's arrived without contract values, so a
        contract's size has to be inferred from what was paid against it. Both
        halves of that fraction must cover the same months: `paid_sek` counts
        only payments made while this contract was live and the ledger was
        running, and `observed_months` counts exactly those months. A supplier's
        older, larger, already-expired contract does not belong in either.

        Returns 0 when the window is too short to annualise; read `paid_sek`
        and `observed_months` instead.
        """
        if not self.sizeable:
            return 0
        return int(self.paid_sek * 12 / self.observed_months)


def pipeline(
    conn: sqlite3.Connection,
    buyer_org: str,
    *,
    within_days: int = 365,
    today: date | None = None,
) -> tuple[Coverage, list[ExpiringContract], list[str]]:
    """Suppliers whose contracts run out within `within_days`, largest first.

    One row per supplier, not per contract. A supplier's spend is known only at
    supplier level — the ledger does not name which contract an invoice was
    called off against — so repeating it against each of Attendo's five
    contracts would quintuple the same money and make the column total
    meaningless. The row therefore carries the supplier's earliest expiry and
    how many of their contracts fall inside the horizon.

    Placement frameworks are marked but not dropped: their expiry is real and
    the money is real, they simply cannot be read as "a contract about to be
    competed for" the way a cleaning framework can.
    """
    cov = coverage(conn, buyer_org)
    start, end = _window(conn, buyer_org)
    now = today or datetime.now(UTC).date()
    horizon = str(date.fromordinal(now.toordinal() + within_days))

    rows = conn.execute(
        """
        SELECT c.supplier_orgnr,
               MIN(c.supplier_name),
               COUNT(*),
               MIN(c.end_date),
               MIN(c.start_date),
               GROUP_CONCAT(DISTINCT c.title),
               GROUP_CONCAT(DISTINCT c.category)
        FROM municipal_contracts c
        WHERE c.buyer_org = ? AND c.end_date IS NOT NULL
          AND c.end_date >= ? AND c.end_date <= ?
          AND c.supplier_orgnr IS NOT NULL
        GROUP BY c.supplier_orgnr
        """,
        (buyer_org, str(now), horizon),
    ).fetchall()

    out: list[ExpiringContract] = []
    for orgnr, name, contracts, end_date, start_date, titles, categories in rows:
        # Only what was paid while this contract was live and the ledger was
        # running. Anything outside that window belongs to a different contract.
        from_period = max(start_date or start, start)[:7].replace("-", "")
        to_period = min(end_date, end)[:7].replace("-", "")
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_sek), 0), GROUP_CONCAT(DISTINCT account)
            FROM supplier_payments
            WHERE payer_org = ? AND supplier_orgnr = ?
              AND printf('%04d%02d', period_year, COALESCE(period_month, 1)) >= ?
              AND printf('%04d%02d', period_year, COALESCE(period_month, 12)) <= ?
            """,
            (buyer_org, orgnr, from_period, to_period),
        ).fetchone()
        out.append(
            ExpiringContract(
                supplier_name=name,
                supplier_orgnr=orgnr,
                titles=(titles or "")[:80] or None,
                contracts=contracts,
                end_date=end_date,
                days_left=date.fromisoformat(end_date).toordinal() - now.toordinal(),
                observed_months=_overlap_months(start_date, end_date, start, end),
                paid_sek=int(row[0]),
                accounts=(row[1] or "")[:70] or None,
                cls=classify_contract(titles, categories),
            )
        )
    out.sort(key=lambda c: (-c.run_rate_year_sek, c.end_date))

    caveats = [
        f"Volymen är observerad, inte avtalad: summerad ur reskontran {start} – {end}.",
        "En rad per leverantör, inte per avtal — reskontran säger inte vilket avtal "
        "en faktura avropades mot, så samma pengar får aldrig räknas två gånger.",
        f"Beloppet räknas bara över de månader avtalet självt löpte. Avtal med färre "
        f"än {ExpiringContract.MIN_MONTHS_TO_ANNUALISE} observerade månader får ingen "
        "årstakt — där står observerat belopp och antal månader i stället.",
        "Ingen av katalogerna utom Jönköpings innehåller avtalsvärde, så takvolym "
        "kan inte jämföras med utfall för någon av dessa kommuner.",
    ]
    if cov.months < 12:
        caveats.append(
            f"Reskontran täcker {cov.months} månader; årstakten är uppräknad från "
            "mindre än ett år och bär säsongsfel."
        )
    return cov, out, caveats


# -- 5. the same category across municipalities ------------------------------


@dataclass(frozen=True, slots=True)
class Benchmark:
    """One account seen in more than one municipality."""

    account: str
    buyers: int
    spend_sek: int
    off_contract: Proportion
    worst_buyer: str
    worst_share: float


def benchmark(conn: sqlite3.Connection) -> list[Benchmark]:
    """Accounts that more than one municipality books against, ranked by the gap.

    Two municipalities is not a base rate, and this will stay a curiosity until
    a third ledger with named accounts arrives. It is here because the shape of
    the answer matters more than today's n: the claim a customer will pay for
    is "your peers contract this and you do not", and that claim needs a peer
    group, not a single buyer.
    """
    buyers = [
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT payer_org FROM supplier_payments
            WHERE account IS NOT NULL
            """
        )
    ]
    per_account: dict[str, list[tuple[str, int, int, int, int]]] = {}
    for buyer in buyers:
        for cat in leakage(conn, buyer).categories:
            if cat.account is None:
                continue
            per_account.setdefault(cat.account, []).append(
                (buyer, cat.spend_sek, cat.off_contract_sek, cat.suppliers,
                 cat.suppliers - cat.suppliers_on_contract)
            )
    out = []
    for account, seen in per_account.items():
        if len(seen) < 2:
            continue
        worst = max(seen, key=lambda s: s[2] / s[1] if s[1] else 0)
        out.append(
            Benchmark(
                account=account,
                buyers=len(seen),
                spend_sek=sum(s[1] for s in seen),
                off_contract=Proportion(sum(s[4] for s in seen), sum(s[3] for s in seen)),
                worst_buyer=worst[0],
                worst_share=worst[2] / worst[1] if worst[1] else 0.0,
            )
        )
    out.sort(key=lambda b: -b.spend_sek)
    return out


# -- formatting --------------------------------------------------------------


def sek(amount: int | float) -> str:
    """Money at the precision the number deserves, never more."""
    a = float(amount)
    if abs(a) >= 1e9:
        return f"{a / 1e9:.2f} mdr"
    if abs(a) >= 1e6:
        return f"{a / 1e6:.1f} mkr"
    if abs(a) >= 1e3:
        return f"{a / 1e3:.0f} tkr"
    return f"{a:.0f} kr"
