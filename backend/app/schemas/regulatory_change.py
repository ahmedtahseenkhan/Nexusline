from __future__ import annotations

import uuid
from datetime import date, datetime

from app.schemas.common import GraphRef
from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import Criticality, ReviewFrequency
from app.models.regulatory_change import (
    Applicability,
    ObligationStatus,
    ObligationType,
    RegChangeStatus,
    ReturnStatus,
)


# --------------------------------------------------------------- obligations ---
class ObligationBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    obligation_type: ObligationType = ObligationType.mandatory
    owner: str = ""
    business_unit: str = ""
    mapped_policies: str = ""
    mapped_controls: str = ""
    status: ObligationStatus = ObligationStatus.open
    due_date: date | None = None


class ObligationCreate(ObligationBase):
    # Optional link to a regulatory change; omit for a standalone obligation.
    regulatory_change_id: uuid.UUID | None = None
    requirement_ids: list[uuid.UUID] = []
    policy_ids: list[uuid.UUID] = []
    control_ids: list[uuid.UUID] = []


class ObligationUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    obligation_type: ObligationType | None = None
    owner: str | None = None
    business_unit: str | None = None
    mapped_policies: str | None = None
    mapped_controls: str | None = None
    status: ObligationStatus | None = None
    due_date: date | None = None
    regulatory_change_id: uuid.UUID | None = None
    requirement_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None
    control_ids: list[uuid.UUID] | None = None


class ObligationRead(ObligationBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    regulatory_change_id: uuid.UUID | None = None
    requirements: list[GraphRef] = []
    policies: list[GraphRef] = []
    controls: list[GraphRef] = []
    created_at: datetime


# --------------------------------------------------------- regulatory changes ---
class RegulatoryChangeBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    regulator: str = "SBP"
    circular_ref: str = ""
    source_url: str = ""
    issued_date: date | None = None
    effective_date: date | None = None
    summary: str = ""
    applicability: Applicability = Applicability.pending
    impact_assessment: str = ""
    status: RegChangeStatus = RegChangeStatus.identified
    owner: str = ""
    priority: Criticality = Criticality.medium
    department: str = ""
    workflow_status: WorkflowState = WorkflowState.draft


class RegulatoryChangeCreate(RegulatoryChangeBase):
    pass


class RegulatoryChangeUpdate(BaseModel):
    title: str | None = None
    regulator: str | None = None
    circular_ref: str | None = None
    source_url: str | None = None
    issued_date: date | None = None
    effective_date: date | None = None
    summary: str | None = None
    applicability: Applicability | None = None
    impact_assessment: str | None = None
    status: RegChangeStatus | None = None
    owner: str | None = None
    priority: Criticality | None = None
    department: str | None = None
    workflow_status: WorkflowState | None = None


class RegulatoryChangeRead(RegulatoryChangeBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    obligation_count: int
    days_to_effective: int | None = None
    is_overdue: bool
    created_at: datetime
    obligations: list[ObligationRead] = []


# --------------------------------------------------------- regulatory returns ---
class RegulatoryReturnBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    regulator: str = "SBP"
    description: str = ""
    frequency: ReviewFrequency = ReviewFrequency.quarterly
    owner: str = ""
    department: str = ""
    submission_channel: str = ""
    next_due_date: date | None = None
    last_submitted_date: date | None = None
    status: ReturnStatus = ReturnStatus.upcoming
    workflow_status: WorkflowState = WorkflowState.draft


class RegulatoryReturnCreate(RegulatoryReturnBase):
    pass


class RegulatoryReturnUpdate(BaseModel):
    name: str | None = None
    regulator: str | None = None
    description: str | None = None
    frequency: ReviewFrequency | None = None
    owner: str | None = None
    department: str | None = None
    submission_channel: str | None = None
    next_due_date: date | None = None
    last_submitted_date: date | None = None
    status: ReturnStatus | None = None
    workflow_status: WorkflowState | None = None


class RegulatoryReturnRead(RegulatoryReturnBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    is_overdue: bool
    days_to_due: int | None = None
    created_at: datetime


# ------------------------------------------------------------------- summary ---
class RegChangeSummary(BaseModel):
    changes_by_status: dict[str, int]
    total_changes: int
    changes_open: int
    changes_in_implementation: int
    changes_overdue: int
    obligations_total: int
    obligations_open: int
    obligations_met: int
    returns_total: int
    returns_due_30: int
    returns_due_60: int
    returns_due_90: int
    returns_overdue: int
