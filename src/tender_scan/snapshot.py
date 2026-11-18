"""The daily snapshot: what the morning's TED refresh left in the database.

Only public TED figures go in. Ledgers, FOIA requests and prospects stay out,
because the snapshot is committed to a public repository every morning.

Two files under `snapshots/`:

    ted-daglig.md   today's numbers, overwritten each day
    historik.csv    one row per day, so the growth is visible over time
"""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# The first two CPV digits name the division. Only the common ones are spelled
# out; anything else prints as its code.
_CPV_DIVISIONS = {
    "30": "Kontorsmaskiner och datorer",
    "32": "Radio, tv och telekom",
    "33": "Medicinsk utrustning",
    "34": "Transportutrustning",
    "39": "Möbler och inredning",
    "45": "Byggarbeten",
    "48": "Programvara",
    "50": "Reparation och underhåll",
    "55": "Hotell och restaurang",
    "60": "Transporttjänster",
    "64": "Post och telekom",
    "66": "Finans och försäkring",
    "71": "Arkitekt- och ingenjörstjänster",
    "72": "IT-tjänster",
    "73": "Forskning och utveckling",
    "75": "Offentlig förvaltning",
    "79": "Företagstjänster",
    "80": "Utbildning",
    "85": "Hälsovård och socialt arbete",
    "90": "Avlopp, avfall och miljö",
    "98": "Övriga tjänster",
}


@dataclass(frozen=True)
class Snapshot:
    date: str
    refreshed_at: str
    notices_fetched: int
    framework_awards_seen: int
    new_framework_xml: int
    frameworks: int
    frameworks_with_cap: int
    cap_total_sek: int
    award_rows: int
    suppliers_with_orgnr: int
    notices_stored: int


def build(conn: sqlite3.Connection, date: str) -> Snapshot | None:
    """Today's figures, or None when no refresh has finished yet."""
    last = conn.execute(
        "SELECT finished_at, notices, framework_ids, xml_fetched FROM refresh_runs"
        " WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    if last is None:
        return None
    frameworks, with_cap, cap_total = conn.execute(
        "SELECT count(*), count(cap_value_sek), coalesce(sum(cap_value_sek), 0)"
        " FROM framework_agreements WHERE is_framework = 1"
    ).fetchone()
    award_rows, suppliers = conn.execute(
        "SELECT count(*), count(DISTINCT supplier_orgnr) FROM award_winners"
    ).fetchone()
    (notices,) = conn.execute("SELECT count(*) FROM notices").fetchone()
    return Snapshot(
        date=date,
        refreshed_at=str(last[0]),
        notices_fetched=last[1] or 0,
        framework_awards_seen=last[2] or 0,
        new_framework_xml=last[3] or 0,
        frameworks=frameworks,
        frameworks_with_cap=with_cap,
        cap_total_sek=cap_total,
        award_rows=award_rows,
        suppliers_with_orgnr=suppliers,
        notices_stored=notices,
    )


def top_divisions(conn: sqlite3.Connection, limit: int = 8) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT substr(cpv_main, 1, 2) AS d, count(*) FROM framework_agreements"
        " WHERE is_framework = 1 AND cpv_main IS NOT NULL"
        " GROUP BY d ORDER BY count(*) DESC, d LIMIT ?",
        (limit,),
    ).fetchall()
    return [(str(d), n) for d, n in rows]


def _sv(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def render_markdown(snap: Snapshot, divisions: list[tuple[str, int]]) -> str:
    share = 100 * snap.frameworks_with_cap / snap.frameworks if snap.frameworks else 0.0
    lines = [
        f"# TED i Sverige, {snap.date}",
        "",
        "Skrivs automatiskt varje morgon efter `tender-scan refresh`. Bara publik",
        "data från TED (ted.europa.eu): svenska notiser och tilldelade ramavtal.",
        "",
        "## Morgonens hämtning",
        "",
        "| | |",
        "| --- | --- |",
        f"| Klar | {snap.refreshed_at.replace('T', ' ').removesuffix('Z')} UTC |",
        f"| Notiser hämtade | {_sv(snap.notices_fetched)} |",
        f"| Ramavtalstilldelningar i fönstret | {_sv(snap.framework_awards_seen)} |",
        f"| Nya ramavtal (XML) | {_sv(snap.new_framework_xml)} |",
        "",
        "## Totalt i databasen",
        "",
        "| | |",
        "| --- | --- |",
        f"| Ramavtal | {_sv(snap.frameworks)} |",
        f"| Med takvolym | {_sv(snap.frameworks_with_cap)} ({share:.0f} %) |",
        f"| Summa takvolym | {snap.cap_total_sek / 1e9:.1f} mdr kr |".replace(".", ","),
        f"| Tilldelningsrader | {_sv(snap.award_rows)} |",
        f"| Leverantörer med orgnr | {_sv(snap.suppliers_with_orgnr)} |",
        f"| Notiser | {_sv(snap.notices_stored)} |",
        "",
    ]
    if divisions:
        lines += ["## Flest ramavtal per CPV-område", "", "| CPV | Område | Ramavtal |"]
        lines += ["| --- | --- | ---: |"]
        for code, n in divisions:
            lines.append(f"| {code} | {_CPV_DIVISIONS.get(code, '')} | {_sv(n)} |")
        lines.append("")
    lines.append("Historiken dag för dag ligger i `historik.csv`.")
    return "\n".join(lines) + "\n"


def write(conn: sqlite3.Connection, out_dir: Path, date: str) -> Snapshot | None:
    """Write both files. Rerunning on the same date replaces that day's row."""
    snap = build(conn, date)
    if snap is None:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ted-daglig.md").write_text(
        render_markdown(snap, top_divisions(conn)), encoding="utf-8"
    )

    history = out_dir / "historik.csv"
    names = [f.name for f in fields(Snapshot)]
    rows: list[dict[str, str]] = []
    if history.exists():
        with history.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("date") != date]
    rows.append({k: str(v) for k, v in asdict(snap).items()})
    rows.sort(key=lambda r: r["date"])
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    history.write_text(buf.getvalue(), encoding="utf-8")
    return snap
