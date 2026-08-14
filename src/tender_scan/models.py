"""Domain model for a procurement notice, parsed from raw TED API data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

# Preferred languages when picking a value from TED's multilingual dicts.
_LANG_PRIORITY = ("eng", "swe")

# TED deadline fields come as a date plus a zone designator but no time,
# e.g. "2026-08-20Z" or "2026-09-03+02:00". Note that datetime.fromisoformat
# would misread "+02:00" here as a *time of day*, so we parse explicitly.
_DATE_WITH_ZONE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?P<zone>Z|[+-]\d{2}:\d{2})?$"
)


@dataclass(frozen=True, slots=True)
class Lot:
    """Per-lot estimate as published in the notice."""

    estimated_value: float | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class Notice:
    id: str
    title: str | None
    buyer: str | None
    cpv: str | None
    deadline: str | None  # UTC ISO-8601 ("YYYY-MM-DDTHH:MM:SSZ"), comparable as text
    estimated_value: float | None  # sum across lots when they share one currency
    currency: str | None
    lots: tuple[Lot, ...]
    url: str | None
    raw: dict[str, Any]


def normalize_deadline(value: str | None) -> str | None:
    """Normalize a TED deadline to UTC ISO-8601 ("YYYY-MM-DDTHH:MM:SSZ").

    TED mixes zone formats in the same field ("2026-08-20Z" vs
    "2026-09-03+02:00"), which breaks plain string comparison. Date-only
    deadlines are interpreted as midnight at the given offset (the start of
    the deadline day — conservative, and preserves ordering). Returns None
    for unparseable input.
    """
    if not value:
        return None
    value = value.strip()

    match = _DATE_WITH_ZONE.match(value)
    if match:
        dt = datetime.fromisoformat(match.group("date"))
        zone = match.group("zone")
        if zone in (None, "Z"):
            tz = UTC
        else:
            sign = 1 if zone[0] == "+" else -1
            hours, minutes = int(zone[1:3]), int(zone[4:6])
            tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
        dt = dt.replace(tzinfo=tz)
    else:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pick_lang(value: dict[str, Any] | None) -> Any:
    if not value:
        return None
    for lang in _LANG_PRIORITY:
        if lang in value:
            return value[lang]
    return next(iter(value.values()))


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_lots(values: list[Any], currencies: list[Any]) -> tuple[Lot, ...]:
    """Pair per-lot values with currencies without assuming index sync.

    TED returns "estimated-value-lot" and "estimated-value-cur-lot" as
    separate arrays. They are only zipped when their lengths match; a single
    distinct currency is applied to every lot; otherwise the currency is
    left unknown rather than guessed.
    """
    if not values:
        return ()
    if len(currencies) == len(values):
        pairs = list(zip(values, currencies, strict=True))
    elif len(set(currencies)) == 1:
        pairs = [(value, currencies[0]) for value in values]
    else:
        pairs = [(value, None) for value in values]
    return tuple(Lot(estimated_value=_to_float(v), currency=c or None) for v, c in pairs)


def total_estimated_value(lots: tuple[Lot, ...]) -> tuple[float | None, str | None]:
    """Sum lot values when they share a single currency; otherwise (None, None)."""
    values = [lot.estimated_value for lot in lots if lot.estimated_value is not None]
    currencies = {lot.currency for lot in lots if lot.estimated_value is not None}
    if not values or len(currencies) != 1:
        return None, None
    return sum(values), currencies.pop()


def format_estimated_value(value: float | None, currency: str | None) -> str | None:
    """Render a numeric value + currency for display, e.g. '18000000 SEK'."""
    if value is None:
        return None
    text = str(int(value)) if value == int(value) else str(value)
    return f"{text} {currency}".strip() if currency else text


def parse_notice(raw: dict[str, Any]) -> Notice:
    """Map one raw notice from the TED Search API to a flat Notice.

    Field names follow the eForms field identifiers returned by
    POST /v3/notices/search (e.g. "publication-number", "notice-title").
    """
    title = _pick_lang(raw.get("notice-title"))

    buyers = _pick_lang(raw.get("buyer-name")) or []
    buyer = "; ".join(buyers) if buyers else None

    cpv_codes = raw.get("classification-cpv") or []
    cpv = ",".join(dict.fromkeys(cpv_codes)) or None

    deadlines = [
        normalized
        for d in raw.get("deadline-receipt-tender-date-lot") or []
        if (normalized := normalize_deadline(d)) is not None
    ]
    deadline = min(deadlines) if deadlines else None

    lots = parse_lots(
        raw.get("estimated-value-lot") or [],
        raw.get("estimated-value-cur-lot") or [],
    )
    estimated_value, currency = total_estimated_value(lots)

    links = raw.get("links") or {}
    html_links = links.get("html") or {}
    url = html_links.get("ENG") or next(iter(html_links.values()), None)

    return Notice(
        id=raw["publication-number"],
        title=title,
        buyer=buyer,
        cpv=cpv,
        deadline=deadline,
        estimated_value=estimated_value,
        currency=currency,
        lots=lots,
        url=url,
        raw=raw,
    )
