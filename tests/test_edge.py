"""Tests for the contract-versus-spend analyses.

The statistics are checked against values worked out by hand rather than
against the implementation's own output, because a test that agrees with
whatever the code happens to do would have let every one of the bugs these
analyses actually had through: a supplier's spend counted once per contract, a
placement framework reported as a dormant one, an interval that fell outside
[0, 1] at the edges where all the interesting proportions live.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from tender_scan import edge
from tender_scan.records import MunicipalContract, SupplierPayment
from tender_scan.storage import Storage

# -- statistics --------------------------------------------------------------


def test_wilson_stays_inside_the_unit_interval_at_the_edges():
    """Where the normal approximation puts its bounds outside [0, 1]."""
    low, high = edge.wilson(0, 10)
    assert low == 0.0
    assert 0.0 < high < 0.4
    low, high = edge.wilson(10, 10)
    assert high == pytest.approx(1.0)
    assert 0.6 < low < 1.0


def test_wilson_matches_a_hand_worked_value():
    # 5 of 20 at z = 1.959964:
    #   denom  = 1 + z^2/20                       = 1.192074
    #   centre = (0.25 + z^2/40) / denom          = 0.290279
    #   half   = z * sqrt(0.1875/20 + z^2/1600) / denom = 0.178423
    low, high = edge.wilson(5, 20)
    assert low == pytest.approx(0.111857, abs=5e-6)
    assert high == pytest.approx(0.468702, abs=5e-6)


def test_wilson_of_nothing_admits_it_knows_nothing():
    assert edge.wilson(0, 0) == (0.0, 1.0)


def test_proportion_carries_its_denominator_into_its_text():
    assert "n=745" in str(edge.Proportion(237, 745))


def test_proportion_of_an_empty_base_is_zero_not_a_crash():
    assert edge.Proportion(0, 0).rate == 0.0


def test_herfindahl_spans_monopoly_to_atomised():
    assert edge.herfindahl([100]) == pytest.approx(1.0)
    assert edge.herfindahl([25, 25, 25, 25]) == pytest.approx(0.25)
    assert edge.effective_suppliers(0.25) == pytest.approx(4.0)


def test_herfindahl_clamps_a_net_refund_to_no_share():
    """A supplier the municipality got money back from does not hold a negative
    share of the market; they hold none."""
    assert edge.herfindahl([100, -50]) == pytest.approx(1.0)
    assert edge.herfindahl([0, 0]) == 0.0


def test_mann_kendall_finds_a_rising_series_and_forgives_a_flat_one():
    rising = edge.mann_kendall(list(range(12)))
    assert rising.direction == "up"
    assert rising.slope == pytest.approx(1.0)
    assert edge.mann_kendall([5] * 12).direction == "flat"


def test_mann_kendall_refuses_to_call_a_trend_on_three_points():
    assert edge.mann_kendall([1, 5, 9]).direction == "flat"


def test_sens_slope_ignores_a_single_outlier():
    """Least squares would be dragged by the spike; the median of slopes is not."""
    series = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 900]
    assert edge.mann_kendall(series).slope == pytest.approx(1.0, abs=0.2)


# -- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("account", "expected"),
    [
        ("Pensionsutbetaln, förmånsbestämd del", edge.CLASS_TRANSFER),
        ("Arbetsmarknadsförsäkringar enligt avtal (AMF)", edge.CLASS_TRANSFER),
        ("Ersättning till försäkringskassan för personlig assistent", edge.CLASS_TRANSFER),
        ("Bostadsanpassningsbidrag", edge.CLASS_TRANSFER),
        ("Avgift övriga intresseföreningar", edge.CLASS_TRANSFER),
        ("Lokalhyror", edge.CLASS_PREMISES),
        ("Förbrukningsavgifter, VA", edge.CLASS_MONOPOLY),
        ("Övriga avgifter (grundad på taxa eller liknande)", edge.CLASS_MONOPOLY),
        ("Köp av huvudverksamhet, placeringskostnad", edge.CLASS_PLACEMENT),
        ("Livsmedel", edge.CLASS_PROCURABLE),
        ("Städ- och renhållningstjänster", edge.CLASS_PROCURABLE),
        (None, edge.CLASS_UNKNOWN),
        ("", edge.CLASS_UNKNOWN),
    ],
)
def test_classify_puts_each_real_account_where_it_belongs(account, expected):
    assert edge.classify(account) == expected


def test_every_excluded_account_can_say_why():
    """The audit is the defence of the number; a rule with no reason is not one."""
    for account in ("Lokalhyror", "Förbrukningsavgifter, VA", "Pensionsutbetaln, del"):
        assert edge.classification_reason(account)
    assert edge.classification_reason("Livsmedel") is None


@pytest.mark.parametrize(
    ("title", "category", "expected"),
    [
        ("9.10. Enstaka platser i bostad med särskild service, LSS", None,
         edge.CLASS_PLACEMENT),
        ("HVB-hem för vuxna", None, edge.CLASS_PLACEMENT),
        (None, "9. Vård och omsorg", edge.CLASS_PLACEMENT),
        ("Individ- och familjeomsorg", None, edge.CLASS_PLACEMENT),
        ("6.02. IT konsulter", "6. IT och telekom", edge.CLASS_PROCURABLE),
        ("Livsmedel", "4. Livsmedel", edge.CLASS_PROCURABLE),
        (None, None, edge.CLASS_PROCURABLE),
    ],
)
def test_classify_contract_separates_a_queue_from_a_market(title, category, expected):
    assert edge.classify_contract(title, category) == expected


# -- fixtures ----------------------------------------------------------------


def _contract(**kw):
    base = dict(
        buyer_org="Testköping", buyer_orgnr="212000-0001", contract_ref="A-1",
        title="Livsmedel", category="4. Livsmedel", supplier_name="Lev AB",
        supplier_orgnr="556036-0793", start_date="2023-01-01", end_date="2026-12-31",
        rank=1, cap_value_sek=None, source="foia", source_file="test.xlsx",
    )
    return MunicipalContract(**{**base, **kw})


def _payment(**kw):
    base = dict(
        payer_org="Testköping", payer_orgnr="212000-0001", supplier_name="Lev AB",
        supplier_orgnr="556036-0793", amount_sek=1000, period_year=2024,
        period_month=1, source="foia", account="Livsmedel", cost_centre="Kök",
    )
    return SupplierPayment(**{**base, **kw})


@pytest.fixture
def conn(tmp_path):
    with Storage(tmp_path / "t.db") as storage:
        storage.insert_contracts([
            _contract(),
            _contract(supplier_name="Tyst AB", supplier_orgnr="556487-9878",
                      contract_ref="A-2"),
            _contract(supplier_name="Vårdbo AB", supplier_orgnr="556614-8309",
                      contract_ref="A-3", title="9.13. HVB-hem för vuxna",
                      category="9. Vård och omsorg"),
        ])
        storage.insert_payments([
            _payment(period_month=m) for m in range(1, 13)
        ] + [
            _payment(supplier_name="Okänd AB", supplier_orgnr="556016-0680",
                     amount_sek=50_000, account="Livsmedel"),
            _payment(supplier_name="Pensionsbolaget", supplier_orgnr="516401-8508",
                     amount_sek=9_000_000, account="Pensionsutbetaln, del"),
        ])
        yield storage.connection()


# -- coverage ----------------------------------------------------------------


def test_coverage_reports_both_halves_and_the_window(conn):
    cov = edge.coverage(conn, "Testköping")
    assert cov.contract_rows == 3
    assert cov.months == 12
    assert cov.first_period == "2024-01"
    assert cov.measurable


def test_coverage_names_the_blocker_when_a_half_is_missing(conn):
    cov = edge.coverage(conn, "Ingenstans")
    assert not cov.measurable
    assert any("avtalskatalog" in b for b in cov.blockers())
    assert any("reskontra" in b for b in cov.blockers())


# -- dormant -----------------------------------------------------------------


def test_dormant_finds_the_contract_that_earned_nothing(conn):
    report = edge.dormant(conn, "Testköping")
    assert [s.supplier_name for s in report.suppliers] == ["Tyst AB"]
    assert report.contracted == 2  # Lev AB and Tyst AB; Vårdbo is counted apart
    assert report.zero_paid == 1


def test_dormant_holds_the_placement_framework_out_of_the_headline(conn):
    """Zero call-offs on an HVB framework is the framework working, not a finding."""
    report = edge.dormant(conn, "Testköping")
    assert [s.supplier_name for s in report.placement_suppliers] == ["Vårdbo AB"]
    assert report.placement_contracted == 1
    assert "Vårdbo AB" not in [s.supplier_name for s in report.suppliers]


def test_dormant_ignores_a_contract_too_young_to_judge(conn):
    """Six weeks of contract inside a twelve-month ledger says nothing."""
    report = edge.dormant(conn, "Testköping", min_live_months=99)
    assert report.contracted == 0
    assert report.suppliers == []


def test_dormant_always_states_what_it_measured_over(conn):
    report = edge.dormant(conn, "Testköping")
    assert any("organisationsnummer" in c for c in report.caveats)
    assert any("2024" in c for c in report.caveats)


# -- leakage -----------------------------------------------------------------


def test_leakage_separates_spend_without_a_live_contract(conn):
    report = edge.leakage(conn, "Testköping")
    livsmedel = next(c for c in report.categories if c.account == "Livsmedel")
    assert livsmedel.spend_sek == 12_000 + 50_000
    assert livsmedel.on_contract_sek == 12_000
    assert livsmedel.off_contract_sek == 50_000


def test_leakage_keeps_transfers_out_of_the_base(conn):
    """Nine million of pension money would otherwise swamp every real finding."""
    report = edge.leakage(conn, "Testköping")
    assert report.excluded[edge.CLASS_TRANSFER] == 9_000_000
    assert all(c.account != "Pensionsutbetaln, del" for c in report.categories)
    assert report.procurable_sek == 62_000


def test_leakage_will_not_credit_a_contract_that_had_expired(tmp_path):
    """The bug this test exists for: joining on the supplier alone scores a 2026
    payment as covered by a contract that ended in 2024."""
    with Storage(tmp_path / "t.db") as storage:
        storage.insert_contracts([_contract(end_date="2024-06-30")])
        storage.insert_payments([_payment(period_year=2026, period_month=3)])
        report = edge.leakage(storage.connection(), "Testköping")
    livsmedel = next(c for c in report.categories if c.account == "Livsmedel")
    assert livsmedel.on_contract_sek == 0
    assert livsmedel.off_contract_share == 1.0


# -- pipeline ----------------------------------------------------------------


def test_pipeline_counts_a_suppliers_money_once_however_many_contracts(tmp_path):
    """The bug this test exists for: five Attendo contracts each claiming the
    whole of Attendo's spend, and a column total five times the truth."""
    with Storage(tmp_path / "t.db") as storage:
        storage.insert_contracts([
            _contract(contract_ref=f"A-{i}", end_date="2026-11-30") for i in range(5)
        ])
        storage.insert_payments([_payment(period_month=m) for m in range(1, 13)])
        _cov, rows, _caveats = edge.pipeline(
            storage.connection(), "Testköping", today=date(2026, 9, 3)
        )
    assert len(rows) == 1
    assert rows[0].contracts == 5
    assert rows[0].paid_sek == 12_000


def test_pipeline_marks_placements_so_they_can_be_left_out_of_a_total(tmp_path):
    with Storage(tmp_path / "t.db") as storage:
        storage.insert_contracts([
            _contract(end_date="2026-11-30"),
            _contract(contract_ref="A-9", supplier_orgnr="556614-8309",
                      supplier_name="Vårdbo AB", end_date="2026-11-30",
                      category="9. Vård och omsorg"),
        ])
        _cov, rows, _caveats = edge.pipeline(
            storage.connection(), "Testköping", today=date(2026, 9, 3)
        )
    assert {r.cls for r in rows} == {edge.CLASS_PROCURABLE, edge.CLASS_PLACEMENT}


def test_pipeline_annualises_from_the_months_it_actually_saw(tmp_path):
    with Storage(tmp_path / "t.db") as storage:
        storage.insert_contracts([_contract(start_date="2024-01-01", end_date="2026-11-30")])
        storage.insert_payments([_payment(period_month=m) for m in range(1, 7)])
        _cov, rows, _caveats = edge.pipeline(
            storage.connection(), "Testköping", today=date(2026, 9, 3)
        )
    # 6 000 kr seen over a 6-month ledger window -> 12 000 kr a year.
    assert rows[0].observed_months == 6
    assert rows[0].run_rate_year_sek == 12_000


def test_pipeline_horizon_excludes_what_expires_later(conn):
    _cov, rows, _caveats = edge.pipeline(
        conn, "Testköping", within_days=30, today=date(2026, 9, 3)
    )
    assert rows == []


# -- formatting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(8_110_000_000, "8.11 mdr"), (933_000_000, "933.0 mkr"), (12_000, "12 tkr"), (500, "500 kr")],
)
def test_sek_uses_the_precision_the_number_deserves(amount, expected):
    assert edge.sek(amount) == expected


def test_sek_survives_a_credit_note(conn):
    assert edge.sek(-2_500_000) == "-2.5 mkr"


def test_overlap_months_counts_only_what_the_ledger_covers():
    assert edge._overlap_months("2020-01-01", "2030-12-31", "2024-01-01", "2024-12-31") == 12
    assert edge._overlap_months("2024-01-01", "2024-03-31", "2024-01-01", "2024-12-31") == 3
    assert edge._overlap_months("2027-01-01", "2027-12-31", "2024-01-01", "2024-12-31") == 0


def test_benchmark_says_nothing_when_only_one_ledger_names_accounts(conn):
    assert edge.benchmark(conn) == []


def test_connection_is_untouched(conn):
    """Every analysis reads; none writes. A report that mutates the record is a bug."""
    before = conn.execute("SELECT COUNT(*) FROM supplier_payments").fetchone()[0]
    edge.dormant(conn, "Testköping")
    edge.leakage(conn, "Testköping")
    edge.pipeline(conn, "Testköping", today=date(2026, 9, 3))
    assert conn.execute("SELECT COUNT(*) FROM supplier_payments").fetchone()[0] == before
    assert isinstance(conn, sqlite3.Connection)
