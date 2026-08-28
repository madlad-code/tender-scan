"""Amount normalization and ceiling-phrase extraction from free notice text.

Two jobs, both of them places where quiet errors are expensive:

1. Turn a Swedish (or English) money expression into a `Decimal`. Swedish public
   procurement text writes the same number as `4 000 000`, `4.000.000`, `4,0 mkr`
   and `4 MSEK`, with four different space characters used as thousands
   separators. Getting this wrong by a factor of 1000 is silent and fatal.
2. Find *ceiling* amounts (takvolym) in prose, and refuse to report an
   *estimated* value as a ceiling. The two must never share a column.

Money is `Decimal` throughout this module. The conversion to integer SEK happens
once, at the storage boundary, through `to_int_sek`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = [
    "MULTIPLIERS",
    "CapMatch",
    "find_caps",
    "parse_amount",
    "parse_amount_with_currency",
    "to_int_sek",
]

# Space characters that Swedish publishers use as thousands separators. The
# narrow no-break space (U+202F) and the thin space (U+2009) come out of Word;
# the no-break space (U+00A0) comes out of Excel and out of HTML.
_SPACES = " \t       "
_SPACE_KILL = str.maketrans("", "", _SPACES)

MULTIPLIERS: dict[str, int] = {
    "tkr": 1_000,
    "tsek": 1_000,
    "kkr": 1_000,
    "tusen": 1_000,
    "mkr": 1_000_000,
    "mnkr": 1_000_000,
    "msek": 1_000_000,
    "milj": 1_000_000,
    "miljon": 1_000_000,
    "miljoner": 1_000_000,
    "mdr": 1_000_000_000,
    "mdkr": 1_000_000_000,
    "mdsek": 1_000_000_000,
    "miljard": 1_000_000_000,
    "miljarder": 1_000_000_000,
}

# A trailing currency token. "kr" is deliberately mapped to None: it names no
# ISO currency, so the caller keeps whatever currency the notice itself states
# rather than inventing one from prose.
_CURRENCIES: dict[str, str | None] = {
    "kr": None,
    "kronor": None,
    "krona": None,
    ":-": None,
    "sek": "SEK",
    "skr": "SEK",
    "eur": "EUR",
    "euro": "EUR",
    "€": "EUR",
}


def _alternation(words: object) -> str:
    """Regex alternation, longest first so `miljoner` wins over `milj`."""
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))  # type: ignore[arg-type]


_MULT_ALT = _alternation(MULTIPLIERS)
_CUR_ALT = _alternation(_CURRENCIES)

_AMOUNT_FULL_RE = re.compile(
    rf"""^\s*
        (?P<sign>[-−])?\s*
        (?P<num>\d[\d{_SPACES}.,]*)
        \s*(?P<mult>(?:{_MULT_ALT})\.?)?
        \s*(?P<cur>(?:{_CUR_ALT})\.?)?
        \s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# The scanning form, for prose. Restricting the space-separated form to groups of
# exactly three digits stops `Del 2 4 000 000` being read as one number.
_NUM_SCAN = (
    rf"\d{{1,3}}(?:[{_SPACES}]\d{{3}})+(?:,\d+)?"
    rf"|\d{{1,3}}(?:\.\d{{3}})+(?:,\d+)?"
    rf"|\d+(?:[.,]\d+)?"
)
_SCAN_RE = re.compile(
    rf"(?<![\d.,])(?:{_NUM_SCAN})"
    rf"(?:\s*(?:{_MULT_ALT})\.?)?"
    rf"(?:\s*(?:{_CUR_ALT})\.?)?",
    re.IGNORECASE,
)


def _valid_thousands(part: str, sep: str) -> bool:
    """`1.234.567` is a valid thousands grouping; `1.23.456` is not."""
    groups = part.split(sep)
    if len(groups) < 2 or not 1 <= len(groups[0]) <= 3:
        return False
    return all(g.isdigit() for g in groups) and all(len(g) == 3 for g in groups[1:])


def _parse_number(raw: str) -> Decimal | None:
    """Digits, dots and commas into a Decimal, or None when the reading is ambiguous.

    Separator rule, applied in this order:

    * Both `.` and `,` present — the rightmost of the two is the decimal
      separator and the other must form valid three-digit groups.
    * Only `,` — more than one comma means thousands grouping; a single comma is
      the Swedish decimal comma.
    * Only `.` — a dot is a thousands separator when there is more than one
      dot-group (`4.000.000`), otherwise a decimal point (`4.5`). A single
      `4.000` therefore reads as 4, not 4000; that is the documented reading and
      the ambiguity is why `parse_amount` exists rather than a bare `float()`.
    """
    s = raw.translate(_SPACE_KILL)
    if not s or not re.fullmatch(r"\d[\d.,]*", s):
        return None

    dots, commas = s.count("."), s.count(",")
    fraction = ""
    decimal_used = False
    if dots and commas:
        if s.rfind(",") > s.rfind("."):
            integer, _, fraction = s.rpartition(",")
            thousands_sep = "."
        else:
            integer, _, fraction = s.rpartition(".")
            thousands_sep = ","
        if not _valid_thousands(integer, thousands_sep):
            return None
        digits = integer.replace(thousands_sep, "")
        decimal_used = True
    elif commas > 1:
        if not _valid_thousands(s, ","):
            return None
        digits = s.replace(",", "")
    elif commas == 1:
        digits, _, fraction = s.partition(",")
        decimal_used = True
    elif dots > 1:
        if not _valid_thousands(s, "."):
            return None
        digits = s.replace(".", "")
    elif dots == 1:
        digits, _, fraction = s.partition(".")
        decimal_used = True
    else:
        digits = s

    if not digits.isdigit():
        return None
    # A separator with nothing after it ("4,") is malformed, not four.
    if decimal_used and not fraction.isdigit():
        return None
    try:
        return Decimal(f"{digits}.{fraction}") if fraction else Decimal(digits)
    except InvalidOperation:
        return None


@dataclass(frozen=True, slots=True)
class _Parsed:
    amount: Decimal
    currency: str | None
    qualified: bool  # carries a unit word or a thousands grouping, not a bare integer


def _parse(text: str | None) -> _Parsed | None:
    if not text:
        return None
    match = _AMOUNT_FULL_RE.match(text)
    if match is None:
        return None

    raw = match.group("num")
    value = _parse_number(raw)
    if value is None:
        return None

    mult = match.group("mult")
    if mult:
        value *= MULTIPLIERS[mult.rstrip(".").lower()]
    if match.group("sign"):
        value = -value

    cur_token = match.group("cur")
    currency = _CURRENCIES[cur_token.rstrip(".").lower()] if cur_token else None
    grouped = any(ch in raw for ch in _SPACES) or raw.count(".") > 1
    return _Parsed(value, currency, bool(mult) or bool(cur_token) or grouped)


def parse_amount_with_currency(text: str | None) -> tuple[Decimal | None, str | None]:
    """Parse one money expression. Returns (amount, ISO currency or None).

    The currency is None both when no currency word is present and when the text
    says only "kr" — see the comment on `_CURRENCIES`.
    """
    parsed = _parse(text)
    return (None, None) if parsed is None else (parsed.amount, parsed.currency)


def parse_amount(text: str | None) -> Decimal | None:
    """The amount alone. None when the text is not an unambiguous money expression."""
    return parse_amount_with_currency(text)[0]


def to_int_sek(amount: Decimal) -> int:
    """Round half-up to whole SEK. Negative amounts round away from zero."""
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# -- ceiling phrases ---------------------------------------------------------

# Each phrase carries its own base confidence. A phrase that names the ceiling
# outright ("takvolym") outscores one that could just as well introduce a
# per-lot or per-call-off limit ("maximalt värde"). Nothing here exceeds 0.60:
# a regex over prose is never as good as a structured eForms field, and M1
# caps document_regex candidates at that level.
_CAP_PATTERNS: tuple[tuple[str, str, float], ...] = (
    ("takvolym", r"takvolym(?:en|er|erna)?", 0.60),
    ("takbelopp", r"takbelopp(?:et|en)?", 0.60),
    ("tak_for_avrop", r"tak(?:et)?\s+för\s+avrop", 0.60),
    ("far_hogst_avropas_for", r"får\s+högst\s+avropas\s+för", 0.60),
    ("maximalt_avropsvarde", r"maximal[ta]?\s+avropsvärde[nt]?", 0.60),
    ("avtalets_hogsta_varde", r"avtalets\s+högsta\s+värde", 0.60),
    ("beraknad_maximal_volym", r"beräknad\s+maximal\s+volym", 0.55),
    ("maximal_volym", r"maximal\s+volym", 0.55),
    ("hogsta_varde", r"högsta\s+värde[t]?", 0.50),
    ("maximalt_varde", r"maximal[t]?\s+värde[t]?", 0.50),
    ("maximalt_belopp", r"maximal[t]?\s+belopp(?:et)?", 0.50),
    ("overall_maximum", r"overall\s+maximum(?:\s+value)?", 0.60),
    ("framework_maximum", r"framework\s+maximum(?:\s+value|\s+amount)?", 0.60),
    ("maximum_value", r"maximum\s+value", 0.50),
    ("maximum_amount", r"maximum\s+amount", 0.50),
    ("ceiling", r"ceiling(?:\s+value|\s+amount)?", 0.50),
)

# Phrases that introduce an *estimate*. When one of these sits closer to an
# amount than any ceiling phrase does, the amount is an estimate and no
# CapMatch is produced. The spec is explicit that the two must never mix.
_ESTIMATE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "uppskattat_varde",
        r"uppskatta\w*\s+(?:total\w*\s+)?(?:värde[t]?|belopp(?:et)?|volym(?:en)?)",
    ),
    ("beraknat_varde", r"beräkna[td]\w*\s+(?:total\w*\s+)?(?:värde[t]?|belopp(?:et)?)"),
    ("preliminart_varde", r"prelimin[äa]r\w*\s+(?:värde[t]?|belopp(?:et)?)"),
    ("prognos", r"prognos(?:tiserat|en|erad\w*)?"),
    ("bedomt_behov", r"bed[öo]m[dt]\w*\s+(?:total\w*\s+)?(?:behov(?:et)?|värde[t]?|volym(?:en)?)"),
    ("estimated_value", r"estimated\s+(?:overall\s+)?(?:value|amount|contract\s+value)"),
    ("approximate_value", r"approximate\s+(?:overall\s+)?(?:value|amount)"),
)

# How far a descriptor may sit from an amount and still describe it.
DESCRIPTOR_WINDOW = 120
# A number written without a unit word and without thousands grouping is a lot
# number, a count or a duration ("Anbudsområde 2"), not a ceiling. Only accept
# such a bare integer when it is large enough that no other reading makes sense.
MIN_BARE_AMOUNT = 10_000
_EXCERPT_PAD = 40
_EXCERPT_MAX = 300


@dataclass(frozen=True, slots=True)
class CapMatch:
    amount: Decimal
    currency: str | None
    confidence: float
    pattern: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class _Descriptor:
    start: int
    end: int
    name: str
    confidence: float
    is_cap: bool


def _descriptors(text: str) -> list[_Descriptor]:
    found: list[_Descriptor] = []
    for name, pattern, confidence in _CAP_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            found.append(_Descriptor(m.start(), m.end(), name, confidence, True))
    for name, pattern in _ESTIMATE_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            found.append(_Descriptor(m.start(), m.end(), name, 0.0, False))
    return found


def _gap(descriptor: _Descriptor, start: int, end: int) -> int:
    """Character distance from a descriptor to an amount, preferring a preceding one."""
    if descriptor.end <= start:
        return start - descriptor.end
    if descriptor.start >= end:
        # +1 so that, at equal distance, the descriptor before the amount wins.
        return descriptor.start - end + 1
    return 0


def _nearest(descriptors: list[_Descriptor], start: int, end: int) -> _Descriptor | None:
    best: _Descriptor | None = None
    best_gap = DESCRIPTOR_WINDOW + 1
    for descriptor in descriptors:
        gap = _gap(descriptor, start, end)
        if gap < best_gap:
            best, best_gap = descriptor, gap
    return best if best_gap <= DESCRIPTOR_WINDOW else None


def _excerpt(text: str, start: int, end: int) -> str:
    window = text[max(0, start - _EXCERPT_PAD) : end + _EXCERPT_PAD]
    collapsed = " ".join(window.split())
    return collapsed[:_EXCERPT_MAX]


def find_caps(text: str | None) -> list[CapMatch]:
    """Ceiling amounts stated in prose, most confident first.

    Every amount is attributed to the descriptor phrase nearest to it. If that
    nearest phrase introduces an estimate rather than a ceiling, the amount is
    dropped — so `Uppskattat värde 24 000 000 kr. Takvolym 30 000 000 kr.`
    yields one match of 30 000 000 and never 24 000 000.
    """
    if not text:
        return []
    descriptors = _descriptors(text)
    if not descriptors:
        return []

    found: list[tuple[int, CapMatch]] = []
    for m in _SCAN_RE.finditer(text):
        parsed = _parse(m.group(0))
        if parsed is None:
            continue
        if not parsed.qualified and abs(parsed.amount) < MIN_BARE_AMOUNT:
            continue
        value, currency = parsed.amount, parsed.currency
        descriptor = _nearest(descriptors, m.start(), m.end())
        if descriptor is None or not descriptor.is_cap:
            continue
        found.append(
            (
                m.start(),
                CapMatch(
                    amount=value,
                    currency=currency,
                    confidence=descriptor.confidence,
                    pattern=descriptor.name,
                    excerpt=_excerpt(
                        text,
                        min(descriptor.start, m.start()),
                        max(descriptor.end, m.end()),
                    ),
                ),
            )
        )

    found.sort(key=lambda item: (-item[1].confidence, item[0]))
    return [match for _, match in found]
