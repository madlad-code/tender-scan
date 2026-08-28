"""M4 — the shared shape every open supplier-ledger loader produces.

One loader per source, one output schema, and **all** normalisation inside the
loader. Nothing downstream is allowed to branch on which municipality a row
came from — the moment it does, adding the fourth source means editing the
report generator.

`read` takes bytes rather than a path or a file object, so every test feeds it
a recorded sample and no test can reach the network. `discover` is the only
network-touching method and takes an injectable fetcher.

## Encoding

Swedish open data is not reliably UTF-8. The detector checks for a byte-order
mark first, then strict UTF-8, then CP1252, and **raises** if none decodes
cleanly. `errors="replace"` is never used: a mangled supplier name matches
nothing and looks exactly like a supplier who was simply not paid.

## Aggregation and idempotency

A source file holds one row per invoice; `SupplierPayment` holds one row per
supplier per month. The loader therefore sums invoices into monthly totals,
which is also what makes re-ingest exact: the same file produces the same
totals, the same `payment_row_hash`, and `INSERT OR IGNORE` adds nothing the
second time.

The limitation that follows: if a publisher reissues a corrected file for a
month at a *different* URL, its rows hash differently and would be added on
top of the originals. Load one file per period, and say so in the report's
method limitations.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

from tender_scan.logging_setup import log_external_call
from tender_scan.money import parse_amount, to_int_sek
from tender_scan.orgnr import normalize_orgnr
from tender_scan.records import AwardWinner, SupplierPayment

SOURCE_OPEN_DATA = "open_data"

# A descriptive agent, so a publisher who looks at their logs can see who this
# is and reach the project rather than blocking an anonymous scraper.
USER_AGENT = "tender-scan/0.1 (+https://github.com/madlad-code/tender-scan)"

Fetcher = Callable[[str], bytes]


class LoaderError(Exception):
    """Raised when a source file cannot be decoded or parsed."""


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One distribution of one period, as the publisher's own catalogue lists it."""

    url: str
    label: str
    year: int | None = None
    month: int | None = None


@dataclass(frozen=True, slots=True)
class RawRow:
    """One invoice line, normalised but not yet aggregated."""

    payer_org: str
    payer_orgnr: str | None
    supplier_name: str
    supplier_id: str | None  # whatever the source calls a supplier id, un-interpreted
    amount: Decimal
    booking_date: date | None
    account_code: str | None
    account_text: str | None
    voucher: str | None


# -- decoding ----------------------------------------------------------------

_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def decode(blob: bytes, name: str) -> str:
    """Decode a source file, or raise naming it. Never lossy.

    Göteborg publishes UTF-16 LE with a BOM; VGR and Västerås publish UTF-8.
    Older municipal exports are CP1252. Guessing wrong is silent, so the BOM
    is checked first and every candidate is tried strictly.
    """
    for bom, encoding in _BOMS:
        if blob.startswith(bom):
            try:
                return blob.decode(encoding)
            except UnicodeDecodeError as exc:
                raise LoaderError(f"{name}: BOM says {encoding} but it does not decode") from exc
    for encoding in ("utf-8", "cp1252"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise LoaderError(f"{name}: decodes as neither UTF-8 nor CP1252")


def strip_bom_keys(row: dict[str, object]) -> dict[str, object]:
    """Västerås's rowstore JSON puts a UTF-8 BOM *inside* its first key.

    The key is literally `"﻿kopare_id"`, so `row["kopare_id"]` raises
    KeyError on that source and only that source.
    """
    return {key.lstrip("﻿"): value for key, value in row.items()}


def parse_json_rows(blob: bytes, name: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(decode(blob, name))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LoaderError(f"{name}: not valid JSON: {exc}") from exc
    results = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(results, list):
        raise LoaderError(f"{name}: no results array")
    return [strip_bom_keys(row) for row in results if isinstance(row, dict)]


def parse_date(value: object) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def parse_money(value: object) -> Decimal | None:
    """Amounts, through the shared normaliser. Negatives are credit notes and real."""
    return parse_amount(str(value or "").strip())


# -- the loader contract -----------------------------------------------------


class Loader(ABC):
    key: str  # "vgr" | "goteborg" | "vasteras"
    payer_org: str  # human-readable buyer name
    payer_orgnr: str  # the buyer's orgnr, normalized
    supplier_id_is_orgnr: bool
    catalogue: str  # the catalogue endpoint discover() queries
    covers: str  # what periods this source publishes, for `payments sources`

    @abstractmethod
    def discover(self, fetch: Fetcher) -> list[SourceFile]:
        """Resolve the current distribution URLs through the source's own catalogue."""

    @abstractmethod
    def read(self, blob: bytes, source_url: str) -> Iterator[RawRow]:
        """Parse one downloaded file. Takes bytes, so no test can reach the network."""


# -- aggregation -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WinnerIndex:
    """Which suppliers are on a framework, by orgnr and by normalised name.

    Payments to everyone else are discarded before they reach the database:
    a municipality pays tens of thousands of suppliers, and only the framework
    winners are call-offs we can attribute.
    """

    orgnrs: frozenset[str]
    names: dict[str, str]  # normalised supplier name -> orgnr

    @classmethod
    def of(cls, winners: Iterable[AwardWinner]) -> WinnerIndex:
        names: dict[str, str] = {}
        orgnrs: set[str] = set()
        for winner in winners:
            key = _name_key(winner.supplier_name)
            if winner.supplier_orgnr:
                orgnrs.add(winner.supplier_orgnr)
                names.setdefault(key, winner.supplier_orgnr)
            else:
                names.setdefault(key, "")
        return cls(frozenset(orgnrs), names)

    def resolve(self, orgnr: str | None, name_key: str) -> tuple[str | None, bool]:
        """(orgnr to store, whether this supplier is on a framework at all)."""
        if orgnr is not None and orgnr in self.orgnrs:
            return orgnr, True
        matched = self.names.get(name_key)
        if matched is not None:
            return orgnr or (matched or None), True
        return orgnr, False


def to_payments(
    rows: Iterable[RawRow],
    loader: Loader,
    source_url: str | None,
    *,
    winners: WinnerIndex | None = None,
) -> list[SupplierPayment]:
    """Aggregate invoice lines into one row per supplier per month.

    When `winners` is given, only suppliers on a framework survive. That index
    is also how a source whose supplier id is *not* an orgnr (Västerås) still
    joins to `award_winners`: the match goes through the normalised name and
    borrows the winner's orgnr. A name with no entry keeps
    `supplier_orgnr = None` rather than a guess.
    """
    totals: dict[tuple[str, str | None, int, int | None], Decimal] = defaultdict(Decimal)
    names: dict[tuple[str, str | None, int, int | None], str] = {}
    for row in rows:
        if row.booking_date is None:
            continue  # a payment with no period cannot be placed in an agreement
        orgnr = normalize_orgnr(row.supplier_id) if loader.supplier_id_is_orgnr else None
        name_key = _name_key(row.supplier_name)
        if winners is not None:
            orgnr, on_framework = winners.resolve(orgnr, name_key)
            if not on_framework:
                continue
        key = (name_key, orgnr, row.booking_date.year, row.booking_date.month)
        totals[key] += row.amount
        names.setdefault(key, row.supplier_name)

    return [
        SupplierPayment(
            payer_org=loader.payer_org,
            payer_orgnr=loader.payer_orgnr,
            supplier_name=names[key],
            supplier_orgnr=key[1],
            amount_sek=to_int_sek(total),
            period_year=key[2],
            period_month=key[3],
            source=SOURCE_OPEN_DATA,
            source_url=source_url,
        )
        for key, total in sorted(totals.items())
    ]


def _name_key(name: str) -> str:
    """Import the one name normaliser rather than writing a second one."""
    from tender_scan.winners import normalize_company_name

    return normalize_company_name(name)


# -- catalogue discovery -----------------------------------------------------

# The EntryScape solr search behind dataportal.se. Each publisher's own
# EntryScape host answers the same API for its own catalogue, which is how the
# current monthly distribution URLs are resolved instead of hardcoded. The
# `publisher:"..."` solr field is rejected with HTTP 400, so filtering is done
# on the client side.
ENTRYSCAPE_SEARCH = "https://{host}/store/search?type=solr&query={query}&limit={limit}"

_TITLE = "http://purl.org/dc/terms/title"
_DOWNLOAD_URL = "http://www.w3.org/ns/dcat#downloadURL"

_PERIOD_YYYYMM = re.compile(r"(20\d{2})[-_ ]?(0[1-9]|1[0-2])(?!\d)")
_PERIOD_YYYY = re.compile(r"(20\d{2})")


def entryscape_search(
    fetch: Fetcher, host: str, query: str = "title:Leverant*", limit: int = 200
) -> list[tuple[str, str]]:
    """(title, downloadURL) for every distribution the catalogue lists.

    A single distribution entry can carry **several** downloadURLs: Göteborg
    publishes its 2026 months as one "Leverantörsreskontra CSV" entry with
    seven URLs under it. Taking only the first silently drops six months of
    invoices, so every URL is returned.
    """
    url = ENTRYSCAPE_SEARCH.format(host=host, query=query, limit=limit)
    payload = json.loads(decode(fetch(url), url))
    found: list[tuple[str, str]] = []
    for child in payload.get("resource", {}).get("children", []):
        for properties in (child.get("metadata") or {}).values():
            downloads = properties.get(_DOWNLOAD_URL)
            if not downloads:
                continue
            titles = properties.get(_TITLE) or []
            title = titles[0].get("value", "") if titles else ""
            for entry in downloads:
                if value := entry.get("value", ""):
                    found.append((title, value))
    return found


def period_of(title: str) -> tuple[int | None, int | None]:
    """`Leverantörsfaktura 202601` -> (2026, 1); `... 2025` -> (2025, None)."""
    if (match := _PERIOD_YYYYMM.search(title)) is not None:
        return int(match.group(1)), int(match.group(2))
    if (match := _PERIOD_YYYY.search(title)) is not None:
        return int(match.group(1)), None
    return None, None


def catalogue_files(fetch: Fetcher, host: str, must_contain: str) -> list[SourceFile]:
    """Distributions whose title names this kind of ledger, newest period first.

    The period comes from the title, which older entries carry ("Leverantörs-
    faktura 202601") and newer grouped entries do not. A file whose period
    cannot be read keeps `year = None`; the CLI reports how many it left out
    rather than filtering them away silently.
    """
    seen: set[str] = set()
    files: list[SourceFile] = []
    for title, url in entryscape_search(fetch, host):
        if must_contain.casefold() not in title.casefold() or not url or url in seen:
            continue
        seen.add(url)
        year, month = period_of(title)
        files.append(SourceFile(url=url, label=title, year=year, month=month))
    return sorted(files, key=lambda f: (f.year or 0, f.month or 0, f.url), reverse=True)


def http_fetch(url: str) -> bytes:
    """The real fetcher. Serial by construction — one call, one file."""
    started = time.monotonic()
    try:
        response = httpx.get(
            url, timeout=120.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
    except httpx.HTTPError as exc:
        log_external_call(url, None, (time.monotonic() - started) * 1000, note=str(exc))
        raise LoaderError(f"Could not fetch {url}: {exc}") from exc
    log_external_call(str(response.url), response.status_code, (time.monotonic() - started) * 1000)
    if response.status_code != 200:
        raise LoaderError(f"{url} returned {response.status_code}")
    return response.content
