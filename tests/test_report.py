import httpx
import pytest

from tender_scan.report import (
    Amount,
    CallOff,
    ReportError,
    fetch_eforms_xml,
    load_framework_data,
    parse_calloff_args,
    parse_eforms_xml,
    read_calloff_csv,
    render_html,
    render_markdown,
)

NOTICE_ID = "214151-2026"

MINIMAL_XML = b"""<?xml version="1.0"?>
<ContractAwardNotice xmlns="urn:oasis:names:specification:ubl:schema:xsd:ContractAwardNotice-2">
  <ProcurementProject><Name>Enkel upphandling</Name></ProcurementProject>
</ContractAwardNotice>
"""


@pytest.fixture
def data(eforms_xml):
    return parse_eforms_xml(eforms_xml, NOTICE_ID)


# -- parsing -----------------------------------------------------------------


def test_extracts_framework_amounts(data):
    """The three headline amounts from docs/validering-vecka1.md."""
    assert data.max_value == Amount(64_000_000.0, "SEK")
    assert data.approx_value == Amount(32_000_000.0, "SEK")
    assert data.estimated_value == Amount(50_000_000.0, "SEK")


def test_extracts_buyer_title_and_cpv(data):
    assert data.buyer == "Försvarsmakten"
    assert data.title == "Standardbatterier"
    assert data.cpv == "31440000"


def test_extracts_winner_and_tender_count(data):
    assert data.winners == ("Lyreco Sverige AB",)
    assert data.tender_count == 6


def test_extracts_award_date_without_zone_suffix(data):
    # cbc:AwardDate is "2026-03-13+01:00" in the XML.
    assert data.award_date == "2026-03-13"


def test_period_is_none_when_notice_omits_it(data):
    assert data.period_start is None
    assert data.period_end is None


def test_url_points_at_the_public_notice(data):
    assert data.notice_id == NOTICE_ID
    assert data.url.endswith(NOTICE_ID)


def test_notice_without_framework_amounts_yields_none():
    data = parse_eforms_xml(MINIMAL_XML, "1-2026")

    assert data.title == "Enkel upphandling"
    assert data.max_value is None
    assert data.approx_value is None
    assert data.estimated_value is None
    assert data.winners == ()


def test_malformed_xml_raises_report_error():
    with pytest.raises(ReportError, match="Could not parse"):
        parse_eforms_xml(b"<notice>", "1-2026")


# -- call-off input ----------------------------------------------------------


def test_parse_calloff_args_with_labels():
    assert parse_calloff_args(["2025=12000000", "2026=6 000 000"]) == [
        CallOff("2025", 12_000_000.0),
        CallOff("2026", 6_000_000.0),
    ]


def test_parse_calloff_args_without_labels_gets_numbered():
    assert parse_calloff_args(["1000", "2000"]) == [
        CallOff("Avrop 1", 1000.0),
        CallOff("Avrop 2", 2000.0),
    ]


def test_parse_calloff_args_rejects_garbage():
    with pytest.raises(ReportError, match="Could not read call-off"):
        parse_calloff_args(["2025=mycket"])


def test_read_calloff_csv_skips_header(tmp_path):
    path = tmp_path / "avrop.csv"
    path.write_text("etikett,belopp\n2025,12000000\n2026,6000000\n", encoding="utf-8")

    assert read_calloff_csv(path) == [
        CallOff("2025", 12_000_000.0),
        CallOff("2026", 6_000_000.0),
    ]


def test_read_calloff_csv_accepts_semicolons_and_bom(tmp_path):
    path = tmp_path / "avrop.csv"
    path.write_text("﻿2025;12000000\n", encoding="utf-8")

    assert read_calloff_csv(path) == [CallOff("2025", 12_000_000.0)]


def test_read_calloff_csv_handles_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    assert read_calloff_csv(path) == []


# -- markdown rendering ------------------------------------------------------


def test_markdown_reports_the_published_facts(data):
    out = render_markdown(data)

    assert "# Ramavtalsrapport: Standardbatterier" in out
    assert "| Takvolym (max) | 64 000 000 SEK |" in out
    assert "| Myndighetens prognos | 32 000 000 SEK |" in out
    assert "Lyreco Sverige AB" in out
    assert NOTICE_ID in out


def test_markdown_states_forecast_share_of_ceiling(data):
    # The core insight of the week-1 validation: 32 of 64 MSEK = 50 %.
    assert "prognos är **50 %** av takvolymen" in render_markdown(data)


def test_markdown_flags_missing_fields_instead_of_inventing_them(data):
    out = render_markdown(data)

    assert "| Avtalsperiod | *saknas i annonsen* |" in out


def test_markdown_without_calloffs_explains_how_to_get_them(data):
    out = render_markdown(data)

    assert "Ingen avropsdata angiven" in out
    assert "offentlighetsprincipen" in out


def test_markdown_with_calloffs_compares_against_ceiling(data):
    out = render_markdown(data, parse_calloff_args(["2025=12000000", "2026=6000000"]))

    assert "Avropat hittills: **18 000 000 SEK**" in out
    assert "**28 %** av takvolymen" in out  # 18 of 64 MSEK
    assert "kvar under taket: 46 000 000 SEK" in out
    assert "**56 %** av myndighetens egen prognos" in out  # 18 of 32 MSEK
    assert "| **Summa** | **18 000 000** |" in out


def test_markdown_says_so_when_notice_has_no_framework_amounts():
    out = render_markdown(parse_eforms_xml(MINIMAL_XML, "1-2026"))

    assert "inga ramavtalsbelopp" in out


def test_calloffs_without_ceiling_still_report_a_total():
    data = parse_eforms_xml(MINIMAL_XML, "1-2026")

    out = render_markdown(data, [CallOff("2025", 5000.0)])

    assert "Avropat hittills: **5 000**" in out


# -- html rendering ----------------------------------------------------------


def test_html_renders_a_standalone_page(data):
    out = render_html(data, parse_calloff_args(["2025=12000000"]))

    assert out.startswith("<!doctype html>")
    assert "<title>Ramavtalsrapport 214151-2026</title>" in out
    assert "<td>64 000 000 SEK</td>" in out
    assert "<th>Summa</th><th>12 000 000</th>" in out


def test_html_drops_markdown_emphasis_markers(data):
    out = render_html(data)

    assert "**" not in out
    assert "50 % av takvolymen" in out


def test_html_escapes_notice_text():
    # Parsed title becomes the literal text: Batterier & kablar <script>
    xml = MINIMAL_XML.replace(b"Enkel upphandling", b"Batterier &amp; kablar &lt;script&gt;")

    out = render_html(parse_eforms_xml(xml, "1-2026"))

    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# -- fetching ----------------------------------------------------------------


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_requests_the_notice_xml(eforms_xml):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=eforms_xml)

    with make_client(handler) as client:
        content = fetch_eforms_xml(NOTICE_ID, client=client)

    assert content == eforms_xml
    assert seen["url"] == f"https://ted.europa.eu/en/notice/{NOTICE_ID}/xml"


def test_fetch_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with make_client(handler) as client, pytest.raises(ReportError, match="404"):
        fetch_eforms_xml("0-2026", client=client)


def test_fetch_raises_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with make_client(handler) as client, pytest.raises(ReportError, match="Could not fetch"):
        fetch_eforms_xml(NOTICE_ID, client=client)


def test_load_prefers_a_local_xml_file_over_the_network(eforms_path):
    data = load_framework_data(NOTICE_ID, xml_path=eforms_path)

    assert data.buyer == "Försvarsmakten"


def test_load_reports_a_missing_local_file(tmp_path):
    with pytest.raises(ReportError, match="Could not read"):
        load_framework_data(NOTICE_ID, xml_path=tmp_path / "nope.xml")
