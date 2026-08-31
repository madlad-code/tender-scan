"""M3 — FOIA-ärendehanterare: begäran om allmän handling, från utkast till svar.

Open data covers a minority of Swedish buyers. Sundsvalls kommun and
Helsingborgs stad, both named in the spec, publish no supplier ledger at all;
so does every central purchasing body. For those, the only route to actual
call-off volumes is offentlighetsprincipen — and that route is a *process*,
with deadlines, not a single email. This module keeps the process.

## Nothing is ever sent from here

`foia new` writes mail text to a file and prints where it went. Dispatch is
manual, always. Sending on a user's behalf to a public authority's registrator
is the kind of action that cannot be taken back, gets logged at the receiving
end under their name, and would be indistinguishable from them having written
it. The tool drafts; the person sends.

## The schedule

A myndighet must handle a request *skyndsamt*. In practice a simple release
takes one to five working days, and silence past that is what needs chasing.

* **Day 3 — written reminder.** Polite, and it timestamps the chase.
* **Day 5 — phone the registrator.** Silence is usually an unread inbox rather
  than a refusal, and a call resolves that in a minute.
* **Day 10 — request a written refusal decision.** An avslag must carry a
  besvärshänvisning, which is what makes it appealable to kammarrätten.
  Without a written decision there is nothing to appeal.

Days are counted from `sent_at`, in calendar days, and `foia due` lists what
has come due.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime

from tender_scan.records import FoiaRequest, FrameworkAgreement

STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
STATUS_PARTIAL = "partial"
STATUS_RECEIVED = "received"
STATUS_REFUSED = "refused"
STATUS_CLOSED = "closed"

STATUSES = (
    STATUS_DRAFT,
    STATUS_SENT,
    STATUS_PARTIAL,
    STATUS_RECEIVED,
    STATUS_REFUSED,
    STATUS_CLOSED,
)

# Statuses that no longer need chasing.
#
# `partial` is deliberately absent: an authority that sent one year of three,
# or the ledger without the framework breakdown, has answered without
# delivering. Treating that as settled is how the missing half gets forgotten,
# so the clock keeps running and `foia due` keeps listing it.
_SETTLED = (STATUS_RECEIVED, STATUS_REFUSED, STATUS_CLOSED)


@dataclass(frozen=True, slots=True)
class Step:
    day: int
    column: str
    action: str


SCHEDULE: tuple[Step, ...] = (
    Step(3, "reminder_1_at", "Skicka skriftlig påminnelse"),
    Step(5, "reminder_2_at", "Ring registratorn"),
    Step(10, "decision_requested_at", "Begär skriftligt avslagsbeslut med besvärshänvisning"),
)


@dataclass(frozen=True, slots=True)
class DueAction:
    request: FoiaRequest
    step: Step
    days_since_sent: int

    def render(self) -> str:
        return (
            f"#{self.request.id} {self.request.target_org} — dag {self.days_since_sent}: "
            f"{self.step.action}"
        )


def _parse(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def due_actions(requests: list[FoiaRequest], *, today: date | None = None) -> list[DueAction]:
    """Steps that have come due and have not been recorded as done.

    Only the earliest outstanding step per request is returned: chasing on day
    3 and day 5 in the same breath reads as noise, and the day-10 escalation is
    only meaningful once the earlier steps have actually happened.
    """
    when = today or datetime.now(UTC).date()
    found: list[DueAction] = []
    for request in requests:
        if request.status in _SETTLED:
            continue
        sent = _parse(request.sent_at)
        if sent is None:
            continue  # not dispatched yet, so no clock has started
        elapsed = (when - sent).days
        for step in SCHEDULE:
            if getattr(request, step.column) is not None:
                continue
            if elapsed >= step.day:
                found.append(DueAction(request, step, elapsed))
            break
    return sorted(found, key=lambda action: -action.days_since_sent)


# -- the outreach ledger -----------------------------------------------------
#
# Batch outreach gets tracked in a spreadsheet before it gets tracked anywhere
# else, because a spreadsheet is what a person reaches for when they are
# sending twenty emails on a Tuesday. That is fine as a working surface and
# useless as a clock: nothing in a spreadsheet tells you that Huddinge is on
# day 6 and owes you a phone call. `read_outreach` moves the ledger into
# `foia_requests`, where `due_actions` can run over it.

# The Swedish column names a hand-kept sheet actually uses, mapped to the
# fields they mean. A sheet may carry any subset; unknown columns are ignored.
_LEDGER_COLUMNS = {
    "kommun": "target_org",
    "organisation": "target_org",
    "myndighet": "target_org",
    "epost": "target_email",
    "e-post": "target_email",
    "status": "status",
    "skickat_datum": "sent_at",
    "paminnelse_datum": "reminder_1_at",
    "påminnelse_datum": "reminder_1_at",
    # A sheet with one escalation column means the day-10 written decision.
    # The day-5 phone call has no column because a call leaves no artefact,
    # so `reminder_2_at` stays NULL rather than being invented here.
    "eskalering_datum": "decision_requested_at",
    "svar_datum": "response_received_at",
    "anteckning": "notes",
    "notering": "notes",
}

# Sheet spellings mapped to the module's own statuses. Both the past participle
# and the supine turn up in the same sheet ("skickad" vs "skickat"), because
# they are typed by hand.
_LEDGER_STATUSES = {
    "": STATUS_DRAFT,
    "ej_skickad": STATUS_DRAFT,
    "ej skickad": STATUS_DRAFT,
    "utkast": STATUS_DRAFT,
    "skickad": STATUS_SENT,
    "skickat": STATUS_SENT,
    "levererat_delvis": STATUS_PARTIAL,
    "levererat delvis": STATUS_PARTIAL,
    "delvis": STATUS_PARTIAL,
    "levererat": STATUS_RECEIVED,
    "levererad": STATUS_RECEIVED,
    "svar": STATUS_RECEIVED,
    "avslag": STATUS_REFUSED,
    "avslagen": STATUS_REFUSED,
    "nekad": STATUS_REFUSED,
    "stangd": STATUS_CLOSED,
    "stängd": STATUS_CLOSED,
    "klar": STATUS_CLOSED,
}

_DATE_FIELDS = (
    "sent_at",
    "reminder_1_at",
    "decision_requested_at",
    "response_received_at",
)


class LedgerError(ValueError):
    """A ledger row that cannot be read without guessing at what it means."""


def read_outreach(text: str) -> list[FoiaRequest]:
    """Parse a hand-kept outreach sheet into requests.

    Tolerant of what a spreadsheet does to a file — a UTF-8 BOM on the first
    header, rows truncated to the last non-empty cell, stray whitespace — and
    intolerant of anything that would require a guess. In particular **dates
    must be ISO-8601**: a sheet holding `03-04-26` cannot be read as either
    March 4th or April 3rd without knowing which convention the author used,
    and picking one silently would put a reminder on the wrong day. Such a
    value raises rather than resolves.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        return []
    columns = {
        name: _LEDGER_COLUMNS[(name or "").strip().lstrip("﻿").lower()]
        for name in reader.fieldnames
        if (name or "").strip().lstrip("﻿").lower() in _LEDGER_COLUMNS
    }
    if "target_org" not in columns.values():
        raise LedgerError(
            "Sheet has no organisation column — expected one of: "
            + ", ".join(sorted(k for k, v in _LEDGER_COLUMNS.items() if v == "target_org"))
        )

    found: list[FoiaRequest] = []
    for line, row in enumerate(reader, start=2):
        fields = _ledger_row(row, columns, line)
        if fields is None:
            continue
        found.append(FoiaRequest(id=None, framework_notice_id=None, **fields))
    return found


def _ledger_row(
    row: dict[str, str | None], columns: dict[str, str], line: int
) -> dict[str, str | None] | None:
    """One sheet row as request fields, or None for a blank row."""
    fields: dict[str, str | None] = {}
    for name, field in columns.items():
        # A row truncated by a spreadsheet yields None for the missing tail;
        # that is an empty cell, not a broken file.
        value = (row.get(name) or "").strip()
        fields[field] = value or None

    org = fields.get("target_org")
    if not org:
        return None  # a trailing blank line, which every sheet grows

    raw_status = (fields.get("status") or "").strip().lower()
    if raw_status not in _LEDGER_STATUSES:
        raise LedgerError(
            f"Rad {line} ({org}): okänd status {raw_status!r}. "
            f"Kända: {', '.join(sorted(s for s in _LEDGER_STATUSES if s))}"
        )
    fields["status"] = _LEDGER_STATUSES[raw_status]

    for field in _DATE_FIELDS:
        value = fields.get(field)
        if value and _parse(value) is None:
            raise LedgerError(
                f"Rad {line} ({org}): {field} = {value!r} är inte ISO-8601. "
                "Skriv datumet som ÅÅÅÅ-MM-DD — 03-04-26 går inte att läsa "
                "som vare sig 4 mars eller 3 april utan att gissa."
            )
        fields.setdefault(field, None)

    fields.setdefault("target_email", None)
    fields.setdefault("notes", None)
    fields["reminder_2_at"] = None
    fields["response_file_path"] = None
    return fields


# -- the request text --------------------------------------------------------

_TEMPLATE = """Ämne: Begäran om utlämnande av allmän handling — avropsstatistik ramavtal {title}

Hej,

Med stöd av offentlighetsprincipen (2 kap. tryckfrihetsförordningen) begär jag
utlämnande av följande allmänna handlingar:

1. Sammanställning av avrop (beställningar) gjorda under ramavtalet
   "{title}"{notice_clause}{period_clause}, fördelat per leverantör och belopp,
   alternativt den leverantörsstatistik eller avtalsuppföljning som {org} för
   över avtalet.

2. Om sådan sammanställning inte finns: utbetalda belopp per leverantör ur
   leverantörsreskontran för samma period, avseende{supplier_clause}.

Jag tar gärna emot handlingarna digitalt till denna e-postadress, i befintligt
format (Excel eller CSV går utmärkt). Om utlämnandet är förenat med avgift
önskar jag besked om beloppet i förväg. Vänligen meddela också om någon del
omfattas av sekretess, och lämna i så fall ut övriga delar.

Tack på förhand,
[Namn]
[Telefon]
[E-post]
"""

_MAX_NAMED_SUPPLIERS = 12


def render_request(
    framework: FrameworkAgreement | None,
    org: str,
    suppliers: list[str] | None = None,
) -> str:
    """The mail text, ready to be read, edited and sent by a human.

    Point 2 is the important one: a myndighet may refuse point 1 as requiring a
    "betydande arbetsinsats", but the supplier ledger is raw data they already
    hold, and refusing to release *that* is much harder to justify.
    """
    title = (framework.title if framework else None) or "[avtalsnamn]"
    notice = framework.notice_id if framework else None
    notice_clause = f" (TED-notis {notice})" if notice else ""

    start = framework.start_date if framework else None
    end = framework.end_date if framework else None
    period_clause = f" under perioden {start}–{end}" if start and end else " under avtalstiden"

    named = suppliers or []
    if not named:
        supplier_clause = " samtliga leverantörer på avtalet"
    elif len(named) <= _MAX_NAMED_SUPPLIERS:
        supplier_clause = " " + ", ".join(named)
    else:
        # A list of forty company names makes the request look like a fishing
        # expedition and invites a refusal. Name a few, then ask for the rest.
        supplier_clause = (
            " "
            + ", ".join(named[:_MAX_NAMED_SUPPLIERS])
            + f" samt övriga {len(named) - _MAX_NAMED_SUPPLIERS} leverantörer på avtalet"
        )

    return _TEMPLATE.format(
        title=title,
        org=org,
        notice_clause=notice_clause,
        period_clause=period_clause,
        supplier_clause=supplier_clause,
    )


def slug(text: str) -> str:
    """A filename-safe fragment of an organisation name."""
    keep = [c if c.isalnum() else "-" for c in text.casefold()]
    return "-".join(part for part in "".join(keep).split("-") if part)[:48] or "org"
