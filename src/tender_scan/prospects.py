"""M6 — prospektlista: suppliers who sit on several framework agreements.

A supplier on one framework is a customer with one problem. A supplier on five
is a customer who cannot see, across any of them, where the call-offs actually
go — and who has five ceilings' worth of reason to want to know. That is the
list this module produces, and it is deliberately **company level only**.

No contact details are looked up. The spec forbids auto-enrichment from
third-party sources, and it is right to: scraping names and addresses out of a
company register into a sales list is a different activity, with different
rules, from reading public procurement data. The orgnr is the key; whoever
works the list looks the company up themselves.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from sqlite3 import Connection

DEFAULT_MIN_FRAMEWORKS = 2

CSV_HEADER = (
    "orgnr",
    "firmanamn",
    "antal_ramavtal",
    "ramavtalstitlar",
    "senaste_tilldelningsdatum",
    "kopare",
    # Named at length on purpose: it is the sum of the *agreements'* ceilings,
    # shared with every other supplier on them, not this company's own share.
    "avtalens_sammanlagda_takvolym_sek",
)


@dataclass(frozen=True, slots=True)
class Prospect:
    orgnr: str
    name: str
    framework_count: int
    framework_titles: tuple[str, ...]
    latest_award_date: str | None
    buyers: tuple[str, ...]
    total_cap_sek: int | None

    def row(self) -> tuple[str, ...]:
        return (
            self.orgnr,
            self.name,
            str(self.framework_count),
            " | ".join(self.framework_titles),
            self.latest_award_date or "",
            " | ".join(self.buyers),
            "" if self.total_cap_sek is None else str(self.total_cap_sek),
        )


def find(
    conn: Connection,
    *,
    cpv: str | None = None,
    min_frameworks: int = DEFAULT_MIN_FRAMEWORKS,
) -> list[Prospect]:
    """Suppliers on at least `min_frameworks` distinct framework agreements.

    `cpv` accepts a wildcard prefix the same way `scan` does — `72*` or
    `72000000`, where the eight-digit form is treated as its own prefix so
    `72000000` matches the whole 72 family the way a caller expects.
    """
    conn.row_factory = None
    prefix = _cpv_prefix(cpv)
    params: list[object] = []
    cpv_clause = ""
    if prefix is not None:
        cpv_clause = "AND f.cpv_main LIKE ?"
        params.append(f"{prefix}%")
    params.append(min_frameworks)

    rows = conn.execute(
        f"""
        SELECT w.supplier_orgnr,
               COUNT(DISTINCT w.notice_id) AS framework_count,
               MAX(w.award_date)           AS latest_award_date
        FROM award_winners w
        JOIN framework_agreements f ON f.notice_id = w.notice_id
        WHERE w.supplier_orgnr IS NOT NULL AND f.is_framework = 1 {cpv_clause}
        GROUP BY w.supplier_orgnr
        HAVING framework_count >= ?
        ORDER BY framework_count DESC, w.supplier_orgnr
        """,
        params,
    ).fetchall()

    found: list[Prospect] = []
    for orgnr, count, latest in rows:
        detail = conn.execute(
            f"""
            SELECT DISTINCT f.notice_id, f.title, f.buyer_name, f.cap_value_sek,
                   w.supplier_name
            FROM award_winners w
            JOIN framework_agreements f ON f.notice_id = w.notice_id
            WHERE w.supplier_orgnr = ? AND f.is_framework = 1 {cpv_clause}
            ORDER BY f.notice_id
            """,
            [orgnr, *([f"{prefix}%"] if prefix is not None else [])],
        ).fetchall()
        caps = [row[3] for row in detail if row[3] is not None]
        found.append(
            Prospect(
                orgnr=orgnr,
                # The same company is spelled several ways across notices
                # ("Atea sverige ab", "Atea Sverige AB"). Take the spelling
                # that looks most like a company name rather than the first.
                name=_best_name(row[4] for row in detail),
                framework_count=count,
                framework_titles=tuple(row[1] for row in detail if row[1]),
                latest_award_date=latest,
                buyers=tuple(dict.fromkeys(row[2] for row in detail if row[2])),
                # A partial sum: only the frameworks whose ceiling was
                # published contribute, so this is a floor, not a total.
                total_cap_sek=sum(caps) if caps else None,
            )
        )
    return found


def _cpv_prefix(cpv: str | None) -> str | None:
    """`72*` and `72000000` both mean "the 72 family".

    CPV pads a family code with trailing zeros, so stripping them turns a code
    into the prefix that matches its whole family — which is what a caller
    means by `--cpv 72000000`. Never shorter than two digits, or `70000000`
    would widen to everything beginning with 7.
    """
    if not cpv:
        return None
    cleaned = cpv.strip().rstrip("*")
    if not cleaned:
        return None
    stripped = cleaned.rstrip("0")
    return stripped if len(stripped) >= 2 else cleaned[:2]


def _best_name(names: Iterable[str]) -> str:
    """The most conventionally-cased spelling, longest as the tie-break."""
    candidates = sorted({name for name in names if name})
    if not candidates:
        return ""
    return max(candidates, key=lambda n: (sum(c.isupper() for c in n) < len(n) / 2, len(n)))


def to_csv(prospects: Sequence[Prospect]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerows(prospect.row() for prospect in prospects)
    return buffer.getvalue()
