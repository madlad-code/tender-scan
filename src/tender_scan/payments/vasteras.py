"""Västerås stad — a rowstore JSON API, and the one source whose supplier id is
not an orgnr.

Two traps:

1. The JSON carries a UTF-8 BOM **inside its first key**: the key is literally
   `"﻿kopare_id"`, so `row["kopare_id"]` raises KeyError on this source and
   only this source. `strip_bom_keys` handles it.
2. `leverantor_id` is an internal supplier number (`10004007`), not an
   organisationsnummer. Matching these rows to `award_winners` therefore goes
   through the supplier *name*, never through a pretend orgnr — which is why
   `supplier_id_is_orgnr` is False and `to_payments` falls back to the name map.
"""

from __future__ import annotations

from collections.abc import Iterator

from tender_scan.payments.base import (
    Fetcher,
    Loader,
    RawRow,
    SourceFile,
    catalogue_files,
    parse_date,
    parse_json_rows,
    parse_money,
)

HOST = "opendata.vasteras.se"


class VasterasLoader(Loader):
    key = "vasteras"
    payer_org = "Västerås stad"
    payer_orgnr = "212000-2080"
    supplier_id_is_orgnr = False
    catalogue = HOST
    covers = "rowstore JSON per year, plus monthly CSV"

    def discover(self, fetch: Fetcher) -> list[SourceFile]:
        return catalogue_files(fetch, HOST, "leverantörsreskontra")

    def read(self, blob: bytes, source_url: str) -> Iterator[RawRow]:
        for row in parse_json_rows(blob, source_url):
            amount = parse_money(row.get("belopp"))
            supplier = str(row.get("leverantor") or "").strip()
            if amount is None or not supplier:
                continue
            yield RawRow(
                payer_org=str(row.get("kopare") or self.payer_org).strip(),
                payer_orgnr=self.payer_orgnr,
                supplier_name=supplier,
                supplier_id=None,  # deliberately dropped: it is not an orgnr
                amount=amount,
                booking_date=parse_date(row.get("datum")),
                account_code=str(row.get("konto_nr") or "").strip() or None,
                account_text=str(row.get("konto_text") or "").strip() or None,
                voucher=str(row.get("verifikationsnummer") or "").strip() or None,
            )
