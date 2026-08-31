"""Minimal read-only web view of the local database (stdlib only).

Serves a small mobile-friendly site over a private network (e.g. a Tailscale
tailnet), not for public exposure. Four pages:

* `/` — the utilisation dashboard: every framework agreement with its ceiling,
  the spend we can actually see, and the coverage that qualifies it.
* `/ramavtal/<notice_id>` — the full M5 report for one agreement, rendered by
  `utilization.render_markdown` so the page and the CLI cannot drift apart.
* `/prospekt` — suppliers sitting on several frameworks (M6).
* `/notiser` — the raw notice list this module started as.

## The rule this module inherits

`utilization_rate` is never shown without `coverage_ratio`. The dashboard is a
table, so the caveat cannot travel as a paragraph the way it does in the
report; instead every row carries its own coverage cells, and a test asserts
that no row renders a rate without them. A reader who sorts by "grad" and stops
reading has still seen how much of the picture is missing.
"""

from __future__ import annotations

import html
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from tender_scan import prospects, utilization
from tender_scan.models import Notice, format_estimated_value
from tender_scan.storage import Storage

# A TED notice id is digits-dash-year. Anything else never reaches the query.
_NOTICE_ID_MAX = 32

_STYLE = """
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; background: #fafafa;
         color: #222; }
  main { margin: 1rem; }
  h1 { font-size: 1.3rem; margin: 0 0 0.2rem; }
  nav { background: #fff; border-bottom: 1px solid #ddd; padding: 0.6rem 1rem;
        position: sticky; top: 0; }
  nav a { color: #0a58ca; text-decoration: none; margin-right: 1rem;
          font-size: 0.9rem; }
  nav a.on { color: #111; font-weight: 600; }
  .meta { color: #666; font-size: 0.85rem; margin: 0 0 1rem; }
  .wrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; background: #fff;
          font-size: 0.85rem; }
  th, td { border: 1px solid #ddd; padding: 0.35rem 0.5rem; text-align: left;
           vertical-align: top; }
  th { background: #f0f0f0; position: sticky; top: 0; }
  td.num { text-align: right; white-space: nowrap; }
  a { color: #0a58ca; }
  .band-high { color: #16610e; font-weight: 600; }
  .band-medium { color: #8a6100; }
  .band-low { color: #a12; }
  .card { background: #fff; border: 1px solid #ddd; border-radius: 8px;
          padding: 0.8rem 1rem; margin-bottom: 0.8rem; }
  .card h2 { font-size: 1rem; margin: 0 0 0.4rem; }
  .card h2 a { color: #0a58ca; text-decoration: none; }
  .field { font-size: 0.85rem; color: #444; margin: 0.15rem 0; }
  .field b { color: #111; }
  .tiles { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-bottom: 1rem; }
  .tile { background: #fff; border: 1px solid #ddd; border-radius: 8px;
          padding: 0.6rem 0.9rem; min-width: 7rem; }
  .tile .n { font-size: 1.2rem; font-weight: 600; }
  .tile .l { font-size: 0.75rem; color: #666; }
  .empty { background: #fff; border: 1px dashed #bbb; border-radius: 8px;
           padding: 1rem; color: #555; font-size: 0.9rem; }
  @media (prefers-color-scheme: dark) {
    body { background: #16181c; color: #e6e6e6; }
    nav, table, .card, .tile, .empty { background: #1f2228; border-color: #383c44; }
    th { background: #262a31; }
    th, td { border-color: #383c44; }
    nav { border-bottom-color: #383c44; }
    nav a.on { color: #fff; }
    .field b { color: #fff; }
    a, nav a { color: #7fb2ff; }
    .band-high { color: #7bd96a; }
    .band-medium { color: #e0b447; }
    .band-low { color: #ff8080; }
  }
"""

_PAGE = """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
<nav>{nav}</nav>
<main>
<h1>{heading}</h1>
<p class="meta">{meta}</p>
{body}
</main>
</body>
</html>
"""

_NAV = (
    ("/", "Utnyttjandegrad"),
    ("/prospekt", "Prospekt"),
    ("/notiser", "Notiser"),
)


def esc(value: object | None) -> str:
    """Escape for HTML, rendering a missing value as an en dash."""
    if value is None or value == "":
        return "–"
    return html.escape(str(value))


def _nav(current: str) -> str:
    links = []
    for path, label in _NAV:
        css = ' class="on"' if path == current else ""
        links.append(f'<a href="{path}"{css}>{label}</a>')
    return "".join(links)


def _page(*, title: str, heading: str, meta: str, body: str, current: str) -> str:
    return _PAGE.format(
        title=html.escape(title),
        style=_STYLE,
        nav=_nav(current),
        heading=html.escape(heading),
        meta=html.escape(meta),
        body=body,
    )


def _tile(number: object, label: str) -> str:
    return (
        '<div class="tile">'
        f'<div class="n">{esc(number)}</div>'
        f'<div class="l">{esc(label)}</div>'
        "</div>"
    )


# -- dashboard ---------------------------------------------------------------


def _rate_cells(u: utilization.Utilization) -> str:
    """The rate and both coverage figures, always emitted together.

    Buyer coverage and period coverage are separate cells rather than one
    blended score because they fail independently: an agreement can name a
    single buyer we hold a full ledger for, or a thousand buyers we hold one
    month for, and only both numbers distinguish those cases.
    """
    band = u.confidence_band
    return (
        f'<td class="num">{esc(utilization.pct(u.utilization_rate))}</td>'
        f'<td class="num">{esc(utilization.pct(u.time_normalized_rate))}</td>'
        f'<td class="num">{esc(utilization.pct(u.coverage_ratio))}</td>'
        f'<td class="num">{esc(utilization.pct(u.period_coverage))}</td>'
        f'<td class="band-{band}">{esc(band)}</td>'
    )


_DASH_HEAD = (
    "<tr><th>Notis</th><th>Ramavtal</th><th>Köpare</th>"
    "<th>Takvolym</th><th>Observerat</th>"
    "<th>Grad</th><th>Tidsnorm.</th><th>Täckn. köpare</th><th>Täckn. period</th>"
    "<th>Band</th></tr>"
)

_DASH_NOTE = (
    '<p class="meta">Varje grad läses tillsammans med sina två täckningstal. '
    "Täckning köpare = andelen avropsberättigade organisationer vi har "
    "fakturadata för. Täckning period = andelen förflutna månader vi har data "
    "för. Där båda är låga är graden en undre gräns, inte en mätning.</p>"
)


def render_dashboard(rows: list[utilization.Utilization]) -> str:
    """Every framework, largest observed spend first."""
    ordered = sorted(
        rows,
        key=lambda u: (u.observed_spend_sek, u.cap_value_sek or 0),
        reverse=True,
    )
    measurable = [u for u in ordered if u.cap_value_sek and u.observed_spend_sek]
    tiles = "".join(
        (
            _tile(len(ordered), "ramavtal"),
            _tile(sum(1 for u in ordered if u.cap_value_sek), "med takvolym"),
            _tile(len(measurable), "mätbara"),
            _tile(utilization.sek(sum(u.observed_spend_sek for u in ordered)), "observerat"),
        )
    )
    if not ordered:
        body = (
            '<div class="empty">Inga ramavtal inlästa. Kör '
            "<code>tender-scan frameworks extract</code> för att fylla "
            "databasen.</div>"
        )
        return _page(
            title="tender-scan",
            heading="Utnyttjandegrad",
            meta="0 ramavtal",
            body=body,
            current="/",
        )

    body_rows = "\n".join(
        "<tr>"
        f'<td><a href="/ramavtal/{esc(u.notice_id)}">{esc(u.notice_id)}</a></td>'
        f"<td>{esc(_clip(u.framework_title, 70))}</td>"
        f"<td>{esc(_clip(u.buyer_name, 40))}</td>"
        f'<td class="num">{esc(utilization.sek(u.cap_value_sek))}</td>'
        f'<td class="num">{esc(utilization.sek(u.observed_spend_sek))}</td>'
        f"{_rate_cells(u)}"
        "</tr>"
        for u in ordered
    )
    table = f'<div class="wrap"><table>{_DASH_HEAD}{body_rows}</table></div>'
    body = f'<div class="tiles">{tiles}</div>{_DASH_NOTE}{table}'
    return _page(
        title="tender-scan — utnyttjandegrad",
        heading="Utnyttjandegrad",
        meta=f"{len(ordered)} ramavtal, {len(measurable)} med både takvolym och observerad spend",
        body=body,
        current="/",
    )


def _clip(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# -- prospects ---------------------------------------------------------------

_PROSPECT_HEAD = (
    "<tr><th>Orgnr</th><th>Leverantör</th><th>Ramavtal</th>"
    "<th>Summa takvolym</th><th>Senaste tilldelning</th><th>Köpare</th></tr>"
)


def render_prospects(found: list[prospects.Prospect]) -> str:
    if not found:
        body = (
            '<div class="empty">Inga leverantörer på fler än ett ramavtal. '
            "Kör <code>tender-scan winners extract</code> först.</div>"
        )
    else:
        rows = "\n".join(
            "<tr>"
            f"<td>{esc(p.orgnr)}</td>"
            f"<td>{esc(p.name)}</td>"
            f'<td class="num">{esc(p.framework_count)}</td>'
            f'<td class="num">{esc(utilization.sek(p.total_cap_sek))}</td>'
            f"<td>{esc(p.latest_award_date)}</td>"
            f"<td>{esc(_clip(', '.join(p.buyers), 60))}</td>"
            "</tr>"
            for p in found
        )
        body = f'<div class="wrap"><table>{_PROSPECT_HEAD}{rows}</table></div>'
    return _page(
        title="tender-scan — prospekt",
        heading="Prospekt",
        meta=f"{len(found)} leverantörer på flera ramavtal, flest avtal först",
        body=body,
        current="/prospekt",
    )


# -- notices -----------------------------------------------------------------

_CARD = """<div class="card">
<h2><a href="{url}">{title}</a></h2>
<p class="field"><b>Buyer:</b> {buyer}</p>
<p class="field"><b>Deadline:</b> {deadline} &middot; <b>Value:</b> {value}</p>
<p class="field"><b>CPV:</b> {cpv} &middot; <b>ID:</b> {id}</p>
</div>"""


def render_html(notices: list[Notice]) -> str:
    """The notice list. English labels, unchanged from the first version."""
    cards = "\n".join(
        _CARD.format(
            url=esc(n.url),
            title=esc(n.title),
            buyer=esc(n.buyer),
            deadline=esc(n.deadline.replace("T", " ")[:16] + " UTC" if n.deadline else None),
            value=esc(format_estimated_value(n.estimated_value, n.currency)),
            cpv=esc(n.cpv),
            id=esc(n.id),
        )
        for n in notices
    )
    if not notices:
        cards = (
            '<div class="empty">Inga notiser inlästa. Kör '
            '<code>tender-scan scan --cpv "72*" --days 30</code>.</div>'
        )
    return _page(
        title="tender-scan — notiser",
        heading="tender-scan",
        meta=f"{len(notices)} stored notices, soonest deadline first",
        body=cards,
        current="/notiser",
    )


# -- routing -----------------------------------------------------------------


def _valid_notice_id(raw: str) -> bool:
    return bool(raw) and len(raw) <= _NOTICE_ID_MAX and all(c.isalnum() or c == "-" for c in raw)


def render_framework(conn: sqlite3.Connection, notice_id: str) -> str | None:
    """The full M5 report for one agreement, or None if it is not stored."""
    found = utilization.load(conn, notice_id)
    if found is None:
        return None
    markdown = utilization.render_markdown(
        found,
        utilization.payment_sources(conn, notice_id),
        utilization.framework_winners(conn, notice_id),
    )
    return utilization.render_html(markdown, found)


def route(storage: Storage, path: str) -> str | None:
    """Map a request path to a rendered page, or None for 404."""
    conn = storage.connection()
    if path in ("/", "/index.html"):
        return render_dashboard(utilization.load_all(conn))
    if path == "/prospekt":
        return render_prospects(prospects.find(conn))
    if path == "/notiser":
        return render_html(storage.list_notices())
    if path.startswith("/ramavtal/"):
        notice_id = unquote(path[len("/ramavtal/") :])
        if not _valid_notice_id(notice_id):
            return None
        return render_framework(conn, notice_id)
    return None


def make_handler(db_path: str | None) -> type[BaseHTTPRequestHandler]:
    class NoticeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?", 1)[0]
            with Storage(db_path) as storage:
                page = route(storage, path)
            if page is None:
                self.send_error(404)
                return
            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # quiet by default; not a production access log

    return NoticeHandler


def serve(host: str, port: int, db_path: str | None = None) -> ThreadingHTTPServer:
    """Create the HTTP server (caller decides when to serve_forever)."""
    return ThreadingHTTPServer((host, port), make_handler(db_path))
