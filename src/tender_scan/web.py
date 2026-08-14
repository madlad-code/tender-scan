"""Minimal read-only web view of stored notices (stdlib only).

Serves a single mobile-friendly HTML page listing the notices in the local
SQLite database. Intended for private access (e.g. over a Tailscale tailnet),
not for public exposure.
"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tender_scan.models import Notice, format_estimated_value
from tender_scan.storage import Storage

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tender-scan</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 1rem; background: #fafafa; color: #222; }}
  h1 {{ font-size: 1.3rem; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 1rem; }}
  .card {{ background: #fff; border: 1px solid #ddd; border-radius: 8px;
          padding: 0.8rem 1rem; margin-bottom: 0.8rem; }}
  .card h2 {{ font-size: 1rem; margin: 0 0 0.4rem; }}
  .card h2 a {{ color: #0a58ca; text-decoration: none; }}
  .field {{ font-size: 0.85rem; color: #444; margin: 0.15rem 0; }}
  .field b {{ color: #111; }}
</style>
</head>
<body>
<h1>tender-scan</h1>
<p class="meta">{count} stored notices, soonest deadline first</p>
{cards}
</body>
</html>
"""

_CARD = """<div class="card">
<h2><a href="{url}">{title}</a></h2>
<p class="field"><b>Buyer:</b> {buyer}</p>
<p class="field"><b>Deadline:</b> {deadline} &middot; <b>Value:</b> {value}</p>
<p class="field"><b>CPV:</b> {cpv} &middot; <b>ID:</b> {id}</p>
</div>"""


def render_html(notices: list[Notice]) -> str:
    def esc(value: str | None) -> str:
        return html.escape(value) if value else "-"

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
    return _PAGE.format(count=len(notices), cards=cards)


def make_handler(db_path: str | None) -> type[BaseHTTPRequestHandler]:
    class NoticeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            with Storage(db_path) as storage:
                body = render_html(storage.list_notices()).encode()
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
