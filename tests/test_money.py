"""Amount normalization and ceiling extraction.

The spec calls this out as the place the errors will be, so these tests are
written against the readings a Swedish procurement document actually uses, not
against whatever the implementation happens to do.
"""

from decimal import Decimal

import pytest

from tender_scan.money import (
    CapMatch,
    find_caps,
    parse_amount,
    parse_amount_with_currency,
    to_int_sek,
)

NBSP = " "
NARROW_NBSP = " "
THIN = " "


# -- parse_amount ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4000000", "4000000"),
        ("4 000 000", "4000000"),
        (f"4{NBSP}000{NBSP}000", "4000000"),
        (f"4{NARROW_NBSP}000{NARROW_NBSP}000", "4000000"),
        (f"4{THIN}000{THIN}000", "4000000"),
        ("4.000.000", "4000000"),
        ("1 234 567,89", "1234567.89"),
        ("4,5 mkr", "4500000"),
        ("4.5 MSEK", "4500000"),
        ("4,5 Mkr", "4500000"),
        ("4,5 miljoner kronor", "4500000"),
        ("2 miljoner", "2000000"),
        ("200 tkr", "200000"),
        ("1,2 mdr", "1200000000"),
        ("3 miljarder kr", "3000000000"),
        ("4 000 000 kr", "4000000"),
        ("4 000 000 kronor", "4000000"),
        ("4 000 000:-", "4000000"),
        ("2 500 000 SEK", "2500000"),
        ("  1 000  ", "1000"),
        ("0", "0"),
    ],
)
def test_parse_amount_readings(text: str, expected: str) -> None:
    assert parse_amount(text) == Decimal(expected)


def test_dotted_thousands_and_decimal_point_are_told_apart() -> None:
    """The documented rule: more than one dot-group is a thousands separator."""
    assert parse_amount("4.000.000") == Decimal("4000000")
    assert parse_amount("1.234.567") == Decimal("1234567")
    # A single dot-group is a decimal point, so this is four, not four thousand.
    assert parse_amount("4.000") == Decimal("4")
    assert parse_amount("4.5") == Decimal("4.5")


def test_comma_is_decimal_when_alone_and_thousands_when_repeated() -> None:
    assert parse_amount("4,5") == Decimal("4.5")
    assert parse_amount("1,234,567") == Decimal("1234567")


def test_mixed_separators_use_the_rightmost_as_decimal() -> None:
    assert parse_amount("1.234.567,89") == Decimal("1234567.89")
    assert parse_amount("1,234,567.89") == Decimal("1234567.89")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",
        "1.23.456",  # malformed thousands grouping
        "1.2345.678",
        "4 000 apples",
        "kr 4 000",  # currency first is not a form we accept
        "4 000 000 zzz",
        ",5",
        "4,",
    ],
)
def test_parse_amount_refuses_rather_than_guesses(text: str) -> None:
    assert parse_amount(text) is None


def test_parse_amount_accepts_none() -> None:
    assert parse_amount(None) is None


def test_negative_amounts_survive() -> None:
    """Credit notes in supplier ledgers are negative and are real."""
    assert parse_amount("-1302,03") == Decimal("-1302.03")
    assert parse_amount("−1 500 kr") == Decimal("-1500")


# -- currency ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "currency"),
    [
        ("2 500 000 SEK", "SEK"),
        ("2 500 000 sek", "SEK"),
        ("1 000 EUR", "EUR"),
        ("1 000 euro", "EUR"),
        ("1 000 €", "EUR"),
        ("4 000 000 kr", None),  # "kr" names no ISO currency
        ("4 000 000 kronor", None),
        ("4 000 000", None),
    ],
)
def test_currency_is_read_only_when_stated(text: str, currency: str | None) -> None:
    amount, found = parse_amount_with_currency(text)
    assert amount is not None
    assert found == currency


# -- to_int_sek --------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("4500000", 4500000),
        ("4500000.4", 4500000),
        ("4500000.5", 4500001),
        ("4500000.49", 4500000),
        ("0.5", 1),
        ("-0.5", -1),
        ("-1302.03", -1302),
    ],
)
def test_to_int_sek_rounds_half_up(value: str, expected: int) -> None:
    result = to_int_sek(Decimal(value))
    assert result == expected
    assert isinstance(result, int)


def test_to_int_sek_never_returns_a_float() -> None:
    assert not isinstance(to_int_sek(Decimal("1.5")), float)


# -- find_caps ---------------------------------------------------------------


def only(matches: list[CapMatch]) -> CapMatch:
    assert len(matches) == 1, [(m.pattern, m.amount) for m in matches]
    return matches[0]


def test_takvolym_phrase_yields_the_amount() -> None:
    match = only(find_caps("Takvolymen för avtalet är 4,5 mkr."))
    assert match.amount == Decimal("4500000")
    assert match.pattern == "takvolym"
    assert match.confidence <= 0.60
    assert "Takvolymen" in match.excerpt


@pytest.mark.parametrize(
    "sentence",
    [
        "Takvolym 30 000 000 kr",
        "Takbeloppet är 30 000 000 kr",
        "Taket för avrop är 30 000 000 kr",
        "Avtalets högsta värde är 30 000 000 kr",
        "Det får högst avropas för 30 000 000 kr",
        "Maximalt värde 30 000 000 kr",
        "Maximalt belopp: 30 000 000 kr",
        "Maximal volym 30 000 000 kr",
        "Beräknad maximal volym 30 000 000 kr",
        "Maximalt avropsvärde 30 000 000 kr",
        "Högsta värdet är 30 000 000 kr",
        "The maximum value is SEK 30 000 000",
        "Maximum amount 30 000 000 kr",
        "Overall maximum 30 000 000 kr",
        "Framework maximum value 30 000 000 kr",
        "The ceiling is 30 000 000 kr",
    ],
)
def test_every_required_phrasing_is_covered(sentence: str) -> None:
    matches = find_caps(sentence)
    assert matches, sentence
    assert matches[0].amount == Decimal("30000000")


def test_amount_before_the_phrase_is_still_found() -> None:
    match = only(find_caps("Beloppet 30 000 000 kr utgör avtalets högsta värde."))
    assert match.amount == Decimal("30000000")


def test_estimated_value_is_never_reported_as_a_cap() -> None:
    assert find_caps("Uppskattat värde 24 000 000 kr.") == []
    assert find_caps("Beräknat värde 24 000 000 kr.") == []
    assert find_caps("The estimated value is 24 000 000 kr.") == []
    assert find_caps("Prognosen är 24 000 000 kr.") == []


def test_an_estimate_next_to_a_cap_does_not_contaminate_it() -> None:
    text = "Uppskattat värde 24 000 000 kr. Takvolymen är 30 000 000 kr."
    match = only(find_caps(text))
    assert match.amount == Decimal("30000000")
    assert match.pattern == "takvolym"


def test_amounts_far_from_any_descriptor_are_ignored() -> None:
    text = "Takvolym 30 000 000 kr." + " x" * 200 + " 99 999 kr."
    match = only(find_caps(text))
    assert match.amount == Decimal("30000000")


def test_text_without_a_descriptor_yields_nothing() -> None:
    assert find_caps("Kontraktet omfattar 12 000 000 kr i tjänster.") == []
    assert find_caps("") == []
    assert find_caps(None) == []


def test_results_are_ordered_by_confidence_then_position() -> None:
    text = "Maximalt värde 10 000 000 kr. Takvolymen är 30 000 000 kr."
    matches = find_caps(text)
    assert [m.amount for m in matches] == [Decimal("30000000"), Decimal("10000000")]
    assert matches[0].confidence > matches[1].confidence


def test_excerpt_is_bounded_and_whitespace_collapsed() -> None:
    text = "Takvolym\n\n   30 000 000 kr   " + "y" * 500
    match = only(find_caps(text))
    assert len(match.excerpt) <= 300
    assert "\n" not in match.excerpt
    assert "Takvolym 30 000 000 kr" in match.excerpt


def test_currency_reaches_the_cap_match() -> None:
    match = only(find_caps("Takvolymen är 1 000 000 EUR."))
    assert match.currency == "EUR"
    assert match.amount == Decimal("1000000")


def test_a_lot_number_is_not_read_as_part_of_the_amount() -> None:
    match = only(find_caps("Anbudsområde 2 har en takvolym på 4 000 000 kr."))
    assert match.amount == Decimal("4000000")
