"""M5 — utnyttjandegrad: what share of a framework's ceiling has actually been
called off, and how much of the picture we can actually see.

## The rule that governs this whole module

`utilization_rate` is never presented without `coverage_ratio`.

If spend is known for 3 of 1 150 organisations entitled to call off an
agreement, the figure is a **lower bound**, not a measurement. A reader who
sees only the percentage has been misled, so the caveat travels with the number
into the view, the terminal, the markdown and the HTML. `render_markdown`
asserts it, and a test asserts it by regex over the rendered output — the
invariant is enforced by the suite rather than by review.

## Where each number comes from

* **Ceiling** — `framework_agreements`, extracted by M1 from the notice's own
  eForms fields, with its source and confidence.
* **Observed spend** — `supplier_payments`, joined to `award_winners` on the
  supplier's orgnr **and** to `framework_buyers` on the payer's orgnr. Both
  halves matter: a payment from an unrelated buyer to a supplier who happens
  to be on this framework is not a call-off on it. Dropping the payer
  condition roughly multiplies observed spend by twenty in this corpus, and
  every krona of that is someone else's money.
* **Coverage** — how many of the buyers named in the notice we hold payment
  data for. NULL for a central purchasing body, whose entitled organisations
  are not published at all.

## Time normalisation

An agreement that has run 18 of 48 months is compared against 37.5 % of the
ceiling, not against 100 %. Both the raw and the time-normalised rate are
reported, each labelled, because the raw one flatters a young agreement and
the normalised one is meaningless once the agreement has ended.
"""

from __future__ import annotations

import html
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from tender_scan.records import AwardWinner

# confidence_band thresholds, named rather than inlined in the SQL string.
BAND_HIGH_CAP_CONFIDENCE = 0.9
BAND_HIGH_COVERAGE = 0.8
BAND_LOW_CAP_CONFIDENCE = 0.7
BAND_LOW_COVERAGE = 0.3

TED_NOTICE_URL = "https://ted.europa.eu/en/notice/-/detail/{notice_id}"

VIEW_SQL = """
CREATE VIEW IF NOT EXISTS utilization AS
WITH buyers AS (
    SELECT notice_id, COUNT(*) AS named_buyers
    FROM framework_buyers
    GROUP BY notice_id
),
observed AS (
    SELECT w.notice_id                       AS notice_id,
           SUM(p.amount_sek)                 AS observed_spend_sek,
           COUNT(DISTINCT p.payer_orgnr)     AS paying_buyers,
           COUNT(DISTINCT p.supplier_orgnr)  AS paid_suppliers,
           COUNT(DISTINCT p.period_year * 100 + COALESCE(p.period_month, 0))
                                             AS observed_months,
           COUNT(*)                          AS payment_rows
    FROM award_winners w
    JOIN framework_agreements f ON f.notice_id = w.notice_id
    JOIN framework_buyers b ON b.notice_id = w.notice_id
    JOIN supplier_payments p
      ON p.supplier_orgnr = w.supplier_orgnr
     AND p.payer_orgnr    = b.buyer_orgnr
    WHERE w.supplier_orgnr IS NOT NULL
    -- Only money spent inside the agreement's own term is a call-off on it.
    -- Compared at month granularity because that is what the ledgers publish.
      AND (
              f.start_date IS NULL OR f.end_date IS NULL
              OR (
                  printf('%04d-%02d-01', p.period_year, COALESCE(p.period_month, 1))
                      >= strftime('%Y-%m-01', f.start_date)
                  AND printf('%04d-%02d-01', p.period_year, COALESCE(p.period_month, 12))
                      <= strftime('%Y-%m-01', f.end_date)
              )
          )
    GROUP BY w.notice_id
)
SELECT
    f.notice_id                                        AS notice_id,
    f.title                                            AS framework_title,
    f.buyer_name                                       AS buyer_name,
    f.cap_value_sek                                    AS cap_value_sek,
    COALESCE(o.observed_spend_sek, 0)                  AS observed_spend_sek,
    CASE
        WHEN f.buyer_is_cpb = 1 THEN NULL
        WHEN COALESCE(bu.named_buyers, 0) = 0 THEN NULL
        ELSE CAST(COALESCE(o.paying_buyers, 0) AS REAL) / bu.named_buyers
    END                                                AS coverage_ratio,
    CASE
        WHEN f.cap_value_sek IS NULL OR f.cap_value_sek = 0 THEN NULL
        ELSE CAST(COALESCE(o.observed_spend_sek, 0) AS REAL) / f.cap_value_sek
    END                                                AS utilization_rate,
    NULL                                               AS confidence_band,
    NULL                                               AS months_elapsed,
    f.max_duration_months                              AS months_total,
    f.start_date                                       AS start_date,
    f.end_date                                         AS end_date,
    f.cap_source                                       AS cap_source,
    f.cap_confidence                                   AS cap_confidence,
    f.buyer_is_cpb                                     AS buyer_is_cpb,
    f.raw_excerpt                                      AS raw_excerpt,
    COALESCE(bu.named_buyers, 0)                       AS named_buyers,
    COALESCE(o.paying_buyers, 0)                       AS paying_buyers,
    COALESCE(o.paid_suppliers, 0)                      AS paid_suppliers,
    COALESCE(o.observed_months, 0)                     AS observed_months,
    COALESCE(o.payment_rows, 0)                        AS payment_rows
FROM framework_agreements f
LEFT JOIN buyers   bu ON bu.notice_id = f.notice_id
LEFT JOIN observed o  ON o.notice_id  = f.notice_id
WHERE f.is_framework = 1;
"""

# `confidence_band` and `months_elapsed` are NULL in the view and filled in by
# `Utilization`: one depends on today's date, which must not be baked into a
# stored view, and the other reads better as named constants than as a nested
# SQL CASE nobody will re-derive.


def create_view(conn: sqlite3.Connection) -> None:
    conn.executescript(VIEW_SQL)
    conn.commit()


def months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


@dataclass(frozen=True, slots=True)
class Utilization:
    """One framework's utilisation, with everything needed to caveat it."""

    notice_id: str
    framework_title: str | None
    buyer_name: str | None
    cap_value_sek: int | None
    observed_spend_sek: int
    coverage_ratio: float | None
    utilization_rate: float | None
    months_elapsed: int | None
    months_total: int | None
    start_date: str | None
    end_date: str | None
    cap_source: str | None
    cap_confidence: float | None
    buyer_is_cpb: bool
    raw_excerpt: str | None
    named_buyers: int
    paying_buyers: int
    paid_suppliers: int
    observed_months: int
    payment_rows: int

    @property
    def period_coverage(self) -> float | None:
        """How many of the elapsed months we actually hold ledger data for.

        Buyer coverage alone flatters badly: one month of a municipality's
        supplier ledger against a 47-month agreement is 1/1 buyers and 1/47
        months, and only the second number tells the reader that the
        utilisation figure is a floor rather than a measurement.
        """
        if not self.months_elapsed:
            return None
        return min(self.observed_months / self.months_elapsed, 1.0)

    @property
    def elapsed_share(self) -> float | None:
        """How far into its term the agreement is, 0.0-1.0."""
        if not self.months_total or self.months_elapsed is None:
            return None
        return min(self.months_elapsed / self.months_total, 1.0)

    @property
    def expected_spend_sek(self) -> int | None:
        """The ceiling pro-rated to the elapsed term — the fair comparison."""
        share = self.elapsed_share
        if share is None or self.cap_value_sek is None:
            return None
        return int(
            (Decimal(self.cap_value_sek) * Decimal(str(share))).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
        )

    @property
    def time_normalized_rate(self) -> float | None:
        """Observed spend against the pro-rated ceiling, not the whole one."""
        expected = self.expected_spend_sek
        if not expected:
            return None
        return self.observed_spend_sek / expected

    @property
    def confidence_band(self) -> str:
        """`high` needs a well-evidenced ceiling AND both kinds of coverage."""
        cap = self.cap_confidence
        coverage = self.coverage_ratio
        period = self.period_coverage
        if (
            cap is not None
            and cap >= BAND_HIGH_CAP_CONFIDENCE
            and coverage is not None
            and coverage >= BAND_HIGH_COVERAGE
            and period is not None
            and period >= BAND_HIGH_COVERAGE
        ):
            return "high"
        if (
            cap is None
            or cap < BAND_LOW_CAP_CONFIDENCE
            or coverage is None
            or coverage < BAND_LOW_COVERAGE
            or (period is not None and period < BAND_LOW_COVERAGE)
        ):
            return "low"
        return "medium"


def _months_elapsed(start: str | None, end: str | None, today: date) -> int | None:
    """Whole months from the start to today, or to the end once it has passed."""
    if not start:
        return None
    try:
        began = date.fromisoformat(start)
    except ValueError:
        return None
    until = today
    if end:
        try:
            finished = date.fromisoformat(end)
            until = min(today, finished)
        except ValueError:
            pass
    return months_between(began, until) if until >= began else 0


def load(
    conn: sqlite3.Connection, notice_id: str, *, today: date | None = None
) -> Utilization | None:
    create_view(conn)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM utilization WHERE notice_id = ?", (notice_id,)).fetchone()
    if row is None:
        return None
    return _from_row(row, today or datetime.now(UTC).date())


def load_all(conn: sqlite3.Connection, *, today: date | None = None) -> list[Utilization]:
    create_view(conn)
    conn.row_factory = sqlite3.Row
    when = today or datetime.now(UTC).date()
    return [
        _from_row(row, when) for row in conn.execute("SELECT * FROM utilization ORDER BY notice_id")
    ]


def _from_row(row: sqlite3.Row, today: date) -> Utilization:
    return Utilization(
        notice_id=row["notice_id"],
        framework_title=row["framework_title"],
        buyer_name=row["buyer_name"],
        cap_value_sek=row["cap_value_sek"],
        observed_spend_sek=row["observed_spend_sek"],
        coverage_ratio=row["coverage_ratio"],
        utilization_rate=row["utilization_rate"],
        months_elapsed=_months_elapsed(row["start_date"], row["end_date"], today),
        months_total=row["months_total"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        cap_source=row["cap_source"],
        cap_confidence=row["cap_confidence"],
        buyer_is_cpb=bool(row["buyer_is_cpb"]),
        raw_excerpt=row["raw_excerpt"],
        named_buyers=row["named_buyers"],
        paying_buyers=row["paying_buyers"],
        paid_suppliers=row["paid_suppliers"],
        observed_months=row["observed_months"],
        payment_rows=row["payment_rows"],
    )


# -- provenance --------------------------------------------------------------


class MissingSource(Exception):
    """Raised when a figure would be rendered without a traceable source."""


@dataclass(frozen=True, slots=True)
class Sourced:
    """A figure and where it came from.

    The spec's rule is that no number reaches a report without a notice id, a
    dataset URL or a diarienummer behind it. Making that a type rather than a
    convention means a template author cannot forget: constructing a `Sourced`
    with an empty source raises, so the omission fails at render time instead
    of shipping as an unattributed percentage.
    """

    value: str
    source: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise MissingSource(f"no source for {self.value!r}")

    def row(self, label: str) -> str:
        return f"| {label} | {self.value} | {self.source} |"


@dataclass(frozen=True, slots=True)
class PaymentSource:
    payer_org: str
    payer_orgnr: str | None
    rows: int
    amount_sek: int
    source_urls: tuple[str, ...]
    first_period: str
    last_period: str


def payment_sources(conn: sqlite3.Connection, notice_id: str) -> list[PaymentSource]:
    """Which payers the observed spend came from, and from which datasets."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT p.payer_org, p.payer_orgnr, p.source_url, p.amount_sek,
               p.period_year, p.period_month
        FROM award_winners w
        JOIN framework_agreements f ON f.notice_id = w.notice_id
        JOIN framework_buyers b ON b.notice_id = w.notice_id
        JOIN supplier_payments p
          ON p.supplier_orgnr = w.supplier_orgnr AND p.payer_orgnr = b.buyer_orgnr
        WHERE w.notice_id = ? AND w.supplier_orgnr IS NOT NULL
      AND (
              f.start_date IS NULL OR f.end_date IS NULL
              OR (
                  printf('%04d-%02d-01', p.period_year, COALESCE(p.period_month, 1))
                      >= strftime('%Y-%m-01', f.start_date)
                  AND printf('%04d-%02d-01', p.period_year, COALESCE(p.period_month, 12))
                      <= strftime('%Y-%m-01', f.end_date)
              )
          )
        """,
        (notice_id,),
    ).fetchall()

    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["payer_org"], []).append(row)

    found: list[PaymentSource] = []
    for payer, entries in sorted(grouped.items()):
        periods = sorted(
            f"{e['period_year']}-{e['period_month']:02d}"
            if e["period_month"]
            else str(e["period_year"])
            for e in entries
        )
        found.append(
            PaymentSource(
                payer_org=payer,
                payer_orgnr=entries[0]["payer_orgnr"],
                rows=len(entries),
                amount_sek=sum(e["amount_sek"] for e in entries),
                source_urls=tuple(sorted({e["source_url"] for e in entries if e["source_url"]})),
                first_period=periods[0],
                last_period=periods[-1],
            )
        )
    return found


def framework_winners(conn: sqlite3.Connection, notice_id: str) -> list[AwardWinner]:
    conn.row_factory = sqlite3.Row
    return [
        AwardWinner(
            notice_id=row["notice_id"],
            supplier_name=row["supplier_name"],
            supplier_orgnr=row["supplier_orgnr"],
            lot_id=row["lot_id"],
            rank=row["rank"],
            awarded_value_sek=row["awarded_value_sek"],
            match_confidence=row["match_confidence"],
        )
        for row in conn.execute(
            "SELECT * FROM award_winners WHERE notice_id = ? "
            "ORDER BY lot_id, COALESCE(rank, 9999), supplier_name",
            (notice_id,),
        )
    ]


# -- rendering ---------------------------------------------------------------


def sek(value: int | None) -> str:
    return "okänt" if value is None else f"{value:,}".replace(",", "\x20") + " SEK"


def pct(value: float | None) -> str:
    return "okänd" if value is None else f"{value:.1%}"


_COVERAGE_UNKNOWN = (
    "Nämnaren är okänd. Ramavtalet upphandlas av en inköpscentral, och vilka "
    "organisationer som får avropa publiceras inte i TED. Utnyttjandegraden nedan "
    "är därför en undre gräns, inte en mätning."
)

_LOW_CONFIDENCE_WARNING = (
    "> **Varning: takvolymen är svagt belagd.** Konfidensen är {confidence:.2f}, "
    "under tröskeln 0,70. Siffran är hämtad ur {source} och bör kontrolleras mot "
    "upphandlingsdokumenten innan rapporten används som beslutsunderlag."
)

_METHOD_LIMITATIONS = """## Metodbegränsningar

- **Utnyttjandegraden är en undre gräns, inte en mätning.** Den bygger på de
  fakturarader som respektive köpare publicerar som öppna data. Allt som inte
  publicerats saknas i summan.
- **Täckningsgraden mäter två saker och båda måste läsas.** Andelen köpare vi har
  data för, och andelen förflutna månader vi har data för. Ett avtal där vi ser en
  månad av fyrtiosju är inte mätt, oavsett hur många köpare som namnges.
- **Takvolymen kommer ur notisens egna eForms-fält.** Där notisen publicerar flera
  motstridiga tak redovisas valet och båda siffrorna i avsnittet Takvolym. Där
  inget tak publicerats är utnyttjandegraden inte beräkningsbar.
- **Leverantörsmatchningen sker på organisationsnummer.** En leverantör vars
  organisationsnummer inte publicerats i notisen, eller vars fakturarader saknar
  organisationsnummer hos köparen, matchas på normaliserat firmanamn och kan
  saknas helt. Ingen matchning görs på gissning.
- **Endast betalningar från de köpare notisen namnger räknas.** En betalning från
  en annan myndighet till samma leverantör är inte ett avrop på det här avtalet.
- **Tidsnormaliseringen antar jämn förbrukning över avtalstiden.** Verkliga avrop
  är ojämna; siffran är en jämförelsepunkt, inte en prognos.
- **En omräkning av en period kan dubbelräknas.** Läs in en fil per period; en
  reviderad fil som publiceras på en ny URL läggs till, inte ersätter."""


def render_markdown(
    utilization: Utilization,
    sources: list[PaymentSource],
    winners: list[AwardWinner],
    *,
    generated: date | None = None,
) -> str:
    """The report. Every figure carries its source; the coverage caveat is
    printed next to every utilisation figure, without exception."""
    u = utilization
    notice = u.notice_id
    when = (generated or datetime.now(UTC).date()).isoformat()
    lines: list[str] = [
        f"# Utnyttjandegrad: {u.framework_title or 'ramavtal'}",
        "",
        f"**Köpare:** {u.buyer_name or 'okänd'}  ",
        f"**Notis:** [{notice}]({TED_NOTICE_URL.format(notice_id=notice)})  ",
        f"**Rapport genererad:** {when}  ",
        f"**Konfidensband:** {u.confidence_band}",
        "",
    ]

    if u.cap_confidence is not None and u.cap_confidence < BAND_LOW_CAP_CONFIDENCE:
        lines += [
            _LOW_CONFIDENCE_WARNING.format(
                confidence=u.cap_confidence, source=u.cap_source or "okänd källa"
            ),
            "",
        ]

    lines += [
        "## Takvolym",
        "",
        "| Uppgift | Värde | Källa |",
        "| --- | --- | --- |",
        Sourced(sek(u.cap_value_sek), notice).row("Takvolym"),
        Sourced(u.cap_source or "inget tak publicerat", notice).row("Fält"),
        Sourced(f"{u.cap_confidence:.2f}" if u.cap_confidence is not None else "-", notice).row(
            "Konfidens"
        ),
        "",
        f"> {u.raw_excerpt or 'Ingen härledning registrerad.'}",
        "",
        "## Observerat avrop",
        "",
    ]

    if sources:
        lines += [
            "| Betalare | Rader | Belopp | Period | Datakälla |",
            "| --- | --- | --- | --- | --- |",
        ]
        for source in sources:
            urls = "<br>".join(source.source_urls) or "okänd"
            period = (
                source.first_period
                if source.first_period == source.last_period
                else f"{source.first_period}–{source.last_period}"
            )
            lines.append(
                f"| {source.payer_org} ({source.payer_orgnr or '-'}) | {source.rows} | "
                f"{sek(source.amount_sek)} | {period} | {urls} |"
            )
        lines += ["", f"**Summa observerat avrop:** {sek(u.observed_spend_sek)}", ""]
    else:
        lines += [
            "Inga betalningar från de köpare notisen namnger har kunnat matchas mot "
            "avtalets leverantörer. Det betyder inte att inga avrop skett — det betyder "
            "att ingen av köparna publicerar sin leverantörsreskontra som öppna data för "
            "den aktuella perioden. Vägen vidare är en begäran enligt "
            "offentlighetsprincipen.",
            "",
        ]

    lines += ["## Täckningsgrad", ""]
    if u.coverage_ratio is None:
        lines += [_COVERAGE_UNKNOWN, ""]
    else:
        lines += [
            f"Vi har betalningsdata för **{u.paying_buyers} av {u.named_buyers}** "
            f"köpare som namnges i notisen — täckningsgrad **{pct(u.coverage_ratio)}**.",
            "",
        ]
    if u.period_coverage is not None:
        lines += [
            f"Datat täcker **{u.observed_months} av {u.months_elapsed}** förflutna "
            f"avtalsmånader — **{pct(u.period_coverage)}** av tiden.",
            "",
        ]
    elif u.start_date and u.months_elapsed == 0:
        lines += [f"Avtalet startar {u.start_date} och har ännu inte börjat löpa.", ""]
    else:
        lines += [
            "Avtalets löptid går inte att fastställa ur notisen, så tidstäckningen är okänd.",
            "",
        ]

    lines += ["## Utnyttjandegrad", "", _rate_paragraph(u), ""]

    lines += ["## Leverantörer", ""]
    if winners:
        lines += ["| Del | Rang | Leverantör | Orgnr |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {w.lot_id} | {w.rank if w.rank is not None else '-'} | {w.supplier_name} | "
            f"{w.supplier_orgnr or 'saknas'} |"
            for w in winners
        ]
        ranked = sum(1 for w in winners if w.rank is not None)
        lines += [
            "",
            f"{len(winners)} tilldelningar. Rangordning publicerad för {ranked} av dem"
            + (
                "."
                if ranked
                else " — vilken leverantör som faktiskt får avropen framgår alltså inte."
            ),
            "",
        ]
    else:
        lines += ["Inga tilldelningar registrerade för notisen.", ""]

    lines += [_METHOD_LIMITATIONS, ""]
    return "\n".join(lines)


def _rate_paragraph(u: Utilization) -> str:
    """Utilisation, never stated without the coverage caveat beside it."""
    if u.cap_value_sek is None:
        return (
            "Ingen takvolym är publicerad i notisen, så utnyttjandegraden går inte att "
            "beräkna. Observerat avrop är "
            f"{sek(u.observed_spend_sek)}."
        )
    caveat = _caveat(u)
    parts = [
        f"Observerat avrop **{sek(u.observed_spend_sek)}** mot en takvolym på "
        f"**{sek(u.cap_value_sek)}** ger en utnyttjandegrad på **{pct(u.utilization_rate)}**. "
        f"{caveat}"
    ]
    expected = u.expected_spend_sek
    # `expected` of 0 means the term has not begun; a "0 % of 0 SEK" paragraph
    # reads as a measurement of nothing rather than as "not started yet".
    if expected and u.months_total:
        parts.append(
            f"Tidsnormaliserat: {u.months_elapsed} av {u.months_total} månader har "
            f"förflutit, vilket motsvarar {pct(u.elapsed_share)} av takvolymen, eller "
            f"{sek(expected)}. Mot den jämförelsepunkten är utnyttjandegraden "
            f"**{pct(u.time_normalized_rate)}**. {caveat}"
        )
    elif u.start_date and u.months_elapsed == 0:
        parts.append(
            f"Avtalet startar {u.start_date} och har ännu inte löpt en hel månad, "
            "så ingen tidsnormaliserad jämförelse är meningsfull."
        )
    else:
        parts.append(
            "Avtalets löptid går inte att fastställa ur notisen, så någon "
            "tidsnormaliserad jämförelse redovisas inte."
        )
    return "\n\n".join(parts)


def _caveat(u: Utilization) -> str:
    """The sentence that must accompany every utilisation figure."""
    if u.coverage_ratio is None:
        return (
            "Täckningsgraden är okänd (inköpscentral), så siffran är en undre gräns, "
            "inte en mätning."
        )
    pieces = [f"täckningsgrad {pct(u.coverage_ratio)} av köparna"]
    if u.period_coverage is not None:
        pieces.append(f"{pct(u.period_coverage)} av avtalstiden")
    return "Siffran är en undre gräns, inte en mätning: " + " och ".join(pieces) + "."


_HTML_PAGE = """<!doctype html>
<html lang="sv"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Utnyttjandegrad {notice_id}</title>
<style>
 body {{ font: 16px/1.6 -apple-system, Segoe UI, Roboto, sans-serif; max-width: 52rem;
        margin: 2rem auto; padding: 0 1rem; color: #14171a; }}
 h1 {{ font-size: 1.6rem; }} h2 {{ font-size: 1.15rem; margin-top: 2rem; }}
 table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }}
 th, td {{ border-bottom: 1px solid #dde; padding: 0.4rem 0.5rem; text-align: left;
           vertical-align: top; }}
 blockquote {{ border-left: 3px solid #ccd; margin: 1rem 0; padding: 0.2rem 1rem;
               color: #555; font-size: 0.9rem; }}
 .warning {{ border-left-color: #c33; color: #900; }}
 code {{ font-size: 0.85em; }}
</style></head><body>
{body}
</body></html>
"""


def render_html(markdown: str, utilization: Utilization) -> str:
    """The same report as a standalone page.

    A deliberately small converter for the subset this module emits — headings,
    tables, blockquotes, bullets, bold — rather than a dependency. Anything it
    does not recognise becomes a paragraph, so no content is ever dropped.
    """
    out: list[str] = []
    in_table = False
    in_list = False

    def close() -> None:
        nonlocal in_table, in_list
        if in_table:
            out.append("</table>")
            in_table = False
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in markdown.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            close()
            continue
        if line.startswith("| --- "):
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not in_table:
                close()
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
                continue
            out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue
        close()
        if line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("> "):
            css = ' class="warning"' if "Varning" in line else ""
            out.append(f"<blockquote{css}>{_inline(line[2:])}</blockquote>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        elif in_list and line.startswith("  "):
            out.append(f" {_inline(line.strip())}")
        else:
            out.append(f"<p>{_inline(line)}</p>")
    close()
    return _HTML_PAGE.format(notice_id=utilization.notice_id, body="\n".join(out))


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=True).replace("&lt;br&gt;", "<br>")
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return _LINK.sub(r'<a href="\2">\1</a>', escaped)
