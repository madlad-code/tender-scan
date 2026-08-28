"""M4 — open supplier-ledger loaders.

Every sample here is byte-accurate: the real encoding, the real line
terminator, the real BOM placement. That matters because each of the three
sources fails *silently* when handled with the usual defaults — one row instead
of fifty thousand, mojibake instead of a supplier name, a KeyError on one
source only. A sample rewritten as tidy UTF-8 would test nothing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tender_scan.payments import LOADERS, GoteborgLoader, VasterasLoader, VgrLoader
from tender_scan.payments.base import (
    LoaderError,
    WinnerIndex,
    decode,
    entryscape_search,
    period_of,
    to_payments,
)
from tender_scan.records import AwardWinner
from tender_scan.storage import Storage


def no_network(url: str) -> bytes:
    raise AssertionError(f"a test must not fetch {url}")


# -- VGR ---------------------------------------------------------------------


def test_vgr_bare_carriage_returns_yield_every_row(vgr_sample: bytes) -> None:
    """The file has no `\\n` at all; `newline=""` would give one 9.7 MB row."""
    assert b"\n" not in vgr_sample
    assert vgr_sample.count(b"\r") == 5  # header plus four data rows
    rows = list(VgrLoader().read(vgr_sample, "vgr.csv"))
    assert len(rows) == 4


def test_vgr_parses_amount_date_and_supplier(vgr_sample: bytes) -> None:
    rows = {row.supplier_name: row for row in VgrLoader().read(vgr_sample, "vgr.csv")}
    swedbank = rows["Swedbank AB"]
    assert swedbank.amount == Decimal("136.98")  # dot decimal separator
    assert swedbank.booking_date == date(2026, 1, 7)
    assert swedbank.supplier_id == "6630000138"
    assert swedbank.payer_orgnr == "232100-0131"


def test_vgr_keeps_negative_amounts(vgr_sample: bytes) -> None:
    """Credit notes are real and they reduce observed spend."""
    amounts = [row.amount for row in VgrLoader().read(vgr_sample, "vgr.csv")]
    assert any(amount < 0 for amount in amounts)


def test_vgr_swedish_characters_survive(vgr_sample: bytes) -> None:
    names = {row.supplier_name for row in VgrLoader().read(vgr_sample, "vgr.csv")}
    assert "Västsvenska TuristRådet AB" in names


def test_vgr_rejects_a_file_whose_columns_changed() -> None:
    with pytest.raises(LoaderError, match="not a VGR supplier ledger"):
        list(VgrLoader().read(b"a;b;c\r1;2;3\r", "other.csv"))


# -- Göteborg ----------------------------------------------------------------


def test_goteborg_is_utf16_and_round_trips_swedish_text(goteborg_sample: bytes) -> None:
    assert goteborg_sample[:2] == b"\xff\xfe"  # UTF-16 LE BOM
    rows = list(GoteborgLoader().read(goteborg_sample, "gbg.csv"))
    assert any(row.account_text == "Övriga främmande tjänster" for row in rows)


def test_goteborg_uses_a_comma_decimal_separator(goteborg_sample: bytes) -> None:
    """The opposite of VGR, in the same national ledger specification."""
    rows = {row.supplier_name: row for row in GoteborgLoader().read(goteborg_sample, "gbg.csv")}
    assert rows["SWEDISH RADIO SUPPLY AB"].amount == Decimal("3270.50")
    assert rows["SWEDISH RADIO SUPPLY AB"].booking_date == date(2026, 7, 2)


def test_goteborg_decoded_as_utf8_would_have_failed(goteborg_sample: bytes) -> None:
    with pytest.raises(UnicodeDecodeError):
        goteborg_sample.decode("utf-8")


# -- Västerås ----------------------------------------------------------------


def test_vasteras_finds_the_bom_prefixed_key(vasteras_sample: bytes) -> None:
    """The first JSON key is literally `"﻿kopare_id"`."""
    assert "﻿kopare_id".encode() in vasteras_sample
    rows = list(VasterasLoader().read(vasteras_sample, "vst.json"))
    assert len(rows) == 2
    assert all(row.payer_org == "VÄSTERÅS STAD" for row in rows)


def test_vasteras_supplier_id_is_never_treated_as_an_orgnr(vasteras_sample: bytes) -> None:
    """`leverantor_id` is an internal number (10004007), not an organisationsnummer."""
    assert VasterasLoader().supplier_id_is_orgnr is False
    assert all(row.supplier_id is None for row in VasterasLoader().read(vasteras_sample, "v.json"))


def test_vasteras_keeps_negative_amounts(vasteras_sample: bytes) -> None:
    rows = list(VasterasLoader().read(vasteras_sample, "vst.json"))
    assert rows[0].amount == Decimal("-1302.03")


def test_vasteras_rejects_json_without_results() -> None:
    with pytest.raises(LoaderError, match="no results array"):
        list(VasterasLoader().read(b'{"nope": 1}', "vst.json"))


# -- decoding ----------------------------------------------------------------


def test_a_file_that_decodes_as_nothing_raises_and_names_itself() -> None:
    # 0x81 and 0x8D are undefined in CP1252 and invalid as a UTF-8 lead byte.
    with pytest.raises(LoaderError, match="broken.csv"):
        decode(b"kopare;belopp\r\x81\x8d\x90", "broken.csv")


def test_decoding_is_never_lossy(goteborg_sample: bytes) -> None:
    """`errors="replace"` would turn a supplier name into something that matches nothing."""
    assert "�" not in decode(goteborg_sample, "gbg.csv")


# -- aggregation and filtering -----------------------------------------------


def winner_index(*pairs: tuple[str, str | None]) -> WinnerIndex:
    return WinnerIndex.of(AwardWinner("1-2026", name, orgnr, "LOT-0000") for name, orgnr in pairs)


def test_invoices_are_aggregated_into_one_row_per_supplier_and_month(
    vasteras_sample: bytes,
) -> None:
    loader = VasterasLoader()
    rows = list(loader.read(vasteras_sample, "v.json"))
    payments = to_payments(rows, loader, "v.json")
    assert len(payments) == 1
    assert payments[0].amount_sek == -1703  # -1302.03 + -400.68, rounded half up
    assert (payments[0].period_year, payments[0].period_month) == (2025, 1)


def test_a_supplier_not_on_any_framework_is_discarded(vgr_sample: bytes) -> None:
    loader = VgrLoader()
    rows = list(loader.read(vgr_sample, "vgr.csv"))
    kept = to_payments(
        rows, loader, "vgr.csv", winners=winner_index(("Sensative AB", "556922-4644"))
    )
    assert [payment.supplier_name for payment in kept] == ["Sensative AB"]


def test_a_source_without_orgnr_joins_through_the_supplier_name(
    vasteras_sample: bytes,
) -> None:
    """Västerås rows can only reach award_winners by name, so the match must work."""
    loader = VasterasLoader()
    rows = list(loader.read(vasteras_sample, "v.json"))
    kept = to_payments(
        rows, loader, "v.json", winners=winner_index(("OneMed Sverige AB", "556053-0022"))
    )
    assert len(kept) == 1
    assert kept[0].supplier_orgnr == "556053-0022"


def test_a_row_without_a_booking_date_is_not_placed_in_a_period() -> None:
    loader = VgrLoader()
    blob = (
        b"kopare_id;kopare;verifikationsnummer;leverantor;leverantor_id;konto_nr;"
        b"konto_text;bokforingsdatum;forvaltning;fakturanummer;nettobelopp\r"
        b"2321000131;VGR;1;Consid AB;5565994307;1;t;;f;-;100.00\r"
    )
    assert to_payments(loader.read(blob, "x.csv"), loader, "x.csv") == []


# -- idempotency -------------------------------------------------------------


def test_loading_the_same_file_twice_adds_nothing_the_second_time(
    tmp_path: Path, vgr_sample: bytes
) -> None:
    loader = VgrLoader()
    payments = to_payments(loader.read(vgr_sample, "vgr.csv"), loader, "vgr.csv")
    with Storage(tmp_path / "t.sqlite3") as storage:
        first = storage.insert_payments(payments)
        second = storage.insert_payments(payments)
        total = storage.connection().execute("SELECT COUNT(*) FROM supplier_payments").fetchone()[0]
    assert first == len(payments) > 0
    assert second == 0
    assert total == first


# -- discovery ---------------------------------------------------------------


def test_discover_reads_the_catalogue_and_never_hardcodes_a_url(vgr_catalogue: bytes) -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        calls.append(url)
        return vgr_catalogue

    files = VgrLoader().discover(fake_fetch)
    assert calls and "vgregion.entryscape.net/store/search" in calls[0]
    assert files
    assert all(file.url.startswith("https://vgregion.entryscape.net/") for file in files)


def test_discovery_sorts_newest_period_first(vgr_catalogue: bytes) -> None:
    files = VgrLoader().discover(lambda url: vgr_catalogue)
    years = [file.year for file in files if file.year]
    assert years == sorted(years, reverse=True)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Leverantörsfaktura 202601", (2026, 1)),
        ("Leverantörsfaktura 2026-01", (2026, 1)),
        ("Leverantörsfakturor 2025", (2025, None)),
        ("Leverantörsreskontra", (None, None)),
        ("Leverantörsfaktura 202613", (2026, None)),  # not a month
    ],
)
def test_period_is_read_from_the_distribution_title(
    title: str, expected: tuple[int | None, int | None]
) -> None:
    assert period_of(title) == expected


def test_catalogue_search_survives_an_entry_with_no_title(vgr_catalogue: bytes) -> None:
    assert entryscape_search(lambda url: vgr_catalogue, "example.test")


# -- registry ----------------------------------------------------------------


def test_every_registered_loader_declares_a_valid_payer_orgnr() -> None:
    from tender_scan.orgnr import is_valid_orgnr

    for key, cls in LOADERS.items():
        loader = cls()
        assert loader.key == key
        assert is_valid_orgnr(loader.payer_orgnr), key


def test_no_loader_reaches_the_network_while_reading(
    vgr_sample: bytes, goteborg_sample: bytes, vasteras_sample: bytes
) -> None:
    samples = {"vgr": vgr_sample, "goteborg": goteborg_sample, "vasteras": vasteras_sample}
    for key, cls in LOADERS.items():
        assert list(cls().read(samples[key], "local"))
    with pytest.raises(AssertionError):
        no_network("https://example.test")
