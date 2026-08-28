"""M5 — utnyttjandegrad.

The invariant this module exists to protect is that a utilisation percentage
never appears without the coverage caveat beside it. That is asserted by regex
over the rendered output rather than left to review, because it is exactly the
kind of thing an edit two months from now would quietly break.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from tender_scan.records import AwardWinner, FrameworkAgreement, SupplierPayment
from tender_scan.storage import Storage
from tender_scan.utilization import (
    MissingSource,
    Sourced,
    Utilization,
    framework_winners,
    load,
    load_all,
    months_between,
    payment_sources,
    pct,
    render_html,
    render_markdown,
    sek,
)

BUYER = "212000-1355"
SUPPLIER = "556599-4307"


def build(
    tmp_path: Path,
    *,
    cap: int | None = 5_000_000,
    cap_confidence: float | None = 0.95,
    start: str | None = "2025-03-01",
    end: str | None = "2029-02-28",
    months: int | None = 47,
    is_cpb: bool = False,
    buyers: list[tuple[str, str | None]] | None = None,
    payments: list[tuple[str, int, int, int | None]] | None = None,
    winners: list[AwardWinner] | None = None,
) -> Path:
    """A database holding one framework, its buyers, winners and payments.

    `payments` entries are (payer_orgnr, amount, year, month).
    """
    db = tmp_path / "t.sqlite3"
    with Storage(db) as storage:
        storage.upsert_framework(
            FrameworkAgreement(
                notice_id="1-2026",
                buyer_name="Göteborgs Stad",
                buyer_orgnr=BUYER,
                title="Ramavtal kommunikationstjänster",
                is_framework=True,
                cap_value_sek=cap,
                estimated_value_sek=4_000_000,
                cap_source="eforms_field" if cap else None,
                cap_confidence=cap_confidence if cap else None,
                start_date=start,
                end_date=end,
                max_duration_months=months,
                buyer_is_cpb=is_cpb,
                raw_excerpt="BT-118 OverallMaximumFrameworkContractsAmount = 5 000 000 SEK",
            )
        )
        storage.replace_framework_buyers(
            "1-2026", buyers if buyers is not None else [(BUYER, "Göteborgs Stad")]
        )
        storage.replace_winners(
            "1-2026",
            winners
            if winners is not None
            else [AwardWinner("1-2026", "Consid AB", SUPPLIER, "LOT-0000", rank=1)],
        )
        storage.insert_payments(
            [
                SupplierPayment(
                    payer_org="Göteborgs Stad",
                    payer_orgnr=payer,
                    supplier_name="Consid AB",
                    supplier_orgnr=SUPPLIER,
                    amount_sek=amount,
                    period_year=year,
                    period_month=month,
                    source="open_data",
                    source_url="https://catalog.goteborg.se/store/6/resource/129628",
                )
                for payer, amount, year, month in (payments or [])
            ]
        )
    return db


def read(db: Path, **kwargs: object) -> Utilization:
    with Storage(db) as storage:
        found = load(storage.connection(), "1-2026", today=kwargs.get("today"))  # type: ignore[arg-type]
    assert found is not None
    return found


def report(db: Path, **kwargs: object) -> str:
    with Storage(db) as storage:
        conn = storage.connection()
        data = load(conn, "1-2026", today=kwargs.get("today"))  # type: ignore[arg-type]
        assert data is not None
        return render_markdown(
            data,
            payment_sources(conn, "1-2026"),
            framework_winners(conn, "1-2026"),
            generated=date(2026, 8, 28),
        )


# -- the invariant -----------------------------------------------------------

# A percentage that is not immediately followed by a coverage statement.
_RATE = re.compile(r"utnyttjandegrad(?:en)?[^.\n]*?(\d+[.,]\d%)", re.IGNORECASE)


def test_a_rendered_report_never_states_a_rate_without_coverage(tmp_path: Path) -> None:
    text = report(build(tmp_path, payments=[(BUYER, 1_896_813, 2026, 7)]), today=date(2026, 8, 28))
    for paragraph in text.split("\n\n"):
        if _RATE.search(paragraph):
            assert "undre gräns" in paragraph, paragraph
            assert "täckningsgrad" in paragraph.casefold(), paragraph


def test_the_coverage_section_is_always_present(tmp_path: Path) -> None:
    assert "## Täckningsgrad" in report(build(tmp_path))


def test_method_limitations_are_present_even_when_the_data_looks_good(
    tmp_path: Path,
) -> None:
    text = report(build(tmp_path, payments=[(BUYER, 4_900_000, 2026, 7)]), today=date(2026, 8, 28))
    assert "## Metodbegränsningar" in text
    assert "undre gräns, inte en mätning" in text


# -- the payer condition -----------------------------------------------------


def test_a_payment_from_an_unrelated_buyer_is_not_counted(tmp_path: Path) -> None:
    """VGR paying a supplier who happens to sit on Göteborg's framework is not
    a call-off on it. Dropping this condition multiplies observed spend."""
    db = build(tmp_path, payments=[("232100-0131", 9_000_000, 2026, 7)])
    assert read(db, today=date(2026, 8, 28)).observed_spend_sek == 0


def test_a_payment_from_a_named_buyer_is_counted(tmp_path: Path) -> None:
    db = build(tmp_path, payments=[(BUYER, 1_896_813, 2026, 7)])
    assert read(db, today=date(2026, 8, 28)).observed_spend_sek == 1_896_813


def test_a_payment_outside_the_agreement_period_is_not_counted(tmp_path: Path) -> None:
    db = build(
        tmp_path,
        start="2027-02-01",
        end="2031-01-31",
        payments=[(BUYER, 1_192_351, 2026, 1)],
    )
    assert read(db, today=date(2026, 8, 28)).observed_spend_sek == 0


def test_a_payment_is_counted_when_the_period_is_unknown(tmp_path: Path) -> None:
    """With no dates published there is nothing to exclude on."""
    db = build(tmp_path, start=None, end=None, months=None, payments=[(BUYER, 500_000, 2020, 1)])
    assert read(db, today=date(2026, 8, 28)).observed_spend_sek == 500_000


def test_a_payment_to_a_supplier_not_on_the_framework_is_not_counted(tmp_path: Path) -> None:
    db = build(
        tmp_path,
        winners=[AwardWinner("1-2026", "Annan AB", "556105-2613", "LOT-0000")],
        payments=[(BUYER, 800_000, 2026, 7)],
    )
    assert read(db, today=date(2026, 8, 28)).observed_spend_sek == 0


# -- coverage ----------------------------------------------------------------


def test_coverage_is_null_for_a_central_purchasing_body(tmp_path: Path) -> None:
    db = build(tmp_path, is_cpb=True, payments=[(BUYER, 500_000, 2026, 7)])
    data = read(db, today=date(2026, 8, 28))
    assert data.coverage_ratio is None
    text = report(db, today=date(2026, 8, 28))
    assert "Nämnaren är okänd" in text
    assert "inköpscentral" in text


def test_coverage_counts_every_buyer_the_notice_names(tmp_path: Path) -> None:
    db = build(
        tmp_path,
        buyers=[(BUYER, "Göteborgs Stad"), ("232100-0131", "VGR"), ("212000-2080", "Västerås")],
        payments=[(BUYER, 500_000, 2026, 7)],
    )
    data = read(db, today=date(2026, 8, 28))
    assert data.named_buyers == 3
    assert data.paying_buyers == 1
    assert data.coverage_ratio == pytest.approx(1 / 3)
    assert "1 av 3" in report(db, today=date(2026, 8, 28))


def test_period_coverage_is_reported_alongside_buyer_coverage(tmp_path: Path) -> None:
    db = build(tmp_path, payments=[(BUYER, 500_000, 2026, 7)])
    data = read(db, today=date(2026, 8, 28))
    assert data.observed_months == 1
    assert data.months_elapsed == 17
    assert data.period_coverage == pytest.approx(1 / 17)
    assert "1 av 17" in report(db, today=date(2026, 8, 28))


# -- time normalization ------------------------------------------------------


def test_spend_is_compared_against_the_pro_rated_ceiling(tmp_path: Path) -> None:
    """18 of 48 months elapsed is measured against 37.5 % of the ceiling."""
    data = Utilization(
        notice_id="1-2026",
        framework_title="t",
        buyer_name="b",
        cap_value_sek=1_000_000,
        observed_spend_sek=400_000,
        coverage_ratio=1.0,
        utilization_rate=0.4,
        months_elapsed=18,
        months_total=48,
        start_date="2025-01-01",
        end_date="2028-12-31",
        cap_source="eforms_field",
        cap_confidence=0.95,
        buyer_is_cpb=False,
        raw_excerpt="x",
        named_buyers=1,
        paying_buyers=1,
        paid_suppliers=1,
        observed_months=18,
        payment_rows=18,
    )
    assert data.elapsed_share == pytest.approx(0.375)
    assert data.expected_spend_sek == 375_000
    assert data.utilization_rate == pytest.approx(0.40)
    assert data.time_normalized_rate == pytest.approx(400_000 / 375_000)


def test_both_the_raw_and_the_normalized_figures_appear(tmp_path: Path) -> None:
    text = report(build(tmp_path, payments=[(BUYER, 1_896_813, 2026, 7)]), today=date(2026, 8, 28))
    assert "37.9%" in text  # raw: 1 896 813 / 5 000 000
    assert "36.2%" in text  # elapsed share: 17 of 47 months
    assert "Tidsnormaliserat" in text


def test_an_agreement_that_has_not_started_is_not_reported_as_zero_percent(
    tmp_path: Path,
) -> None:
    text = report(build(tmp_path, start="2027-02-01", end="2031-01-31"), today=date(2026, 8, 28))
    assert "har ännu inte" in text
    assert "Tidsnormaliserat" not in text


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ((2025, 1, 1), (2026, 1, 1), 12),
        ((2025, 1, 15), (2026, 1, 14), 11),
        ((2025, 1, 1), (2025, 1, 31), 0),
        ((2025, 3, 1), (2025, 1, 1), 0),
    ],
)
def test_months_between_rounds_down(
    start: tuple[int, int, int], end: tuple[int, int, int], expected: int
) -> None:
    assert months_between(date(*start), date(*end)) == expected


# -- missing ceiling ---------------------------------------------------------


def test_a_framework_with_no_ceiling_still_renders(tmp_path: Path) -> None:
    db = build(tmp_path, cap=None, cap_confidence=None, payments=[(BUYER, 500_000, 2026, 7)])
    data = read(db, today=date(2026, 8, 28))
    assert data.utilization_rate is None
    text = report(db, today=date(2026, 8, 28))
    assert "Ingen takvolym är publicerad" in text
    assert "500 000 SEK" in text


# -- confidence band ---------------------------------------------------------


def test_confidence_band_boundaries(tmp_path: Path) -> None:
    def band(cap_confidence: float, coverage: float | None, period: float) -> str:
        return Utilization(
            notice_id="1",
            framework_title=None,
            buyer_name=None,
            cap_value_sek=100,
            observed_spend_sek=1,
            coverage_ratio=coverage,
            utilization_rate=0.01,
            months_elapsed=100,
            months_total=100,
            start_date=None,
            end_date=None,
            cap_source="eforms_field",
            cap_confidence=cap_confidence,
            buyer_is_cpb=False,
            raw_excerpt=None,
            named_buyers=1,
            paying_buyers=1,
            paid_suppliers=1,
            observed_months=int(period * 100),
            payment_rows=1,
        ).confidence_band

    assert band(0.90, 0.80, 0.80) == "high"
    assert band(0.89, 0.80, 0.80) == "medium"
    assert band(0.90, 0.79, 0.80) == "medium"
    assert band(0.90, 0.80, 0.79) == "medium"
    assert band(0.69, 1.0, 1.0) == "low"
    assert band(0.95, None, 1.0) == "low"
    assert band(0.95, 0.29, 1.0) == "low"
    assert band(0.95, 0.80, 0.29) == "low"


def test_a_weak_ceiling_is_flagged_prominently(tmp_path: Path) -> None:
    text = report(build(tmp_path, cap_confidence=0.54), today=date(2026, 8, 28))
    assert "Varning: takvolymen är svagt belagd" in text
    assert "0.54" in text


def test_a_well_evidenced_ceiling_carries_no_warning(tmp_path: Path) -> None:
    assert "Varning: takvolymen" not in report(build(tmp_path, cap_confidence=0.95))


# -- provenance --------------------------------------------------------------


def test_a_figure_without_a_source_cannot_be_constructed() -> None:
    with pytest.raises(MissingSource):
        Sourced("5 000 000 SEK", "")
    with pytest.raises(MissingSource):
        Sourced("5 000 000 SEK", "   ")


def test_every_ceiling_figure_carries_the_notice_id(tmp_path: Path) -> None:
    text = report(build(tmp_path))
    for line in text.splitlines():
        if line.startswith("| Takvolym |") or line.startswith("| Konfidens |"):
            assert line.rstrip().endswith("1-2026 |")


def test_observed_spend_carries_its_dataset_url(tmp_path: Path) -> None:
    text = report(build(tmp_path, payments=[(BUYER, 500_000, 2026, 7)]), today=date(2026, 8, 28))
    assert "https://catalog.goteborg.se/store/6/resource/129628" in text


def test_a_framework_with_no_payments_says_where_to_go_next(tmp_path: Path) -> None:
    text = report(build(tmp_path))
    assert "offentlighetsprincipen" in text
    assert "betyder inte att inga avrop skett" in text


# -- winners -----------------------------------------------------------------


def test_the_supplier_list_shows_rank_where_published(tmp_path: Path) -> None:
    text = report(
        build(
            tmp_path,
            winners=[
                AwardWinner("1-2026", "Consid AB", SUPPLIER, "LOT-0000", rank=1),
                AwardWinner("1-2026", "Annan AB", "556105-2613", "LOT-0000"),
            ],
        )
    )
    assert "| LOT-0000 | 1 | Consid AB |" in text
    assert "| LOT-0000 | - | Annan AB |" in text
    assert "Rangordning publicerad för 1 av dem" in text


# -- formatting and html -----------------------------------------------------


def test_amounts_are_grouped_with_plain_spaces() -> None:
    assert sek(1_896_813) == "1 896 813 SEK"
    assert sek(None) == "okänt"
    assert pct(None) == "okänd"
    assert pct(0.379) == "37.9%"


def test_html_keeps_every_section_and_escapes_content(tmp_path: Path) -> None:
    db = build(tmp_path, payments=[(BUYER, 500_000, 2026, 7)])
    with Storage(db) as storage:
        conn = storage.connection()
        data = load(conn, "1-2026", today=date(2026, 8, 28))
        assert data is not None
        markdown = render_markdown(
            data, payment_sources(conn, "1-2026"), framework_winners(conn, "1-2026")
        )
    page = render_html(markdown, data)
    assert page.startswith("<!doctype html>")
    for heading in ("Takvolym", "Observerat avrop", "Täckningsgrad", "Metodbegränsningar"):
        assert f"<h2>{heading}</h2>" in page
    assert "<table>" in page
    assert "<script" not in page


# -- the view ----------------------------------------------------------------


def test_the_view_lists_only_frameworks(tmp_path: Path) -> None:
    db = build(tmp_path)
    with Storage(db) as storage:
        storage.upsert_framework(
            FrameworkAgreement(notice_id="2-2026", is_framework=False, cap_value_sek=None)
        )
        rows = load_all(storage.connection(), today=date(2026, 8, 28))
    assert [row.notice_id for row in rows] == ["1-2026"]


def test_the_view_is_created_idempotently(tmp_path: Path) -> None:
    db = build(tmp_path)
    with Storage(db) as storage:
        conn = storage.connection()
        assert load(conn, "1-2026") is not None
        assert load(conn, "1-2026") is not None


def test_an_unknown_notice_returns_none(tmp_path: Path) -> None:
    with Storage(build(tmp_path)) as storage:
        assert load(storage.connection(), "999-2026") is None


def test_a_direct_sqlite_reader_sees_the_same_totals(tmp_path: Path) -> None:
    db = build(tmp_path, payments=[(BUYER, 1_896_813, 2026, 7)])
    with Storage(db) as storage:
        load(storage.connection(), "1-2026", today=date(2026, 8, 28))
    conn = sqlite3.connect(db)
    total = conn.execute("SELECT observed_spend_sek FROM utilization").fetchone()[0]
    assert total == 1_896_813
