"""Command-line interface for tender-scan."""

from __future__ import annotations

from pathlib import Path

import typer

from tender_scan import prospects, utilization
from tender_scan import report as report_module
from tender_scan.eforms import DEFAULT_CACHE_DIR, EformsError, notice_text, parse_graph
from tender_scan.frameworks import extract_framework, named_buyers, needs_review, validate
from tender_scan.fx import FxRates
from tender_scan.models import Notice, format_estimated_value, parse_notice
from tender_scan.orgnr import normalize_orgnr
from tender_scan.payments import LOADERS, SourceFile, http_fetch, to_payments
from tender_scan.payments.base import WinnerIndex
from tender_scan.records import AwardWinner, FrameworkAgreement
from tender_scan.storage import Storage
from tender_scan.ted_client import TedClient
from tender_scan.winners import extract_winners, summarize

app = typer.Typer(help="Monitor Swedish public procurement notices from TED.", no_args_is_help=True)


@app.command()
def scan(
    cpv: str = typer.Option(..., help="CPV code or wildcard prefix, e.g. 72000000 or 72*"),
    days: int = typer.Option(30, help="Look back this many days of publications"),
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
) -> None:
    """Fetch notices from TED (country=SE) and store them locally."""
    stored = 0
    with TedClient() as client, Storage(db) as storage:
        for raw in client.search_notices(cpv=cpv, days=days):
            storage.upsert(parse_notice(raw))
            stored += 1
    typer.echo(f"Stored {stored} notices (CPV {cpv}, last {days} days).")


def _truncate(value: str | None, width: int) -> str:
    text = value or "-"
    return text[: width - 1] + "…" if len(text) > width else text


def _format_deadline(deadline: str | None) -> str | None:
    # "2026-08-26T22:00:00Z" -> "2026-08-26 22:00" (UTC)
    return deadline.replace("T", " ")[:16] if deadline else None


def _format_row(notice: Notice) -> str:
    return "  ".join(
        [
            notice.id.ljust(12),
            _truncate(_format_deadline(notice.deadline), 16).ljust(16),
            _truncate(format_estimated_value(notice.estimated_value, notice.currency), 14).ljust(
                14
            ),
            _truncate(notice.buyer, 30).ljust(30),
            _truncate(notice.title, 50),
        ]
    )


@app.command(name="list")
def list_notices(
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
) -> None:
    """Print stored notices as a table, soonest deadline first."""
    with Storage(db) as storage:
        notices = storage.list_notices()

    if not notices:
        typer.echo("No notices stored. Run `tender-scan scan --cpv <code>` first.")
        raise typer.Exit()

    header = "  ".join(
        ["ID".ljust(12), "DEADLINE".ljust(16), "EST. VALUE".ljust(14), "BUYER".ljust(30), "TITLE"]
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    for notice in notices:
        typer.echo(_format_row(notice))
    typer.echo(f"\n{len(notices)} notices.")


@app.command(name="rapport")
def rapport(
    notice_id: str = typer.Argument(
        ..., help="TED publication number, e.g. 214151-2026", metavar="ID"
    ),
    avrop: list[str] = typer.Option(
        [], "--avrop", help="Call-off as 'label=amount' or 'amount' (repeatable)"
    ),
    avrop_fil: Path | None = typer.Option(
        None, "--avrop-fil", help="CSV file with call-offs: label,amount"
    ),
    xml: Path | None = typer.Option(
        None, "--xml", help="Read a local eForms XML file instead of fetching from TED"
    ),
    format_: str = typer.Option("md", "--format", help="Output format: md or html"),
    out: Path | None = typer.Option(None, "--ut", help="Write the report here instead of stdout"),
) -> None:
    """Build a framework agreement report (ceiling vs forecast vs call-offs) for one notice."""
    if format_ not in ("md", "html"):
        typer.echo(f"Unknown format {format_!r}; use 'md' or 'html'.", err=True)
        raise typer.Exit(code=2)

    try:
        data = report_module.load_framework_data(notice_id, xml_path=xml)
        calloffs = report_module.parse_calloff_args(list(avrop))
        if avrop_fil is not None:
            calloffs += report_module.read_calloff_csv(avrop_fil)
    except report_module.ReportError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"Could not read {avrop_fil}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    render = report_module.render_html if format_ == "html" else report_module.render_markdown
    text = render(data, calloffs)

    if out is not None:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Report written to {out}")
    else:
        typer.echo(text)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address"),
    port: int = typer.Option(8000, help="Port"),
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
) -> None:
    """Serve stored notices as a web page (read-only, for private networks)."""
    from tender_scan.web import serve as make_server

    server = make_server(host, port, db)
    typer.echo(f"Serving on http://{host}:{port} (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    app()


# -- frameworks (M1: takvolymsextraktion) ------------------------------------

frameworks_app = typer.Typer(
    help="Extract framework ceilings (takvolym) from notice XML.", no_args_is_help=True
)
app.add_typer(frameworks_app, name="frameworks")


def _xml_files(cache: Path) -> list[Path]:
    if not cache.is_dir():
        raise typer.BadParameter(f"{cache} is not a directory")
    return sorted(cache.glob("*.xml"))


def _extract_from_cache(
    paths: list[Path], fx: FxRates | None
) -> tuple[
    list[FrameworkAgreement], dict[str, list[tuple[str, str | None]]], list[tuple[str, str]]
]:
    """Read each cached XML into a row. Never fetches; a bad file is skipped, not fatal."""
    rows: list[FrameworkAgreement] = []
    buyers: dict[str, list[tuple[str, str | None]]] = {}
    skipped: list[tuple[str, str]] = []
    for path in paths:
        notice_id = path.stem
        try:
            xml_bytes = path.read_bytes()
            graph = parse_graph(xml_bytes, notice_id)
        except (OSError, EformsError) as exc:
            skipped.append((notice_id, str(exc)))
            continue
        rows.append(extract_framework(graph, fx=fx, text=notice_text(xml_bytes)))
        buyers[notice_id] = named_buyers(graph)
    return rows, buyers, skipped


@frameworks_app.command("extract")
def frameworks_extract(
    cache: Path = typer.Option(
        Path(DEFAULT_CACHE_DIR), help="Directory of cached notice XML to read"
    ),
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
    limit: int | None = typer.Option(None, help="Stop after this many notices"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be written"),
) -> None:
    """Read cached notice XML into the framework_agreements table."""
    paths = _xml_files(cache)
    if limit is not None:
        paths = paths[:limit]

    if dry_run:
        # No database, so no FX cache either: an unconvertible amount is reported
        # as such rather than silently converted with an invented rate.
        rows, _, skipped = _extract_from_cache(paths, None)
        for row in rows:
            cap = f"{row.cap_value_sek:,}".replace(",", " ") if row.cap_value_sek else "-"
            typer.echo(f"{row.notice_id:14} {cap:>16}  {_truncate(row.title, 60)}")
        typer.echo(f"Would write {len(rows)} rows ({len(skipped)} skipped). Nothing was written.")
        return

    with Storage(db) as storage:
        rows, buyers, skipped = _extract_from_cache(paths, FxRates(storage.connection()))
        for row in rows:
            storage.upsert_framework(row)
            storage.replace_framework_buyers(row.notice_id, buyers[row.notice_id])
    for notice_id, reason in skipped:
        typer.echo(f"skipped {notice_id}: {reason}", err=True)
    typer.echo(f"Wrote {len(rows)} framework rows ({len(skipped)} skipped).")


@frameworks_app.command("review")
def frameworks_review(
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
) -> None:
    """Print the manual review queue: no ceiling, or one found on weak evidence."""
    with Storage(db) as storage:
        rows = [row for row in storage.list_frameworks() if needs_review(row)]
    if not rows:
        typer.echo("Granskningskön är tom.")
        return
    for row in rows:
        cap = f"{row.cap_value_sek:,}".replace(",", " ") if row.cap_value_sek else "inget tak"
        confidence = f"{row.cap_confidence:.2f}" if row.cap_confidence is not None else "-"
        typer.echo(f"{row.notice_id:14} {cap:>16}  konfidens {confidence}")
        typer.echo(f"  {_truncate(row.buyer_name, 40)} — {_truncate(row.title, 70)}")
        typer.echo(f"  {row.raw_excerpt or '-'}")
    typer.echo(f"\n{len(rows)} rader i granskningskön.")


@frameworks_app.command("validate")
def frameworks_validate(
    cache: Path = typer.Option(..., help="Directory of cached notice XML to validate against"),
    limit: int | None = typer.Option(None, help="Stop after this many notices"),
) -> None:
    """Report the ceiling hit rate per cap_source over a corpus of cached XML."""
    paths = _xml_files(cache)
    if limit is not None:
        paths = paths[:limit]
    rows, _, skipped = _extract_from_cache(paths, None)
    typer.echo(validate(rows, skipped).render())


# -- winners (M2: leverantörsregister) ---------------------------------------

winners_app = typer.Typer(
    help="Extract framework award winners from notice XML.", no_args_is_help=True
)
app.add_typer(winners_app, name="winners")


def _extract_winners_from_cache(
    paths: list[Path], fx: FxRates | None, known: dict[str, str]
) -> tuple[dict[str, list[AwardWinner]], list[tuple[str, str]]]:
    """Winners per notice. `known` grows as orgnr are learned, so a supplier
    identified in one notice can be matched by name in a later one."""
    per_notice: dict[str, list[AwardWinner]] = {}
    skipped: list[tuple[str, str]] = []
    for path in paths:
        notice_id = path.stem
        try:
            graph = parse_graph(path.read_bytes(), notice_id)
        except (OSError, EformsError) as exc:
            skipped.append((notice_id, str(exc)))
            continue
        rows = extract_winners(graph, fx=fx, known=known)
        per_notice[notice_id] = rows
        for row in rows:
            if row.supplier_orgnr and row.match_confidence == 1.0:
                known.setdefault(row.supplier_name, row.supplier_orgnr)
    return per_notice, skipped


@winners_app.command("extract")
def winners_extract(
    cache: Path = typer.Option(
        Path(DEFAULT_CACHE_DIR), help="Directory of cached notice XML to read"
    ),
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
    limit: int | None = typer.Option(None, help="Stop after this many notices"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be written"),
) -> None:
    """Read cached notice XML into the award_winners table."""
    paths = _xml_files(cache)
    if limit is not None:
        paths = paths[:limit]

    if dry_run:
        per_notice, skipped = _extract_winners_from_cache(paths, None, {})
        rows = [row for rows in per_notice.values() for row in rows]
        for row in rows[:40]:
            rank = f"#{row.rank}" if row.rank is not None else "-"
            typer.echo(
                f"{row.notice_id:14} {row.lot_id:10} {rank:>4} "
                f"{str(row.supplier_orgnr or '-'):13} {_truncate(row.supplier_name, 40)}"
            )
        typer.echo(summarize(rows, len(per_notice), skipped).render())
        typer.echo("Nothing was written.")
        return

    with Storage(db) as storage:
        known = {
            row.supplier_name: row.supplier_orgnr
            for row in storage.list_winners()
            if row.supplier_orgnr
        }
        per_notice, skipped = _extract_winners_from_cache(
            paths, FxRates(storage.connection()), known
        )
        for notice_id, rows in per_notice.items():
            storage.replace_winners(notice_id, rows)
    all_rows = [row for rows in per_notice.values() for row in rows]
    for notice_id, reason in skipped:
        typer.echo(f"skipped {notice_id}: {reason}", err=True)
    typer.echo(summarize(all_rows, len(per_notice), skipped).render())


@winners_app.command("list")
def winners_list(
    notice: str | None = typer.Option(None, help="Only this notice id"),
    orgnr: str | None = typer.Option(None, help="Only this supplier orgnr (NNNNNN-NNNN)"),
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
) -> None:
    """Print stored award winners."""
    wanted = normalize_orgnr(orgnr) if orgnr else None
    if orgnr and wanted is None:
        raise typer.BadParameter(f"{orgnr} is not a valid organisationsnummer")
    with Storage(db) as storage:
        rows = storage.list_winners(notice)
    if wanted is not None:
        rows = [row for row in rows if row.supplier_orgnr == wanted]
    for row in rows:
        rank = f"#{row.rank}" if row.rank is not None else "-"
        value = f"{row.awarded_value_sek:,}".replace(",", "\x20") if row.awarded_value_sek else "-"
        typer.echo(
            f"{row.notice_id:14} {row.lot_id:10} {rank:>4} {value:>16} "
            f"{str(row.supplier_orgnr or '-'):13} {_truncate(row.supplier_name, 40)}"
        )
    typer.echo(f"{len(rows)} rader.")


# -- payments (M4: öppen fakturadata) ----------------------------------------

payments_app = typer.Typer(
    help="Load open supplier-ledger data for framework winners.", no_args_is_help=True
)
app.add_typer(payments_app, name="payments")


@payments_app.command("sources")
def payments_sources() -> None:
    """List the registered loaders, their payer orgnr and what they cover."""
    for key, cls in LOADERS.items():
        loader = cls()
        typer.echo(f"{key:10} {loader.payer_orgnr:13} {loader.payer_org}")
        typer.echo(f"           katalog: {loader.catalogue} — {loader.covers}")
    typer.echo(
        "\nSundsvalls kommun och Helsingborgs stad publicerar ingen "
        "leverantörsreskontra som öppna data; de går via modul 3 (offentlighetsprincipen)."
    )


def _pick_files(files: list[SourceFile], year: int | None, month: int | None) -> list[SourceFile]:
    if year is not None:
        files = [f for f in files if f.year == year]
    if month is not None:
        files = [f for f in files if f.month in (None, month)]
    return files


@payments_app.command("load")
def payments_load(
    source: str = typer.Argument(..., help=f"One of: {', '.join(LOADERS)}"),
    year: int | None = typer.Option(None, help="Only distributions for this year"),
    month: int | None = typer.Option(None, help="Only distributions for this month"),
    file: Path | None = typer.Option(None, help="Read this local file instead of fetching"),
    url: str | None = typer.Option(None, help="Fetch this distribution URL instead of discovering"),
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report counts and write nothing"),
) -> None:
    """Load one source's supplier ledger, keeping only framework winners."""
    if source not in LOADERS:
        raise typer.BadParameter(f"unknown source {source!r}; try one of {', '.join(LOADERS)}")
    loader = LOADERS[source]()

    with Storage(db) as storage:
        winners = WinnerIndex.of(storage.list_winners())
        if not winners.names:
            typer.echo(
                "award_winners är tom — kör `winners extract` först, annars "
                "filtreras alla rader bort.",
                err=True,
            )

        if file is not None:
            jobs = [(SourceFile(url=str(file), label=file.name), file.read_bytes())]
        elif url is not None:
            jobs = [(SourceFile(url=url, label=url), http_fetch(url))]
        else:
            available = loader.discover(http_fetch)
            # Newer catalogue entries group several months under one untitled
            # distribution, so their period is unreadable. Say how many were
            # left out instead of filtering them away silently.
            undated = [f for f in available if f.year is None]
            if undated:
                typer.echo(
                    f"{len(undated)} distribution(er) saknar period i titeln och kan inte "
                    "väljas med --year/--month. Hämta en av dem med --url:",
                    err=True,
                )
                for candidate in undated[:5]:
                    typer.echo(f"  {candidate.url}", err=True)
            found = _pick_files([f for f in available if f.year is not None], year, month)
            if not found:
                typer.echo("Inga distributioner matchade urvalet.", err=True)
                raise typer.Exit(1)
            typer.echo(f"{len(found)} fil(er) att hämta:")
            for candidate in found:
                typer.echo(f"  {candidate.label} — {candidate.url}")
            jobs = [(candidate, http_fetch(candidate.url)) for candidate in found]

        kept = 0
        inserted = 0
        for candidate, blob in jobs:
            rows = loader.read(blob, candidate.url)
            payments = to_payments(rows, loader, candidate.url, winners=winners)
            kept += len(payments)
            if not dry_run:
                inserted += storage.insert_payments(payments)

    if dry_run:
        typer.echo(f"Would keep {kept} aggregated rows. Nothing was written.")
    else:
        typer.echo(f"Kept {kept} aggregated rows, inserted {inserted} new ones.")


# -- report (M5: utnyttjandegrad) --------------------------------------------


@app.command("report")
def utilization_report(
    notice_id: str = typer.Argument(..., help="TED publication number, e.g. 109559-2026"),
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
    out: Path | None = typer.Option(None, help="Write the report here instead of stdout"),
    fmt: str = typer.Option("md", "--format", help="md or html"),
) -> None:
    """Build the utilization report for one framework from stored data."""
    if fmt not in ("md", "html"):
        raise typer.BadParameter("--format must be md or html")
    with Storage(db) as storage:
        conn = storage.connection()
        data = utilization.load(conn, notice_id)
        if data is None:
            typer.echo(
                f"{notice_id} finns inte som ramavtal i databasen. Kör `frameworks extract` först.",
                err=True,
            )
            raise typer.Exit(1)
        text = utilization.render_markdown(
            data,
            utilization.payment_sources(conn, notice_id),
            utilization.framework_winners(conn, notice_id),
        )
    if fmt == "html":
        text = utilization.render_html(text, data)
    if out is not None:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Skrev {out}")
    else:
        typer.echo(text)


@app.command("utilization")
def utilization_table(
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
    measurable: bool = typer.Option(
        False, "--measurable", help="Only frameworks with both a ceiling and observed spend"
    ),
) -> None:
    """Print the utilization view as a table, largest observed spend first."""
    with Storage(db) as storage:
        rows = utilization.load_all(storage.connection())
    if measurable:
        rows = [r for r in rows if r.cap_value_sek and r.observed_spend_sek]
    rows.sort(key=lambda r: r.observed_spend_sek, reverse=True)
    typer.echo(
        f"{'notis':14} {'takvolym':>16} {'observerat':>16} {'grad':>7} "
        f"{'täckning':>9} {'band':>7}  köpare"
    )
    for row in rows:
        # The coverage column is printed on the same line as the rate, always:
        # a utilization figure without it is a misleading number.
        typer.echo(
            f"{row.notice_id:14} {utilization.sek(row.cap_value_sek):>16} "
            f"{utilization.sek(row.observed_spend_sek):>16} "
            f"{utilization.pct(row.utilization_rate):>7} "
            f"{utilization.pct(row.coverage_ratio):>9} {row.confidence_band:>7}  "
            f"{_truncate(row.buyer_name, 34)}"
        )
    typer.echo(f"{len(rows)} ramavtal.")


# -- prospects (M6) ----------------------------------------------------------


@app.command("prospects")
def prospects_command(
    cpv: str | None = typer.Option(None, help="CPV code or wildcard prefix, e.g. 72000000 or 72*"),
    min_frameworks: int = typer.Option(
        prospects.DEFAULT_MIN_FRAMEWORKS,
        "--min-frameworks",
        help="Only suppliers on at least this many framework agreements",
    ),
    out: Path | None = typer.Option(None, help="Write CSV here instead of stdout"),
    db: str | None = typer.Option(None, help="SQLite database path (default: $TENDER_SCAN_DB)"),
) -> None:
    """Export suppliers who sit on several framework agreements, company level only."""
    with Storage(db) as storage:
        found = prospects.find(storage.connection(), cpv=cpv, min_frameworks=min_frameworks)
    csv_text = prospects.to_csv(found)
    if out is not None:
        out.write_text(csv_text, encoding="utf-8")
        typer.echo(f"Skrev {len(found)} rader till {out}")
        typer.echo(
            "Listan är på bolagsnivå. Inga kontaktuppgifter hämtas automatiskt från tredje part."
        )
    else:
        typer.echo(csv_text, nl=False)
