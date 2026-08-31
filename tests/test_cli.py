from pathlib import Path

import httpx
from typer.testing import CliRunner

from tender_scan import cli
from tender_scan.cli import app
from tender_scan.records import (
    AwardWinner,
    FoiaRequest,
    FrameworkAgreement,
    SupplierPayment,
)
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


# -- report / utilization (M5) -----------------------------------------------


def _measurable_db(tmp_path: Path) -> Path:
    db = tmp_path / "t.sqlite3"
    with Storage(db) as storage:
        storage.upsert_framework(
            FrameworkAgreement(
                notice_id="1-2026",
                buyer_name="Göteborgs Stad",
                buyer_orgnr="212000-1355",
                title="Ramavtal kommunikationstjänster",
                is_framework=True,
                cap_value_sek=5_000_000,
                cap_source="eforms_field",
                cap_confidence=0.95,
                start_date="2025-03-01",
                end_date="2029-02-28",
                max_duration_months=47,
                raw_excerpt="BT-118 = 5 000 000 SEK",
            )
        )
        storage.replace_framework_buyers("1-2026", [("212000-1355", "Göteborgs Stad")])
        storage.replace_winners(
            "1-2026", [AwardWinner("1-2026", "Consid AB", "556599-4307", "LOT-0000", rank=1)]
        )
        storage.insert_payments(
            [
                SupplierPayment(
                    payer_org="Göteborgs Stad",
                    payer_orgnr="212000-1355",
                    supplier_name="Consid AB",
                    supplier_orgnr="556599-4307",
                    amount_sek=1_896_813,
                    period_year=2026,
                    period_month=7,
                    source="open_data",
                    source_url="https://catalog.goteborg.se/store/6/resource/129628",
                )
            ]
        )
    return db


def test_report_writes_markdown_to_a_file(tmp_path: Path) -> None:
    out = tmp_path / "r.md"
    result = CliRunner().invoke(
        app, ["report", "1-2026", "--db", str(_measurable_db(tmp_path)), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert "## Metodbegränsningar" in text
    assert "1 896 813 SEK" in text


def test_report_renders_html(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["report", "1-2026", "--db", str(_measurable_db(tmp_path)), "--format", "html"]
    )
    assert result.exit_code == 0, result.output
    assert "<!doctype html>" in result.output


def test_report_rejects_an_unknown_format(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["report", "1-2026", "--db", str(_measurable_db(tmp_path)), "--format", "pdf"]
    )
    assert result.exit_code != 0


def test_report_says_what_to_run_when_the_notice_is_missing(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["report", "999-2026", "--db", str(tmp_path / "t.sqlite3")])
    assert result.exit_code == 1
    assert "frameworks extract" in result.output


def test_utilization_table_prints_coverage_beside_every_rate(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["utilization", "--measurable", "--db", str(_measurable_db(tmp_path))]
    )
    assert result.exit_code == 0, result.output
    assert "täckning" in result.output
    row = next(line for line in result.output.splitlines() if line.startswith("1-2026"))
    assert "37.9%" in row
    assert "100.0%" in row  # the coverage column, on the same line as the rate


# -- prospects (M6) ----------------------------------------------------------


def test_prospects_writes_a_csv(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    with Storage(db) as storage:
        for notice_id in ("1-2026", "2-2026"):
            storage.upsert_framework(
                FrameworkAgreement(
                    notice_id=notice_id,
                    title=f"Ramavtal {notice_id}",
                    is_framework=True,
                    cpv_main="72000000",
                    cap_value_sek=1_000_000,
                )
            )
            storage.replace_winners(
                notice_id,
                [AwardWinner(notice_id, "Consid AB", "556599-4307", "LOT-0000")],
            )
    out = tmp_path / "prospects.csv"
    result = CliRunner().invoke(
        app, ["prospects", "--cpv", "72*", "--db", str(db), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "Skrev 1 rader" in result.output
    assert "Inga kontaktuppgifter" in result.output
    assert "556599-4307" in out.read_text(encoding="utf-8")


# -- foia (M3) ---------------------------------------------------------------


def _foia_db(tmp_path: Path) -> Path:
    db = tmp_path / "t.sqlite3"
    with Storage(db) as storage:
        storage.insert_foia(
            FoiaRequest(
                id=None,
                target_org="Sundsvalls kommun",
                target_email=None,
                framework_notice_id="1-2026",
                status="draft",
            )
        )
    return db


def test_foia_sent_starts_the_clock_and_due_then_lists_the_reminder(tmp_path: Path) -> None:
    db = _foia_db(tmp_path)
    runner = CliRunner()
    assert (
        runner.invoke(app, ["foia", "sent", "1", "--on", "2026-08-01", "--db", str(db)]).exit_code
        == 0
    )
    before = runner.invoke(app, ["foia", "due", "--today", "2026-08-02", "--db", str(db)])
    after = runner.invoke(app, ["foia", "due", "--today", "2026-08-05", "--db", str(db)])
    assert "Inget att göra" in before.output
    assert "påminnelse" in after.output


def test_foia_did_removes_a_step_from_the_due_list(tmp_path: Path) -> None:
    db = _foia_db(tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["foia", "sent", "1", "--on", "2026-08-01", "--db", str(db)])
    runner.invoke(app, ["foia", "did", "1", "reminder_1", "--on", "2026-08-04", "--db", str(db)])
    # Sent 2026-08-01, so the day-5 phone call comes due on 2026-08-06.
    result = runner.invoke(app, ["foia", "due", "--today", "2026-08-06", "--db", str(db)])
    assert "Ring registratorn" in result.output


def test_foia_did_rejects_an_unknown_step(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["foia", "did", "1", "skickabrev", "--db", str(_foia_db(tmp_path))]
    )
    assert result.exit_code != 0
    assert "step must be one of" in result.output


def test_foia_ingest_links_the_file_and_closes_the_clock(tmp_path: Path) -> None:
    db = _foia_db(tmp_path)
    answer = tmp_path / "svar.csv"
    answer.write_text("leverantor;belopp\n", encoding="utf-8")
    runner = CliRunner()
    runner.invoke(app, ["foia", "sent", "1", "--on", "2026-08-01", "--db", str(db)])
    result = runner.invoke(app, ["foia", "ingest", "1", str(answer), "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "supplier_payments" in result.output
    with Storage(db) as storage:
        row = storage.get_foia(1)
    assert row is not None and row.status == "received"
    assert row.response_file_path == str(answer.resolve())
    due = runner.invoke(app, ["foia", "due", "--today", "2026-09-01", "--db", str(db)])
    assert "Inget att göra" in due.output


def test_foia_ingest_rejects_a_missing_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["foia", "ingest", "1", str(tmp_path / "nope.csv"), "--db", str(_foia_db(tmp_path))]
    )
    assert result.exit_code != 0


def test_foia_commands_reject_an_unknown_id(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite3"
    result = CliRunner().invoke(app, ["foia", "sent", "42", "--db", str(db)])
    assert result.exit_code == 1
    assert "Ingen begäran med id 42" in result.output


def test_foia_new_dry_run_logs_nothing(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    result = CliRunner().invoke(
        app, ["foia", "new", "--org", "Helsingborgs stad", "--db", str(db), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "Inget loggades och ingenting skickades" in result.output
    with Storage(db) as storage:
        assert storage.list_foia() == []


def test_foia_list_prints_every_request(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["foia", "list", "--db", str(_foia_db(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "Sundsvalls kommun" in result.output


LEDGER_CSV = (
    "﻿kommun,epost,batch,status,skickat_datum,paminnelse_datum,"
    "eskalering_datum,svar_datum,anteckning\n"
    "Göteborgs stad,sled@goteborg.se,1,skickad,2026-08-31,,,,\n"
    "Huddinge kommun,sc@huddinge.se,1,levererat_delvis,2026-08-31,,,,bara 2025\n"
)


def test_foia_import_syncs_a_sheet_and_reruns_without_duplicating(tmp_path):
    db = str(tmp_path / "t.db")
    sheet = tmp_path / "batch1.csv"
    sheet.write_text(LEDGER_CSV, encoding="utf-8")

    first = runner.invoke(app, ["foia", "import", str(sheet), "--db", db])
    assert first.exit_code == 0, first.output
    assert "2 tillagda" in first.output

    # Re-running an unchanged sheet must not log the same request twice.
    again = runner.invoke(app, ["foia", "import", str(sheet), "--db", db])
    assert again.exit_code == 0, again.output
    assert "0 tillagda, 0 uppdaterade, 2 oförändrade" in again.output

    with Storage(db) as storage:
        rows = storage.list_foia()
    assert [r.target_org for r in rows] == ["Göteborgs stad", "Huddinge kommun"]
    assert rows[1].status == "partial"


def test_foia_import_updates_a_changed_row_in_place(tmp_path):
    db = str(tmp_path / "t.db")
    sheet = tmp_path / "batch1.csv"
    sheet.write_text(LEDGER_CSV, encoding="utf-8")
    runner.invoke(app, ["foia", "import", str(sheet), "--db", db])

    sheet.write_text(LEDGER_CSV.replace("skickad", "levererat"), encoding="utf-8")
    result = runner.invoke(app, ["foia", "import", str(sheet), "--db", db])

    assert result.exit_code == 0, result.output
    assert "1 uppdaterade" in result.output
    with Storage(db) as storage:
        assert storage.list_foia()[0].status == "received"


def test_foia_import_dry_run_writes_nothing(tmp_path):
    db = str(tmp_path / "t.db")
    sheet = tmp_path / "batch1.csv"
    sheet.write_text(LEDGER_CSV, encoding="utf-8")

    result = runner.invoke(app, ["foia", "import", str(sheet), "--db", db, "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "skulle läggas till" in result.output
    with Storage(db) as storage:
        assert storage.list_foia() == []


def test_foia_import_reports_a_bad_sheet_without_a_traceback(tmp_path):
    db = str(tmp_path / "t.db")
    sheet = tmp_path / "bad.csv"
    sheet.write_text(LEDGER_CSV.replace("2026-08-31", "03-04-26", 1), encoding="utf-8")

    result = runner.invoke(app, ["foia", "import", str(sheet), "--db", db])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
