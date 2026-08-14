import httpx
from typer.testing import CliRunner

from tender_scan import cli
from tender_scan.cli import app
from tender_scan.ted_client import TedClient

runner = CliRunner()


def make_offline_client(search_response) -> TedClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=dict(search_response, totalNoticeCount=5))

    return TedClient(
        base_url="https://api.ted.example",
        min_request_interval=0,
        transport=httpx.MockTransport(handler),
    )


def test_scan_stores_notices(tmp_path, search_response, monkeypatch):
    monkeypatch.setattr(cli, "TedClient", lambda: make_offline_client(search_response))
    db = str(tmp_path / "test.db")

    result = runner.invoke(app, ["scan", "--cpv", "72*", "--days", "30", "--db", db])

    assert result.exit_code == 0
    assert "Stored 5 notices" in result.output


def test_list_shows_table(tmp_path, search_response, monkeypatch):
    monkeypatch.setattr(cli, "TedClient", lambda: make_offline_client(search_response))
    db = str(tmp_path / "test.db")
    runner.invoke(app, ["scan", "--cpv", "72*", "--db", db])

    result = runner.invoke(app, ["list", "--db", db])

    assert result.exit_code == 0
    assert "ID" in result.output
    assert "450106-2026" in result.output
    assert "18000000 SEK" in result.output
    assert "5 notices." in result.output


def test_list_empty_db(tmp_path):
    result = runner.invoke(app, ["list", "--db", str(tmp_path / "empty.db")])

    assert result.exit_code == 0
    assert "No notices stored" in result.output


def test_rapport_from_local_xml(eforms_path):
    result = runner.invoke(app, ["rapport", "214151-2026", "--xml", str(eforms_path)])

    assert result.exit_code == 0
    assert "Ramavtalsrapport: Standardbatterier" in result.output
    assert "64 000 000 SEK" in result.output
    assert "Ingen avropsdata angiven" in result.output


def test_rapport_with_inline_calloffs(eforms_path):
    result = runner.invoke(
        app,
        [
            "rapport",
            "214151-2026",
            "--xml",
            str(eforms_path),
            "--avrop",
            "2025=12000000",
            "--avrop",
            "2026=6000000",
        ],
    )

    assert result.exit_code == 0
    assert "Avropat hittills: **18 000 000 SEK**" in result.output
    assert "**28 %** av takvolymen" in result.output


def test_rapport_with_calloff_csv(tmp_path, eforms_path):
    csv_path = tmp_path / "avrop.csv"
    csv_path.write_text("etikett,belopp\n2025,12000000\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["rapport", "214151-2026", "--xml", str(eforms_path), "--avrop-fil", str(csv_path)],
    )

    assert result.exit_code == 0
    assert "| 2025 | 12 000 000 |" in result.output


def test_rapport_writes_html_to_file(tmp_path, eforms_path):
    out_path = tmp_path / "rapport.html"

    result = runner.invoke(
        app,
        [
            "rapport",
            "214151-2026",
            "--xml",
            str(eforms_path),
            "--format",
            "html",
            "--ut",
            str(out_path),
        ],
    )

    assert result.exit_code == 0
    assert str(out_path) in result.output
    assert out_path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_rapport_rejects_unknown_format(eforms_path):
    result = runner.invoke(
        app, ["rapport", "214151-2026", "--xml", str(eforms_path), "--format", "pdf"]
    )

    assert result.exit_code == 2
    assert "Unknown format" in result.output


def test_rapport_reports_missing_xml_file(tmp_path):
    result = runner.invoke(app, ["rapport", "1-2026", "--xml", str(tmp_path / "nope.xml")])

    assert result.exit_code != 0
