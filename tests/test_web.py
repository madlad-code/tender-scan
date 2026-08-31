"""The web view.

The dashboard inherits M5's invariant — a utilisation percentage never appears
without its coverage figures — and the table form makes it easier to break than
the report does, so it is asserted here by counting cells rather than by eye.
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.request

from tests.test_utilization import build

from tender_scan.models import parse_notice
from tender_scan.storage import Storage
from tender_scan.web import (
    render_dashboard,
    render_html,
    render_prospects,
    route,
    serve,
)


def test_render_html_escapes_and_lists(search_response):
    notices = [parse_notice(raw) for raw in search_response["notices"]]
    page = render_html(notices)

    assert "5 stored notices" in page
    assert "450106-2026" in page
    assert "18000000 SEK" in page
    assert "<script" not in page


def test_render_html_empty():
    assert "0 stored notices" in render_html([])


def test_dashboard_lists_the_framework_and_links_to_its_report(tmp_path):
    db = build(tmp_path, payments=[("212000-1355", 1_000_000, 2025, 7)])
    with Storage(db) as storage:
        page = route(storage, "/")

    assert "1-2026" in page
    assert 'href="/ramavtal/1-2026"' in page
    assert "Ramavtal kommunikationstjänster" in page
    assert "5 000 000 SEK" in page  # the ceiling, space-grouped by sek()
    assert "1 000 000 SEK" in page  # observed spend


def test_dashboard_never_shows_a_rate_without_both_coverage_figures(tmp_path):
    """Every data row carries the rate cells and the coverage cells together."""
    db = build(tmp_path, payments=[("212000-1355", 1_000_000, 2025, 7)])
    with Storage(db) as storage:
        page = route(storage, "/")

    header = re.search(r"<tr>(<th>.*?</th>)+</tr>", page).group(0)
    assert "Täckn. köpare" in header
    assert "Täckn. period" in header
    # 10 columns in the header, and the data row must fill all of them: a row
    # that dropped the coverage cells would still render, just shorter.
    assert header.count("<th>") == 10
    data_rows = re.findall(r"<tr><td>.*?</tr>", page)
    assert data_rows
    for row in data_rows:
        assert row.count("<td") == 10


def test_dashboard_empty_database_explains_the_next_command(tmp_path):
    with Storage(tmp_path / "empty.db") as storage:
        page = route(storage, "/")

    assert "0 ramavtal" in page
    assert "frameworks extract" in page


def test_dashboard_orders_by_observed_spend(tmp_path):
    db = build(tmp_path, payments=[("212000-1355", 1_000_000, 2025, 7)])
    with Storage(db) as storage:
        rows = route(storage, "/")
    assert rows  # single framework; ordering asserted directly on the renderer

    from tender_scan.utilization import Utilization

    def one(notice_id: str, spend: int) -> Utilization:
        return Utilization(
            notice_id=notice_id,
            framework_title="t",
            buyer_name="b",
            cap_value_sek=10_000_000,
            observed_spend_sek=spend,
            coverage_ratio=0.5,
            utilization_rate=spend / 10_000_000,
            months_elapsed=10,
            months_total=40,
            start_date="2025-01-01",
            end_date="2028-04-30",
            cap_source="eforms_field",
            cap_confidence=0.9,
            buyer_is_cpb=False,
            raw_excerpt=None,
            named_buyers=2,
            paying_buyers=1,
            paid_suppliers=1,
            observed_months=5,
            payment_rows=5,
        )

    page = render_dashboard([one("small-2026", 10), one("big-2026", 9_000_000)])
    assert page.index("big-2026") < page.index("small-2026")


def test_framework_report_page_renders_and_unknown_id_is_404(tmp_path):
    db = build(tmp_path, payments=[("212000-1355", 1_000_000, 2025, 7)])
    with Storage(db) as storage:
        page = route(storage, "/ramavtal/1-2026")
        assert route(storage, "/ramavtal/999-2026") is None
        # A path that could never be a notice id is rejected before the query.
        assert route(storage, "/ramavtal/../../etc/passwd") is None

    assert "Utnyttjandegrad" in page
    assert "Metodbegränsningar" in page


def test_prospects_page_empty_state():
    page = render_prospects([])
    assert "winners extract" in page
    assert "0 leverantörer" in page


def test_prospects_page_lists_a_supplier(tmp_path):
    from tender_scan.prospects import Prospect

    page = render_prospects(
        [
            Prospect(
                orgnr="556599-4307",
                name="Atea Sverige AB",
                framework_count=3,
                framework_titles=("a", "b", "c"),
                latest_award_date="2026-04-01",
                buyers=("Göteborgs Stad",),
                total_cap_sek=12_000_000,
            )
        ]
    )
    assert "Atea Sverige AB" in page
    assert "12 000 000 SEK" in page
    assert "1 leverantörer" in page


def test_server_serves_every_page(tmp_path, search_response):
    db = build(tmp_path, payments=[("212000-1355", 1_000_000, 2025, 7)])
    with Storage(db) as storage:
        for raw in search_response["notices"]:
            storage.upsert(parse_notice(raw))

    server = serve("127.0.0.1", 0, str(db))  # port 0: OS picks a free port
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:

        def get(path: str) -> str:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as response:
                assert response.status == 200
                return response.read().decode()

        assert "1-2026" in get("/")
        assert "450106-2026" in get("/notiser")
        assert "Prospekt" in get("/prospekt")
        assert "Metodbegränsningar" in get("/ramavtal/1-2026")

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=5)
