"""Client for the TED (Tenders Electronic Daily) Search API.

The public search endpoint is anonymous — no API key required:
POST https://api.ted.europa.eu/v3/notices/search
Docs: https://docs.ted.europa.eu/api/latest/index.html
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.ted.europa.eu"
SEARCH_PATH = "/v3/notices/search"

# eForms field identifiers to request. Verified against the live API:
# unsupported names are rejected with an explicit error listing valid values.
SEARCH_FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "classification-cpv",
    "deadline-receipt-tender-date-lot",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "publication-date",
    "links",
]


class TedApiError(Exception):
    """Raised when the TED API returns an error response."""


class RateLimiter:
    """Enforces a minimum interval between consecutive requests."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            elapsed = self._clock() - self._last
            remaining = self.min_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


def build_query(cpv: str, days: int, country: str = "SWE", today: date | None = None) -> str:
    """Build a TED expert-search query for country + CPV + publication window.

    ``cpv`` may be an exact code ("72000000") or a wildcard prefix ("72*").
    """
    since = (today or date.today()) - timedelta(days=days)
    return (
        f"(place-of-performance IN ({country})) "
        f"AND (classification-cpv IN ({cpv})) "
        f"AND (publication-date >= {since:%Y%m%d})"
    )


class TedClient:
    """Thin client over the TED Search API with pagination and rate limiting."""

    def __init__(
        self,
        base_url: str | None = None,
        page_size: int = 50,
        min_request_interval: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.page_size = page_size
        self._rate_limiter = RateLimiter(min_request_interval)
        self._client = httpx.Client(
            base_url=base_url or os.environ.get("TED_API_BASE_URL", DEFAULT_BASE_URL),
            timeout=30.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TedClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def search_notices(
        self, cpv: str, days: int = 30, country: str = "SWE"
    ) -> Iterator[dict[str, Any]]:
        """Yield raw notices matching country + CPV published in the last ``days`` days."""
        query = build_query(cpv, days, country)
        page = 1
        while True:
            data = self._search_page(query, page)
            notices = data.get("notices", [])
            yield from notices
            total = data.get("totalNoticeCount", 0)
            if not notices or page * self.page_size >= total:
                return
            page += 1

    def _search_page(self, query: str, page: int) -> dict[str, Any]:
        self._rate_limiter.wait()
        payload = {
            "query": query,
            "fields": SEARCH_FIELDS,
            "page": page,
            "limit": self.page_size,
        }
        response = self._client.post(SEARCH_PATH, json=payload)
        if response.status_code != 200:
            raise TedApiError(f"TED API returned {response.status_code}: {response.text[:500]}")
        return response.json()
