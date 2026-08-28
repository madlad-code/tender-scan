import xml.etree.ElementTree as ET
from decimal import Decimal

import httpx
import pytest

from tender_scan.eforms import (
    Amount,
    EformsError,
    amount,
    child,
    coded_text,
    date_part,
    fetch_notice_xml,
    first_text,
    load_graph,
    local_name,
    parse_graph,
)

# One contract settling two tenders that belong to *different* lots: the winner
# of LOT-0002 must not surface as a winner of LOT-0001.
CROSS_LOT_XML = b"""<?xml version="1.0"?>
<ContractAwardNotice xmlns="urn:oasis:names:specification:ubl:schema:xsd:ContractAwardNotice-2">
  <NoticeTypeCode listName="result">can-standard</NoticeTypeCode>
  <ProcurementProject><Name>Delad upphandling</Name></ProcurementProject>
  <ProcurementProjectLot>
    <ID schemeName="Lot">LOT-0001</ID>
    <TenderingProcess><ContractingSystem>
      <ContractingSystemTypeCode listName="framework-agreement">fa-w-rc</ContractingSystemTypeCode>
    </ContractingSystem></TenderingProcess>
  </ProcurementProjectLot>
  <ProcurementProjectLot><ID schemeName="Lot">LOT-0002</ID></ProcurementProjectLot>
  <NoticeResult>
    <LotResult>
      <ID schemeName="result">RES-0001</ID>
      <SettledContract><ID schemeName="contract">CON-0001</ID></SettledContract>
      <TenderLot><ID schemeName="Lot">LOT-0001</ID></TenderLot>
    </LotResult>
    <LotTender>
      <ID schemeName="tender">TEN-0001</ID>
      <RankCode>2</RankCode>
      <TenderingParty><ID>TPA-0001</ID></TenderingParty>
      <TenderLot><ID schemeName="Lot">LOT-0001</ID></TenderLot>
    </LotTender>
    <LotTender>
      <ID schemeName="tender">TEN-0002</ID>
      <TenderingParty><ID>TPA-0002</ID></TenderingParty>
      <TenderLot><ID schemeName="Lot">LOT-0002</ID></TenderLot>
    </LotTender>
    <SettledContract>
      <ID schemeName="contract">CON-0001</ID>
      <AwardDate>2026-02-01+01:00</AwardDate>
      <LotTender><ID>TEN-0001</ID></LotTender>
      <LotTender><ID>TEN-0002</ID></LotTender>
    </SettledContract>
    <TenderingParty><ID>TPA-0001</ID><Tenderer><ID>ORG-0002</ID></Tenderer></TenderingParty>
    <TenderingParty><ID>TPA-0002</ID><Tenderer><ID>ORG-0003</ID></Tenderer></TenderingParty>
    <Organizations>
      <Organization><Company>
        <PartyIdentification><ID schemeName="organization">ORG-0002</ID></PartyIdentification>
        <PartyName><Name>Vinnare Ett AB</Name></PartyName>
      </Company></Organization>
      <Organization><Company>
        <PartyIdentification><ID schemeName="organization">ORG-0003</ID></PartyIdentification>
        <PartyName><Name>Vinnare Tva AB</Name></PartyName>
      </Company></Organization>
    </Organizations>
  </NoticeResult>
</ContractAwardNotice>
"""


@pytest.fixture
def graph_1884(eforms_1884):
    return parse_graph(eforms_1884, "1884-2026")


@pytest.fixture
def graph_15840(eforms_15840):
    return parse_graph(eforms_15840, "15840-2026")


@pytest.fixture
def graph_8020(eforms_8020):
    return parse_graph(eforms_8020, "8020-2026")


def exploding_client() -> httpx.Client:
    """A client that fails the test if anything asks it for the network."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"the network was touched: {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


# -- helpers -----------------------------------------------------------------


def test_helpers_match_by_local_name_whatever_the_prefix():
    root = ET.fromstring(
        b'<a:Notice xmlns:a="urn:a" xmlns:b="urn:b">'
        b"<b:Wrapper><a:Value>17</a:Value></b:Wrapper></a:Notice>"
    )

    assert local_name(root.tag) == "Notice"
    assert child(root, "Wrapper") is not None
    assert child(root, "Value") is None  # a grandchild, not a child
    assert first_text(root, "Value") == "17"


def test_amount_is_decimal_never_float():
    el = ET.fromstring(b'<MaximumValueAmount currencyID="SEK">1500000</MaximumValueAmount>')

    parsed = amount(el)

    assert parsed == Amount(Decimal("1500000"), "SEK")
    assert isinstance(parsed.value, Decimal)
    assert not isinstance(parsed.value, float)


def test_amount_returns_none_for_missing_or_unreadable_values():
    assert amount(None) is None
    assert amount(ET.fromstring(b"<Amount/>")) is None
    assert amount(ET.fromstring(b"<Amount>ej angivet</Amount>")) is None


def test_coded_text_selects_on_the_codelist():
    root = ET.fromstring(
        b"<TenderingProcess>"
        b'<ContractingSystemTypeCode listName="dps-usage">none</ContractingSystemTypeCode>'
        b'<ContractingSystemTypeCode listName="framework-agreement">fa-mix'
        b"</ContractingSystemTypeCode></TenderingProcess>"
    )

    assert coded_text(root, "ContractingSystemTypeCode", "framework-agreement") == "fa-mix"


def test_date_part_drops_the_zone_offset():
    assert date_part("2025-08-14+02:00") == "2025-08-14"
    assert date_part("2025-12-05Z") == "2025-12-05"
    assert date_part(None) is None


# -- 1884-2026: single lot ---------------------------------------------------


def test_1884_reads_the_notice_level_amounts(graph_1884):
    assert graph_1884.overall_maximum == Amount(Decimal("3000000"), "SEK")
    assert graph_1884.overall_approximate == Amount(Decimal("1500000"), "SEK")
    assert graph_1884.estimated_overall == Amount(Decimal("3000000"), "SEK")


def test_1884_has_one_lot_carrying_its_own_ceiling(graph_1884):
    assert list(graph_1884.lots) == ["LOT-0000"]
    assert len(graph_1884.lot_results) == 1

    result = graph_1884.lot_results[0]

    assert result.result_id == "RES-0001"
    assert result.lot_id == "LOT-0000"
    assert result.max_value == Amount(Decimal("1500000"), "SEK")
    assert result.reestimated_value == Amount(Decimal("1500000"), "SEK")
    assert result.winner_selection_status == "selec-w"
    assert result.tender_count == 2


def test_1884_is_a_framework_without_reopened_competition(graph_1884):
    assert graph_1884.is_framework() is True
    assert graph_1884.lots["LOT-0000"].framework_type == "fa-wo-rc"


def test_1884_resolves_the_full_elements_not_the_stubs(graph_1884):
    """The id stubs inside LotResult come first in document order; they must lose."""
    assert set(graph_1884.lot_tenders) == {"TEN-0001", "TEN-0002"}
    assert graph_1884.lot_tenders["TEN-0001"].tendering_party_id == "TPA-0001"
    assert graph_1884.lot_tenders["TEN-0002"].tendering_party_id == "TPA-0002"
    assert graph_1884.lot_tenders["TEN-0001"].lot_id == "LOT-0000"

    contract = graph_1884.settled_contracts["CON-0001"]

    assert contract.award_date == "2025-12-05"
    assert contract.title == "IT-Konsulter Comos-AFRY Sweden AB"
    assert contract.lot_tender_ids == ("TEN-0001",)


def test_1884_lot_result_keeps_the_stub_ids_it_points_at(graph_1884):
    result = graph_1884.lot_results[0]

    assert result.settled_contract_ids == ("CON-0001", "CON-0002")
    assert result.lot_tender_ids == ("TEN-0001", "TEN-0002")


def test_1884_names_both_winners_with_their_contracts(graph_1884):
    winners = graph_1884.winners_for_lot("LOT-0000")

    assert [(org.name, contract) for org, contract in winners] == [
        ("AFRY Sweden AB", "CON-0001"),
        ("PlantVision AB", "CON-0002"),
    ]


def test_1884_identifies_the_buyer_and_the_notice(graph_1884):
    assert graph_1884.notice_id == "1884-2026"
    assert graph_1884.notice_type == "can-standard"
    assert graph_1884.title == "IT-Konsulter Comos"
    assert graph_1884.cpv_main == "72246000"
    assert graph_1884.buyer_org_id == "ORG-0001"
    assert graph_1884.buyer.name == "Gryaab AB"
    assert graph_1884.buyer.company_id == "5561372177"


def test_1884_lot_period_and_estimate(graph_1884):
    lot = graph_1884.lots["LOT-0000"]

    assert lot.name == "IT-Konsulter Comos"
    assert lot.estimated_value == Amount(Decimal("3000000"), "SEK")
    assert (lot.period_start, lot.period_end) == ("2026-01-01", "2029-12-31")


# -- 15840-2026: three lots --------------------------------------------------


def test_15840_attaches_each_ceiling_to_the_right_lot(graph_15840):
    """A mis-join produces the right multiset of values, so assert lot by lot."""
    ceilings = {result.lot_id: result.max_value for result in graph_15840.lot_results}

    assert ceilings == {
        "LOT-0001": Amount(Decimal("8000000"), "SEK"),
        "LOT-0002": Amount(Decimal("8000000"), "SEK"),
        "LOT-0003": Amount(Decimal("14000000"), "SEK"),
    }
    assert list(graph_15840.lots) == ["LOT-0001", "LOT-0002", "LOT-0003"]
    assert [result.result_id for result in graph_15840.lot_results] == [
        "RES-0001",
        "RES-0002",
        "RES-0003",
    ]


def test_15840_records_the_disagreement_instead_of_reconciling_it(graph_15840):
    """Overall 8M vs 30M of lot ceilings vs a 24M forecast: all three stay as published."""
    lot_total = sum(
        (result.max_value.value for result in graph_15840.lot_results if result.max_value),
        Decimal(0),
    )

    assert graph_15840.overall_maximum == Amount(Decimal("8000000"), "SEK")
    assert lot_total == Decimal("30000000")
    assert graph_15840.overall_approximate == Amount(Decimal("24000000"), "SEK")


def test_15840_winners_do_not_leak_between_lots(graph_15840):
    assert [(org.name, con) for org, con in graph_15840.winners_for_lot("LOT-0001")] == [
        ("Techstep AB", "CON-0001")
    ]
    assert [(org.name, con) for org, con in graph_15840.winners_for_lot("LOT-0002")] == [
        ("Techstep AB", "CON-0002")
    ]
    assert [(org.name, con) for org, con in graph_15840.winners_for_lot("LOT-0003")] == [
        ("Techstep AB", "CON-0003")
    ]
    assert graph_15840.winners_for_lot("LOT-0009") == ()


def test_15840_keeps_both_orgnr_shapes_raw(graph_15840):
    """CompanyID is stored verbatim; normalizing it is orgnr.py's job."""
    assert graph_15840.organizations["ORG-0001"].company_id == "2321000024"
    assert graph_15840.organizations["ORG-0002"].company_id == "202100-2742"
    assert graph_15840.buyer.name == "Region Uppsala"


# -- 8020-2026: no ceiling published -----------------------------------------


def test_8020_has_no_ceiling_but_a_forecast(graph_8020):
    assert graph_8020.overall_maximum is None
    assert graph_8020.overall_approximate == Amount(Decimal("28000000"), "SEK")
    assert graph_8020.lot_results[0].max_value is None
    assert graph_8020.lot_results[0].reestimated_value == Amount(Decimal("28000000"), "SEK")


def test_8020_is_still_a_framework(graph_8020):
    assert graph_8020.is_framework() is True
    assert graph_8020.lots["LOT-0001"].framework_type == "fa-wo-rc"


def test_8020_lot_period(graph_8020):
    lot = graph_8020.lots["LOT-0001"]

    assert (lot.period_start, lot.period_end) == ("2025-08-26", "2027-08-25")


def test_8020_reads_company_id_without_a_scheme_attribute(graph_8020):
    assert graph_8020.organizations["ORG-0001"].company_id == "202100-2841"
    assert graph_8020.organizations["ORG-0003"].company_id == "559052-2248"


def test_8020_winner_resolves_through_a_contract_without_a_title(graph_8020):
    winners = graph_8020.winners_for_lot("LOT-0001")

    assert [(org.name, con) for org, con in winners] == [("Thingwave AB", "CON-0001")]
    assert graph_8020.settled_contracts["CON-0001"].title is None
    assert graph_8020.settled_contracts["CON-0001"].award_date == "2025-08-14"


# -- across the fixtures -----------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("eforms_1884", {"Gryaab AB", "Förvaltningsrätten", "AFRY Sweden AB", "PlantVision AB"}),
        (
            "eforms_15840",
            {"Region Uppsala", "Förvaltningsrätten i Uppsala", "Techstep AB"},
        ),
        (
            "eforms_8020",
            {"Luleå tekniska universitet", "Förvaltningsrätten i Luleå", "Thingwave AB"},
        ),
    ],
)
def test_every_organization_resolves_to_a_name_and_a_company_id(fixture, expected, request):
    graph = parse_graph(request.getfixturevalue(fixture), "x-2026")

    assert {org.name for org in graph.organizations.values()} == expected
    assert all(org.company_id for org in graph.organizations.values())
    assert all(org.country == "SWE" for org in graph.organizations.values())


@pytest.mark.parametrize("fixture", ["eforms_1884", "eforms_15840", "eforms_8020"])
def test_every_parsed_amount_is_a_decimal(fixture, request):
    graph = parse_graph(request.getfixturevalue(fixture), "x-2026")

    amounts = [
        graph.overall_maximum,
        graph.overall_approximate,
        graph.estimated_overall,
        *(lot.estimated_value for lot in graph.lots.values()),
        *(result.max_value for result in graph.lot_results),
        *(result.reestimated_value for result in graph.lot_results),
    ]

    assert any(a is not None for a in amounts)
    assert all(isinstance(a.value, Decimal) for a in amounts if a is not None)


# -- graph edge cases --------------------------------------------------------


def test_one_contract_across_two_lots_does_not_leak_a_winner():
    graph = parse_graph(CROSS_LOT_XML, "2-2026")

    assert [(org.name, con) for org, con in graph.winners_for_lot("LOT-0001")] == [
        ("Vinnare Ett AB", "CON-0001")
    ]
    assert graph.winners_for_lot("LOT-0002") == ()  # no LotResult claims that lot


def test_rank_is_read_only_when_the_notice_publishes_one():
    graph = parse_graph(CROSS_LOT_XML, "2-2026")

    assert graph.lot_tenders["TEN-0001"].rank == 2
    assert graph.lot_tenders["TEN-0002"].rank is None


def test_notice_without_lots_or_results_is_not_a_framework():
    graph = parse_graph(
        b'<ContractAwardNotice xmlns="urn:ubl">'
        b"<ProcurementProject><Name>Enkel upphandling</Name></ProcurementProject>"
        b"</ContractAwardNotice>",
        "3-2026",
    )

    assert graph.title == "Enkel upphandling"
    assert graph.is_framework() is False
    assert graph.lot_results == ()
    assert graph.buyer is None
    assert graph.overall_maximum is None


def test_malformed_xml_raises_eforms_error():
    with pytest.raises(EformsError, match="Could not parse"):
        parse_graph(b"<ContractAwardNotice>", "4-2026")


# -- fetching ----------------------------------------------------------------


def test_a_cached_notice_is_never_fetched_again(tmp_path, eforms_1884):
    (tmp_path / "1884-2026.xml").write_bytes(eforms_1884)

    with exploding_client() as client:
        content = fetch_notice_xml("1884-2026", cache_dir=tmp_path, client=client)

    assert content == eforms_1884


def test_the_default_cache_dir_comes_from_the_environment(tmp_path, monkeypatch, eforms_1884):
    monkeypatch.setenv("TENDER_SCAN_XML_CACHE", str(tmp_path))
    (tmp_path / "1884-2026.xml").write_bytes(eforms_1884)

    with exploding_client() as client:
        assert fetch_notice_xml("1884-2026", client=client) == eforms_1884


def test_a_fetched_notice_is_written_to_the_cache(tmp_path, eforms_8020):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=eforms_8020)

    cache_dir = tmp_path / "xml_cache"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first_call = fetch_notice_xml("8020-2026", cache_dir=cache_dir, client=client)
    with exploding_client() as client:
        second_call = fetch_notice_xml("8020-2026", cache_dir=cache_dir, client=client)

    assert calls == ["https://ted.europa.eu/en/notice/8020-2026/xml"]
    assert first_call == second_call == eforms_8020
    assert (cache_dir / "8020-2026.xml").read_bytes() == eforms_8020


def test_fetch_raises_on_http_error(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(EformsError, match="404"),
    ):
        fetch_notice_xml("0-2026", cache_dir=tmp_path, client=client)

    assert list(tmp_path.iterdir()) == []


def test_fetch_raises_on_transport_error(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(EformsError, match="Could not fetch"),
    ):
        fetch_notice_xml("0-2026", cache_dir=tmp_path, client=client)


def test_load_graph_prefers_an_explicit_file_over_the_cache(tmp_path, eforms_1884):
    path = tmp_path / "notice.xml"
    path.write_bytes(eforms_1884)

    graph = load_graph("1884-2026", xml_path=path, client=exploding_client())

    assert graph.buyer.name == "Gryaab AB"


def test_load_graph_reports_a_missing_file(tmp_path):
    with pytest.raises(EformsError, match="Could not read"):
        load_graph("1884-2026", xml_path=tmp_path / "nope.xml")


# -- fields added for M1/M2 --------------------------------------------------


def test_issue_date_is_the_notices_own_date_not_the_contracts(eforms_431354: bytes) -> None:
    """431354-2026 carries a SettledContract IssueDate of 2026-06-12 as well."""
    graph = parse_graph(eforms_431354, "431354-2026")
    assert graph.issue_date == "2026-06-22"


def test_issue_date_strips_the_timezone_suffix(eforms_1884: bytes) -> None:
    """The extension carries an earlier 2026-01-01Z; the root IssueDate wins."""
    assert parse_graph(eforms_1884, "1884-2026").issue_date == "2026-01-02"


def test_framework_maximum_is_read_at_both_levels(eforms_431354: bytes) -> None:
    """BT-271 lives inside RequestedTenderTotal's eForms extension, not beside it."""
    graph = parse_graph(eforms_431354, "431354-2026")
    assert graph.framework_maximum is not None
    assert graph.framework_maximum.value == Decimal("8000000")
    assert graph.framework_maximum.currency == "SEK"
    lot = next(iter(graph.lots.values()))
    assert lot.framework_maximum is not None
    assert lot.framework_maximum.value == Decimal("8000000")


def test_the_three_structured_ceilings_disagree_and_all_three_survive(
    eforms_431354: bytes,
) -> None:
    """Recorded, not corrected: 4M overall, 4M per lot, 8M framework maximum."""
    graph = parse_graph(eforms_431354, "431354-2026")
    assert graph.overall_maximum is not None and graph.overall_maximum.value == Decimal("4000000")
    assert graph.lot_results[0].max_value is not None
    assert graph.lot_results[0].max_value.value == Decimal("4000000")
    assert graph.framework_maximum is not None
    assert graph.framework_maximum.value == Decimal("8000000")


def test_framework_maximum_is_none_when_absent(eforms_1884: bytes) -> None:
    graph = parse_graph(eforms_1884, "1884-2026")
    assert graph.framework_maximum is None
    assert all(lot.framework_maximum is None for lot in graph.lots.values())


def test_payable_amount_is_read_faithfully_including_zero(eforms_470310: bytes) -> None:
    """A published 0 means the buyer disclosed no value; the reader records the 0."""
    graph = parse_graph(eforms_470310, "470310-2026")
    values = sorted(
        t.payable_amount.value for t in graph.lot_tenders.values() if t.payable_amount is not None
    )
    assert Decimal("0") in values
    assert Decimal("160000000") in values


def test_rank_code_is_parsed(eforms_470310: bytes) -> None:
    ranks = {t.rank for t in graph_ranks(eforms_470310)}
    assert 1 in ranks


def graph_ranks(xml_bytes: bytes):
    return parse_graph(xml_bytes, "470310-2026").lot_tenders.values()


def test_rank_is_none_when_the_notice_publishes_no_ranking(eforms_1884: bytes) -> None:
    graph = parse_graph(eforms_1884, "1884-2026")
    assert all(t.rank is None for t in graph.lot_tenders.values())


def test_ted_double_encoded_ampersands_are_undone() -> None:
    """TED publishes `Ernst &amp;amp; Young`, so one XML decode leaves `&amp;`."""
    xml = (
        b'<?xml version="1.0" encoding="utf-8"?><ContractAwardNotice '
        b'xmlns="urn:oasis:names:specification:ubl:schema:xsd:ContractAwardNotice-2">'
        b"<UBLExtensions><UBLExtension><ExtensionContent><EformsExtension>"
        b"<NoticeResult><Organization><PartyIdentification><ID>ORG-0001</ID>"
        b"</PartyIdentification><PartyName><Name>Ernst &amp;amp; Young Aktiebolag</Name>"
        b"</PartyName></Organization></NoticeResult>"
        b"</EformsExtension></ExtensionContent></UBLExtension></UBLExtensions>"
        b"</ContractAwardNotice>"
    )
    graph = parse_graph(xml, "1-2026")
    assert graph.organizations["ORG-0001"].name == "Ernst & Young Aktiebolag"
