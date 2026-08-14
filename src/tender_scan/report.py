"""Framework agreement report engine.

Automates the manual week-1 validation (docs/validering-vecka1.md): given a
TED publication number, fetch the notice's eForms XML, extract the framework
agreement amounts (ceiling, the buyer's own forecast, estimated contract
value, period when published), and render a comparison report — optionally
against call-off amounts supplied by the user.

eForms XML is UBL 2.3 with eForms extensions. Elements are matched by local
name (namespace-agnostic) so the parser tolerates SDK version drift; the
relevant business terms are:

  OverallMaximumFrameworkContractsAmount      takvolym (ceiling, BT-118)
  OverallApproximateFrameworkContractsAmount  buyer's own forecast (BT-661)
  EstimatedOverallContractAmount              estimated contract value
"""

from __future__ import annotations

import csv
import html
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

XML_URL_TEMPLATE = "https://ted.europa.eu/en/notice/{notice_id}/xml"
NOTICE_URL_TEMPLATE = "https://ted.europa.eu/en/notice/-/detail/{notice_id}"


class ReportError(Exception):
    """Raised when the notice XML cannot be fetched or parsed."""


@dataclass(frozen=True, slots=True)
class Amount:
    value: float
    currency: str | None

    def format(self) -> str:
        text = f"{self.value:,.0f}".replace(",", " ")
        return f"{text} {self.currency}" if self.currency else text


@dataclass(frozen=True, slots=True)
class CallOff:
    label: str
    amount: float


@dataclass(frozen=True, slots=True)
class FrameworkData:
    """Facts extracted from one eForms contract award notice."""

    notice_id: str
    title: str | None
    buyer: str | None
    cpv: str | None
    max_value: Amount | None  # takvolym (ceiling)
    approx_value: Amount | None  # buyer's own forecast
    estimated_value: Amount | None
    tender_count: int | None
    winners: tuple[str, ...]
    award_date: str | None
    period_start: str | None
    period_end: str | None
    url: str


# -- XML parsing (namespace-agnostic by local name) --------------------------


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _first(root: ET.Element, local_name: str) -> ET.Element | None:
    return next((el for el in root.iter() if _local(el.tag) == local_name), None)


def _first_text(root: ET.Element, local_name: str) -> str | None:
    el = _first(root, local_name)
    text = (el.text or "").strip() if el is not None else ""
    return text or None


def _amount(el: ET.Element | None) -> Amount | None:
    if el is None:
        return None
    try:
        value = float((el.text or "").strip())
    except ValueError:
        return None
    return Amount(value=value, currency=el.get("currencyID"))


def _date_part(text: str | None) -> str | None:
    return text[:10] if text else None


def _child(el: ET.Element, local_name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == local_name), None)


def _organization_names(root: ET.Element) -> dict[str, str]:
    """Map organization IDs (ORG-xxxx) to company names."""
    names: dict[str, str] = {}
    for org in (el for el in root.iter() if _local(el.tag) == "Organization"):
        org_id = name = None
        for el in org.iter():
            local = _local(el.tag)
            if local == "ID" and el.get("schemeName") == "organization" and org_id is None:
                org_id = (el.text or "").strip()
            elif local == "Name" and name is None:
                name = (el.text or "").strip()
        if org_id and name:
            names[org_id] = name
    return names


def _winners(root: ET.Element, org_names: dict[str, str]) -> tuple[str, ...]:
    """Resolve SettledContract -> LotTender -> TenderingParty -> Tenderer -> name."""
    tender_to_party: dict[str, str] = {}
    party_to_org: dict[str, str] = {}
    for el in root.iter():
        local = _local(el.tag)
        if local == "LotTender":
            tender_id = _child(el, "ID")
            party = _child(el, "TenderingParty")
            party_id = _child(party, "ID") if party is not None else None
            if tender_id is not None and party_id is not None:
                tender_to_party[(tender_id.text or "").strip()] = (party_id.text or "").strip()
        elif local == "TenderingParty":
            party_id = _child(el, "ID")
            tenderer = _child(el, "Tenderer")
            org_id = _child(tenderer, "ID") if tenderer is not None else None
            if party_id is not None and org_id is not None:
                party_to_org[(party_id.text or "").strip()] = (org_id.text or "").strip()

    winners: list[str] = []
    for contract in (el for el in root.iter() if _local(el.tag) == "SettledContract"):
        for lot_tender in (c for c in contract if _local(c.tag) == "LotTender"):
            tender_id = _child(lot_tender, "ID")
            if tender_id is None:
                continue
            org_id = party_to_org.get(tender_to_party.get((tender_id.text or "").strip(), ""))
            name = org_names.get(org_id or "")
            if name and name not in winners:
                winners.append(name)
    return tuple(winners)


def _buyer(root: ET.Element, org_names: dict[str, str]) -> str | None:
    contracting = _first(root, "ContractingParty")
    if contracting is None:
        return None
    party = _child(contracting, "Party")
    if party is None:
        return None
    identification = _child(party, "PartyIdentification")
    org_id = _child(identification, "ID") if identification is not None else None
    if org_id is None:
        return None
    return org_names.get((org_id.text or "").strip())


def _tender_count(root: ET.Element) -> int | None:
    total = None
    for stats in (el for el in root.iter() if _local(el.tag) == "ReceivedSubmissionsStatistics"):
        code = _child(stats, "StatisticsCode")
        numeric = _child(stats, "StatisticsNumeric")
        if code is not None and numeric is not None and (code.text or "").strip() == "tenders":
            total = (total or 0) + int(float((numeric.text or "0").strip()))
    return total


def _period(root: ET.Element) -> tuple[str | None, str | None]:
    """Start/end of the first PlannedPeriod with actual dates, if published."""
    for period in (el for el in root.iter() if _local(el.tag) == "PlannedPeriod"):
        start = _child(period, "StartDate")
        end = _child(period, "EndDate")
        if start is not None or end is not None:
            return (
                _date_part((start.text or "").strip() if start is not None else None),
                _date_part((end.text or "").strip() if end is not None else None),
            )
    return None, None


def parse_eforms_xml(xml_bytes: bytes, notice_id: str) -> FrameworkData:
    """Extract framework agreement facts from one eForms notice XML."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ReportError(f"Could not parse eForms XML for {notice_id}: {exc}") from exc

    org_names = _organization_names(root)
    project = _first(root, "ProcurementProject")
    title = _first_text(project, "Name") if project is not None else None
    cpv_el = _first(root, "ItemClassificationCode")
    award_date = _date_part(_first_text(root, "AwardDate"))
    period_start, period_end = _period(root)

    return FrameworkData(
        notice_id=notice_id,
        title=title,
        buyer=_buyer(root, org_names),
        cpv=(cpv_el.text or "").strip() if cpv_el is not None else None,
        max_value=_amount(_first(root, "OverallMaximumFrameworkContractsAmount")),
        approx_value=_amount(_first(root, "OverallApproximateFrameworkContractsAmount")),
        estimated_value=_amount(_first(root, "EstimatedOverallContractAmount")),
        tender_count=_tender_count(root),
        winners=_winners(root, org_names),
        award_date=award_date,
        period_start=period_start,
        period_end=period_end,
        url=NOTICE_URL_TEMPLATE.format(notice_id=notice_id),
    )


# -- fetching ----------------------------------------------------------------


def fetch_eforms_xml(notice_id: str, client: httpx.Client | None = None) -> bytes:
    """Fetch the multilingual eForms XML for one notice from ted.europa.eu."""
    url = XML_URL_TEMPLATE.format(notice_id=notice_id)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise ReportError(f"Could not fetch {url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    if response.status_code != 200:
        raise ReportError(f"TED returned {response.status_code} for {url}")
    return response.content


def load_framework_data(
    notice_id: str,
    xml_path: Path | None = None,
    client: httpx.Client | None = None,
) -> FrameworkData:
    """Load one notice from a local eForms XML file, or from TED when no path is given."""
    if xml_path is not None:
        try:
            xml_bytes = xml_path.read_bytes()
        except OSError as exc:
            raise ReportError(f"Could not read {xml_path}: {exc}") from exc
    else:
        xml_bytes = fetch_eforms_xml(notice_id, client=client)
    return parse_eforms_xml(xml_bytes, notice_id)


# -- call-off data -----------------------------------------------------------


def parse_calloff_args(args: list[str]) -> list[CallOff]:
    """Parse inline call-offs from CLI options: "2025=1200000" or just "1200000"."""
    calloffs: list[CallOff] = []
    for arg in args:
        label, _, raw_amount = arg.rpartition("=")
        try:
            amount = float(raw_amount.strip().replace(" ", "").replace("\xa0", ""))
        except ValueError as exc:
            raise ReportError(
                f"Could not read call-off {arg!r}; expected 'label=amount' or 'amount'."
            ) from exc
        calloffs.append(CallOff(label=label.strip() or f"Avrop {len(calloffs) + 1}", amount=amount))
    return calloffs


def read_calloff_csv(path: Path) -> list[CallOff]:
    """Read call-offs from a CSV file: label,amount (also accepts ';')."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines:
        return []
    delimiter = ";" if ";" in lines[0] else ","
    calloffs: list[CallOff] = []
    for row in csv.reader(lines, delimiter=delimiter):
        if len(row) < 2:
            continue
        label, raw_amount = row[0].strip(), row[1].strip()
        try:
            amount = float(raw_amount.replace(" ", "").replace(" ", ""))
        except ValueError:
            continue  # header or malformed row
        calloffs.append(CallOff(label=label or f"Avrop {len(calloffs) + 1}", amount=amount))
    return calloffs


# -- rendering ---------------------------------------------------------------

_MISSING = "*saknas i annonsen*"

_NO_CALLOFF_NOTE = (
    "Ingen avropsdata angiven. Faktiskt avropat finns inte i någon öppen databas — "
    "begär ut det enligt offentlighetsprincipen (mall: docs/begaran-mall.md) och kör "
    "om rapporten med `--avrop` eller `--avrop-fil`."
)


def _fmt(amount: Amount | None) -> str:
    return amount.format() if amount else _MISSING


def _pct(part: float, whole: Amount | None) -> str | None:
    if whole is None or whole.value == 0:
        return None
    return f"{part / whole.value * 100:.0f} %"


def _summary_rows(data: FrameworkData) -> list[tuple[str, str, str]]:
    """(label, value, eForms source) rows for the report header table."""
    period = _MISSING
    if data.period_start or data.period_end:
        period = f"{data.period_start or '?'} – {data.period_end or '?'}"
    return [
        ("Köpare", data.buyer or _MISSING, "cac:ContractingParty"),
        ("Avtalsområde (CPV)", data.cpv or _MISSING, "MainCommodityClassification"),
        ("Takvolym (max)", _fmt(data.max_value), "OverallMaximumFrameworkContractsAmount"),
        (
            "Myndighetens prognos",
            _fmt(data.approx_value),
            "OverallApproximateFrameworkContractsAmount",
        ),
        ("Uppskattat kontraktsvärde", _fmt(data.estimated_value), "EstimatedOverallContractAmount"),
        (
            "Antal anbudsgivare",
            str(data.tender_count) if data.tender_count is not None else _MISSING,
            "ReceivedSubmissionsStatistics",
        ),
        ("Vinnare", "; ".join(data.winners) or _MISSING, "SettledContract"),
        ("Kontrakt tecknat", data.award_date or _MISSING, "AwardDate"),
        ("Avtalsperiod", period, "PlannedPeriod"),
    ]


def _analysis_lines(data: FrameworkData, calloffs: list[CallOff]) -> list[str]:
    """The comparison bullets: ceiling vs forecast vs call-offs."""
    lines: list[str] = []
    if data.max_value and data.approx_value and data.max_value.value:
        share = _pct(data.approx_value.value, data.max_value)
        lines.append(
            f"Myndighetens egen prognos är **{share}** av takvolymen "
            f"({data.approx_value.format()} av {data.max_value.format()})."
        )
    elif data.max_value:
        lines.append(
            f"Takvolym {data.max_value.format()}; myndigheten har inte publicerat någon "
            "egen prognos i annonsen."
        )
    else:
        lines.append(
            "Annonsen innehåller inga ramavtalsbelopp (takvolym/prognos) — den är "
            "möjligen inte en ramavtalstilldelning."
        )

    if calloffs:
        total = sum(c.amount for c in calloffs)
        reference = data.max_value or data.approx_value or data.estimated_value
        total_amount = Amount(total, reference.currency if reference else None)
        vs_max = _pct(total, data.max_value)
        vs_approx = _pct(total, data.approx_value)
        lines.append(f"Avropat hittills: **{total_amount.format()}**.")
        if vs_max:
            headroom = Amount(data.max_value.value - total, data.max_value.currency)
            lines.append(
                f"Det är **{vs_max}** av takvolymen — kvar under taket: {headroom.format()}."
            )
        if vs_approx:
            lines.append(f"Motsvarar **{vs_approx}** av myndighetens egen prognos.")
    return lines


def render_markdown(data: FrameworkData, calloffs: list[CallOff] | None = None) -> str:
    calloffs = calloffs or []
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    out = [
        f"# Ramavtalsrapport: {data.title or data.notice_id}",
        "",
        f"**TED-annons:** [{data.notice_id}]({data.url}) · Genererad {generated} av tender-scan.",
        "Alla uppgifter i tabellen är hämtade ur den offentliga eForms-annonsen.",
        "",
        "| Uppgift | Värde | Källa (eForms) |",
        "|---|---|---|",
    ]
    out += [f"| {label} | {value} | `{source}` |" for label, value, source in _summary_rows(data)]
    out += ["", "## Takvolym vs prognos", ""]
    out += [f"- {line}" for line in _analysis_lines(data, calloffs)]

    out += ["", "## Avrop", ""]
    if calloffs:
        out += ["| Avrop | Belopp |", "|---|---|"]
        out += [f"| {c.label} | {c.amount:,.0f} |".replace(",", " ") for c in calloffs]
        total = sum(c.amount for c in calloffs)
        out.append(f"| **Summa** | **{total:,.0f}** |".replace(",", " "))
    else:
        out.append(f"*{_NO_CALLOFF_NOTE}*")
    out.append("")
    return "\n".join(out)


_HTML_PAGE = """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ramavtalsrapport {notice_id}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 46rem;
         padding: 0 1rem; background: #fafafa; color: #222; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 1.6rem; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; }}
  th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left;
            font-size: 0.9rem; }}
  th {{ background: #f0f0f0; }}
  .meta {{ color: #666; font-size: 0.85rem; }}
  code {{ background: #eee; padding: 0 0.2rem; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>Ramavtalsrapport: {title}</h1>
<p class="meta">TED-annons: <a href="{url}">{notice_id}</a> · Genererad {generated}
av tender-scan. Alla uppgifter i tabellen är hämtade ur den offentliga eForms-annonsen.</p>
<table>
<tr><th>Uppgift</th><th>Värde</th><th>Källa (eForms)</th></tr>
{summary_rows}
</table>
<h2>Takvolym vs prognos</h2>
<ul>
{analysis}
</ul>
<h2>Avrop</h2>
{calloffs}
</body>
</html>
"""


def render_html(data: FrameworkData, calloffs: list[CallOff] | None = None) -> str:
    calloffs = calloffs or []

    def esc(text: str) -> str:
        return html.escape(text, quote=True)

    def strip_md(text: str) -> str:
        return text.replace("**", "").replace("*", "").replace("`", "")

    summary = "\n".join(
        f"<tr><td>{esc(label)}</td><td>{esc(strip_md(value))}</td>"
        f"<td><code>{esc(source)}</code></td></tr>"
        for label, value, source in _summary_rows(data)
    )
    analysis = "\n".join(
        f"<li>{esc(strip_md(line))}</li>" for line in _analysis_lines(data, calloffs)
    )
    if calloffs:
        rows = "\n".join(
            f"<tr><td>{esc(c.label)}</td><td>{c.amount:,.0f}</td></tr>".replace(",", " ")
            for c in calloffs
        )
        total = sum(c.amount for c in calloffs)
        total_row = f"<tr><th>Summa</th><th>{total:,.0f}</th></tr>".replace(",", " ")
        calloff_html = (
            f"<table>\n<tr><th>Avrop</th><th>Belopp</th></tr>\n{rows}\n{total_row}\n</table>"
        )
    else:
        calloff_html = f'<p class="meta">{esc(strip_md(_NO_CALLOFF_NOTE))}</p>'

    return _HTML_PAGE.format(
        notice_id=esc(data.notice_id),
        title=esc(data.title or data.notice_id),
        url=esc(data.url),
        generated=datetime.now(UTC).strftime("%Y-%m-%d"),
        summary_rows=summary,
        analysis=analysis,
        calloffs=calloff_html,
    )
