"""Audit plan, programmes and calendar — structural invariants.

The plan's whole purpose is answering "did we do what we told the board we would do?",
which only works if the *commitment* is recorded separately from what happened and the
coverage arithmetic is right. The programme's purpose is that a checklist generated from
a framework keeps a link back to the clause it tests — without that link the finished
working papers are not defensible to a certification auditor.
"""
import uuid

import pytest

from app.models.audit_plan import (
    AuditPlan,
    AuditPlanItem,
    AuditPlanStatus,
    AuditProgram,
    AuditProgramStep,
)
from app.models.custom_field import CUSTOM_FIELD_MODELS
from app.services import entity_types


def _plan(**kwargs) -> AuditPlan:
    plan = AuditPlan(year=2026, title="FY26 plan", **kwargs)
    plan.items = []
    return plan


def _item(*, started: bool = False, quarter: int = 1, hours: int = 40) -> AuditPlanItem:
    return AuditPlanItem(
        title="Audit of something",
        planned_quarter=quarter,
        budgeted_hours=hours,
        engagement_id=uuid.uuid4() if started else None,
    )


# -------------------------------------------------------------- plan coverage ---
def test_an_empty_plan_reports_zero_rather_than_dividing_by_zero():
    plan = _plan()
    assert plan.planned_count == 0
    assert plan.started_count == 0
    assert plan.coverage_pct == 0
    assert plan.planned_hours == 0


def test_coverage_counts_only_lines_that_became_engagements():
    """A line is 'delivered' when it has an engagement — intent alone is not coverage."""
    plan = _plan()
    plan.items = [_item(started=True), _item(), _item()]
    assert plan.planned_count == 3
    assert plan.started_count == 1
    assert plan.coverage_pct == 33


def test_full_coverage_is_a_hundred_percent():
    plan = _plan()
    plan.items = [_item(started=True), _item(started=True)]
    assert plan.coverage_pct == 100


def test_planned_hours_sum_the_lines_not_the_budget():
    """The budget is what was granted; planned hours are what the lines actually add up
    to. Reporting one as the other hides an over- or under-committed plan."""
    plan = _plan(budget_hours=500)
    plan.items = [_item(hours=120), _item(hours=80)]
    assert plan.planned_hours == 200
    assert plan.budget_hours == 500


@pytest.mark.parametrize("status", list(AuditPlanStatus))
def test_the_plan_lifecycle_covers_submission_and_approval(status):
    assert status.value in {"draft", "submitted", "approved", "active", "closed"}


def test_the_lifecycle_has_a_distinct_submitted_state():
    """Board sign-off is a state of the plan, not just a flag on the approval request —
    an audit committee asks whether the plan *is* approved, not whether a request exists."""
    assert AuditPlanStatus.submitted != AuditPlanStatus.approved
    assert AuditPlanStatus.draft.value == "draft"


# ---------------------------------------------------------------- programmes ---
def test_a_programme_reports_its_step_count():
    program = AuditProgram(name="ISO 27001 programme")
    program.steps = [
        AuditProgramStep(title="A.5.1", order_index=1),
        AuditProgramStep(title="A.5.2", order_index=2),
    ]
    assert program.step_count == 2


def test_an_empty_programme_is_not_an_error():
    program = AuditProgram(name="Blank")
    program.steps = []
    assert program.step_count == 0


def test_a_step_can_carry_the_clause_it_tests():
    """Without the requirement link, generated working papers cannot be traced back to
    the standard they were meant to evidence."""
    step = AuditProgramStep(title="A.8.1", requirement_id=uuid.uuid4())
    assert step.requirement_id is not None
    assert "requirement_id" in {c.name for c in AuditProgramStep.__table__.columns}


# ------------------------------------------------------------------ wiring ---
@pytest.mark.parametrize("key", ["audit_plan", "audit_program"])
def test_new_record_types_accept_comments_and_attachments(key):
    """Unregistered entity types are rejected by the shared panels, so a plan would have
    nowhere to keep the board pack that approved it."""
    spec = entity_types.spec(key)
    assert spec is not None
    assert spec.read_perm == "internal_audit:read"
    assert spec.write_perm == "internal_audit:write"


@pytest.mark.parametrize("key", ["audit_plan", "audit_program"])
def test_new_record_types_accept_custom_fields(key):
    assert key in CUSTOM_FIELD_MODELS


def test_plan_tables_are_tenant_isolated():
    from app.db.rls import TENANT_SCOPED_TABLES

    for table in ("audit_plans", "audit_plan_items", "audit_programs", "audit_program_steps"):
        assert table in TENANT_SCOPED_TABLES, f"{table} has no row-level security policy"
