from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import GraphRef

from app.models.base import WorkflowState
from app.models.enums import (
    AuditEngagementStatus,
    AuditFindingStatus,
    AuditProcedureResult,
    Criticality,
    ReviewFrequency,
    Severity,
)


# --------------------------------------------------------------- auditable units ---
class AuditableUnitBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = ""
    owner: str = ""
    inherent_risk: Criticality = Criticality.medium
    audit_frequency: ReviewFrequency = ReviewFrequency.annual
    last_audited_date: date | None = None
    next_audit_due: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class AuditableUnitCreate(AuditableUnitBase):
    pass


class AuditableUnitUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    owner: str | None = None
    inherent_risk: Criticality | None = None
    audit_frequency: ReviewFrequency | None = None
    last_audited_date: date | None = None
    next_audit_due: date | None = None
    workflow_status: WorkflowState | None = None


class AuditableUnitRead(AuditableUnitBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    is_overdue: bool
    created_at: datetime


# ------------------------------------------------------------------ procedures ---
class ProcedureBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    result: AuditProcedureResult = AuditProcedureResult.pending
    conclusion: str = ""
    workpaper_ref: str = ""
    performed_by: str = ""
    performed_date: date | None = None


class ProcedureCreate(ProcedureBase):
    pass


class ProcedureUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    result: AuditProcedureResult | None = None
    conclusion: str | None = None
    workpaper_ref: str | None = None
    performed_by: str | None = None
    performed_date: date | None = None


class ProcedureRead(ProcedureBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    engagement_id: uuid.UUID
    created_at: datetime


# -------------------------------------------------------------------- findings ---
class FindingBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    rating: Severity = Severity.medium
    risk_implication: str = ""
    recommendation: str = ""
    management_response: str = ""
    action_owner: str = ""
    due_date: date | None = None
    status: AuditFindingStatus = AuditFindingStatus.open


class FindingCreate(FindingBase):
    control_ids: list[uuid.UUID] = []
    risk_ids: list[uuid.UUID] = []
    requirement_ids: list[uuid.UUID] = []


class FindingUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    rating: Severity | None = None
    risk_implication: str | None = None
    recommendation: str | None = None
    management_response: str | None = None
    action_owner: str | None = None
    due_date: date | None = None
    status: AuditFindingStatus | None = None
    closed_date: date | None = None
    control_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None
    requirement_ids: list[uuid.UUID] | None = None


class FindingRead(FindingBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    engagement_id: uuid.UUID
    reference: str
    closed_date: date | None
    is_overdue: bool
    # What the finding is raised against (into the core graph).
    controls: list[GraphRef] = []
    risks: list[GraphRef] = []
    requirements: list[GraphRef] = []
    created_at: datetime


class FindingSummary(BaseModel):
    """Server-computed remediation follow-up counts for the findings stat cards."""

    total: int
    open: int
    overdue: int


# ------------------------------------------------------------------ engagements ---
class EngagementBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    scope: str = ""
    objectives: str = ""
    auditable_unit_id: uuid.UUID | None = None
    lead_auditor: str = ""
    audit_team: str = ""
    status: AuditEngagementStatus = AuditEngagementStatus.planned
    period_start: date | None = None
    period_end: date | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    conclusion: str = ""
    rating: Severity | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class EngagementCreate(EngagementBase):
    pass


class EngagementUpdate(BaseModel):
    title: str | None = None
    scope: str | None = None
    objectives: str | None = None
    auditable_unit_id: uuid.UUID | None = None
    lead_auditor: str | None = None
    audit_team: str | None = None
    status: AuditEngagementStatus | None = None
    period_start: date | None = None
    period_end: date | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    conclusion: str | None = None
    rating: Severity | None = None
    workflow_status: WorkflowState | None = None


class EngagementRead(EngagementBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    finding_count: int
    open_finding_count: int
    is_overdue: bool
    created_at: datetime
    procedures: list[ProcedureRead] = []
    findings: list[FindingRead] = []
