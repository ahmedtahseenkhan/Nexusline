from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import GoalAuditResult, GoalStatus, ReviewFrequency
from app.schemas.common import UserRef

_LEGACY = "Legacy free text, accepted for one release; send the *_id instead. "


class Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


class GoalAuditCreate(BaseModel):
    result: GoalAuditResult = GoalAuditResult.not_assessed
    planned_date: date | None = None
    conducted_date: date | None = None
    metric_description: str = ""
    success_criteria: str = ""
    result_description: str = ""
    auditor: str = ""


class GoalAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    goal_id: uuid.UUID
    result: GoalAuditResult
    planned_date: date | None
    conducted_date: date | None
    metric_description: str
    success_criteria: str
    result_description: str
    auditor: str
    created_at: datetime


class GoalBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    # Phase 1: the owner is picked; ``owner`` text is kept in step with the key (and
    # matched onto it when sent alone) — see services.ref_fields.
    owner_id: uuid.UUID | None = None
    owner: str = Field(default="", description=_LEGACY + "Matched onto a user by email or name.")
    status: GoalStatus = GoalStatus.not_started
    audit_metric: str = ""
    success_criteria: str = ""
    audit_frequency: ReviewFrequency = ReviewFrequency.annual
    # ``workflow_status`` is not writable: it moves only through the record lifecycle.
    # The approval owner is picked; its ``workflow_owner`` text is read-only.
    workflow_owner_id: uuid.UUID | None = None


class GoalCreate(GoalBase):
    next_audit_date: date | None = None
    risk_ids: list[uuid.UUID] = Field(default_factory=list)
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    owner_id: uuid.UUID | None = None
    owner: str | None = Field(default=None, description=_LEGACY)
    status: GoalStatus | None = None
    audit_metric: str | None = None
    success_criteria: str | None = None
    audit_frequency: ReviewFrequency | None = None
    workflow_owner_id: uuid.UUID | None = None
    next_audit_date: date | None = None
    risk_ids: list[uuid.UUID] | None = None
    project_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None


class GoalRead(GoalBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    owner_ref: UserRef | None = None
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""  # legacy text
    workflow_owner_ref: UserRef | None = None
    next_audit_date: date | None
    last_audit_date: date | None
    audit_count: int
    last_result: GoalAuditResult | None
    is_audit_overdue: bool
    audits: list[GoalAuditRead] = []
    risks: list[Ref] = []
    projects: list[Ref] = []
    policies: list[Ref] = []
    created_at: datetime
