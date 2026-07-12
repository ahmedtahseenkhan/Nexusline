from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import GraphRef

from app.models.base import WorkflowState
from app.models.enums import (
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    ReviewFrequency,
    TestResult,
)


class ControlLinkRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


class ControlBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    reference: str = ""
    description: str = ""
    objective: str = ""
    owner: str = ""
    control_type: ControlType = ControlType.production
    classification: str = ""
    documentation_url: str = ""
    status: ControlStatus = ControlStatus.planned
    effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    workflow_status: WorkflowState = WorkflowState.draft
    opex: float | None = Field(default=None, ge=0)
    capex: float | None = Field(default=None, ge=0)
    resource_utilization: int | None = Field(default=None, ge=0, le=100)
    audit_frequency: ReviewFrequency = ReviewFrequency.annual
    audit_metric: str = ""
    audit_success_criteria: str = ""
    maintenance_frequency: ReviewFrequency = ReviewFrequency.quarterly


class ControlCreate(ControlBase):
    # Optional explicit schedule overrides (otherwise derived from the frequency).
    next_audit_date: date | None = None
    next_maintenance_date: date | None = None
    # Relationship inputs.
    policy_ids: list[uuid.UUID] = []
    requirement_ids: list[uuid.UUID] = []
    risk_ids: list[uuid.UUID] = []


class ControlUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    reference: str | None = None
    description: str | None = None
    objective: str | None = None
    owner: str | None = None
    control_type: ControlType | None = None
    classification: str | None = None
    documentation_url: str | None = None
    status: ControlStatus | None = None
    effectiveness: ControlEffectiveness | None = None
    workflow_status: WorkflowState | None = None
    opex: float | None = Field(default=None, ge=0)
    capex: float | None = Field(default=None, ge=0)
    resource_utilization: int | None = Field(default=None, ge=0, le=100)
    audit_frequency: ReviewFrequency | None = None
    audit_metric: str | None = None
    audit_success_criteria: str | None = None
    next_audit_date: date | None = None
    maintenance_frequency: ReviewFrequency | None = None
    next_maintenance_date: date | None = None
    policy_ids: list[uuid.UUID] | None = None
    requirement_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None


class ControlRead(ControlBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    next_audit_date: date | None = None
    last_audit_date: date | None = None
    next_maintenance_date: date | None = None
    last_maintenance_date: date | None = None
    audit_count: int = 0
    last_audit_result: TestResult | None = None
    is_audit_overdue: bool = False
    maintenance_count: int = 0
    last_maintenance_result: TestResult | None = None
    is_maintenance_overdue: bool = False
    policies: list[ControlLinkRef] = []
    requirements: list[ControlLinkRef] = []
    risks: list[ControlLinkRef] = []
    # Reverse links (read-only).
    incidents: list[GraphRef] = []
    exceptions: list[GraphRef] = []
    projects: list[GraphRef] = []


class ControlRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    reference: str


# --------------------------------------------------------------- control tests
class ControlAuditCreate(BaseModel):
    result: TestResult = TestResult.not_assessed
    planned_date: date | None = None
    conducted_date: date | None = None
    metric_description: str = ""
    success_criteria: str = ""
    result_description: str = ""
    improvement: str = ""
    auditor: str = ""


class ControlAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    result: TestResult
    planned_date: date | None
    conducted_date: date | None
    metric_description: str
    success_criteria: str
    result_description: str
    improvement: str
    auditor: str
    created_at: datetime


class ControlMaintenanceCreate(BaseModel):
    result: TestResult = TestResult.not_assessed
    task: str = ""
    planned_date: date | None = None
    conducted_date: date | None = None
    conclusion: str = ""


class ControlMaintenanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    result: TestResult
    task: str
    planned_date: date | None
    conducted_date: date | None
    conclusion: str
    created_at: datetime
