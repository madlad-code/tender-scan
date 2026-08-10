import threading
import urllib.error
import urllib.request

from tender_scan.models import parse_notice
from tender_scan.storage import Storage
from tender_scan.web import render_html, serve


def test_render_html_escapes_and_lists(search_response):
    notices = [parse_notice(raw) for raw in search_response["notices"]]
    page = render_html(notices)

    assert "5 stored notices" in page
    assert "450106-2026" in page
    assert "18000000 SEK" in page
    assert "<script" not in page


def test_render_html_empty():
    assert "0 stored notices" in render_html([])


def test_server_serves_page(tmp_path, search_response):
    db = str(tmp_path / "test.db")
    with Storage(db) as storage:
        for raw in search_response["notices"]:
            storage.upsert(parse_notice(raw))

    server = serve("127.0.0.1", 0, db)  # port 0: OS picks a free port
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            body = response.read().decode()
        assert response.status == 200
        assert "450106-2026" in body

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=5)
