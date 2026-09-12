from __future__ import annotations

import uuid
from datetime import date, datetime

from app.schemas.common import GraphRef, LookupRef, UnitRef, UserRef
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

# Phase 1 picker fields: each ``*_id`` wins over the legacy text field it sits beside when
# both are sent. The text is still accepted this release (older clients, CSV import) and
# is matched to an id when it names exactly one active record; on read it holds the
# picked record's display name, or the unmatched text.
_WF_OWNER = "User who owns the approval workflow. `workflow_status` changes only through the workflow endpoints."
_ACTION_OWNER = "User who owns the action; wins over `action_owner` text."
_RISK_CATEGORY = "Value from the `risk_category` lookup list; wins over `category` text."
_ASSESSOR = "User running the assessment; wins over `assessor` text."
_RCSA_UNIT = "Business unit assessed; wins over `business_unit` text."
_PROCESS = "Process assessed (GET /processes); wins over `process` text."
_KRI_OWNER = "User who owns the indicator; wins over `owner` text."
_KRI_UNIT = "Business unit the indicator measures; wins over `business_area` text."
_KRI_CATEGORY = "Value from the `kri_category` lookup list; wins over `category` text."
_LOSS_UNIT = "Business unit (line) that suffered the loss; wins over `business_line` text."


# ------------------------------------------------------------- RCSA risk lines ---
class RcsaRiskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    category: str = ""
    category_id: uuid.UUID | None = Field(default=None, description=_RISK_CATEGORY)
    inherent_likelihood: int = Field(default=1, ge=1, le=5)
    inherent_impact: int = Field(default=1, ge=1, le=5)
    control_description: str = ""
    control_effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    residual_likelihood: int = Field(default=1, ge=1, le=5)
    residual_impact: int = Field(default=1, ge=1, le=5)
    action: str = ""
    action_owner: str = ""
    action_owner_id: uuid.UUID | None = Field(default=None, description=_ACTION_OWNER)
    due_date: date | None = None


class RcsaRiskCreate(RcsaRiskBase):
    risk_id: uuid.UUID | None = None
    control_id: uuid.UUID | None = None


class RcsaRiskUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = Field(default=None, description=_RISK_CATEGORY)
    inherent_likelihood: int | None = Field(default=None, ge=1, le=5)
    inherent_impact: int | None = Field(default=None, ge=1, le=5)
    control_description: str | None = None
    control_effectiveness: ControlEffectiveness | None = None
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_impact: int | None = Field(default=None, ge=1, le=5)
    action: str | None = None
    action_owner: str | None = None
    action_owner_id: uuid.UUID | None = Field(default=None, description=_ACTION_OWNER)
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
    category_ref: LookupRef | None = None
    action_owner_ref: UserRef | None = None
    created_at: datetime


# --------------------------------------------------------------- RCSA campaigns ---
class RcsaBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    business_unit: str = ""
    business_unit_id: uuid.UUID | None = Field(default=None, description=_RCSA_UNIT)
    process: str = ""
    process_id: uuid.UUID | None = Field(default=None, description=_PROCESS)
    assessor: str = ""
    assessor_id: uuid.UUID | None = Field(default=None, description=_ASSESSOR)
    status: RcsaStatus = RcsaStatus.planned
    period: str = ""
    due_date: date | None = None
    completed_date: date | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class RcsaCreate(RcsaBase):
    pass


class RcsaUpdate(BaseModel):
    title: str | None = None
    business_unit: str | None = None
    business_unit_id: uuid.UUID | None = Field(default=None, description=_RCSA_UNIT)
    process: str | None = None
    process_id: uuid.UUID | None = Field(default=None, description=_PROCESS)
    assessor: str | None = None
    assessor_id: uuid.UUID | None = Field(default=None, description=_ASSESSOR)
    status: RcsaStatus | None = None
    period: str | None = None
    due_date: date | None = None
    completed_date: date | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class RcsaRead(RcsaBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    business_unit_ref: UnitRef | None = None
    process_ref: UnitRef | None = None
    assessor_ref: UserRef | None = None
    workflow_owner_ref: UserRef | None = None
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
    category_id: uuid.UUID | None = Field(default=None, description=_KRI_CATEGORY)
    business_area: str = ""
    business_unit_id: uuid.UUID | None = Field(default=None, description=_KRI_UNIT)
    owner: str = ""
    owner_id: uuid.UUID | None = Field(default=None, description=_KRI_OWNER)
    unit: str = ""
    frequency: ReviewFrequency = ReviewFrequency.monthly
    direction: KriDirection = KriDirection.higher_is_worse
    warning_threshold: float | None = None
    limit_threshold: float | None = None
    current_value: float | None = None
    last_measured_date: date | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class KriCreate(KriBase):
    risk_ids: list[uuid.UUID] = []


class KriUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = Field(default=None, description=_KRI_CATEGORY)
    business_area: str | None = None
    business_unit_id: uuid.UUID | None = Field(default=None, description=_KRI_UNIT)
    owner: str | None = None
    owner_id: uuid.UUID | None = Field(default=None, description=_KRI_OWNER)
    unit: str | None = None
    frequency: ReviewFrequency | None = None
    direction: KriDirection | None = None
    warning_threshold: float | None = None
    limit_threshold: float | None = None
    current_value: float | None = None
    last_measured_date: date | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    risk_ids: list[uuid.UUID] | None = None


class KriRead(KriBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    owner_ref: UserRef | None = None
    business_unit_ref: UnitRef | None = None
    category_ref: LookupRef | None = None
    workflow_owner_ref: UserRef | None = None
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
    business_unit_id: uuid.UUID | None = Field(default=None, description=_LOSS_UNIT)
    gross_loss: float = 0
    recovery: float = 0
    currency: str = "PKR"
    status: LossEventStatus = LossEventStatus.open
    occurrence_date: date | None = None
    discovery_date: date | None = None
    accounting_date: date | None = None
    root_cause: str = ""
    action_owner: str = ""
    action_owner_id: uuid.UUID | None = Field(default=None, description=_ACTION_OWNER)
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class LossEventCreate(LossEventBase):
    incident_id: uuid.UUID | None = None
    risk_ids: list[uuid.UUID] = []


class LossEventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    basel_event_type: BaselEventType | None = None
    business_line: str | None = None
    business_unit_id: uuid.UUID | None = Field(default=None, description=_LOSS_UNIT)
    gross_loss: float | None = None
    recovery: float | None = None
    currency: str | None = None
    status: LossEventStatus | None = None
    occurrence_date: date | None = None
    discovery_date: date | None = None
    accounting_date: date | None = None
    root_cause: str | None = None
    action_owner: str | None = None
    action_owner_id: uuid.UUID | None = Field(default=None, description=_ACTION_OWNER)
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    incident_id: uuid.UUID | None = None
    risk_ids: list[uuid.UUID] | None = None


class LossEventRead(LossEventBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    business_unit_ref: UnitRef | None = None
    action_owner_ref: UserRef | None = None
    workflow_owner_ref: UserRef | None = None
    net_loss: float
    incident_id: uuid.UUID | None = None
    incident: GraphRef | None = None
    risks: list[GraphRef] = []
    created_at: datetime
