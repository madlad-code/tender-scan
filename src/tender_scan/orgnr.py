"""Swedish organisationsnummer: one canonical spelling, one validity rule.

The same organisation arrives spelled four different ways — `5562248012` from
one eForms `CompanyID`, `202100-2742` from the next, `165562248012` from a
register export, `20 21 00 - 2742` from a hand-kept spreadsheet. Payments are
matched to award winners on this identifier, so everything is reduced to
`NNNNNN-NNNN` before it is stored or compared.

A number that fails the Luhn check is not an organisationsnummer. It is
rejected rather than stored as a slightly-wrong join key that would silently
attach one supplier's money to another.
"""

from __future__ import annotations

# The 12-digit form carries a leading century. Organisationsnummer always use
# 16, but exports that run orgnr and personnummer through the same column also
# produce 18/19/20.
_CENTURIES = ("16", "18", "19", "20")

# Everything people put around and between the groups: whitespace (plain,
# non-breaking, thin), hyphen, en dash, and the personnummer-style '+'.
_SEPARATORS = str.maketrans("", "", " \t\r\n\xa0  -–+")


# -- parsing -----------------------------------------------------------------


def _digits(value: str | None) -> str | None:
    """Reduce any accepted spelling to bare ten digits, or None."""
    if not value:
        return None
    cleaned = value.translate(_SEPARATORS)
    if not (cleaned.isascii() and cleaned.isdigit()):
        return None
    if len(cleaned) == 12 and cleaned[:2] in _CENTURIES:
        cleaned = cleaned[2:]
    return cleaned if len(cleaned) == 10 else None


def _luhn_ok(digits: str) -> bool:
    """Luhn checksum over all ten digits, doubling every second one from the left."""
    total = 0
    for index, char in enumerate(digits):
        product = int(char) * (2 if index % 2 == 0 else 1)
        total += product - 9 if product > 9 else product
    return total % 10 == 0


# -- public API --------------------------------------------------------------


def is_valid_orgnr(value: str | None) -> bool:
    """True when the value is ten digits that pass the Luhn check."""
    digits = _digits(value)
    return digits is not None and _luhn_ok(digits)


def normalize_orgnr(value: str | None) -> str | None:
    """Return the orgnr as `NNNNNN-NNNN`, or None when it is not a valid one."""
    digits = _digits(value)
    if digits is None or not _luhn_ok(digits):
        return None
    return f"{digits[:6]}-{digits[6:]}"
