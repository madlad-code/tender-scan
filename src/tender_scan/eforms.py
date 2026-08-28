"""One eForms notice, read as a graph of ids instead of a bag of fields.

eForms publishes the facts we care about — who won which lot, and under which
ceiling — as separate elements linked by id, so every downstream module (cap
extraction, winner matching, reports) would otherwise repeat the same walk:

    LotResult ──TenderLot/ID───────────────► LOT-nnnn
        ├── FrameworkAgreementValues/MaximumValueAmount   (that lot's ceiling)
        └── SettledContract/ID ────────────► CON-nnnn
    SettledContract ──LotTender/ID─────────► TEN-nnnn
    LotTender ──TenderingParty/ID──────────► TPA-nnnn
    TenderingParty ──Tenderer/ID───────────► ORG-nnnn

Doing it once here also keeps the two traps in one place. First, the XML is
UBL 2.3 with eForms extensions and the namespace prefixes drift between SDK
versions, so everything is matched by *local name*. Second, LotTender and
SettledContract each appear twice: as bare id stubs inside LotResult, and as
full elements later in NoticeResult. The full ones are selected by the
children they carry (TenderingParty / AwardDate), never by document order.

Amounts are Decimal because they are money. Rounding to integer SEK, and any
currency conversion, belongs to the caller.
"""

from __future__ import annotations

import html
import os
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

XML_URL_TEMPLATE = "https://ted.europa.eu/en/notice/{notice_id}/xml"
DEFAULT_CACHE_DIR = "data/xml_cache"


class EformsError(Exception):
    """Raised when a notice XML cannot be fetched, read or parsed."""


# -- namespace-agnostic helpers ----------------------------------------------
# Public because report.py and the other readers share them; they all take an
# optional element so an absent parent short-circuits to None instead of
# forcing a None check at every call site.


def local_name(tag: str) -> str:
    return tag.split("}")[-1]


def name_text(el: ET.Element | None) -> str | None:
    """Text of a human-readable name, with TED's double-encoded entities undone.

    TED publishes `Ernst &amp;amp; Young Aktiebolag` — the ampersand is escaped
    twice, so one XML decode leaves a literal `&amp;` in the name. That reaches
    a report as-is and, worse, stops the name matching a supplier ledger. 10 of
    the 137 cached notices are affected. Applied only to names: amounts, dates
    and ids have no entities to undo and must not be touched.
    """
    text = text_of(el)
    return html.unescape(text) if text else text


def text_of(el: ET.Element | None) -> str | None:
    text = (el.text or "").strip() if el is not None else ""
    return text or None


def first(root: ET.Element | None, name: str) -> ET.Element | None:
    """The first descendant-or-self with this local name, in document order."""
    if root is None:
        return None
    return next((el for el in root.iter() if local_name(el.tag) == name), None)


def first_name_text(root: ET.Element | None, name: str) -> str | None:
    return name_text(first(root, name))


def first_text(root: ET.Element | None, name: str) -> str | None:
    return text_of(first(root, name))


def child(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    return next((c for c in el if local_name(c.tag) == name), None)


def children(el: ET.Element | None, name: str) -> list[ET.Element]:
    if el is None:
        return []
    return [c for c in el if local_name(c.tag) == name]


def coded_text(root: ET.Element | None, name: str, list_name: str) -> str | None:
    """Text of the first `name` element tagged with a given codelist.

    eForms reuses element names across codelists — a lot carries two
    ContractingSystemTypeCode children, one for `dps-usage` and one for
    `framework-agreement` — so the listName is part of the selector.
    """
    if root is None:
        return None
    for el in root.iter():
        if local_name(el.tag) == name and el.get("listName") == list_name:
            return text_of(el)
    return None


def amount(el: ET.Element | None) -> Amount | None:
    text = text_of(el)
    if el is None or text is None:
        return None
    try:
        return Amount(value=Decimal(text), currency=el.get("currencyID"))
    except InvalidOperation:
        return None


def date_part(text: str | None) -> str | None:
    """Trim the zone offset eForms dates carry: "2025-08-14+02:00" -> "2025-08-14"."""
    return text[:10] if text else None


# -- notice facts ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Amount:
    value: Decimal
    currency: str | None


@dataclass(frozen=True, slots=True)
class Organization:
    org_id: str
    name: str | None
    company_id: str | None  # raw CompanyID text; normalization is orgnr.py's job
    country: str | None
    city: str | None


@dataclass(frozen=True, slots=True)
class Lot:
    lot_id: str
    name: str | None
    estimated_value: Amount | None
    framework_maximum: Amount | None  # BT-271 at lot level, inside RequestedTenderTotal
    framework_type: str | None  # "fa-wo-rc" | "fa-w-rc" | "fa-mix" | "none" | None
    period_start: str | None
    period_end: str | None


@dataclass(frozen=True, slots=True)
class LotResult:
    result_id: str
    lot_id: str | None
    max_value: Amount | None  # the per-lot ceiling (BT-271)
    reestimated_value: Amount | None
    winner_selection_status: str | None
    tender_count: int | None
    settled_contract_ids: tuple[str, ...]
    lot_tender_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LotTender:
    tender_id: str
    tendering_party_id: str | None
    lot_id: str | None
    rank: int | None
    # The tender's own value. Published as 0 when the buyer disclosed none; this
    # module reports what the notice says and leaves that reading to the caller.
    payable_amount: Amount | None


@dataclass(frozen=True, slots=True)
class SettledContract:
    contract_id: str
    award_date: str | None
    title: str | None
    lot_tender_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NoticeGraph:
    notice_id: str
    notice_type: str | None
    issue_date: str | None  # the notice's own publication date, for FX conversion
    title: str | None
    cpv_main: str | None
    buyer_org_id: str | None
    organizations: dict[str, Organization]
    lots: dict[str, Lot]
    lot_results: tuple[LotResult, ...]
    lot_tenders: dict[str, LotTender]
    tendering_parties: dict[str, str]  # TPA-id -> ORG-id
    settled_contracts: dict[str, SettledContract]
    overall_maximum: Amount | None
    overall_approximate: Amount | None
    framework_maximum: Amount | None  # BT-271 at notice level
    estimated_overall: Amount | None

    @property
    def buyer(self) -> Organization | None:
        return self.organizations.get(self.buyer_org_id or "")

    def is_framework(self) -> bool:
        return any(lot.framework_type not in (None, "none") for lot in self.lots.values())

    def winners_for_lot(self, lot_id: str) -> tuple[tuple[Organization, str | None], ...]:
        """(organisation, settled-contract id) for every distinct winner of one lot."""
        winners: list[tuple[Organization, str | None]] = []
        seen: set[str] = set()
        for result in self.lot_results:
            if result.lot_id != lot_id:
                continue
            for tender_id, contract_id in self.tenders_of(result):
                tender = self.lot_tenders.get(tender_id)
                if tender is None or tender.lot_id not in (None, lot_id):
                    continue  # one contract may settle tenders across several lots
                org_id = self.tendering_parties.get(tender.tendering_party_id or "")
                org = self.organizations.get(org_id or "")
                if org is None or org.org_id in seen:
                    continue
                seen.add(org.org_id)
                winners.append((org, contract_id))
        return tuple(winners)

    def tenders_of(self, result: LotResult) -> Iterator[tuple[str, str | None]]:
        """Tender ids of one LotResult, each with the contract that settled it."""
        settled: set[str] = set()
        for contract_id in result.settled_contract_ids:
            contract = self.settled_contracts.get(contract_id)
            if contract is None:
                continue
            for tender_id in contract.lot_tender_ids:
                settled.add(tender_id)
                yield tender_id, contract_id
        for tender_id in result.lot_tender_ids:
            if tender_id not in settled:
                yield tender_id, None


# -- parsing -----------------------------------------------------------------


def _organization(org: ET.Element) -> Organization | None:
    """One efac:Organization. Its parts are nested under Company but unique in the element,
    so they are read from the whole element — Name in particular must not pick up
    the contact person, which is why it goes through PartyName."""
    org_id = text_of(child(first(org, "PartyIdentification"), "ID"))
    if org_id is None:
        return None
    address = first(org, "PostalAddress")
    return Organization(
        org_id=org_id,
        name=first_name_text(first(org, "PartyName"), "Name"),
        # CompanyID carries schemeID="002" in some notices and no attribute in
        # others, so the attribute is never part of the selector.
        company_id=first_text(org, "CompanyID"),
        country=first_text(first(address, "Country"), "IdentificationCode"),
        city=first_text(address, "CityName"),
    )


def _lot(el: ET.Element) -> Lot | None:
    lot_id = text_of(child(el, "ID"))
    if lot_id is None:
        return None
    project = child(el, "ProcurementProject")
    period = first(project, "PlannedPeriod")
    return Lot(
        lot_id=lot_id,
        name=first_name_text(project, "Name"),
        estimated_value=amount(first(project, "EstimatedOverallContractAmount")),
        framework_maximum=amount(first(project, "FrameworkMaximumAmount")),
        framework_type=coded_text(el, "ContractingSystemTypeCode", "framework-agreement"),
        period_start=date_part(first_text(period, "StartDate")),
        period_end=date_part(first_text(period, "EndDate")),
    )


def _tender_count(result: ET.Element) -> int | None:
    """Received tenders for one lot; the statistics block also counts other things."""
    total = None
    for stats in children(result, "ReceivedSubmissionsStatistics"):
        numeric = text_of(child(stats, "StatisticsNumeric"))
        if text_of(child(stats, "StatisticsCode")) == "tenders" and numeric is not None:
            total = (total or 0) + int(float(numeric))
    return total


def _lot_result(el: ET.Element) -> LotResult | None:
    result_id = text_of(child(el, "ID"))
    if result_id is None:
        return None
    values = child(el, "FrameworkAgreementValues")
    return LotResult(
        result_id=result_id,
        lot_id=text_of(child(child(el, "TenderLot"), "ID")),
        max_value=amount(child(values, "MaximumValueAmount")),
        reestimated_value=amount(child(values, "ReestimatedValueAmount")),
        winner_selection_status=coded_text(el, "TenderResultCode", "winner-selection-status"),
        tender_count=_tender_count(el),
        settled_contract_ids=_stub_ids(el, "SettledContract"),
        lot_tender_ids=_stub_ids(el, "LotTender"),
    )


def _stub_ids(el: ET.Element, name: str) -> tuple[str, ...]:
    return tuple(
        text for stub in children(el, name) if (text := text_of(child(stub, "ID"))) is not None
    )


def _lot_tender(el: ET.Element) -> LotTender | None:
    tender_id = text_of(child(el, "ID"))
    if tender_id is None:
        return None
    rank = text_of(child(el, "RankCode"))
    return LotTender(
        tender_id=tender_id,
        tendering_party_id=text_of(child(child(el, "TenderingParty"), "ID")),
        lot_id=text_of(child(child(el, "TenderLot"), "ID")),
        rank=int(rank) if rank is not None and rank.isdigit() else None,
        payable_amount=amount(child(child(el, "LegalMonetaryTotal"), "PayableAmount")),
    )


def _settled_contract(el: ET.Element) -> SettledContract | None:
    contract_id = text_of(child(el, "ID"))
    if contract_id is None:
        return None
    return SettledContract(
        contract_id=contract_id,
        award_date=date_part(text_of(child(el, "AwardDate"))),
        title=name_text(child(el, "Title")),
        lot_tender_ids=_stub_ids(el, "LotTender"),
    )


def _is_full_lot_tender(el: ET.Element) -> bool:
    """Full LotTenders carry a TenderingParty; the stubs inside LotResult carry only an ID."""
    return child(el, "TenderingParty") is not None


def _is_full_settled_contract(el: ET.Element) -> bool:
    return child(el, "AwardDate") is not None or child(el, "LotTender") is not None


def parse_graph(xml_bytes: bytes, notice_id: str) -> NoticeGraph:
    """Read one eForms notice XML into a resolved graph."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise EformsError(f"Could not parse eForms XML for {notice_id}: {exc}") from exc

    notice_result = first(root, "NoticeResult")
    project = child(root, "ProcurementProject")  # the notice-level one; lots have their own

    organizations = {}
    for el in root.iter():
        if local_name(el.tag) == "Organization" and (org := _organization(el)) is not None:
            organizations[org.org_id] = org

    lots = {}
    for el in root.iter():
        if local_name(el.tag) == "ProcurementProjectLot" and (lot := _lot(el)) is not None:
            lots[lot.lot_id] = lot

    lot_results = []
    lot_tenders = {}
    settled_contracts = {}
    tendering_parties = {}
    for el in list(notice_result.iter()) if notice_result is not None else []:
        name = local_name(el.tag)
        if name == "LotResult" and (result := _lot_result(el)) is not None:
            lot_results.append(result)
        elif name == "LotTender" and _is_full_lot_tender(el):
            if (tender := _lot_tender(el)) is not None:
                lot_tenders[tender.tender_id] = tender
        elif name == "SettledContract" and _is_full_settled_contract(el):
            if (contract := _settled_contract(el)) is not None:
                settled_contracts[contract.contract_id] = contract
        elif name == "TenderingParty":
            party_id = text_of(child(el, "ID"))
            org_id = text_of(child(child(el, "Tenderer"), "ID"))
            if party_id is not None and org_id is not None:
                tendering_parties[party_id] = org_id

    buyer_party = first(child(root, "ContractingParty"), "PartyIdentification")

    return NoticeGraph(
        notice_id=notice_id,
        notice_type=coded_text(root, "NoticeTypeCode", "result"),
        # Direct child only: SettledContract carries its own IssueDate deeper in
        # the extension, and that one is the contract's date, not the notice's.
        issue_date=date_part(text_of(child(root, "IssueDate"))),
        title=first_name_text(project, "Name"),
        cpv_main=first_text(
            first(project, "MainCommodityClassification"), "ItemClassificationCode"
        ),
        buyer_org_id=text_of(child(buyer_party, "ID")),
        organizations=organizations,
        lots=lots,
        lot_results=tuple(lot_results),
        lot_tenders=lot_tenders,
        tendering_parties=tendering_parties,
        settled_contracts=settled_contracts,
        overall_maximum=amount(first(notice_result, "OverallMaximumFrameworkContractsAmount")),
        overall_approximate=amount(
            first(notice_result, "OverallApproximateFrameworkContractsAmount")
        ),
        framework_maximum=amount(first(project, "FrameworkMaximumAmount")),
        estimated_overall=amount(first(project, "EstimatedOverallContractAmount")),
    )


# -- fetching ----------------------------------------------------------------


# Free-text elements a Swedish buyer states the ceiling in when they do not
# fill in the structured field. Titles are excluded: they are too short to
# carry an amount and too easy to misread ("Ramavtal 2026-2030").
_TEXT_TAGS = ("Description", "Note", "AdditionalInformation")


def notice_text(xml_bytes: bytes) -> str:
    """All prose in one notice, for the regex ceiling fallback.

    The structured fields are always preferred; this exists because 43 of the
    137 cached Swedish framework notices publish no ceiling field at all, and
    a handful of those state it in the description instead.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""
    parts = [
        el.text.strip()
        for el in root.iter()
        if local_name(el.tag) in _TEXT_TAGS and el.text and el.text.strip()
    ]
    return "\n".join(parts)


def _cache_path(notice_id: str, cache_dir: Path | None) -> Path:
    directory = cache_dir or Path(os.environ.get("TENDER_SCAN_XML_CACHE", DEFAULT_CACHE_DIR))
    return Path(directory) / f"{notice_id}.xml"


def fetch_notice_xml(
    notice_id: str,
    cache_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> bytes:
    """Return one notice's eForms XML, from the on-disk cache when it is there.

    Notice XML never changes once published, so a cached file is authoritative
    and the network is not touched at all.
    """
    path = _cache_path(notice_id, cache_dir)
    if path.exists():
        return path.read_bytes()

    url = XML_URL_TEMPLATE.format(notice_id=notice_id)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise EformsError(f"Could not fetch {url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    if response.status_code != 200:
        raise EformsError(f"TED returned {response.status_code} for {url}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return response.content


def load_graph(
    notice_id: str,
    xml_path: Path | None = None,
    cache_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> NoticeGraph:
    """Load one notice from an explicit XML file, or from the cache/TED."""
    if xml_path is not None:
        try:
            xml_bytes = xml_path.read_bytes()
        except OSError as exc:
            raise EformsError(f"Could not read {xml_path}: {exc}") from exc
    else:
        xml_bytes = fetch_notice_xml(notice_id, cache_dir=cache_dir, client=client)
    return parse_graph(xml_bytes, notice_id)
