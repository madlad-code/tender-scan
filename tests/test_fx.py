"""Currency conversion tests.

Nothing here touches the network: every FxRates gets an injected fetch that
replays recorded CSV. No exchange rate is hardcoded in fx.py either — every
number asserted below comes out of tests/fixtures/ecb_sek_eur.csv or out of
Decimal arithmetic over it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tender_scan.fx import MAX_LOOKBACK_DAYS, FxError, FxRates, parse_ecb_csv

# Deliberately not the ECB's column order: TIME_PERIOD/OBS_VALUE sit at index 4
# and 2 here, so a parser that reads by index instead of by header name fails.
USD_CSV = (
    "KEY,FREQ,OBS_VALUE,CURRENCY,TIME_PERIOD,OBS_STATUS\r\n"
    "EXR.D.USD.EUR.SP00.A,D,1.0801,USD,2026-07-02,A\r\n"
    "EXR.D.USD.EUR.SP00.A,D,1.0824,USD,2026-07-03,A\r\n"
    "EXR.D.USD.EUR.SP00.A,D,1.0790,USD,2026-07-06,A\r\n"
)

# Same series with the 2026-07-03 observation missing, to check that a cross
# rate falls back to a day where *both* legs are quoted.
USD_CSV_NO_JULY_3 = "\n".join(line for line in USD_CSV.splitlines() if "2026-07-03" not in line)


class FakeFetch:
    """Replays a recorded CSV per ECB series and records every call."""

    def __init__(self, **series: str) -> None:
        self.series = series
        self.calls: list[tuple[str, date, date]] = []

    def __call__(self, currency: str, start: date, end: date) -> str:
        self.calls.append((currency, start, end))
        if currency not in self.series:
            raise AssertionError(f"unexpected fetch of the {currency} series")
        return self.series[currency]


def exploding_fetch(currency: str, start: date, end: date) -> str:
    raise AssertionError(f"fetch must not be called (asked for {currency})")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A bare connection: fx.py has to create its own fx_rates table."""
    connection = sqlite3.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def fetch(ecb_csv: str) -> FakeFetch:
    return FakeFetch(SEK=ecb_csv, USD=USD_CSV)


# -- identity ----------------------------------------------------------------


@pytest.mark.parametrize("currency", [None, "SEK", "sek"])
def test_sek_is_identity_and_never_fetches(conn: sqlite3.Connection, currency: str | None) -> None:
    rates = FxRates(conn, fetch=exploding_fetch)
    rate = rates.rate(currency, date(2026, 7, 5))

    assert rate.sek_per_unit == Decimal(1)
    assert isinstance(rate.sek_per_unit, Decimal)
    assert rate.currency == "SEK"
    assert rate.rate_date == date(2026, 7, 5)
    assert rate.source == "identity"


def test_identity_conversion_does_not_fetch(conn: sqlite3.Connection) -> None:
    fetcher = FakeFetch()
    rates = FxRates(conn, fetch=fetcher)

    assert rates.to_sek(Decimal("1234.56"), None, date(2026, 7, 5)) == 1235
    assert fetcher.calls == []


# -- EUR ---------------------------------------------------------------------


def test_eur_rate_comes_from_the_recorded_csv(conn: sqlite3.Connection, fetch: FakeFetch) -> None:
    rate = FxRates(conn, fetch=fetch).rate("EUR", date(2026, 7, 1))

    assert rate.sek_per_unit == Decimal("11.0955")
    assert isinstance(rate.sek_per_unit, Decimal)
    assert rate.rate_date == date(2026, 7, 1)
    assert rate.currency == "EUR"
    assert "D.SEK.EUR.SP00.A" in rate.source
    assert fetch.calls[0][0] == "SEK"  # SEK per EUR is the D.SEK.EUR series


@pytest.mark.parametrize("weekend_day", [date(2026, 7, 4), date(2026, 7, 5)])
def test_weekend_walks_back_to_the_last_quoted_day(
    conn: sqlite3.Connection, fetch: FakeFetch, weekend_day: date
) -> None:
    rate = FxRates(conn, fetch=fetch).rate("EUR", weekend_day)

    assert rate.sek_per_unit == Decimal("11.0315")
    # The date the rate is actually quoted for, never the date that was asked for.
    assert rate.rate_date == date(2026, 7, 3)
    assert rate.rate_date != weekend_day


def test_date_beyond_the_lookback_window_raises(conn: sqlite3.Connection, fetch: FakeFetch) -> None:
    oldest_observation = date(2026, 6, 29)
    too_old = oldest_observation - timedelta(days=MAX_LOOKBACK_DAYS + 1)

    with pytest.raises(FxError):
        FxRates(conn, fetch=fetch).rate("EUR", too_old)


# -- caching -----------------------------------------------------------------


def test_one_fetch_populates_the_whole_window(conn: sqlite3.Connection, fetch: FakeFetch) -> None:
    rates = FxRates(conn, fetch=fetch)

    assert rates.rate("EUR", date(2026, 7, 3)).sek_per_unit == Decimal("11.0315")
    assert len(fetch.calls) == 1

    assert rates.rate("EUR", date(2026, 6, 30)).sek_per_unit == Decimal("11.0935")
    assert rates.rate("EUR", date(2026, 7, 2)).sek_per_unit == Decimal("11.0775")
    assert len(fetch.calls) == 1


def test_cached_rates_survive_a_new_instance(conn: sqlite3.Connection, fetch: FakeFetch) -> None:
    FxRates(conn, fetch=fetch).rate("EUR", date(2026, 7, 3))

    fresh = FxRates(conn, fetch=exploding_fetch)
    assert fresh.rate("EUR", date(2026, 7, 1)).sek_per_unit == Decimal("11.0955")


def test_rate_round_trips_through_the_text_column(
    conn: sqlite3.Connection, fetch: FakeFetch
) -> None:
    FxRates(conn, fetch=fetch).rate("EUR", date(2026, 7, 3))

    stored, column_type = conn.execute(
        "SELECT sek_per_unit, typeof(sek_per_unit) FROM fx_rates "
        "WHERE currency = 'EUR' AND rate_date = '2026-07-03'"
    ).fetchone()

    assert column_type == "text"
    assert Decimal(stored) == Decimal("11.0315")
    assert stored == "11.0315"


# -- conversion --------------------------------------------------------------


def test_to_sek_returns_int_and_rounds_half_up(conn: sqlite3.Connection, fetch: FakeFetch) -> None:
    rates = FxRates(conn, fetch=fetch)
    day = date(2026, 7, 5)

    assert rates.to_sek(Decimal("2.5"), "SEK", day) == 3
    assert rates.to_sek(Decimal("3.5"), None, day) == 4  # half up, not half even
    assert rates.to_sek(Decimal("2.4999"), "SEK", day) == 2
    assert isinstance(rates.to_sek(Decimal("1"), "SEK", day), int)

    # 100 EUR at the 2026-07-03 rate: 100 * 11.0315 = 1103.15
    assert rates.to_sek(Decimal("100"), "EUR", day) == 1103


# -- cross rates -------------------------------------------------------------


def test_usd_is_crossed_through_the_euro(conn: sqlite3.Connection, fetch: FakeFetch) -> None:
    rate = FxRates(conn, fetch=fetch).rate("USD", date(2026, 7, 3))

    expected = Decimal("11.0315") / Decimal("1.0824")  # (SEK per EUR) / (USD per EUR)
    assert rate.sek_per_unit == expected
    assert rate.sek_per_unit == Decimal("10.19170362158167036215816704")
    assert rate.rate_date == date(2026, 7, 3)
    assert rate.currency == "USD"
    assert sorted(currency for currency, _, _ in fetch.calls) == ["SEK", "USD"]


def test_usd_conversion_rounds_to_int_sek(conn: sqlite3.Connection, fetch: FakeFetch) -> None:
    rates = FxRates(conn, fetch=fetch)

    expected = (Decimal("250000") * (Decimal("11.0315") / Decimal("1.0824"))).to_integral_value()
    assert rates.to_sek(Decimal("250000"), "USD", date(2026, 7, 3)) == int(expected) == 2547926


def test_cross_rate_uses_a_day_both_series_quote(conn: sqlite3.Connection, ecb_csv: str) -> None:
    fetch = FakeFetch(SEK=ecb_csv, USD=USD_CSV_NO_JULY_3)
    rate = FxRates(conn, fetch=fetch).rate("USD", date(2026, 7, 3))

    # 2026-07-03 has a SEK quote but no USD quote, so both legs step back a day.
    assert rate.rate_date == date(2026, 7, 2)
    assert rate.sek_per_unit == Decimal("11.0775") / Decimal("1.0801")


# -- CSV parsing -------------------------------------------------------------


def test_parse_ecb_csv_reads_by_header_name(ecb_csv: str) -> None:
    observations = parse_ecb_csv(ecb_csv)

    assert observations[date(2026, 7, 1)] == Decimal("11.0955")
    assert date(2026, 7, 4) not in observations  # business days only
    assert date(2026, 7, 5) not in observations
    assert parse_ecb_csv(USD_CSV)[date(2026, 7, 3)] == Decimal("1.0824")


def test_parse_ecb_csv_skips_rows_without_an_observation() -> None:
    text = (
        "TIME_PERIOD,OBS_VALUE\r\n2026-07-01,11.0955\r\n2026-07-02,\r\n2026-07-03,not-a-number\r\n"
    )

    assert parse_ecb_csv(text) == {date(2026, 7, 1): Decimal("11.0955")}
