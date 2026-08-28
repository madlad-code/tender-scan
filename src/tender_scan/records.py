"""Row-shaped records for the schema v3 tables.

`storage.py` needs typed rows for framework agreements, award winners and
supplier payments — but those rows are produced by the extraction modules
(eForms parsing, cap detection, the payment loaders), which themselves import
storage. Putting the dataclasses in this leaf module, which imports nothing
from the package, breaks that cycle.

Each field mirrors one column, in DDL order. Money is integer SEK, as
everywhere else on the storage boundary. Fields that the writer stamps itself
default to None.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameworkAgreement:
    """One notice, plus whatever ceiling could be pinned down and how sure we are."""

    notice_id: str
    buyer_name: str | None = None
    buyer_orgnr: str | None = None
    title: str | None = None
    is_framework: bool = False
    cap_value_sek: int | None = None
    estimated_value_sek: int | None = None
    cap_source: str | None = None  # 'eforms_field' | 'document_regex' | 'manual'
    cap_confidence: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    max_duration_months: int | None = None
    cpv_main: str | None = None
    # True when the buyer is a known central purchasing body. Those publish no
    # list of the organisations entitled to call off, so coverage has no
    # denominator and the report must say so rather than imply full coverage.
    buyer_is_cpb: bool = False
    raw_excerpt: str | None = None
    updated_at: str | None = None  # storage stamps the current UTC time when None


@dataclass(frozen=True, slots=True)
class AwardWinner:
    """One supplier awarded one lot of one notice."""

    notice_id: str
    supplier_name: str
    supplier_orgnr: str | None
    lot_id: str
    rank: int | None = None
    awarded_value_sek: int | None = None
    match_confidence: float | None = None
    award_date: str | None = None  # from the notice's SettledContract, when published
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class SupplierPayment:
    """One payment line from a buyer to a supplier, for one period."""

    payer_org: str
    payer_orgnr: str | None
    supplier_name: str
    supplier_orgnr: str | None
    amount_sek: int
    period_year: int
    period_month: int | None
    source: str  # 'open_data' | 'foia' | 'annual_report'
    source_url: str | None = None
    row_hash: str | None = None  # storage computes it via payment_row_hash when None
    ingested_at: str | None = None
