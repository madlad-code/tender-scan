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

from dataclasses import dataclass
from datetime import UTC, date, datetime

from tender_scan.records import FoiaRequest, FrameworkAgreement

STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
STATUS_RECEIVED = "received"
STATUS_REFUSED = "refused"
STATUS_CLOSED = "closed"

STATUSES = (STATUS_DRAFT, STATUS_SENT, STATUS_RECEIVED, STATUS_REFUSED, STATUS_CLOSED)

# Statuses that no longer need chasing.
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
