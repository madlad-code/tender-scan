import json
from datetime import date

import httpx
import pytest

from tender_scan.ted_client import (
    SEARCH_PATH,
    RateLimiter,
    TedApiError,
    TedClient,
    build_query,
)


def make_client(handler, **kwargs) -> TedClient:
    return TedClient(
        base_url="https://api.ted.example",
        min_request_interval=0,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_build_query():
    query = build_query("72*", days=30, today=date(2026, 8, 10))
    assert query == (
        "(place-of-performance IN (SWE)) "
        "AND (classification-cpv IN (72*)) "
        "AND (publication-date >= 20260711)"
    )


def test_search_single_page(search_response):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=dict(search_response, totalNoticeCount=5))

    with make_client(handler, page_size=50) as client:
        notices = list(client.search_notices("72*", days=30))

    assert len(notices) == 5
    assert notices[0]["publication-number"] == "449657-2026"
    assert len(requests) == 1
    body = requests[0]
    assert body["page"] == 1
    assert body["limit"] == 50
    assert "classification-cpv IN (72*)" in body["query"]
    assert "place-of-performance IN (SWE)" in body["query"]


def test_search_paginates_until_total(search_response):
    pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        pages.append(body["page"])
        # Report 7 total: with page_size=5 that means two pages.
        payload = dict(search_response, totalNoticeCount=7)
        if body["page"] == 2:
            payload["notices"] = search_response["notices"][:2]
        return httpx.Response(200, json=payload)

    with make_client(handler, page_size=5) as client:
        notices = list(client.search_notices("72*"))

    assert pages == [1, 2]
    assert len(notices) == 7


def test_search_stops_on_empty_page(search_response):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"notices": [], "totalNoticeCount": 100})

    with make_client(handler) as client:
        assert list(client.search_notices("72*")) == []


def test_error_response_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "bad query"})

    with make_client(handler) as client, pytest.raises(TedApiError, match="400"):
        list(client.search_notices("72*"))


def test_request_path_and_fields(search_response):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["fields"] = json.loads(request.content)["fields"]
        return httpx.Response(200, json=search_response)

    with make_client(handler) as client:
        list(client.search_notices("72*"))

    assert seen["path"] == SEARCH_PATH
    assert "publication-number" in seen["fields"]


def test_rate_limiter_sleeps_between_calls():
    now = {"t": 0.0}
    sleeps = []

    def clock():
        return now["t"]

    def sleep(seconds):
        sleeps.append(seconds)
        now["t"] += seconds

    limiter = RateLimiter(1.0, clock=clock, sleep=sleep)
    limiter.wait()  # first call: no sleep
    now["t"] += 0.3
    limiter.wait()  # 0.7s remaining
    assert sleeps == [pytest.approx(0.7)]
