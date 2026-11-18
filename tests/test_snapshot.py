import csv
from pathlib import Path

from typer.testing import CliRunner

from tender_scan import snapshot
from tender_scan.cli import app
from tender_scan.storage import Storage

runner = CliRunner()


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "t.sqlite3"
    with Storage(db) as storage:
        conn = storage.connection()
        started = storage.start_refresh(3, 3)
        storage.finish_refresh(started, notices=12, framework_ids=4, xml_fetched=2, xml_failed=0)
        for nid, cap, cpv in [
            ("1-2026", 5_000_000, "72000000"),
            ("2-2026", None, "72100000"),
            ("3-2026", 1_000_000_000, "45000000"),
        ]:
            conn.execute(
                "INSERT INTO framework_agreements (notice_id, is_framework, cap_value_sek,"
                " cpv_main, updated_at) VALUES (?, 1, ?, ?, '2026-11-18T00:00:00Z')",
                (nid, cap, cpv),
            )
        conn.execute(
            "INSERT INTO award_winners (notice_id, supplier_name, supplier_orgnr, lot_id,"
            " updated_at) VALUES ('1-2026', 'A AB', '5560000000', 'LOT-1', 'x')"
        )
        conn.commit()
    return db


def test_snapshot_writes_markdown_and_one_history_row_per_day(tmp_path: Path) -> None:
    db = _db(tmp_path)
    out = tmp_path / "snapshots"
    for _ in range(2):  # a rerun the same morning replaces the row, never doubles it
        result = runner.invoke(
            app, ["snapshot", "--out", str(out), "--date", "2026-11-18", "--db", str(db)]
        )
        assert result.exit_code == 0, result.output
    runner.invoke(app, ["snapshot", "--out", str(out), "--date", "2026-11-19", "--db", str(db)])

    md = (out / "ted-daglig.md").read_text(encoding="utf-8")
    assert "| Ramavtal | 3 |" in md
    assert "| Med takvolym | 2 (67 %) |" in md
    assert "| 72 | IT-tjänster | 2 |" in md
    with (out / "historik.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["date"] for r in rows] == ["2026-11-18", "2026-11-19"]
    assert rows[0]["new_framework_xml"] == "2"
    assert rows[0]["suppliers_with_orgnr"] == "1"


def test_snapshot_without_a_finished_refresh_fails(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite3"
    with Storage(db):
        pass
    result = runner.invoke(app, ["snapshot", "--out", str(tmp_path / "s"), "--db", str(db)])
    assert result.exit_code == 1
    assert not (tmp_path / "s").exists()


def test_snapshot_holds_no_ledger_or_prospect_fields() -> None:
    names = {f for f in snapshot.Snapshot.__dataclass_fields__}
    assert not any(w in n for n in names for w in ("payment", "prospect", "foia", "spend"))
