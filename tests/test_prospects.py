"""M6 — prospektlista.

Company level only. The test that matters most is the one asserting no contact
details are produced: the spec forbids auto-enrichment from third-party
sources, and a future edit that "helpfully" adds an email column should fail
here rather than ship.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from tender_scan.prospects import (
    CSV_HEADER,
    DEFAULT_MIN_FRAMEWORKS,
    Prospect,
    _best_name,
    _cpv_prefix,
    find,
    to_csv,
)
from tender_scan.records import AwardWinner, FrameworkAgreement
from tender_scan.storage import Storage


def seed(tmp_path: Path) -> Path:
    """Two suppliers on two IT frameworks, one on a single non-IT framework."""
    db = tmp_path / "t.sqlite3"
    frameworks = [
        ("1-2026", "Ramavtal IT-konsulttjänster", "72000000", "Umeå universitet", 5_000_000),
        ("2-2026", "Webbkonsulttjänster", "72212000", "Region Uppsala", 15_000_000),
        ("3-2026", "Möbler", "39000000", "Adda Inköpscentral AB", 690_000_000),
    ]
    winners = [
        AwardWinner("1-2026", "Consid AB", "556599-4307", "LOT-0000", award_date="2026-03-01"),
        AwardWinner("2-2026", "Consid ab", "556599-4307", "LOT-0000", award_date="2026-05-22"),
        AwardWinner("1-2026", "Ensam AB", "556105-2613", "LOT-0000", award_date="2026-01-01"),
        AwardWinner("3-2026", "Consid AB", "556599-4307", "LOT-0000", award_date="2026-07-01"),
        AwardWinner("3-2026", "Utan Orgnr AB", None, "LOT-0000"),
    ]
    with Storage(db) as storage:
        for notice_id, title, cpv, buyer, cap in frameworks:
            storage.upsert_framework(
                FrameworkAgreement(
                    notice_id=notice_id,
                    title=title,
                    buyer_name=buyer,
                    is_framework=True,
                    cpv_main=cpv,
                    cap_value_sek=cap,
                )
            )
        for notice_id in ("1-2026", "2-2026", "3-2026"):
            storage.replace_winners(notice_id, [w for w in winners if w.notice_id == notice_id])
    return db


def prospects_of(db: Path, **kwargs: object) -> list[Prospect]:
    with Storage(db) as storage:
        return find(storage.connection(), **kwargs)  # type: ignore[arg-type]


# -- selection ---------------------------------------------------------------


def test_only_suppliers_on_several_frameworks_are_listed(tmp_path: Path) -> None:
    found = prospects_of(seed(tmp_path), min_frameworks=2)
    assert [p.orgnr for p in found] == ["556599-4307"]
    assert found[0].framework_count == 3


def test_the_threshold_is_inclusive(tmp_path: Path) -> None:
    db = seed(tmp_path)
    assert len(prospects_of(db, min_frameworks=3)) == 1
    assert prospects_of(db, min_frameworks=4) == []


def test_a_cpv_filter_narrows_the_frameworks_counted(tmp_path: Path) -> None:
    """The furniture framework must not count towards an IT prospect list."""
    found = prospects_of(seed(tmp_path), cpv="72000000", min_frameworks=2)
    assert found[0].framework_count == 2
    assert "Möbler" not in " ".join(found[0].framework_titles)


def test_a_supplier_without_an_orgnr_is_not_listed(tmp_path: Path) -> None:
    """The orgnr is the key; a row without one cannot be joined or looked up."""
    found = prospects_of(seed(tmp_path), min_frameworks=1)
    assert all(p.orgnr for p in found)
    assert "Utan Orgnr AB" not in {p.name for p in found}


def test_the_default_threshold_is_two() -> None:
    assert DEFAULT_MIN_FRAMEWORKS == 2


# -- fields ------------------------------------------------------------------


def test_the_latest_award_date_is_reported(tmp_path: Path) -> None:
    found = prospects_of(seed(tmp_path), min_frameworks=2)
    assert found[0].latest_award_date == "2026-07-01"


def test_the_ceiling_sum_only_counts_published_ceilings(tmp_path: Path) -> None:
    found = prospects_of(seed(tmp_path), cpv="72*", min_frameworks=2)
    assert found[0].total_cap_sek == 20_000_000


def test_buyers_and_titles_are_carried_through(tmp_path: Path) -> None:
    found = prospects_of(seed(tmp_path), cpv="72*", min_frameworks=2)
    assert set(found[0].buyers) == {"Umeå universitet", "Region Uppsala"}
    assert set(found[0].framework_titles) == {
        "Ramavtal IT-konsulttjänster",
        "Webbkonsulttjänster",
    }


def test_the_best_spelling_of_the_company_name_is_chosen(tmp_path: Path) -> None:
    """The same company is spelled several ways across notices."""
    assert prospects_of(seed(tmp_path), min_frameworks=2)[0].name == "Consid AB"
    assert _best_name(["ATEA SVERIGE AB", "Atea Sverige AB"]) == "Atea Sverige AB"
    assert _best_name([]) == ""


# -- cpv prefixes ------------------------------------------------------------


@pytest.mark.parametrize(
    ("cpv", "prefix"),
    [
        ("72*", "72"),
        ("72000000", "72"),
        ("72212000", "72212"),
        ("70000000", "70"),  # never narrowed to a single digit
        ("", None),
        (None, None),
        ("*", None),
    ],
)
def test_cpv_prefixes(cpv: str | None, prefix: str | None) -> None:
    assert _cpv_prefix(cpv) == prefix


# -- csv ---------------------------------------------------------------------


def test_csv_has_the_columns_the_spec_asks_for(tmp_path: Path) -> None:
    rows = list(csv.DictReader(io.StringIO(to_csv(prospects_of(seed(tmp_path))))))
    assert list(rows[0]) == list(CSV_HEADER)
    assert rows[0]["orgnr"] == "556599-4307"
    assert rows[0]["antal_ramavtal"] == "3"


def test_csv_carries_no_contact_details(tmp_path: Path) -> None:
    """The spec forbids auto-enrichment from third-party sources."""
    text = to_csv(prospects_of(seed(tmp_path)))
    forbidden = ("epost", "e-post", "email", "telefon", "phone", "adress", "kontakt")
    assert not any(word in CSV_HEADER_TEXT for word in forbidden), CSV_HEADER
    assert "@" not in text


CSV_HEADER_TEXT = " ".join(CSV_HEADER).casefold()


def test_csv_is_empty_but_valid_when_nothing_qualifies(tmp_path: Path) -> None:
    text = to_csv(prospects_of(seed(tmp_path), min_frameworks=99))
    assert text.strip() == ",".join(CSV_HEADER)


def test_csv_quotes_the_pipe_joined_titles(tmp_path: Path) -> None:
    rows = list(csv.DictReader(io.StringIO(to_csv(prospects_of(seed(tmp_path))))))
    assert " | " in rows[0]["ramavtalstitlar"]
