"""Workflow routing: progress arithmetic and the guarantees that keep it safe.

Two guarantees matter more than the feature itself:

1. **A record type with no enabled route behaves exactly as before.** The designer must
   be addable to a running install without disturbing anything already in flight.
2. **No stage can bypass segregation of duties**, because a stage does not implement
   approving — it raises a real ``ApprovalRequest`` and waits, so the SoD check that
   already exists is the one that runs.
"""
import inspect
import uuid

import pytest

from app.models.workflow import (
    ApproverMode,
    StageStatus2,
    TimeoutAction,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowInstanceStage,
    WorkflowInstanceStatus,
    WorkflowStage,
)
from app.services import workflow_engine


def _instance(*statuses: StageStatus2) -> WorkflowInstance:
    instance = WorkflowInstance(entity_type="risk", entity_id=uuid.uuid4())
    instance.steps = [
        WorkflowInstanceStage(order_index=i + 1, name=f"Stage {i + 1}", status=s)
        for i, s in enumerate(statuses)
    ]
    return instance


# ----------------------------------------------------------------- progress ---
def test_a_fresh_instance_points_at_its_first_stage():
    instance = _instance(StageStatus2.in_progress, StageStatus2.pending, StageStatus2.pending)
    assert instance.current_step is not None
    assert instance.current_step.order_index == 1
    assert instance.total_stages == 3
    assert instance.completed_stages == 0


def test_progress_advances_as_stages_are_approved():
    instance = _instance(StageStatus2.approved, StageStatus2.in_progress, StageStatus2.pending)
    assert instance.completed_stages == 1
    assert instance.current_step.order_index == 2


def test_a_finished_route_has_no_current_stage():
    instance = _instance(StageStatus2.approved, StageStatus2.approved)
    assert instance.current_step is None
    assert instance.completed_stages == instance.total_stages


def test_skipped_stages_do_not_count_as_completed():
    """After a rejection the remaining stages are skipped, not approved — reporting them
    as done would claim sign-off nobody gave."""
    instance = _instance(StageStatus2.rejected, StageStatus2.skipped, StageStatus2.skipped)
    assert instance.completed_stages == 0
    assert instance.current_step is None


def test_a_rejected_stage_stops_the_route_finding_a_next_step():
    instance = _instance(StageStatus2.approved, StageStatus2.rejected, StageStatus2.skipped)
    assert instance.current_step is None
    assert instance.completed_stages == 1


# -------------------------------------------------------------- definitions ---
def test_a_definition_reports_its_stage_count():
    definition = WorkflowDefinition(entity_type="risk", name="Risk acceptance")
    definition.stages = [WorkflowStage(name="Owner", order_index=1), WorkflowStage(name="CRO", order_index=2)]
    assert definition.stage_count == 2


def test_definitions_ship_disabled():
    """Creating a route must not silently start intercepting records."""
    assert WorkflowDefinition.__table__.c.enabled.default.arg is False


def test_every_approver_mode_is_resolvable():
    for mode in ApproverMode:
        assert mode.value in {"role", "named_user", "record_owner", "line_manager"}


def test_timeout_actions_cover_the_three_real_choices():
    assert {t.value for t in TimeoutAction} == {"escalate", "auto_approve", "block"}


def test_instance_lifecycle_distinguishes_cancelled_from_rejected():
    """Abandoning a route is not the same as being refused, and an audit trail has to
    show which happened."""
    assert WorkflowInstanceStatus.cancelled != WorkflowInstanceStatus.rejected
    assert {s.value for s in WorkflowInstanceStatus} == {
        "in_progress", "approved", "rejected", "cancelled",
    }


# --------------------------------------------------------------- guarantees ---
@pytest.mark.asyncio
async def test_no_definition_means_no_workflow(monkeypatch):
    """The safety property: an entity type nobody has configured keeps its old behaviour."""

    async def _none(_db, _entity_type):
        return None

    monkeypatch.setattr(workflow_engine, "definition_for", _none)
    result = await workflow_engine.start(
        None, tenant_id=uuid.uuid4(), entity_type="risk", entity_id=uuid.uuid4(),
        entity_label="R-001", link="/risks", requested_by=uuid.uuid4(),
        requested_by_email="a@b.c",
    )
    assert result is None


def test_stages_do_not_implement_approving():
    """A stage that decided for itself could bypass segregation of duties. The engine
    must only ever raise an ApprovalRequest and wait for the approvals module."""
    source = inspect.getsource(workflow_engine)
    assert "ApprovalRequest(" in source, "a stage must raise a real approval request"
    for forbidden in ("ApprovalAction(", "enforce_segregation_of_duties"):
        assert forbidden not in source, (
            f"{forbidden} in the engine means approving is being re-implemented here"
        )


def test_the_engine_reacts_to_decisions_rather_than_polling():
    assert hasattr(workflow_engine, "on_approval_decided")
    assert "approval_request_id" in {
        c.name for c in WorkflowInstanceStage.__table__.columns
    }


def test_workflow_tables_are_tenant_isolated():
    from app.db.rls import TENANT_SCOPED_TABLES

    for table in (
        "workflow_definitions", "workflow_stages",
        "workflow_instances", "workflow_instance_stages",
    ):
        assert table in TENANT_SCOPED_TABLES, f"{table} has no row-level security policy"


def test_the_approvals_endpoint_advances_the_route():
    """Without this call the designer would define routes that never progress."""
    from app.api.v1 import approvals

    source = inspect.getsource(approvals.decide_approval)
    assert "workflow_engine.on_approval_decided" in source


# ------------------------------------------------- event vs. condition alerts ---
def test_the_alert_reconciler_preserves_event_notifications():
    """The scanner deletes any notification it did not just produce, because an alert
    describes a *condition* that has resolved. A workflow completing is an *event* — it
    is written directly by the module that observed it, and the reconciler runs every
    time the notification list is opened, so without this guard the user never sees it."""
    import inspect

    from app.services import notifications

    assert notifications.EVENT_PREFIX == "event:"
    source = inspect.getsource(notifications.refresh)
    assert "EVENT_PREFIX" in source, "refresh() would garbage-collect event notifications"


def test_workflow_completion_is_recorded_as_an_event():
    import inspect

    from app.api.v1 import approvals

    source = inspect.getsource(approvals.decide_approval)
    assert "EVENT_PREFIX" in source
    assert "workflow-done:" in source
