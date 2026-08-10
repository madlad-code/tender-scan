"""Domain model for a procurement notice, parsed from raw TED API data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Preferred languages when picking a value from TED's multilingual dicts.
_LANG_PRIORITY = ("eng", "swe")


@dataclass(frozen=True, slots=True)
class Notice:
    id: str
    title: str | None
    buyer: str | None
    cpv: str | None
    deadline: str | None
    estimated_value: str | None
    url: str | None
    raw: dict[str, Any]


def _pick_lang(value: dict[str, Any] | None) -> Any:
    if not value:
        return None
    for lang in _LANG_PRIORITY:
        if lang in value:
            return value[lang]
    return next(iter(value.values()))


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

    deadlines = raw.get("deadline-receipt-tender-date-lot") or []
    deadline = min(deadlines) if deadlines else None

    values = raw.get("estimated-value-lot") or []
    currencies = raw.get("estimated-value-cur-lot") or []
    estimated_value = None
    if values:
        currency = currencies[0] if currencies else ""
        estimated_value = f"{values[0]} {currency}".strip()

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
        url=url,
        raw=raw,
    )
