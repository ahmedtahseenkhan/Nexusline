"""Driving a record through a user-defined approval route.

The engine is deliberately thin, because the hard parts already exist. Approving,
counting N-eyes, refusing the maker as a checker, chasing overdue decisions and writing
the audit trail all live in the approvals module. A stage here does exactly one thing:
raise a real :class:`~app.models.approval.ApprovalRequest` and wait for it. When that
request is decided, :func:`on_approval_decided` moves the instance on.

That choice is what makes the feature safe to add to a running system — there is no
second approval mechanism to keep in step with the first, and no way for a workflow
stage to bypass segregation of duties.

**Nothing changes for a record type without an enabled definition.** ``definition_for``
returns ``None`` and every caller falls back to the fixed lifecycle the platform has
always had.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest
from app.models.enums import ApprovalStatus
from app.models.workflow import (
    ApproverMode,
    StageStatus2,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowInstanceStage,
    WorkflowInstanceStatus,
    WorkflowStage,
)
from app.services.refs import next_reference

__all__ = [
    "definition_for",
    "instance_for",
    "on_approval_decided",
    "start",
]


async def definition_for(db: AsyncSession, entity_type: str) -> WorkflowDefinition | None:
    """The enabled definition for a record type, or ``None`` — which means "behave as
    this platform always has"."""
    return await db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.entity_type == entity_type,
            WorkflowDefinition.enabled.is_(True),
        )
    )


async def instance_for(
    db: AsyncSession, entity_type: str, entity_id: uuid.UUID
) -> WorkflowInstance | None:
    """The live instance for a record, if it is currently routing."""
    return await db.scalar(
        select(WorkflowInstance)
        .where(
            WorkflowInstance.entity_type == entity_type,
            WorkflowInstance.entity_id == entity_id,
            WorkflowInstance.status == WorkflowInstanceStatus.in_progress,
        )
        .order_by(WorkflowInstance.created_at.desc())
    )


async def resolve_approver(
    db: AsyncSession, stage: WorkflowStage, record_owner_email: str
) -> str:
    """A human label for who decides this stage.

    ``record_owner`` and ``line_manager`` resolve against the record rather than the
    definition, which is what lets one route serve every record of a type instead of
    needing a copy per department. Line-manager resolution has no directory to consult
    yet, so it falls back to the owner and says so.
    """
    if stage.approver_mode == ApproverMode.record_owner:
        return record_owner_email or "record owner"
    if stage.approver_mode == ApproverMode.line_manager:
        return f"line manager of {record_owner_email}" if record_owner_email else "line manager"
    return stage.approver_ref or ("any approver" if stage.approver_mode == ApproverMode.role else "")


async def start(
    db: AsyncSession,
    *,
    tenant_id,
    entity_type: str,
    entity_id: uuid.UUID,
    entity_label: str,
    link: str,
    requested_by,
    requested_by_email: str,
    record_owner_email: str = "",
) -> WorkflowInstance | None:
    """Begin routing a record. Returns ``None`` when the type has no enabled definition.

    Re-starting a record that is already routing returns the live instance rather than a
    second one — two open routes for the same record would leave "which approval counts?"
    unanswerable.
    """
    definition = await definition_for(db, entity_type)
    if definition is None or not definition.stages:
        return None

    existing = await instance_for(db, entity_type, entity_id)
    if existing is not None:
        return existing

    instance = WorkflowInstance(
        tenant_id=tenant_id,
        definition_id=definition.id,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        started_by=requested_by,
        started_by_email=requested_by_email,
    )
    db.add(instance)
    await db.flush()

    for stage in definition.stages:
        db.add(
            WorkflowInstanceStage(
                tenant_id=tenant_id,
                instance_id=instance.id,
                stage_id=stage.id,
                order_index=stage.order_index,
                name=stage.name,
                approver_label=await resolve_approver(db, stage, record_owner_email),
            )
        )
    await db.flush()
    await db.refresh(instance)

    await _open_stage(
        db, instance, instance.steps[0], link=link,
        requested_by=requested_by, requested_by_email=requested_by_email,
    )
    return instance


async def _open_stage(
    db: AsyncSession,
    instance: WorkflowInstance,
    step: WorkflowInstanceStage,
    *,
    link: str,
    requested_by,
    requested_by_email: str,
) -> None:
    """Raise the real approval request this stage waits on."""
    stage = (
        await db.scalar(select(WorkflowStage).where(WorkflowStage.id == step.stage_id))
        if step.stage_id
        else None
    )
    required = stage.required_approvals if stage else 1
    sla_days = stage.sla_days if stage else 0

    approval = ApprovalRequest(
        tenant_id=instance.tenant_id,
        title=f"{instance.entity_label or instance.entity_type}: {step.name}",
        description=(
            f"Stage {step.order_index} of {instance.total_stages} — "
            f"{step.approver_label or 'approval required'}"
        ),
        entity_type=instance.entity_type,
        entity_id=instance.entity_id,
        entity_label=instance.entity_label,
        link=link,
        approver=step.approver_label,
        required_approvals=max(1, required),
        requested_by=requested_by,
        requested_by_email=requested_by_email,
        due_date=(date.today() + timedelta(days=sla_days)) if sla_days else None,
    )
    approval.reference = await next_reference(db, ApprovalRequest, "APR")
    db.add(approval)
    await db.flush()

    step.approval_request_id = approval.id
    step.status = StageStatus2.in_progress
    step.due_date = approval.due_date
    await db.flush()


async def on_approval_decided(db: AsyncSession, approval: ApprovalRequest) -> WorkflowInstance | None:
    """Advance (or terminate) the instance whose stage this approval was.

    Called from the approvals decision endpoint. An approval that is not part of a
    workflow — the overwhelming majority — returns ``None`` immediately, so single-stage
    approvals are unaffected.
    """
    step = await db.scalar(
        select(WorkflowInstanceStage).where(
            WorkflowInstanceStage.approval_request_id == approval.id
        )
    )
    if step is None:
        return None
    instance = await db.scalar(
        select(WorkflowInstance).where(WorkflowInstance.id == step.instance_id)
    )
    if instance is None or instance.status != WorkflowInstanceStatus.in_progress:
        return None

    now = datetime.now(timezone.utc)

    if approval.status == ApprovalStatus.rejected:
        # One rejection ends the route. Remaining stages are marked skipped rather than
        # left pending, so the record's history reads as a decision rather than a stall.
        step.status = StageStatus2.rejected
        step.decided_at = now
        step.decision_comment = approval.decision_comment
        for later in instance.steps:
            if later.status == StageStatus2.pending:
                later.status = StageStatus2.skipped
        instance.status = WorkflowInstanceStatus.rejected
        instance.completed_at = now
        await db.flush()
        return instance

    if approval.status != ApprovalStatus.approved:
        return None  # partial N-eyes: still gathering votes on this stage

    step.status = StageStatus2.approved
    step.decided_at = now
    step.decision_comment = approval.decision_comment
    await db.flush()
    await db.refresh(instance)

    next_step = instance.current_step
    if next_step is None:
        instance.status = WorkflowInstanceStatus.approved
        instance.completed_at = now
        await db.flush()
        return instance

    await _open_stage(
        db, instance, next_step, link=approval.link,
        requested_by=instance.started_by, requested_by_email=instance.started_by_email,
    )
    return instance


async def cancel(db: AsyncSession, instance: WorkflowInstance) -> WorkflowInstance:
    """Abandon a route, cancelling whatever approval is currently open."""
    for step in instance.steps:
        if step.status in (StageStatus2.pending, StageStatus2.in_progress):
            step.status = StageStatus2.skipped
            if step.approval_request_id:
                approval = await db.scalar(
                    select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id)
                )
                if approval is not None and approval.status == ApprovalStatus.pending:
                    approval.status = ApprovalStatus.cancelled
    instance.status = WorkflowInstanceStatus.cancelled
    instance.completed_at = datetime.now(timezone.utc)
    await db.flush()
    return instance
