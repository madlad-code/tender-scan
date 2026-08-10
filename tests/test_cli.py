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
