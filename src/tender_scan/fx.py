"""Dated currency conversion to SEK, against the ECB daily reference rates.

Framework ceilings are published in whatever currency the buyer used, while
everything downstream of this module is integer SEK. A conversion that cannot
be pointed at afterwards is worthless in a report about public money, so no
rate is ever hardcoded or approximated: every rate is one dated ECB
observation, cached verbatim as text and carrying the URL it came from.

The ECB quotes every currency against the euro (units of X per 1 EUR), which
makes SEK per X a cross rate: (SEK per EUR) / (X per EUR), two series.
Business days only — no weekend or TARGET-holiday rows — so a requested date
walks back to the most recent quoted day, and gives up rather than guessing.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import httpx

from tender_scan.logging_setup import log_external_call

ECB_URL_TEMPLATE = "https://data-api.ecb.europa.eu/service/data/EXR/D.{currency}.EUR.SP00.A"
MAX_LOOKBACK_DAYS = 10

# The euro leg of every cross rate: D.SEK.EUR.SP00.A is SEK per 1 EUR.
_BASE_SERIES = "SEK"

# storage.py owns this table in schema v3; the DDL is repeated here verbatim so
# fx.py also works against a bare sqlite3 connection (tests, ad-hoc scripts).
_FX_SCHEMA = """
CREATE TABLE IF NOT EXISTS fx_rates (
    currency     TEXT NOT NULL,
    rate_date    TEXT NOT NULL,
    sek_per_unit TEXT NOT NULL,
    source       TEXT,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (currency, rate_date)
);
"""


class FxError(Exception):
    """Raised when no dated rate can be established for a currency and a date."""


@dataclass(frozen=True, slots=True)
class Rate:
    currency: str
    rate_date: date  # the date the rate is actually quoted for (<= the one requested)
    sek_per_unit: Decimal
    source: str  # the URL(s) it came from, or "identity" for SEK


# -- parsing -----------------------------------------------------------------


def parse_ecb_csv(text: str) -> dict[date, Decimal]:
    """Map TIME_PERIOD -> OBS_VALUE from one ECB csvdata response.

    Read by header name, never by column index: the column order is not part of
    the ECB's published contract, and a silently shifted column would poison
    every converted amount. Rows without a usable observation are skipped —
    the series legitimately carries flagged rows with an empty value.
    """
    observations: dict[date, Decimal] = {}
    for row in csv.DictReader(io.StringIO(text, newline="")):
        period = (row.get("TIME_PERIOD") or "").strip()
        value = (row.get("OBS_VALUE") or "").strip()
        if not period or not value:
            continue
        try:
            observations[date.fromisoformat(period)] = Decimal(value)
        except (ValueError, InvalidOperation):
            continue
    return observations


# -- fetching ----------------------------------------------------------------


def fetch_ecb_csv(currency: str, start: date, end: date) -> str:
    """Fetch one daily ECB series as CSV. The injection point for tests."""
    url = ECB_URL_TEMPLATE.format(currency=currency)
    params = {
        "startPeriod": start.isoformat(),
        "endPeriod": end.isoformat(),
        "format": "csvdata",
    }
    started = time.monotonic()
    try:
        response = httpx.get(url, params=params, timeout=30.0)
    except httpx.HTTPError as exc:
        log_external_call(url, None, (time.monotonic() - started) * 1000, note=str(exc))
        raise FxError(f"Could not fetch {url}: {exc}") from exc
    log_external_call(str(response.url), response.status_code, (time.monotonic() - started) * 1000)
    if response.status_code != 200:
        raise FxError(f"ECB returned {response.status_code} for {response.url}")
    return response.text


# -- rates -------------------------------------------------------------------


class FxRates:
    """Dated SEK rates: cached in sqlite, fetched from the ECB on a miss."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        fetch: Callable[[str, date, date], str] | None = None,
    ) -> None:
        self._conn = conn
        self._fetch = fetch or fetch_ecb_csv
        self._windows: dict[str, list[tuple[date, date]]] = {}
        conn.executescript(_FX_SCHEMA)
        conn.commit()

    def rate(self, currency: str | None, on: date) -> Rate:
        """The rate for `currency` on `on`, walking back to the last quoted day."""
        code = (currency or "SEK").strip().upper()
        if code == "SEK":
            return Rate(currency="SEK", rate_date=on, sek_per_unit=Decimal(1), source="identity")

        found = self._cached(code, on)
        if found is None:
            self._load(code, on)
            found = self._cached(code, on)
        if found is None:
            raise FxError(
                f"No ECB rate for {code} on {on.isoformat()} or in the "
                f"{MAX_LOOKBACK_DAYS} days before it"
            )
        return found

    def to_sek(self, amount: Decimal, currency: str | None, on: date) -> int:
        """Convert to whole SEK, rounded half up — the storage boundary is an int."""
        converted = amount * self.rate(currency, on).sek_per_unit
        return int(converted.quantize(Decimal(1), rounding=ROUND_HALF_UP))

    # -- cache -------------------------------------------------------------

    def _cached(self, currency: str, on: date) -> Rate | None:
        """The cached rate for `on`, or for the last quoted day before it.

        A date with no row is either a non-business day or a date nobody has
        fetched yet, and only a fetched window tells those apart. Walking back
        through a half-filled cache would answer 2026-07-05 with the 2026-07-01
        rate while the real 2026-07-03 quote sits unfetched, so the walk-back
        runs only inside a window this instance actually fetched.
        """
        exact = self._select(currency, on, on)
        if exact is not None or not self._is_fetched(currency, on):
            return exact
        return self._select(currency, on - timedelta(days=MAX_LOOKBACK_DAYS), on)

    def _select(self, currency: str, earliest: date, latest: date) -> Rate | None:
        row = self._conn.execute(
            "SELECT rate_date, sek_per_unit, source FROM fx_rates "
            "WHERE currency = ? AND rate_date BETWEEN ? AND ? "
            "ORDER BY rate_date DESC LIMIT 1",
            (currency, earliest.isoformat(), latest.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return Rate(
            currency=currency,
            rate_date=date.fromisoformat(row[0]),
            sek_per_unit=Decimal(row[1]),
            source=row[2] or "",
        )

    def _is_fetched(self, currency: str, on: date) -> bool:
        lookback = on - timedelta(days=MAX_LOOKBACK_DAYS)
        return any(
            start <= lookback and on <= end for start, end in self._windows.get(currency, [])
        )

    def _remember_window(self, currency: str, start: date, end: date) -> None:
        self._windows.setdefault(currency, []).append((start, end))

    def _store(self, currency: str, observations: dict[date, Decimal], source: str) -> None:
        fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._conn.executemany(
            "INSERT OR REPLACE INTO fx_rates "
            "(currency, rate_date, sek_per_unit, source, fetched_at) VALUES (?, ?, ?, ?, ?)",
            [
                (currency, day.isoformat(), str(value), source, fetched_at)
                for day, value in sorted(observations.items())
            ],
        )
        self._conn.commit()

    # -- loading -----------------------------------------------------------

    def _load(self, currency: str, on: date) -> None:
        """Fetch and cache a whole window, not a single day: one call covers the walk-back."""
        start = on - timedelta(days=MAX_LOOKBACK_DAYS)
        base_url = ECB_URL_TEMPLATE.format(currency=_BASE_SERIES)
        sek_per_eur = parse_ecb_csv(self._fetch(_BASE_SERIES, start, on))
        # The euro leg is fetched for every currency, so cache it under EUR too.
        self._store("EUR", sek_per_eur, base_url)
        self._remember_window("EUR", start, on)
        if currency == "EUR":
            return

        url = ECB_URL_TEMPLATE.format(currency=currency)
        per_eur = parse_ecb_csv(self._fetch(currency, start, on))
        # Only days both series quote: crossing two different days is not a rate.
        crossed = {
            day: sek_per_eur[day] / per_eur[day] for day in sek_per_eur.keys() & per_eur.keys()
        }
        self._store(currency, crossed, f"{base_url} / {url}")
        self._remember_window(currency, start, on)
