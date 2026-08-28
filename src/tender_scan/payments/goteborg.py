"""Göteborgs Stad — same national ledger specification, three different details.

The trap: the file is **UTF-16 little-endian with a BOM**. Decoded as UTF-8 it
raises; decoded as latin-1 it produces mojibake with no error at all, and a
mangled supplier name matches nothing while looking like a supplier who was
never paid. The decoder checks the BOM first and never falls back to a lossy
mode.

Second difference from VGR: the decimal separator is a comma (`3270,50`), and
the date column is `datum`, not `bokforingsdatum`.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator

from tender_scan.payments.base import (
    Fetcher,
    Loader,
    LoaderError,
    RawRow,
    SourceFile,
    catalogue_files,
    decode,
    parse_date,
    parse_money,
)

HOST = "catalog.goteborg.se"


class GoteborgLoader(Loader):
    key = "goteborg"
    payer_org = "Göteborgs Stad"
    payer_orgnr = "212000-1355"
    supplier_id_is_orgnr = True
    catalogue = HOST
    covers = "monthly CSV, 2016 onwards"

    def discover(self, fetch: Fetcher) -> list[SourceFile]:
        return catalogue_files(fetch, HOST, "leverantörsfaktur")

    def read(self, blob: bytes, source_url: str) -> Iterator[RawRow]:
        reader = csv.DictReader(decode(blob, source_url).splitlines(), delimiter=",")
        if reader.fieldnames is None or "belopp" not in reader.fieldnames:
            raise LoaderError(f"{source_url}: not a Göteborg supplier ledger (columns changed?)")
        for row in reader:
            amount = parse_money(row.get("belopp"))
            supplier = (row.get("leverantor") or "").strip()
            if amount is None or not supplier:
                continue
            yield RawRow(
                payer_org=(row.get("kopare") or self.payer_org).strip(),
                payer_orgnr=self.payer_orgnr,
                supplier_name=supplier,
                supplier_id=(row.get("leverantor_id") or "").strip() or None,
                amount=amount,
                booking_date=parse_date(row.get("datum")),
                account_code=(row.get("konto_nr") or "").strip() or None,
                account_text=(row.get("konto_text") or "").strip() or None,
                voucher=(row.get("verifikationsnummer") or "").strip() or None,
            )
