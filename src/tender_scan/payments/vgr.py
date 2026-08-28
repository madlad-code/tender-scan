"""Västra Götalandsregionen — the spec's primary source, and the one that joins
straight to `award_winners` because its `leverantor_id` really is an orgnr.

The trap: the file's line terminator is a **bare carriage return**. There is no
`\n` anywhere in it, so `wc -l` reports 0 and the usual csv advice —
`open(..., newline="")` — yields one row containing the whole 9.7 MB file. The
lines are split explicitly here, and a test asserts the row count from a
CR-only sample.
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

HOST = "vgregion.entryscape.net"


def split_lines(text: str) -> list[str]:
    """Universal newlines by hand: CRLF, then bare CR, then split on LF.

    `str.splitlines` would also split on U+2028, U+0085 and the vertical tab,
    any of which can legitimately sit inside a supplier name.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


class VgrLoader(Loader):
    key = "vgr"
    payer_org = "Västra Götalandsregionen"
    payer_orgnr = "232100-0131"
    supplier_id_is_orgnr = True
    catalogue = HOST
    covers = "monthly CSV, 2024 onwards"

    def discover(self, fetch: Fetcher) -> list[SourceFile]:
        return catalogue_files(fetch, HOST, "leverantörsfaktur")

    def read(self, blob: bytes, source_url: str) -> Iterator[RawRow]:
        lines = split_lines(decode(blob, source_url))
        reader = csv.DictReader(lines, delimiter=";")
        if reader.fieldnames is None or "nettobelopp" not in reader.fieldnames:
            raise LoaderError(f"{source_url}: not a VGR supplier ledger (columns changed?)")
        for row in reader:
            # Amounts use a dot decimal separator here and a comma in Göteborg;
            # every published VGR amount carries exactly two decimals.
            amount = parse_money(row.get("nettobelopp"))
            supplier = (row.get("leverantor") or "").strip()
            if amount is None or not supplier:
                continue
            yield RawRow(
                payer_org=(row.get("kopare") or self.payer_org).strip(),
                payer_orgnr=self.payer_orgnr,
                supplier_name=supplier,
                supplier_id=(row.get("leverantor_id") or "").strip() or None,
                amount=amount,
                booking_date=parse_date(row.get("bokforingsdatum")),
                account_code=(row.get("konto_nr") or "").strip() or None,
                account_text=(row.get("konto_text") or "").strip() or None,
                voucher=(row.get("verifikationsnummer") or "").strip() or None,
            )
