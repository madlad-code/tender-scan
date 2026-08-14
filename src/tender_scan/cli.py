"""Command-line interface for tender-scan."""

from __future__ import annotations

from pathlib import Path

import typer

from tender_scan import report as report_module
from tender_scan.models import Notice, format_estimated_value, parse_notice
from tender_scan.storage import Storage
from tender_scan.ted_client import TedClient

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
