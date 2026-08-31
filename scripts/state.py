#!/usr/bin/env python3
"""Regenerate STATE.md — one page describing where this project actually is.

## Why this exists

The project is worked on from more than one place: a terminal agent that can
read the code but knows nothing about what was decided in a browser, and a
browser assistant that knows the plan but cannot see the repository. Each one
reconstructs the other's half by asking questions, badly and expensively.

STATE.md is the shared answer. It is committed, so anything that can read the
repository can read it, and it is regenerated at the start of every session, so
it is never the stale summary someone forgot to update.

## What is generated and what is not

Everything a machine can observe is generated: the branch and whether it is
pushed, the recent commits, which containers are running and how old their
image is, how many rows are in each table, which records requests are open.

Everything a machine cannot observe — where you are in the plan, what you are
waiting for, what you decided and why — lives between the MANUAL markers and is
copied through untouched. Regenerating never destroys it. That section is the
point of the file; the generated parts are there so it does not have to repeat
what `git log` already knows.

Standard library only, so it runs under the system interpreter without the
project's virtualenv — a session hook cannot assume one is active.

Usage:
    python3 scripts/state.py           # rewrite STATE.md, print nothing
    python3 scripts/state.py --print   # rewrite, then print it (for hooks)
    python3 scripts/state.py --check   # print without writing
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "STATE.md"
DEFAULT_DB = ROOT / "data" / "tender_scan.db"

MANUAL_START = "<!-- MANUELLT:START -->"
MANUAL_END = "<!-- MANUELLT:SLUT -->"

# Kept when STATE.md does not exist yet, so the first run explains itself.
MANUAL_SEED = """\
### Var jag är

_Skriv fritt här. Den här delen skrivs aldrig över av generatorn._

- Läge: (t.ex. "M0-M6 klara, en enda mätbar utnyttjandegrad, jagar fler öppna reskontror")
- Blockerat av: (t.ex. "väntar på svar från Sundsvall")
- Nästa beslut: (t.ex. "bygga fler laddare eller skicka fler begäranden först")

### Skickade mejl och kontakter

_Utlämnandebegäranden spåras i databasen och listas nedan automatiskt.
Allt annat — säljmejl, samtal, möten — skrivs här._

| Datum | Vem | Vad | Status |
| --- | --- | --- | --- |
"""

COMMIT_COUNT = 8
DOCKER_TIMEOUT = 8


def run(*args: str, timeout: int = 10) -> str:
    """A command's stdout, or "" if it fails for any reason.

    Nothing here is important enough to break a session over: a missing docker
    daemon or a detached HEAD should degrade one section, not the file.
    """
    try:
        done = subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


# -- generated sections ------------------------------------------------------


def git_section() -> str:
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD") or "okänd"
    upstream = run("git", "rev-parse", "--abbrev-ref", "@{u}")
    dirty = run("git", "status", "--porcelain")
    changed = len([line for line in dirty.splitlines() if line.strip()])

    lines = [f"- Gren: `{branch}`"]
    if upstream:
        counts = run("git", "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        behind, _, ahead = counts.partition("\t")
        ahead = ahead.strip() or "0"
        behind = behind.strip() or "0"
        if ahead != "0":
            word = "commit opushad" if ahead == "1" else "commits opushade"
            lines.append(f"- **{ahead} {word}** till `{upstream}`")
        else:
            lines.append(f"- Synkad med `{upstream}`")
        if behind != "0":
            lines.append(f"- {behind} att hämta från `{upstream}`")
    else:
        lines.append("- Ingen uppström satt — inget är pushat någonstans")

    if changed:
        noun = "ändrad fil" if changed == 1 else "ändrade filer"
        lines.append(f"- Arbetsträd: {changed} {noun}")
    else:
        lines.append("- Arbetsträd: rent")

    log = run("git", "log", f"-{COMMIT_COUNT}", "--format=%h %ad %s", "--date=short")
    if log:
        lines.append("")
        lines.append("| Commit | Datum | Vad |")
        lines.append("| --- | --- | --- |")
        for line in log.splitlines():
            sha, _, rest = line.partition(" ")
            when, _, subject = rest.partition(" ")
            lines.append(f"| `{sha}` | {when} | {escape_cell(subject)} |")
    return "\n".join(lines)


def docker_section() -> str:
    ps = run(
        "docker",
        "ps",
        "--filter",
        "name=tender-scan",
        "--format",
        "{{.Names}}\t{{.Status}}\t{{.Image}}",
        timeout=DOCKER_TIMEOUT,
    )
    if not ps:
        return "- Inga tender-scan-containrar igång (eller ingen docker-daemon nåbar)."

    built = run(
        "docker",
        "image",
        "inspect",
        "tender-scan-app",
        "--format",
        "{{.Created}}",
        timeout=DOCKER_TIMEOUT,
    )
    lines = ["| Container | Status | Image |", "| --- | --- | --- |"]
    for line in ps.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            lines.append(f"| `{parts[0]}` | {escape_cell(parts[1])} | `{parts[2]}` |")
    if built:
        lines.append("")
        lines.append(f"- Image `tender-scan-app` byggd: {built[:19].replace('T', ' ')} UTC")
        lines.append(
            "- Byggs **inte** om av sig själv. Efter en kodändring: `docker compose up -d --build`."
        )
    lines.append(
        "- Nås bara över tailnet: **http://tender-scan:8000**. "
        "`localhost:8000` är avsiktligt stängt (`network_mode: service:tailscale`)."
    )
    return "\n".join(lines)


TABLES = (
    ("notices", "notiser från TED"),
    ("framework_agreements", "ramavtal med takvolym"),
    ("award_winners", "tilldelade leverantörer"),
    ("framework_buyers", "avropsberättigade köpare"),
    ("supplier_payments", "fakturarader från öppna reskontror"),
    ("foia_requests", "utlämnandebegäranden"),
)


def db_path() -> Path:
    return Path(os.environ.get("TENDER_SCAN_DB") or DEFAULT_DB)


def data_section() -> str:
    path = db_path()
    if not path.exists():
        return f"- Ingen databas på `{path.relative_to(ROOT)}`. Kör `tender-scan scan` först."

    # Read-only, so a running server is never disturbed by generating this file.
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as err:
        return f"- Databasen gick inte att läsa: {err}"

    lines = ["| Tabell | Rader | Vad |", "| --- | --- | --- |"]
    with conn:
        present = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        for table, what in TABLES:
            if table not in present:
                lines.append(f"| `{table}` | – | {what} (tabellen finns inte) |")
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            flag = " ⚠️ tom" if count == 0 else ""
            lines.append(f"| `{table}` | {count}{flag} | {what} |")
    conn.close()
    return "\n".join(lines)


def foia_section() -> str:
    path = db_path()
    if not path.exists():
        return "- Ingen databas ännu."
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = list(
            conn.execute(
                "SELECT id, target_org, framework_notice_id, sent_at, status "
                "FROM foia_requests ORDER BY COALESCE(sent_at, '') DESC, id DESC"
            )
        )
        conn.close()
    except sqlite3.Error:
        return "- Tabellen `foia_requests` gick inte att läsa."

    if not rows:
        return (
            "- Inga begäranden registrerade. Tabellen finns och har fälten för "
            "hela klockan (`sent_at`, `reminder_1_at`, `reminder_2_at`, "
            "`decision_requested_at`) — den används bara inte ännu.\n"
            '- Registrera ett: `tender-scan foia new --framework <notis> --org "<myndighet>"`, '
            "och `tender-scan foia sent <id>` när du faktiskt skickat det."
        )

    lines = ["| # | Myndighet | Ramavtal | Skickat | Status |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        lines.append(
            f"| {row['id']} | {escape_cell(row['target_org'])} | "
            f"`{row['framework_notice_id'] or '–'}` | {row['sent_at'] or '–'} | "
            f"{row['status'] or '–'} |"
        )
    lines.append("")
    lines.append("- Deadlines räknas av `tender-scan foia due` — den här filen upprepar dem inte.")
    return "\n".join(lines)


def escape_cell(text: str | None) -> str:
    return (text or "–").replace("|", "\\|")


# -- assembly ----------------------------------------------------------------

TEMPLATE = """\
# Läge — tender-scan

<!-- Genererad av scripts/state.py vid varje sessionsstart.
     Redigera inte de genererade avsnitten för hand; de skrivs över.
     Allt mellan MANUELLT:START och MANUELLT:SLUT behålls som det är. -->

_Genererad {generated} UTC._

## Planen och kontakterna

{manual}

## Kod

{git}

## Vad som kör

{docker}

## Vad databasen innehåller

{data}

## Utlämnandebegäranden

{foia}

## Var siffrorna kommer ifrån

Utnyttjandegraden bygger på fakturarader som köparen publicerat som öppna data.
En grad utan sina två täckningstal — andel köpare och andel förflutna månader —
är en undre gräns, inte en mätning. Webbvyn och rapporten visar alltid båda.
Detaljerna står i README under *Utnyttjandegrad*.
"""


def read_manual() -> str:
    """The hand-written block from the existing file, or the seed."""
    if not STATE.exists():
        return MANUAL_SEED.strip()
    text = STATE.read_text(encoding="utf-8")
    found = re.search(
        re.escape(MANUAL_START) + r"\n(.*?)\n?" + re.escape(MANUAL_END),
        text,
        re.DOTALL,
    )
    return found.group(1).strip() if found else MANUAL_SEED.strip()


def build() -> str:
    manual = f"{MANUAL_START}\n{read_manual()}\n{MANUAL_END}"
    return TEMPLATE.format(
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        manual=manual,
        git=git_section(),
        docker=docker_section(),
        data=data_section(),
        foia=foia_section(),
    )


_GENERATED_LINE = re.compile(r"^_Genererad .*$", re.MULTILINE)


def _current() -> str:
    return STATE.read_text(encoding="utf-8") if STATE.exists() else ""


def _substance(text: str) -> str:
    """The file without its own timestamp.

    The hook runs at every session start, so writing unconditionally would
    restamp the file each time and leave the working tree permanently dirty
    with a diff that says nothing. Comparing on substance means the file is
    rewritten only when something about the project actually changed.
    """
    return _GENERATED_LINE.sub("", text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--print", dest="show", action="store_true", help="print after writing")
    parser.add_argument("--check", action="store_true", help="print without writing")
    args = parser.parse_args(argv)

    text = build()
    if not args.check and _substance(text) != _substance(_current()):
        STATE.write_text(text, encoding="utf-8")
    if args.show or args.check:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
