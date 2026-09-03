"""M7 — municipal contract catalogues and supplier ledgers obtained by records request.

Modules 1–6 answer the question from the *notice* side: TED publishes a ceiling,
the winners, and sometimes the buyers entitled to call off. This module answers
it from the *municipality* side, using what a records request actually returns —
which is two files with no relation to TED at all:

* an **avtalskatalog**, one row per supplier per contract, and
* a **leverantörsreskontra**, one row per invoice.

Held together they measure something no open source publishes: how much of a
municipality's spend reaches the suppliers it has signed contracts with, and how
many of those suppliers get nothing. The pair is the point. A catalogue alone
lists intentions; a ledger alone lists payments to names.

## Every delivery is a different file

Five municipalities answered the same request with five formats: an e-avrop
matrix with its header on row four, a Mercell export with two of its columns
merged into a free-text period, a contract system's PDF, and two ordinary
spreadsheets whose column names agree on nothing. There is no shared schema to
find, so each reader owns its format entirely and they all produce
`MunicipalContract`. Nothing downstream branches on which municipality a row
came from.

Readers take bytes rather than paths for the same reason `payments.base` does:
a test feeds a recorded sample and cannot reach a file system or a network.

## What the numbers here may and may not claim

`avtalstrohet` — contracted share of spend — is only computed for a buyer whose
catalogue *and* ledger are both stored, and it is always reported next to the
ledger's own window. Two limits are structural and are carried in
`Coverage.caveats` rather than left for the reader to remember:

* **A catalogue is not a census.** Grästorp said so in writing: their database
  holds mainly framework agreements and omits construction procurements, direct
  awards and several central-body agreements. Spend outside the catalogue is
  therefore not proof of maverick buying — some of it is contracted under a
  contract the catalogue never held.
* **A ledger window is not a contract term.** A supplier with zero payments is
  only meaningful if their contract was live while the ledger was running, so
  `zero_calloff` counts contracts overlapping the window and no others — and it
  is not computed at all below `MIN_ZERO_MONTHS`. One month of ledger would
  report that 95 % of a city's suppliers got nothing, which is true of any
  month and says nothing about any supplier.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from tender_scan.orgnr import normalize_orgnr
from tender_scan.records import MunicipalContract, SupplierPayment

SOURCE_FOIA = "foia"

# Below this many months of ledger, "paid nothing" is a statement about the
# window rather than about the supplier, so `zero_calloff` stays None.
MIN_ZERO_MONTHS = 12


class ReaderError(Exception):
    """Raised when a delivered file is not the shape its reader expects."""


# -- small parsers -----------------------------------------------------------

_DATE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


def parse_iso_date(value: object) -> str | None:
    """The ISO date inside a cell, or None.

    Spreadsheets hand back a datetime, a `YYYY-MM-DD 00:00:00` string, or an
    `YYYYMMDD` integer depending on the exporter, and all three mean the same
    day. Anything without a full year-month-day is dropped rather than guessed:
    a half-parsed date puts a contract in the wrong window.
    """
    if value is None or value == "":
        return None
    match = _DATE.search(str(value))
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_int_sek(value: object) -> int | None:
    """A contract value in whole SEK, or None when the cell holds no number."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return int(value)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in ("-", "."):
        return None
    try:
        return int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


_RANK = re.compile(r"rang\s*:?\s*(\d+)", re.IGNORECASE)


def parse_rank(value: object) -> int | None:
    """The rank a supplier holds on a ranked framework, or None.

    Göteborg puts a bare integer in its own column; Bjurholm writes the rank
    into a free-text `Avtalsform` such as `Rangordnat avtal Rang:3 Gräns då
    konkurrensutsättning inträder 1000000 kr`. Both mean third in line.
    """
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return int(value) or None
    match = _RANK.search(str(value))
    if match:
        return int(match.group(1))
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def clean(value: object) -> str | None:
    """A trimmed cell, or None when it is empty or the exporter's `0.0` filler."""
    if value is None:
        return None
    text = " ".join(str(value).replace("_x000D_", " ").split())
    if not text or text in ("0.0", "None", "-"):
        return None
    return text


def overlaps(start: str | None, end: str | None, window: tuple[str, str]) -> bool:
    """True when a contract term overlaps a ledger window at all.

    An open-ended term counts as running: a catalogue that leaves `T.o.m.`
    blank is saying the contract has not ended, not that it never started.
    """
    lo, hi = window
    return (end or "9999-12-31") >= lo and (start or "0000-01-01") <= hi


# -- spreadsheet access ------------------------------------------------------


def _xlsx_rows(blob: bytes, sheet: str | int = 0) -> Iterator[tuple[object, ...]]:
    try:
        import openpyxl
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise ReaderError("openpyxl is required to read .xlsx deliveries") from exc
    book = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    try:
        worksheet = book[sheet] if isinstance(sheet, str) else book.worksheets[sheet]
        yield from worksheet.iter_rows(values_only=True)
    finally:
        book.close()


def _xls_rows(blob: bytes, sheet: str) -> Iterator[list[object]]:
    try:
        import xlrd
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise ReaderError("xlrd is required to read the .xls deliveries") from exc
    book = xlrd.open_workbook(file_contents=blob)
    worksheet = book.sheet_by_name(sheet)
    for index in range(worksheet.nrows):
        yield worksheet.row_values(index)


def _header_index(row: Iterable[object], wanted: Iterable[str], where: str) -> dict[str, int]:
    header = {clean(cell): index for index, cell in enumerate(row)}
    missing = [name for name in wanted if name not in header]
    if missing:
        raise ReaderError(f"{where}: missing column(s) {', '.join(missing)}")
    return {name: header[name] for name in wanted}


# -- catalogue readers -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Catalogue:
    """A reader for one municipality's delivered contract catalogue."""

    key: str
    buyer_org: str
    label: str
    read: object  # Callable[[bytes], list[MunicipalContract]]


def read_goteborg(blob: bytes) -> list[MunicipalContract]:
    """Göteborgs Stad: one sheet, one row per supplier per framework, rank in its own column."""
    rows = _xlsx_rows(blob, "Blad1")
    columns = _header_index(
        next(rows),
        (
            "Avtalsnummer_Original",
            "Leverantörsnamn_Original",
            "Leverantör_Organisationsnummer_Original",
            "Beställningsgrupp",
            "Delområden",
            "Startdatum_Avtal",
            "Slutdatum_Avtal",
            "Rangordning",
        ),
        "Göteborg",
    )
    out = []
    for row in rows:
        supplier = clean(row[columns["Leverantörsnamn_Original"]])
        if supplier is None:
            continue
        out.append(
            MunicipalContract(
                buyer_org="Göteborgs Stad",
                supplier_name=supplier,
                supplier_orgnr=normalize_orgnr(
                    clean(row[columns["Leverantör_Organisationsnummer_Original"]])
                ),
                contract_ref=clean(row[columns["Avtalsnummer_Original"]]),
                title=clean(row[columns["Beställningsgrupp"]]),
                category=clean(row[columns["Delområden"]]),
                start_date=parse_iso_date(row[columns["Startdatum_Avtal"]]),
                end_date=parse_iso_date(row[columns["Slutdatum_Avtal"]]),
                rank=parse_rank(row[columns["Rangordning"]]),
            )
        )
    return out


def read_huddinge(blob: bytes) -> list[MunicipalContract]:
    """Huddinge kommun: current contracts on Blad1, expired ones on Blad2.

    Both sheets are read. An expired contract is not noise — it is what a
    supplier's previous place looked like, and it is the only way to see a
    framework change hands.
    """
    out = []
    for sheet in ("Blad1", "Blad2"):
        rows = _xlsx_rows(blob, sheet)
        columns = _header_index(
            next(rows),
            ("Diarie", "Kategori", "Varugrupp", "Fr.o.m.", "T.o.m.", "Leverantör", "Orgnr"),
            f"Huddinge/{sheet}",
        )
        for row in rows:
            supplier = clean(row[columns["Leverantör"]])
            if supplier is None:
                continue
            out.append(
                MunicipalContract(
                    buyer_org="Huddinge kommun",
                    supplier_name=supplier,
                    supplier_orgnr=normalize_orgnr(clean(row[columns["Orgnr"]])),
                    contract_ref=clean(row[columns["Diarie"]]),
                    title=clean(row[columns["Varugrupp"]]),
                    category=clean(row[columns["Kategori"]]),
                    start_date=parse_iso_date(row[columns["Fr.o.m."]]),
                    end_date=parse_iso_date(row[columns["T.o.m."]]),
                )
            )
    return out


def read_bjurholm(blob: bytes) -> list[MunicipalContract]:
    """Bjurholms kommun: an e-avrop matrix whose header sits on row four.

    Rows one to three are the export's own title block. The rank lives inside
    the free-text `Avtalsform`, and `Avtalstecknare` records that Umeå kommun
    signed most of these on Bjurholm's behalf — kept as the category prefix
    would lose it, so it goes nowhere but is why a small municipality has 972
    contract rows.
    """
    rows = list(_xls_rows(blob, "Statistik"))
    if len(rows) < 5:
        raise ReaderError("Bjurholm: sheet 'Statistik' has no data rows")
    columns = _header_index(
        rows[3],
        (
            "Organisation",
            "Diarie",
            "Kategori",
            "Varugrupp",
            "Fr.o.m.",
            "T.o.m.",
            "Leverantör",
            "Orgnr",
            "Avtalsform",
        ),
        "Bjurholm",
    )
    out = []
    for row in rows[4:]:
        supplier = clean(row[columns["Leverantör"]])
        buyer = clean(row[columns["Organisation"]])
        if supplier is None or buyer is None:
            continue
        out.append(
            MunicipalContract(
                buyer_org="Bjurholms kommun",
                supplier_name=supplier,
                supplier_orgnr=normalize_orgnr(clean(row[columns["Orgnr"]])),
                contract_ref=clean(row[columns["Diarie"]]),
                title=clean(row[columns["Varugrupp"]]),
                category=clean(row[columns["Kategori"]]),
                start_date=parse_iso_date(row[columns["Fr.o.m."]]),
                end_date=parse_iso_date(row[columns["T.o.m."]]),
                rank=parse_rank(row[columns["Avtalsform"]]),
            )
        )
    return out


_PERIOD = re.compile(r"(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})")


def read_grastorp(blob: bytes) -> list[MunicipalContract]:
    """Grästorps kommun: a Mercell export with the term in one free-text column.

    The header is on row two — row one is the export stamp — and there is no
    organisationsnummer column at all, so every supplier here is name-only and
    joins to a ledger on nothing. That is a property of the delivery, not a
    bug to work around.
    """
    rows = list(_xlsx_rows(blob, "Blad2"))
    if len(rows) < 3:
        raise ReaderError("Grästorp: sheet 'Blad2' has no data rows")
    columns = _header_index(
        rows[1], ("Avtal", "Leverantör", "Avtalstyp", "Avtalsperiod"), "Grästorp"
    )
    out = []
    for row in rows[2:]:
        supplier = clean(row[columns["Leverantör"]])
        if supplier is None:
            continue
        period = _PERIOD.search(clean(row[columns["Avtalsperiod"]]) or "")
        out.append(
            MunicipalContract(
                buyer_org="Grästorps kommun",
                supplier_name=supplier,
                title=clean(row[columns["Avtal"]]),
                category=clean(row[columns["Avtalstyp"]]),
                start_date=period.group(1) if period else None,
                end_date=period.group(2) if period else None,
            )
        )
    return out


_PDF_ROW = re.compile(
    r"^(?P<title>.+?)\s+(?P<ref>\S+)\s+"
    r"(?P<officer>[A-ZÅÄÖ][\wÅÄÖåäö\-]+(?: [A-ZÅÄÖ][\wÅÄÖåäö\-]+)*)\s+"
    r"(?P<start>\d{4}-\d{2}-\d{2}) 00:00\s+(?P<end>\d{4}-\d{2}-\d{2}) 00:00\s+"
    r"(?P<supplier>.+?)(?:\s+(?P<value>\d{4,}))?$"
)


def read_jonkoping(blob: bytes) -> list[MunicipalContract]:
    """Jönköpings kommun: a PDF export, one contract row per line.

    A PDF is not a machine-readable delivery and the municipality said as much
    — they are mid-migration to a new contract database and this is what an
    automated extract gives. It is parsed anyway because it is the only
    catalogue in the batch that carries a contract *value*, which is the
    municipal equivalent of the takvolym module 1 pulls out of a notice.

    Lines that do not match the row shape are skipped rather than guessed at;
    the text layer splits some supplier names mid-word (`Atea S verig e AB`),
    so supplier names from this source are unreliable and its organisation
    numbers are absent entirely.
    """
    try:
        import pdfplumber
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise ReaderError("pdfplumber is required to read the Jönköping PDF") from exc
    out = []
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").split("\n"):
                text = line.strip()
                if not text or text.startswith("Namn Referensnummer"):
                    continue
                match = _PDF_ROW.match(text)
                if match is None:
                    continue
                out.append(
                    MunicipalContract(
                        buyer_org="Jönköpings kommun",
                        supplier_name=match.group("supplier").strip(),
                        contract_ref=match.group("ref"),
                        title=match.group("title").strip(),
                        category=match.group("officer"),
                        start_date=match.group("start"),
                        end_date=match.group("end"),
                        cap_value_sek=parse_int_sek(match.group("value")),
                    )
                )
    return out


CATALOGUES: dict[str, Catalogue] = {
    c.key: c
    for c in (
        Catalogue("goteborg", "Göteborgs Stad", "Avtal 2023-2026 (xlsx)", read_goteborg),
        Catalogue("huddinge", "Huddinge kommun", "Avtalskatalogen (xlsx)", read_huddinge),
        Catalogue("bjurholm", "Bjurholms kommun", "Avtalsstatistik e-avrop (xls)", read_bjurholm),
        Catalogue("grastorp", "Grästorps kommun", "Avtalsdatabasen Mercell (xlsx)", read_grastorp),
        Catalogue("jonkoping", "Jönköpings kommun", "ContractExport (pdf)", read_jonkoping),
    )
}


# -- ledger readers ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ledger:
    """A reader for one municipality's delivered supplier ledger."""

    key: str
    buyer_org: str
    label: str
    read: object  # Callable[[bytes], list[SupplierPayment]]


def _aggregate(
    rows: Iterable[tuple[str, str | None, str, int]]
    | Iterable[tuple[str, str | None, str, int, str | None, str | None]],
    payer_org: str,
    payer_orgnr: str | None,
    source_url: str | None,
) -> list[SupplierPayment]:
    """Sum invoice lines into one row per supplier per month.

    The same aggregation `payments.base` performs, and for the same reason:
    it is what makes a re-ingest of the identical file a no-op.

    Rows may carry two more fields — the account the line was booked against
    and the cost centre that spent it. When they do, they join the grouping
    key: a supplier paid out of two budgets in one month stays two rows, which
    is the whole point of having asked for the columns. Ledgers without them
    group exactly as before.

    Lines that net to zero over a month are dropped. A credit note that
    reverses an invoice in the same period is not spend, and a supplier whose
    year nets to nothing did not sell anything.
    """
    totals: dict[tuple[str, str | None, int, int, str | None, str | None], int] = defaultdict(int)
    for row in rows:
        period, orgnr, name, amount = row[:4]
        account, cost_centre = (row[4], row[5]) if len(row) > 4 else (None, None)
        totals[(name, orgnr, int(period[:4]), int(period[5:7]), account, cost_centre)] += amount
    return [
        SupplierPayment(
            payer_org=payer_org,
            payer_orgnr=payer_orgnr,
            supplier_name=name,
            supplier_orgnr=orgnr,
            amount_sek=amount,
            period_year=year,
            period_month=month,
            source=SOURCE_FOIA,
            source_url=source_url,
            account=account,
            cost_centre=cost_centre,
        )
        for (name, orgnr, year, month, account, cost_centre), amount in sorted(
            totals.items(),
            key=lambda item: (
                item[0][0],
                item[0][1] or "",
                item[0][2],
                item[0][3],
                item[0][4] or "",
                item[0][5] or "",
            ),
        )
        if amount
    ]


# Borås replaces a supplier's name with this when the counterparty is a person.
# Those rows carry no organisation number and must never be summed into one
# "supplier" — they are thousands of unrelated individuals.
_BORAS_REDACTED = ("[innehåller personuppgifter]", "[Kan innehålla personuppgifter]")


def read_boras(blob: bytes, source_url: str | None = None) -> list[SupplierPayment]:
    """Borås Stad: the `Öppna data` invoice extract, one file per year.

    Rows whose supplier has been redacted for containing personal data are
    dropped: they have no organisation number, they are not one counterparty,
    and keeping them would inflate a "supplier" that does not exist.

    The buyer's name is the reader's, not the file's. The extract shouts
    `BORÅS STAD` in every row, and a payer that spells itself differently from
    its own catalogue is a second municipality as far as every join here is
    concerned.
    """
    rows = _xlsx_rows(blob, 0)
    columns = _header_index(
        next(rows),
        ("kopare", "kopare_id", "leverantor", "leverantor_id", "belopp", "datum"),
        "Borås",
    )
    payer_orgnr = None
    lines = []
    for row in rows:
        name = clean(row[columns["leverantor"]])
        period = parse_iso_date(row[columns["datum"]])
        amount = row[columns["belopp"]]
        if name is None or period is None or not isinstance(amount, int | float):
            continue
        if name in _BORAS_REDACTED:
            continue
        payer_orgnr = payer_orgnr or normalize_orgnr(clean(row[columns["kopare_id"]]))
        orgnr = normalize_orgnr(clean(row[columns["leverantor_id"]]))
        lines.append((period, orgnr, name, int(round(amount))))
    return _aggregate(lines, "Borås Stad", payer_orgnr, source_url)


def read_bjurholm_ledger(blob: bytes, source_url: str | None = None) -> list[SupplierPayment]:
    """Bjurholms kommun: an 89-column accounts-payable dump.

    Six of those columns matter. `Fakturadatum` dates the row rather than the
    payment date, so a period matches the invoice a supplier issued, which is
    what a supplier recognises as their own revenue.
    """
    rows = _xlsx_rows(blob, "Sheet0")
    columns = _header_index(
        next(rows),
        ("Organisationsnr", "Levnamn", "Fakturabelopp", "Fakturadatum"),
        "Bjurholm",
    )
    lines = []
    for row in rows:
        name = clean(row[columns["Levnamn"]])
        period = parse_iso_date(row[columns["Fakturadatum"]])
        amount = row[columns["Fakturabelopp"]]
        if name is None or period is None or not isinstance(amount, int | float):
            continue
        orgnr = normalize_orgnr(clean(row[columns["Organisationsnr"]]))
        lines.append((period, orgnr, name, int(round(amount))))
    return _aggregate(lines, "Bjurholms kommun", None, source_url)


def read_huddinge_ledger(blob: bytes, source_url: str | None = None) -> list[SupplierPayment]:
    """Huddinge kommun: the accounts-payable extract, one file per year.

    The richest ledger any of the twenty sent. Besides the supplier and the
    amount it names `Konto(T)` — what the money was booked as — and
    `Ansvar(T)` — which unit spent it. Both are kept, because "Huddinge paid
    Telia 4 MSEK" and "Huddinge paid Telia 4 MSEK for mobile telephony out of
    twelve different schools' budgets" are different findings, and only the
    second one tells a supplier where the buying decision is made.

    `Period` is the accounting period as `YYYYMM` and is what the municipality
    itself closes its books on, so it dates the row in preference to
    `Ver.datum`, which is when the voucher happened to be entered.

    Credit notes arrive as negative amounts and are kept as they are: they are
    how a ledger reverses an invoice, and dropping them would overstate spend.
    """
    rows = _xlsx_rows(blob, 0)
    columns = _header_index(
        next(rows),
        ("Period", "Organisationsnr.", "Lev.nr(T)", "Belopp", "Konto(T)", "Ansvar(T)"),
        "Huddinge",
    )
    lines = []
    for row in rows:
        name = clean(row[columns["Lev.nr(T)"]])
        period = clean(row[columns["Period"]])
        amount = row[columns["Belopp"]]
        if name is None or period is None or not isinstance(amount, int | float):
            continue
        if len(period) != 6 or not period.isdigit():
            continue
        orgnr = normalize_orgnr(clean(row[columns["Organisationsnr."]]))
        lines.append(
            (
                f"{period[:4]}-{period[4:]}-01",
                orgnr,
                name,
                int(round(amount)),
                clean(row[columns["Konto(T)"]]),
                clean(row[columns["Ansvar(T)"]]),
            )
        )
    return _aggregate(lines, "Huddinge kommun", None, source_url)


LEDGERS: dict[str, Ledger] = {
    lg.key: lg
    for lg in (
        Ledger("boras", "Borås Stad", "Öppna data, ett år per fil (xlsx)", read_boras),
        Ledger(
            "bjurholm",
            "Bjurholms kommun",
            "Leverantörsreskontraöversikt (xlsx)",
            read_bjurholm_ledger,
        ),
        Ledger(
            "huddinge",
            "Huddinge kommun",
            "Leverantörsreskontra med konto och ansvar, ett år per fil (xlsx)",
            read_huddinge_ledger,
        ),
    )
}


# -- the view ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Kommun:
    """What is known about one municipality, and how much of it is measurable."""

    buyer_org: str
    contract_rows: int
    contract_suppliers: int
    active_contracts: int
    active_suppliers: int
    contracts_with_value: int
    catalogue_value_sek: int | None
    ledger_window: tuple[str, str] | None
    ledger_months: int
    ledger_rows: int
    ledger_total_sek: int
    ledger_suppliers: int
    contracted_spend_sek: int | None
    zero_calloff: int | None
    caveats: tuple[str, ...] = ()

    @property
    def avtalstrohet(self) -> float | None:
        """Contracted share of observed spend, or None when it cannot be measured."""
        if self.contracted_spend_sek is None or not self.ledger_total_sek:
            return None
        return self.contracted_spend_sek / self.ledger_total_sek

    @property
    def zero_calloff_rate(self) -> float | None:
        """Share of suppliers with a live contract that were paid nothing."""
        if self.zero_calloff is None or not self.active_suppliers:
            return None
        return self.zero_calloff / self.active_suppliers

    @property
    def measurable(self) -> bool:
        """True when both halves of the pair are stored for this buyer."""
        return self.ledger_window is not None and self.contract_rows > 0


_NO_ORGNR = "Katalogen saknar organisationsnummer, så inga rader kan matchas mot en reskontra."
_CATALOGUE_PARTIAL = (
    "En avtalskatalog är inte en folkräkning: kommunen kan ha avtal som databasen "
    "aldrig innehöll (entreprenad, direktupphandling, avrop via inköpscentral). "
    "Spend utanför katalogen är därför inte bevis på avtalslöst inköp."
)
_LEDGER_WINDOW = (
    "Reskontran täcker {lo} till {hi}. Avtal utanför det fönstret räknas inte som "
    "utan avrop, och avtalstroheten gäller bara den perioden."
)
_SHORT_WINDOW = (
    "Reskontran täcker {n} månad(er), färre än {floor}. Andelen leverantörer utan "
    "avrop redovisas inte: i ett så kort fönster fakturerar de flesta leverantörer "
    "ingenting oavsett hur avtalet används."
)


def _fetch_contracts(conn) -> dict[str, list[tuple]]:
    rows = conn.execute(
        "SELECT buyer_org, supplier_orgnr, supplier_name, start_date, end_date, cap_value_sek "
        "FROM municipal_contracts"
    ).fetchall()
    grouped: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(tuple(row[1:]))
    return grouped


def _fetch_payments(conn) -> dict[str, list[tuple]]:
    """The ledger rows this module is allowed to use as a denominator.

    Only `source = 'foia'`. Module 4's `open_data` rows are deliberately
    filtered down to suppliers who won a TED framework before they are stored,
    so every one of them is contracted by construction — dividing by them would
    report an avtalstrohet near 100 % for any municipality with an open ledger.
    A share of spend needs the whole ledger or none of it.
    """
    rows = conn.execute(
        "SELECT payer_org, supplier_orgnr, supplier_name, amount_sek, period_year, period_month "
        "FROM supplier_payments WHERE source = ?",
        (SOURCE_FOIA,),
    ).fetchall()
    grouped: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(tuple(row[1:]))
    return grouped


def _key(orgnr: str | None, name: str) -> str:
    return normalize_orgnr(orgnr) or " ".join((name or "").split()).casefold()


def load_kommuner(conn) -> list[Kommun]:
    """Every municipality with a catalogue or a ledger stored, biggest ledger first."""
    contracts = _fetch_contracts(conn)
    payments = _fetch_payments(conn)
    out = []
    for buyer in sorted(set(contracts) | set(payments)):
        rows = contracts.get(buyer, [])
        paid = payments.get(buyer, [])
        window = None
        months = {(y, m) for *_, y, m in paid}
        if paid:
            periods = [f"{y:04d}-{m or 1:02d}-01" for *_, y, m in paid]
            window = (min(periods), max(periods)[:8] + "31")
        total = sum(amount for _, _, amount, _, _ in paid)
        by_supplier: dict[str, int] = defaultdict(int)
        for orgnr, name, amount, _, _ in paid:
            by_supplier[_key(orgnr, name)] += amount

        keys = {_key(orgnr, name) for orgnr, name, _, _, _ in rows}
        active = [r for r in rows if window and overlaps(r[2], r[3], window)]
        active_keys = {_key(orgnr, name) for orgnr, name, _, _, _ in active}
        has_orgnr = any(orgnr for orgnr, *_ in rows)
        values = [r[4] for r in rows if r[4]]

        contracted = zero = None
        caveats: list[str] = []
        if rows and window and has_orgnr:
            contracted = sum(amount for key, amount in by_supplier.items() if key in keys)
            caveats.append(_LEDGER_WINDOW.format(lo=window[0], hi=window[1]))
            caveats.append(_CATALOGUE_PARTIAL)
            if len(months) >= MIN_ZERO_MONTHS:
                zero = sum(1 for key in active_keys if key not in by_supplier)
            else:
                caveats.append(_SHORT_WINDOW.format(n=len(months), floor=MIN_ZERO_MONTHS))
        elif rows and not has_orgnr:
            caveats.append(_NO_ORGNR)

        out.append(
            Kommun(
                buyer_org=buyer,
                contract_rows=len(rows),
                contract_suppliers=len(keys),
                active_contracts=len(active),
                active_suppliers=len(active_keys),
                contracts_with_value=len(values),
                catalogue_value_sek=sum(values) or None,
                ledger_window=window,
                ledger_months=len(months),
                ledger_rows=len(paid),
                ledger_total_sek=total,
                ledger_suppliers=len(by_supplier),
                contracted_spend_sek=contracted,
                zero_calloff=zero,
                caveats=tuple(caveats),
            )
        )
    return sorted(out, key=lambda k: (k.ledger_total_sek, k.contract_rows), reverse=True)


@dataclass(frozen=True, slots=True)
class SupplierRow:
    """One supplier's standing with one municipality."""

    supplier_name: str
    supplier_orgnr: str | None
    contracts: int
    active: bool
    categories: tuple[str, ...]
    earliest_start: str | None
    latest_end: str | None
    rank: int | None
    paid_sek: int
    months_paid: int
    fields: dict[str, object] = field(default_factory=dict)


def load_suppliers(conn, buyer_org: str, limit: int | None = None) -> list[SupplierRow]:
    """Every supplier a municipality has a contract with or has paid, biggest paid first.

    The rows with a contract and no payment are the point of the table, so they
    are kept rather than filtered out, and `paid_sek` is 0 for them.
    """
    window_rows = conn.execute(
        "SELECT MIN(period_year), MIN(period_month), MAX(period_year), MAX(period_month) "
        "FROM supplier_payments WHERE payer_org = ? AND source = ?",
        (buyer_org, SOURCE_FOIA),
    ).fetchone()
    window = None
    if window_rows and window_rows[0]:
        window = (
            f"{window_rows[0]:04d}-{window_rows[1] or 1:02d}-01",
            f"{window_rows[2]:04d}-{window_rows[3] or 12:02d}-31",
        )

    merged: dict[str, dict] = {}
    for row in conn.execute(
        "SELECT supplier_orgnr, supplier_name, category, start_date, end_date, rank "
        "FROM municipal_contracts WHERE buyer_org = ?",
        (buyer_org,),
    ):
        key = _key(row[0], row[1])
        entry = merged.setdefault(
            key,
            {
                "name": row[1],
                "orgnr": row[0],
                "contracts": 0,
                "cats": set(),
                "start": None,
                "end": None,
                "rank": None,
                "paid": 0,
                "months": 0,
                "active": False,
            },
        )
        entry["contracts"] += 1
        if row[2]:
            entry["cats"].add(row[2])
        if row[3] and (entry["start"] is None or row[3] < entry["start"]):
            entry["start"] = row[3]
        if entry["end"] is None or (row[4] or "9999") > (entry["end"] or ""):
            entry["end"] = row[4]
        if row[5] and (entry["rank"] is None or row[5] < entry["rank"]):
            entry["rank"] = row[5]
        if window and overlaps(row[3], row[4], window):
            entry["active"] = True

    for row in conn.execute(
        "SELECT supplier_orgnr, supplier_name, SUM(amount_sek), COUNT(*) "
        "FROM supplier_payments WHERE payer_org = ? AND source = ? GROUP BY 1, 2",
        (buyer_org, SOURCE_FOIA),
    ):
        key = _key(row[0], row[1])
        entry = merged.setdefault(
            key,
            {
                "name": row[1],
                "orgnr": row[0],
                "contracts": 0,
                "cats": set(),
                "start": None,
                "end": None,
                "rank": None,
                "paid": 0,
                "months": 0,
                "active": False,
            },
        )
        entry["paid"] += row[2]
        entry["months"] += row[3]
        entry["orgnr"] = entry["orgnr"] or row[0]

    rows = [
        SupplierRow(
            supplier_name=e["name"],
            supplier_orgnr=e["orgnr"],
            contracts=e["contracts"],
            active=e["active"],
            categories=tuple(sorted(e["cats"]))[:3],
            earliest_start=e["start"],
            latest_end=e["end"],
            rank=e["rank"],
            paid_sek=e["paid"],
            months_paid=e["months"],
        )
        for e in merged.values()
    ]
    rows.sort(key=lambda r: (r.paid_sek, r.contracts), reverse=True)
    return rows[:limit] if limit else rows


def expiring(conn, buyer_org: str | None = None, before: str | None = None) -> list[tuple]:
    """Contracts ending on or before a date, soonest first.

    The renewal calendar: a contract's end date is when its incumbent is at
    risk and every other supplier gets a chance, which is the one moment a
    supplier actually acts on.
    """
    sql = (
        "SELECT buyer_org, end_date, title, supplier_name, contract_ref, cap_value_sek "
        "FROM municipal_contracts WHERE end_date IS NOT NULL"
    )
    args: list[object] = []
    if buyer_org:
        sql += " AND buyer_org = ?"
        args.append(buyer_org)
    if before:
        sql += " AND end_date <= ?"
        args.append(before)
    sql += " ORDER BY end_date"
    return [tuple(row) for row in conn.execute(sql, args)]
