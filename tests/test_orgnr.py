import pytest

from tender_scan.orgnr import is_valid_orgnr, normalize_orgnr

# Real organisationsnummer taken from live TED notices. Every one of these must
# pass: if the checksum rejects one, the implementation is wrong, not the number.
REAL_ORGNR = [
    "5562248012",
    "5563365989",
    "2321000016",
    "2321000024",
    "5568194798",
    "5564480282",
    "5566651831",
    "5592271752",
    "2220001412",
    "202100-2742",
    "202100-2841",
    "559052-2248",
    "5564050770",
]


@pytest.mark.parametrize("value", REAL_ORGNR)
def test_real_orgnr_from_ted_validate(value):
    assert is_valid_orgnr(value)
    assert normalize_orgnr(value) is not None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5562248012", "556224-8012"),
        ("556224-8012", "556224-8012"),
        ("165562248012", "556224-8012"),
        ("16 556224-8012", "556224-8012"),
        ("20 21 00 - 2742", "202100-2742"),
        ("  2021002742  ", "202100-2742"),
        ("202100\xa02742", "202100-2742"),
        ("162021002742", "202100-2742"),
    ],
)
def test_normalize_accepts_every_spelling(value, expected):
    assert normalize_orgnr(value) == expected
    assert is_valid_orgnr(value)


def test_normalize_is_idempotent():
    once = normalize_orgnr("5562248012")
    assert normalize_orgnr(once) == once


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "556224-8013",  # wrong check digit
        "5562248013",
        "2021002743",
        "556224801",  # nine digits
        "55622480123",  # eleven digits
        "1234567890123",
        "55622480AB",
        "Bolaget AB",
        "995562248012",  # twelve digits, but not a century prefix
    ],
)
def test_rejects_anything_that_is_not_an_orgnr(value):
    assert normalize_orgnr(value) is None
    assert is_valid_orgnr(value) is False
