"""Annual audit plan — sign-off lifecycle, scheduling and delivery links.

Regressions from live verification: approving a plan in the Approvals inbox left it
"submitted" (the write-back only knew records with ``workflow_status``); a PATCH could
set "approved" without any board decision; re-submitting raised a second approval; a
line could be scheduled in November and Q1 at once.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

import app.models  # noqa: F401 - populate mappers
from app.api.v1.audit_plan import _schedule, line_window
from app.models.audit_plan import (
    AuditPlan,
    AuditPlanStatus,
    content_edit_refusal,
    manual_status_refusal,
    plan_decision_target,
    quarter_of_month,
)
from app.schemas.audit_plan import PlanItemCreate, PlanItemRead, PlanItemUpdate
from app.services import record_workflow as rw

S = AuditPlanStatus


# ------------------------------------------------------------ manual status ---
@pytest.mark.parametrize("current", [S.draft, S.submitted, S.active, S.closed])
def test_an_edit_can_never_mark_a_plan_approved(current):
    assert manual_status_refusal(current, S.approved) is not None


@pytest.mark.parametrize("current", [S.draft, S.approved])
def test_an_edit_can_never_mark_a_plan_submitted(current):
    """Submission raises the approval request; a status flip would skip it."""
    assert manual_status_refusal(current, S.submitted) is not None


def test_a_draft_cannot_jump_to_delivery_or_closure():
    assert manual_status_refusal(S.draft, S.active) is not None
    assert manual_status_refusal(S.draft, S.closed) is not None


def test_after_sign_off_the_plan_moves_into_delivery_and_closes():
    assert manual_status_refusal(S.approved, S.active) is None
    assert manual_status_refusal(S.approved, S.closed) is None
    assert manual_status_refusal(S.active, S.closed) is None


def test_an_approved_plan_cannot_be_edited_back_to_draft():
    assert manual_status_refusal(S.active, S.draft) is not None
    assert manual_status_refusal(S.approved, S.draft) is not None


def test_echoing_the_current_status_is_not_a_change():
    for status in S:
        assert manual_status_refusal(status, status) is None


# --------------------------------------------------------- inbox decisions ---
def test_approval_signs_off_a_submitted_plan_and_rejection_returns_it():
    assert plan_decision_target(S.submitted, True) == S.approved
    assert plan_decision_target(S.submitted, False) == S.draft


@pytest.mark.parametrize("current", [S.draft, S.approved, S.active, S.closed])
def test_a_stale_decision_moves_nothing(current):
    assert plan_decision_target(current, True) is None
    assert plan_decision_target(current, False) is None


def test_the_write_back_knows_audit_plans():
    """The approvals inbox writes a decision back through record_workflow; the plan has
    no workflow_status, so it needs its own entry or approving it does nothing."""
    assert "audit_plans" in rw._STATUS_DECISIONS


def test_approving_stamps_the_date_and_rejecting_clears_it():
    plan = AuditPlan(year=2026, title="FY26", status=S.submitted)
    assert rw._decide_audit_plan(plan, True) == ("submitted", "approved")
    assert plan.status == S.approved
    assert plan.approved_on == date.today()

    plan = AuditPlan(year=2026, title="FY26", status=S.submitted, approved_on=date(2020, 1, 1))
    assert rw._decide_audit_plan(plan, False) == ("submitted", "draft")
    assert plan.status == S.draft
    assert plan.approved_on is None


def test_a_decision_on_a_plan_that_moved_on_leaves_it_alone():
    plan = AuditPlan(year=2026, title="FY26", status=S.active, approved_on=date(2026, 1, 5))
    assert rw._decide_audit_plan(plan, False) is None
    assert plan.status == S.active
    assert plan.approved_on == date(2026, 1, 5)


class _FakeDb:
    def __init__(self, record):
        self.record = record
        self.flushed = 0

    async def get(self, model, entity_id):
        assert model is AuditPlan
        return self.record

    async def flush(self):
        self.flushed += 1


async def test_an_inbox_approval_marks_the_plan_approved(monkeypatch):
    from app.services import audit

    logged = []

    async def fake_record(db, **kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(audit, "record", fake_record)
    plan = AuditPlan(id=uuid.uuid4(), tenant_id=uuid.uuid4(), year=2026, title="FY26",
                     reference="AP-001", status=S.submitted)
    db = _FakeDb(plan)
    result = await rw.write_back(
        db, entity_type="audit_plan", entity_id=plan.id, approved=True,
        via="approval APR-001", actor=object(),
    )
    assert result == "approved"
    assert plan.status == S.approved and plan.approved_on == date.today()
    assert db.flushed == 1
    assert logged and logged[0]["changes"]["from"] == "submitted"
    assert logged[0]["changes"]["to"] == "approved"


async def test_an_inbox_rejection_returns_the_plan_to_draft(monkeypatch):
    from app.services import audit

    async def fake_record(db, **kwargs):
        pass

    monkeypatch.setattr(audit, "record", fake_record)
    plan = AuditPlan(id=uuid.uuid4(), tenant_id=uuid.uuid4(), year=2026, title="FY26",
                     reference="AP-002", status=S.submitted)
    result = await rw.write_back(
        _FakeDb(plan), entity_type="audit_plan", entity_id=plan.id, approved=False,
        via="approval APR-002", comment="Coverage of treasury is missing", actor=object(),
    )
    assert result == "draft"
    assert plan.status == S.draft


# --------------------------------------------------------- content locking ---
def test_a_plan_awaiting_sign_off_cannot_change_underneath_the_board():
    assert content_edit_refusal(S.submitted) is not None
    assert content_edit_refusal(S.closed) is not None


@pytest.mark.parametrize("status", [S.draft, S.approved, S.active])
def test_draft_and_approved_plans_can_be_amended(status):
    assert content_edit_refusal(status) is None


# --------------------------------------------------------------- schedule ---
def test_months_map_to_their_quarters():
    assert [quarter_of_month(m) for m in range(1, 13)] == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]


def test_a_month_alone_sets_the_quarter():
    assert PlanItemCreate(title="Payroll", planned_month=11).planned_quarter == 4


def test_a_month_that_contradicts_its_quarter_is_refused():
    with pytest.raises(ValidationError):
        PlanItemCreate(title="Payroll", planned_month=11, planned_quarter=1)
    with pytest.raises(ValidationError):
        PlanItemUpdate(planned_month=11, planned_quarter=1)


def test_a_consistent_month_and_quarter_are_accepted():
    assert PlanItemCreate(title="x", planned_month=5, planned_quarter=2).planned_quarter == 2
    assert PlanItemUpdate(planned_month=5, planned_quarter=2).planned_month == 5


def test_an_update_naming_a_month_moves_the_line_to_its_quarter():
    assert _schedule(1, None, {"planned_month": 8}) == {"planned_month": 8, "planned_quarter": 3}


def test_moving_a_line_to_another_quarter_drops_a_month_that_no_longer_fits():
    assert _schedule(4, 11, {"planned_quarter": 2}) == {"planned_quarter": 2, "planned_month": None}


def test_moving_quarter_keeps_a_month_that_still_fits():
    assert _schedule(4, 11, {"planned_quarter": 4}) == {"planned_quarter": 4}


def test_clearing_the_month_keeps_the_quarter():
    assert _schedule(4, 11, {"planned_month": None}) == {"planned_month": None}


def test_fieldwork_window_follows_the_month_or_the_quarter():
    assert line_window(2026, 4, 11) == (date(2026, 11, 1), date(2026, 11, 30))
    assert line_window(2026, 1, None) == (date(2026, 1, 1), date(2026, 3, 31))
    assert line_window(2026, 4, None) == (date(2026, 10, 1), date(2026, 12, 31))
    assert line_window(2028, 1, 2) == (date(2028, 2, 1), date(2028, 2, 29))


def test_a_plan_line_reports_the_engagement_that_delivers_it():
    fields = PlanItemRead.model_fields
    for name in ("engagement_id", "engagement_reference", "engagement_title", "engagement_status"):
        assert name in fields
