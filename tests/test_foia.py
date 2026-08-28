"""M3 — FOIA case handler.

The invariant here is procedural rather than numeric: **nothing is ever sent**.
A test asserts no network client is constructed and no mail API is reachable,
because the failure mode — a draft going out to a public authority's registrator
under the user's name — cannot be taken back.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tender_scan.foia import (
    SCHEDULE,
    STATUS_DRAFT,
    STATUS_RECEIVED,
    STATUS_REFUSED,
    STATUS_SENT,
    due_actions,
    render_request,
    slug,
)
from tender_scan.records import FoiaRequest, FrameworkAgreement
from tender_scan.storage import Storage

FRAMEWORK = FrameworkAgreement(
    notice_id="109559-2026",
    title="Upphandling kommunikationstjänster",
    buyer_name="Göteborgs Stad",
    is_framework=True,
    cap_value_sek=5_000_000,
    start_date="2025-03-11",
    end_date="2029-03-10",
)


def request(**overrides: object) -> FoiaRequest:
    base = {
        "id": 1,
        "target_org": "Göteborgs Stad",
        "target_email": "registrator@goteborg.se",
        "framework_notice_id": "109559-2026",
        "status": STATUS_SENT,
        "sent_at": "2026-08-01",
    }
    return FoiaRequest(**{**base, **overrides})  # type: ignore[arg-type]


# -- the schedule ------------------------------------------------------------


def test_the_schedule_is_the_one_the_spec_names() -> None:
    assert [(step.day, step.column) for step in SCHEDULE] == [
        (3, "reminder_1_at"),
        (5, "reminder_2_at"),
        (10, "decision_requested_at"),
    ]


@pytest.mark.parametrize(
    ("days", "expected"),
    [(0, None), (2, None), (3, "reminder_1_at"), (4, "reminder_1_at")],
)
def test_the_first_step_comes_due_on_day_three(days: int, expected: str | None) -> None:
    actions = due_actions([request()], today=date(2026, 8, 1 + days))
    assert (actions[0].step.column if actions else None) == expected


def test_only_the_earliest_outstanding_step_is_listed() -> None:
    """Day 12 with nothing done still asks for the reminder, not the escalation."""
    actions = due_actions([request()], today=date(2026, 8, 13))
    assert len(actions) == 1
    assert actions[0].step.column == "reminder_1_at"


def test_the_next_step_appears_once_the_previous_one_is_recorded() -> None:
    actions = due_actions([request(reminder_1_at="2026-08-04")], today=date(2026, 8, 13))
    assert actions[0].step.column == "reminder_2_at"


def test_the_escalation_appears_on_day_ten() -> None:
    sent = request(reminder_1_at="2026-08-04", reminder_2_at="2026-08-06")
    # Sent 2026-08-01, so day 10 is 2026-08-11.
    assert due_actions([sent], today=date(2026, 8, 11))[0].step.column == "decision_requested_at"
    assert due_actions([sent], today=date(2026, 8, 10)) == []


def test_an_unsent_draft_has_no_clock() -> None:
    assert due_actions([request(status=STATUS_DRAFT, sent_at=None)], today=date(2027, 1, 1)) == []


@pytest.mark.parametrize("status", [STATUS_RECEIVED, STATUS_REFUSED, "closed"])
def test_a_settled_request_is_not_chased(status: str) -> None:
    assert due_actions([request(status=status)], today=date(2026, 9, 1)) == []


def test_the_most_overdue_request_is_listed_first() -> None:
    actions = due_actions(
        [request(id=1, sent_at="2026-08-20"), request(id=2, sent_at="2026-08-01")],
        today=date(2026, 8, 25),
    )
    assert [action.request.id for action in actions] == [2, 1]


def test_an_unparseable_sent_date_is_ignored_rather_than_crashing() -> None:
    assert due_actions([request(sent_at="igår")], today=date(2026, 9, 1)) == []


def test_the_rendered_action_names_the_request_and_the_step() -> None:
    line = due_actions([request()], today=date(2026, 8, 6))[0].render()
    assert "#1" in line and "Göteborgs Stad" in line and "dag 5" in line


# -- the request text --------------------------------------------------------


def test_the_request_cites_the_legal_basis_and_names_the_agreement() -> None:
    text = render_request(FRAMEWORK, "Göteborgs Stad", ["Consid AB"])
    assert "tryckfrihetsförordningen" in text
    assert "Upphandling kommunikationstjänster" in text
    assert "109559-2026" in text
    assert "2025-03-11–2029-03-10" in text
    assert "Consid AB" in text


def test_the_request_always_asks_for_the_ledger_as_a_fallback() -> None:
    """Point 1 can be refused as a betydande arbetsinsats; point 2 is raw data."""
    text = render_request(FRAMEWORK, "Göteborgs Stad")
    assert "leverantörsreskontran" in text
    assert "samtliga leverantörer" in text


def test_a_long_supplier_list_is_summarised_rather_than_dumped() -> None:
    names = [f"Bolag {n} AB" for n in range(40)]
    text = render_request(FRAMEWORK, "Göteborgs Stad", names)
    assert "Bolag 0 AB" in text
    assert "Bolag 39 AB" not in text
    assert "övriga 28 leverantörer" in text


def test_the_request_renders_without_a_framework_row() -> None:
    text = render_request(None, "Sundsvalls kommun")
    assert "[avtalsnamn]" in text
    assert "under avtalstiden" in text
    assert "Sundsvalls kommun" in text


def test_the_draft_leaves_the_senders_identity_to_be_filled_in() -> None:
    """It is the user's request, sent under their name, not the tool's."""
    text = render_request(FRAMEWORK, "Göteborgs Stad")
    assert "[Namn]" in text
    assert "[E-post]" in text


@pytest.mark.parametrize(
    ("org", "expected"),
    [
        ("Göteborgs Stad", "göteborgs-stad"),
        ("Region Stockholm / SLL", "region-stockholm-sll"),
        ("!!!", "org"),
    ],
)
def test_slug_is_filename_safe(org: str, expected: str) -> None:
    assert slug(org) == expected


# -- storage -----------------------------------------------------------------


def test_a_request_round_trips_through_storage(tmp_path: Path) -> None:
    with Storage(tmp_path / "t.sqlite3") as storage:
        request_id = storage.insert_foia(
            FoiaRequest(
                id=None,
                target_org="Sundsvalls kommun",
                target_email=None,
                framework_notice_id="1-2026",
                status=STATUS_DRAFT,
            )
        )
        storage.update_foia(request_id, sent_at="2026-08-01", status=STATUS_SENT)
        stored = storage.get_foia(request_id)
        assert stored is not None
        assert stored.status == STATUS_SENT
        assert stored.sent_at == "2026-08-01"
        assert [r.id for r in storage.list_foia(status=STATUS_SENT)] == [request_id]


def test_updating_an_unknown_column_is_refused(tmp_path: Path) -> None:
    """A typo'd column name must not silently do nothing."""
    with Storage(tmp_path / "t.sqlite3") as storage:
        request_id = storage.insert_foia(
            FoiaRequest(
                id=None,
                target_org="X",
                target_email=None,
                framework_notice_id=None,
                status=STATUS_DRAFT,
            )
        )
        with pytest.raises(ValueError, match="unknown foia_requests columns"):
            storage.update_foia(request_id, statuz="sent")


# -- nothing is sent ---------------------------------------------------------


def test_the_module_imports_nothing_that_could_send_anything() -> None:
    """Drafting is safe; dispatch is the user's own act, under their name."""
    import ast

    from tender_scan import foia as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"smtplib", "email", "httpx", "requests", "urllib", "socket"})


def test_the_cli_draft_command_writes_a_file_and_sends_nothing(tmp_path: Path) -> None:
    """`foia new` must produce a path for a human to read, not a dispatch."""
    from typer.testing import CliRunner

    from tender_scan.cli import app

    db = tmp_path / "t.sqlite3"
    with Storage(db) as storage:
        storage.upsert_framework(FRAMEWORK)
    result = CliRunner().invoke(
        app,
        [
            "foia",
            "new",
            "--framework",
            "109559-2026",
            "--org",
            "Göteborgs Stad",
            "--out-dir",
            str(tmp_path / "foia"),
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "skicka själv" in result.output
    written = list((tmp_path / "foia").glob("*.txt"))
    assert len(written) == 1
    assert "tryckfrihetsförordningen" in written[0].read_text(encoding="utf-8")
    with Storage(db) as storage:
        assert [r.status for r in storage.list_foia()] == [STATUS_DRAFT]
