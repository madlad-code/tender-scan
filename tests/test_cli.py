from pathlib import Path

import httpx
from typer.testing import CliRunner

from tender_scan import cli
from tender_scan.cli import app
from tender_scan.records import AwardWinner
from tender_scan.storage import Storage
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


# -- frameworks (M1) ---------------------------------------------------------


def _corpus(tmp_path: Path) -> Path:
    """A small cache directory built from the committed fixtures."""
    cache = tmp_path / "xml"
    cache.mkdir()
    for notice_id in ("1884-2026", "15840-2026", "8020-2026"):
        source = Path(__file__).parent / "fixtures" / f"eforms_{notice_id}.xml"
        (cache / f"{notice_id}.xml").write_bytes(source.read_bytes())
    return cache


def test_frameworks_extract_writes_rows(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    result = CliRunner().invoke(
        app, ["frameworks", "extract", "--cache", str(_corpus(tmp_path)), "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "Wrote 3 framework rows" in result.output
    with Storage(db) as storage:
        rows = {row.notice_id: row for row in storage.list_frameworks()}
    assert rows["1884-2026"].cap_value_sek == 3_000_000
    assert rows["8020-2026"].cap_value_sek is None


def test_frameworks_extract_dry_run_writes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    result = CliRunner().invoke(
        app,
        [
            "frameworks",
            "extract",
            "--cache",
            str(_corpus(tmp_path)),
            "--db",
            str(db),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Nothing was written" in result.output
    with Storage(db) as storage:
        assert storage.list_frameworks() == []


def test_frameworks_extract_skips_an_unreadable_file(tmp_path: Path) -> None:
    cache = _corpus(tmp_path)
    (cache / "broken-2026.xml").write_bytes(b"<not-xml")
    db = tmp_path / "t.sqlite3"
    result = CliRunner().invoke(
        app, ["frameworks", "extract", "--cache", str(cache), "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "Wrote 3 framework rows (1 skipped)" in result.output


def test_frameworks_review_lists_the_queue(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    runner = CliRunner()
    runner.invoke(
        app, ["frameworks", "extract", "--cache", str(_corpus(tmp_path)), "--db", str(db)]
    )
    result = runner.invoke(app, ["frameworks", "review", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "8020-2026" in result.output
    assert "1884-2026" not in result.output


def test_frameworks_validate_prints_the_denominator(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["frameworks", "validate", "--cache", str(_corpus(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "2 av 3" in result.output


# -- winners (M2) ------------------------------------------------------------


def test_winners_extract_writes_rows(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    result = CliRunner().invoke(
        app, ["winners", "extract", "--cache", str(_corpus(tmp_path)), "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    with Storage(db) as storage:
        rows = storage.list_winners()
    assert {row.notice_id for row in rows} == {"1884-2026", "15840-2026", "8020-2026"}
    assert "Leverantörsrader:         6" in result.output


def test_winners_extract_dry_run_writes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    result = CliRunner().invoke(
        app,
        ["winners", "extract", "--cache", str(_corpus(tmp_path)), "--db", str(db), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "Nothing was written." in result.output
    with Storage(db) as storage:
        assert storage.list_winners() == []


def test_winners_list_filters_by_orgnr(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    runner = CliRunner()
    runner.invoke(app, ["winners", "extract", "--cache", str(_corpus(tmp_path)), "--db", str(db)])
    result = runner.invoke(app, ["winners", "list", "--orgnr", "5562248012", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "AFRY Sweden AB" in result.output
    assert "PlantVision AB" not in result.output


def test_winners_list_rejects_an_invalid_orgnr(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["winners", "list", "--orgnr", "1234567890", "--db", str(tmp_path / "t.sqlite3")]
    )
    assert result.exit_code != 0
    assert "not a valid organisationsnummer" in result.output


# -- payments (M4) -----------------------------------------------------------


PAYMENT_FIXTURES = Path(__file__).parent / "fixtures" / "payments"


def _with_winner(db: Path, name: str, orgnr: str | None) -> None:
    with Storage(db) as storage:
        storage.replace_winners("1-2026", [AwardWinner("1-2026", name, orgnr, "LOT-0000")])


def test_payments_sources_names_the_two_missing_publishers() -> None:
    result = CliRunner().invoke(app, ["payments", "sources"])
    assert result.exit_code == 0, result.output
    assert "232100-0131" in result.output
    assert "Sundsvalls kommun" in result.output
    assert "Helsingborgs stad" in result.output


def test_payments_load_from_a_local_file(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    _with_winner(db, "Sensative AB", "556922-4644")
    result = CliRunner().invoke(
        app,
        [
            "payments",
            "load",
            "vgr",
            "--file",
            str(PAYMENT_FIXTURES / "vgr_sample.csv"),
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Kept 1 aggregated rows, inserted 1 new ones." in result.output


def test_payments_load_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    _with_winner(db, "Sensative AB", "556922-4644")
    args = [
        "payments",
        "load",
        "vgr",
        "--file",
        str(PAYMENT_FIXTURES / "vgr_sample.csv"),
        "--db",
        str(db),
    ]
    runner = CliRunner()
    runner.invoke(app, args)
    result = runner.invoke(app, args)
    assert "inserted 0 new ones" in result.output


def test_payments_load_dry_run_writes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    _with_winner(db, "Sensative AB", "556922-4644")
    result = CliRunner().invoke(
        app,
        [
            "payments",
            "load",
            "vgr",
            "--file",
            str(PAYMENT_FIXTURES / "vgr_sample.csv"),
            "--db",
            str(db),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Nothing was written." in result.output
    with Storage(db) as storage:
        stored = storage.connection().execute("SELECT COUNT(*) FROM supplier_payments").fetchone()
    assert stored[0] == 0


def test_payments_load_warns_when_there_are_no_winners_to_match(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "payments",
            "load",
            "vgr",
            "--file",
            str(PAYMENT_FIXTURES / "vgr_sample.csv"),
            "--db",
            str(tmp_path / "t.sqlite3"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "award_winners är tom" in result.output


def test_payments_load_rejects_an_unknown_source(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["payments", "load", "malmo", "--db", str(tmp_path / "t.sqlite3")]
    )
    assert result.exit_code != 0
    assert "unknown source" in result.output
