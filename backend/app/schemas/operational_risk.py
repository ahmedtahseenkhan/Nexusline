from __future__ import annotations

import uuid
from datetime import date, datetime

from app.schemas.common import GraphRef
from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import (
    BaselEventType,
    ControlEffectiveness,
    KriDirection,
    KriStatus,
    LossEventStatus,
    RcsaStatus,
    ReviewFrequency,
)


# ------------------------------------------------------------- RCSA risk lines ---
class RcsaRiskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    category: str = ""
    inherent_likelihood: int = Field(default=1, ge=1, le=5)
    inherent_impact: int = Field(default=1, ge=1, le=5)
    control_description: str = ""
    control_effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    residual_likelihood: int = Field(default=1, ge=1, le=5)
    residual_impact: int = Field(default=1, ge=1, le=5)
    action: str = ""
    action_owner: str = ""
    due_date: date | None = None


class RcsaRiskCreate(RcsaRiskBase):
    risk_id: uuid.UUID | None = None
    control_id: uuid.UUID | None = None


class RcsaRiskUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    inherent_likelihood: int | None = Field(default=None, ge=1, le=5)
    inherent_impact: int | None = Field(default=None, ge=1, le=5)
    control_description: str | None = None
    control_effectiveness: ControlEffectiveness | None = None
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_impact: int | None = Field(default=None, ge=1, le=5)
    action: str | None = None
    action_owner: str | None = None
    due_date: date | None = None
    risk_id: uuid.UUID | None = None
    control_id: uuid.UUID | None = None


class RcsaRiskRead(RcsaRiskBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    assessment_id: uuid.UUID
    inherent_score: int
    residual_score: int
    risk_id: uuid.UUID | None = None
    control_id: uuid.UUID | None = None
    risk: GraphRef | None = None
    control: GraphRef | None = None
    created_at: datetime


# --------------------------------------------------------------- RCSA campaigns ---
class RcsaBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    business_unit: str = ""
    process: str = ""
    assessor: str = ""
    status: RcsaStatus = RcsaStatus.planned
    period: str = ""
    due_date: date | None = None
    completed_date: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class RcsaCreate(RcsaBase):
    pass


class RcsaUpdate(BaseModel):
    title: str | None = None
    business_unit: str | None = None
    process: str | None = None
    assessor: str | None = None
    status: RcsaStatus | None = None
    period: str | None = None
    due_date: date | None = None
    completed_date: date | None = None
    workflow_status: WorkflowState | None = None


class RcsaRead(RcsaBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    risk_count: int
    is_overdue: bool
    created_at: datetime
    risks: list[RcsaRiskRead] = []


# --------------------------------------------------------------- KRI measurements ---
class MeasurementCreate(BaseModel):
    value: float
    as_of_date: date | None = None
    notes: str = ""


class MeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    value: float
    as_of_date: date | None
    notes: str
    created_at: datetime


# ------------------------------------------------------------------------- KRIs ---
class KriBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = ""
    business_area: str = ""
    owner: str = ""
    unit: str = ""
    frequency: ReviewFrequency = ReviewFrequency.monthly
    direction: KriDirection = KriDirection.higher_is_worse
    warning_threshold: float | None = None
    limit_threshold: float | None = None
    current_value: float | None = None
    last_measured_date: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class KriCreate(KriBase):
    risk_ids: list[uuid.UUID] = []


class KriUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    business_area: str | None = None
    owner: str | None = None
    unit: str | None = None
    frequency: ReviewFrequency | None = None
    direction: KriDirection | None = None
    warning_threshold: float | None = None
    limit_threshold: float | None = None
    current_value: float | None = None
    last_measured_date: date | None = None
    workflow_status: WorkflowState | None = None
    risk_ids: list[uuid.UUID] | None = None


class KriRead(KriBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    status: KriStatus
    is_breached: bool
    created_at: datetime
    risks: list[GraphRef] = []
    measurements: list[MeasurementRead] = []


# ------------------------------------------------------------------ loss events ---
class LossEventBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    basel_event_type: BaselEventType = BaselEventType.execution_delivery_process_management
    business_line: str = ""
    gross_loss: float = 0
    recovery: float = 0
    currency: str = "PKR"
    status: LossEventStatus = LossEventStatus.open
    occurrence_date: date | None = None
    discovery_date: date | None = None
    accounting_date: date | None = None
    root_cause: str = ""
    action_owner: str = ""
    workflow_status: WorkflowState = WorkflowState.draft


class LossEventCreate(LossEventBase):
    incident_id: uuid.UUID | None = None
    risk_ids: list[uuid.UUID] = []


class LossEventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    basel_event_type: BaselEventType | None = None
    business_line: str | None = None
    gross_loss: float | None = None
    recovery: float | None = None
    currency: str | None = None
    status: LossEventStatus | None = None
    occurrence_date: date | None = None
    discovery_date: date | None = None
    accounting_date: date | None = None
    root_cause: str | None = None
    action_owner: str | None = None
    workflow_status: WorkflowState | None = None
    incident_id: uuid.UUID | None = None
    risk_ids: list[uuid.UUID] | None = None


class LossEventRead(LossEventBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    net_loss: float
    incident_id: uuid.UUID | None = None
    incident: GraphRef | None = None
    risks: list[GraphRef] = []
    created_at: datetime
