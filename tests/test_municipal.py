"""M7 — the municipal catalogue/ledger pair and the rules it must not break."""

from __future__ import annotations

import io

import openpyxl
import pytest

from tender_scan import municipal, web
from tender_scan.records import MunicipalContract, SupplierPayment
from tender_scan.storage import Storage

# -- small parsers -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-01-31 00:00:00", "2024-01-31"),
        (20241017, "2024-10-17"),
        ("2019-06-01 - 2026-09-30", "2019-06-01"),
        ("", None),
        (None, None),
        ("hösten 2024", None),
        ("2024-02-31", None),
    ],
)
def test_parse_iso_date(value, expected):
    assert municipal.parse_iso_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3, 3),
        ("2", 2),
        ("Rangordnat avtal Rang:3 Gräns då konkurrensutsättning inträder 1000000 kr", 3),
        ("Ramavtal och enstaka köp", None),
        ("", None),
        (0, None),
    ],
)
def test_parse_rank(value, expected):
    assert municipal.parse_rank(value) == expected


def test_clean_drops_the_exporters_filler():
    assert municipal.clean("0.0") is None
    assert municipal.clean("E3. Tekniska konsulter_x000D_ Konsultuppdrag") == (
        "E3. Tekniska konsulter Konsultuppdrag"
    )


def test_overlaps_treats_an_open_term_as_running():
    window = ("2024-10-01", "2026-08-31")
    assert municipal.overlaps("2020-01-01", None, window)
    assert municipal.overlaps(None, "2025-01-01", window)
    assert not municipal.overlaps("2019-01-01", "2024-09-30", window)
    assert not municipal.overlaps("2026-09-01", "2030-01-01", window)


# -- readers -----------------------------------------------------------------


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


GOTEBORG_HEADER = [
    "Avtalsnummer_Original",
    "Leverantörsnamn_Original",
    "Leverantör_Organisationsnummer_Original",
    "Avtalstyp",
    "Beställningsgrupp",
    "Delområden",
    "Startdatum_Avtal",
    "Slutdatum_Avtal",
    "Slutdatum_Avtal_Max",
    "Avtalsförlängning_Avtal",
    "Rangordning",
]


def test_read_goteborg_keeps_rank_and_term():
    blob = _xlsx(
        {
            "Blad1": [
                GOTEBORG_HEADER,
                [
                    "IK17157-02",
                    "Recover AB",
                    "556530-9233",
                    "Ramavtal Göteborgs Stad",
                    "Högtrycksspolning",
                    "Göteborg - Slamsugning",
                    "2019-01-21 00:00:00",
                    "2023-01-20 00:00:00",
                    None,
                    None,
                    1,
                ],
                [None] * 11,
            ]
        }
    )
    rows = municipal.read_goteborg(blob)
    assert len(rows) == 1
    assert rows[0].buyer_org == "Göteborgs Stad"
    assert rows[0].supplier_orgnr == "556530-9233"
    assert rows[0].rank == 1
    assert (rows[0].start_date, rows[0].end_date) == ("2019-01-21", "2023-01-20")


def test_read_huddinge_reads_both_the_live_and_the_expired_sheet():
    header = [
        "Diarie",
        "Kategori",
        "Varugrupp",
        "Undergrupp",
        "Fr.o.m.",
        "T.o.m.",
        "Leverantör",
        "Orgnr",
    ]
    blob = _xlsx(
        {
            "Blad1": [
                header,
                [
                    "UPP-1",
                    "2. Entreprenad",
                    "Tekniska konsulter",
                    "E3",
                    "2024-09-02",
                    "2026-08-31",
                    "ÅF-Infrastructure AB",
                    "556185-2103",
                ],
            ],
            "Blad2": [
                header,
                [
                    "UPP-0",
                    "Vård och omsorg",
                    "Jourhem",
                    "x",
                    "2019-01-07",
                    "2023-01-05",
                    "Stockholms Stadsmission",
                    "802003-1954",
                ],
            ],
        }
    )
    rows = municipal.read_huddinge(blob)
    assert [r.supplier_name for r in rows] == ["ÅF-Infrastructure AB", "Stockholms Stadsmission"]
    assert all(r.buyer_org == "Huddinge kommun" for r in rows)


def test_read_grastorp_splits_the_free_text_period():
    blob = _xlsx(
        {
            "Blad2": [
                ["Mercell Commerce - uttaget 20260616", None, None, None],
                ["Avtal", "Leverantör", "Avtalstyp", "Avtalsperiod"],
                [
                    "Avfallshämtning",
                    "Ragn-Sells KommunPartner AB",
                    "Ramavtal",
                    "2019-06-01 - 2026-09-30",
                ],
            ]
        }
    )
    rows = municipal.read_grastorp(blob)
    assert (rows[0].start_date, rows[0].end_date) == ("2019-06-01", "2026-09-30")
    assert rows[0].supplier_orgnr is None  # the export has no orgnr column at all


def test_a_missing_column_names_itself_rather_than_raising_a_keyerror():
    blob = _xlsx({"Blad1": [["Avtalsnummer_Original", "Leverantörsnamn_Original"], ["a", "b"]]})
    with pytest.raises(municipal.ReaderError, match="Göteborg: missing column"):
        municipal.read_goteborg(blob)


BORAS_HEADER = [
    "kopare_id",
    "kopare",
    "verifikationsnummer",
    "leverantor",
    "leverantor_id",
    "konto_nr",
    "konto_text",
    "belopp",
    "datum",
    "forvaltning",
]


def _boras_row(supplier, orgnr, amount, when):
    return [
        2120001561,
        "BORÅS STAD",
        1,
        supplier,
        orgnr,
        5510,
        "Livsmedel",
        amount,
        when,
        "Grundskolenämnden",
    ]


def test_read_boras_aggregates_by_month_and_names_the_buyer_itself():
    blob = _xlsx(
        {
            "Blad1": [
                BORAS_HEADER,
                _boras_row("Menigo Foodservice AB", "5560444647", 1000.4, "2025-01-05 00:00:00"),
                _boras_row("Menigo Foodservice AB", "5560444647", 500.6, "2025-01-20 00:00:00"),
                _boras_row("Menigo Foodservice AB", "5560444647", 250, "2025-02-01 00:00:00"),
            ]
        }
    )
    rows = municipal.read_boras(blob)
    assert [(r.period_year, r.period_month, r.amount_sek) for r in rows] == [
        (2025, 1, 1501),
        (2025, 2, 250),
    ]
    # Not "BORÅS STAD": a payer that spells itself differently from its own
    # catalogue is a different municipality to every join downstream.
    assert {r.payer_org for r in rows} == {"Borås Stad"}
    assert {r.payer_orgnr for r in rows} == {"212000-1561"}
    assert {r.source for r in rows} == {municipal.SOURCE_FOIA}


def test_read_boras_drops_the_rows_redacted_for_personal_data():
    blob = _xlsx(
        {
            "Blad1": [
                BORAS_HEADER,
                _boras_row("[Kan innehålla personuppgifter]", 0, -4000, "2023-12-01 00:00:00"),
                _boras_row("Atea Sverige AB", "5564480282", 4000, "2023-12-01 00:00:00"),
            ]
        }
    )
    rows = municipal.read_boras(blob)
    assert [r.supplier_name for r in rows] == ["Atea Sverige AB"]


def test_read_bjurholm_ledger_dates_a_row_by_its_invoice_date():
    header = [
        "Utbet.enhet",
        "Organisationsnr",
        "Fakturabelopp",
        "Levnamn",
        "Fakturadatum",
        "Betalningsdatum",
    ]
    blob = _xlsx(
        {
            "Sheet0": [
                header,
                [12, "5564480282", 1500, "ATEA SVERIGE AB", 20260115, 20260220],
            ]
        }
    )
    rows = municipal.read_bjurholm_ledger(blob)
    assert (rows[0].period_year, rows[0].period_month) == (2026, 1)
    assert rows[0].payer_org == "Bjurholms kommun"


def test_the_jonkoping_pdf_row_shape_keeps_the_contract_value():
    line = (
        "Datorer med tillhörande tjänster 2021 21/44 Peter Strandsäter "
        "2021-12-01 00:00 2026-12-01 00:00 Atea Sverige AB 160000000"
    )
    match = municipal._PDF_ROW.match(line)
    assert match is not None
    assert match.group("ref") == "21/44"
    assert municipal.parse_int_sek(match.group("value")) == 160_000_000


# -- storage and the view ----------------------------------------------------


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "t.db")


def _contract(**kwargs):
    base = dict(
        buyer_org="Testköping",
        supplier_name="Alfa AB",
        supplier_orgnr="556448-0282",
        contract_ref="UPP-1",
        start_date="2024-01-01",
        end_date="2027-12-31",
    )
    return MunicipalContract(**{**base, **kwargs})


def _payment(month, amount, **kwargs):
    base = dict(
        payer_org="Testköping",
        payer_orgnr=None,
        supplier_name="Alfa AB",
        supplier_orgnr="556448-0282",
        amount_sek=amount,
        period_year=2025,
        period_month=month,
        source=municipal.SOURCE_FOIA,
    )
    return SupplierPayment(**{**base, **kwargs})


def test_reingesting_the_same_catalogue_adds_nothing(db):
    with Storage(db) as storage:
        assert storage.insert_contracts([_contract()]) == 1
        assert storage.insert_contracts([_contract(supplier_orgnr="5564480282")]) == 0


def test_a_ranked_framework_keeps_one_row_per_supplier(db):
    with Storage(db) as storage:
        added = storage.insert_contracts(
            [
                _contract(supplier_name="Alfa AB", supplier_orgnr="556448-0282", rank=1),
                _contract(supplier_name="Beta AB", supplier_orgnr="556033-9086", rank=2),
            ]
        )
    assert added == 2


def test_no_avtalstrohet_without_a_ledger(db):
    with Storage(db) as storage:
        storage.insert_contracts([_contract()])
        (kommun,) = municipal.load_kommuner(storage.connection())
    assert kommun.avtalstrohet is None
    assert kommun.zero_calloff is None
    assert kommun.measurable is False


def test_avtalstrohet_is_the_contracted_share_of_the_ledger(db):
    with Storage(db) as storage:
        storage.insert_contracts([_contract()])
        storage.insert_payments(
            [_payment(month, 100) for month in range(1, 13)]
            + [
                _payment(1, 300, supplier_name="Okänd AB", supplier_orgnr="556999-9999"),
            ]
        )
        (kommun,) = municipal.load_kommuner(storage.connection())
    assert kommun.ledger_total_sek == 1500
    assert kommun.contracted_spend_sek == 1200
    assert kommun.avtalstrohet == pytest.approx(0.8)


def test_zero_calloff_needs_a_year_of_ledger(db):
    contracts = [_contract(), _contract(supplier_name="Tyst AB", supplier_orgnr="556033-9086")]
    with Storage(db) as storage:
        storage.insert_contracts(contracts)
        storage.insert_payments([_payment(1, 100)])
        (short,) = municipal.load_kommuner(storage.connection())
        assert short.zero_calloff is None
        assert any("färre än" in c for c in short.caveats)

        storage.insert_payments([_payment(month, 100) for month in range(2, 13)])
        (full,) = municipal.load_kommuner(storage.connection())
    assert full.ledger_months == 12
    assert full.zero_calloff == 1  # Tyst AB has a live contract and no payment
    assert full.zero_calloff_rate == pytest.approx(0.5)


def test_a_contract_that_expired_before_the_ledger_is_not_counted_as_silent(db):
    with Storage(db) as storage:
        storage.insert_contracts(
            [
                _contract(),
                _contract(
                    supplier_name="Gammal AB",
                    supplier_orgnr="556033-9086",
                    start_date="2018-01-01",
                    end_date="2020-12-31",
                ),
            ]
        )
        storage.insert_payments([_payment(month, 100) for month in range(1, 13)])
        (kommun,) = municipal.load_kommuner(storage.connection())
    assert kommun.contract_suppliers == 2
    assert kommun.active_suppliers == 1
    assert kommun.zero_calloff == 0


def test_open_data_rows_are_never_a_denominator(db):
    """Module 4 stores only framework winners, so dividing by them reports ~100 %."""
    with Storage(db) as storage:
        storage.insert_contracts([_contract()])
        storage.insert_payments(
            [_payment(month, 100, source="open_data") for month in range(1, 13)]
        )
        (kommun,) = municipal.load_kommuner(storage.connection())
    assert kommun.ledger_total_sek == 0
    assert kommun.avtalstrohet is None


def test_a_catalogue_without_orgnr_says_so_instead_of_matching_on_names(db):
    with Storage(db) as storage:
        storage.insert_contracts([_contract(supplier_orgnr=None)])
        storage.insert_payments([_payment(month, 100) for month in range(1, 13)])
        (kommun,) = municipal.load_kommuner(storage.connection())
    assert kommun.avtalstrohet is None
    assert any("organisationsnummer" in c for c in kommun.caveats)


def test_load_suppliers_keeps_the_contracts_with_no_payment(db):
    with Storage(db) as storage:
        storage.insert_contracts(
            [_contract(), _contract(supplier_name="Tyst AB", supplier_orgnr="556033-9086")]
        )
        storage.insert_payments([_payment(1, 500)])
        rows = municipal.load_suppliers(storage.connection(), "Testköping")
    assert [(r.supplier_name, r.paid_sek) for r in rows] == [("Alfa AB", 500), ("Tyst AB", 0)]


def test_expiring_lists_the_renewal_calendar(db):
    with Storage(db) as storage:
        storage.insert_contracts(
            [
                _contract(end_date="2027-12-31"),
                _contract(
                    supplier_name="Beta AB", supplier_orgnr="556033-9086", end_date="2026-03-01"
                ),
            ]
        )
        rows = municipal.expiring(storage.connection(), "Testköping", before="2026-12-31")
    assert [r[1] for r in rows] == ["2026-03-01"]


# -- the web pages inherit the rule ------------------------------------------


def test_the_kommun_table_never_prints_a_rate_without_its_window(db):
    with Storage(db) as storage:
        storage.insert_contracts([_contract()])
        storage.insert_payments([_payment(month, 100) for month in range(1, 13)])
        rows = municipal.load_kommuner(storage.connection())
        page = web.render_kommuner(rows)
    assert "2025-01 – 2025-12" in page
    assert "Avtalstrohet" in page
    # A municipality with a catalogue and no ledger must show a dash, never a
    # rate divided by nothing.
    with Storage(db) as storage:
        storage.insert_contracts([_contract(buyer_org="Tomköping")])
        rendered = web.render_kommuner(municipal.load_kommuner(storage.connection()))
    assert "Tomköping" in rendered
    assert rendered.count("–") >= 2


def test_a_kommun_page_carries_every_caveat_the_view_produced(db):
    with Storage(db) as storage:
        storage.insert_contracts([_contract()])
        storage.insert_payments([_payment(1, 100)])
        (kommun,) = municipal.load_kommuner(storage.connection())
        page = web.render_kommun(
            kommun, municipal.load_suppliers(storage.connection(), "Testköping")
        )
    for caveat in kommun.caveats:
        assert caveat[:40] in page


def test_an_unknown_municipality_is_a_404_not_an_empty_page(db):
    with Storage(db) as storage:
        assert web.route(storage, "/kommun/Finns%20Inte") is None
