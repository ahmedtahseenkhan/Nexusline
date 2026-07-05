from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import BaselEventType
from app.models.scenario import CapitalStatus, ScenarioStatus


# ----------------------------------------------------------- scenario analysis ---
class ScenarioBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    basel_event_type: BaselEventType = BaselEventType.execution_delivery_process_management
    business_line: str = ""
    description: str = ""
    frequency_per_year: float = 0
    typical_loss: float = 0
    worst_case_loss: float = 0
    currency: str = "PKR"
    confidence_level: str = ""
    participants: str = ""
    assumptions: str = ""
    owner: str = ""
    status: ScenarioStatus = ScenarioStatus.draft
    review_date: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class ScenarioCreate(ScenarioBase):
    pass


class ScenarioUpdate(BaseModel):
    title: str | None = None
    basel_event_type: BaselEventType | None = None
    business_line: str | None = None
    description: str | None = None
    frequency_per_year: float | None = None
    typical_loss: float | None = None
    worst_case_loss: float | None = None
    currency: str | None = None
    confidence_level: str | None = None
    participants: str | None = None
    assumptions: str | None = None
    owner: str | None = None
    status: ScenarioStatus | None = None
    review_date: date | None = None
    workflow_status: WorkflowState | None = None


class ScenarioRead(ScenarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    expected_annual_loss: float
    created_at: datetime


# --------------------------------------------------------- capital calculation ---
class CapitalBase(BaseModel):
    period: str = ""
    business_indicator: float = 0
    avg_annual_loss: float = 0
    currency: str = "PKR"
    notes: str = ""
    status: CapitalStatus = CapitalStatus.draft
    workflow_status: WorkflowState = WorkflowState.draft


class CapitalCreate(CapitalBase):
    pass


class CapitalUpdate(BaseModel):
    period: str | None = None
    business_indicator: float | None = None
    avg_annual_loss: float | None = None
    currency: str | None = None
    notes: str | None = None
    status: CapitalStatus | None = None
    workflow_status: WorkflowState | None = None


class CapitalRead(CapitalBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    bic: float
    loss_component: float
    ilm: float
    orc: float
    created_at: datetime


# ------------------------------------------------------------------ summary ---
class ScenarioSummaryRow(BaseModel):
    basel_event_type: str
    count: int
    expected_annual_loss: float


class CapitalSnapshot(BaseModel):
    reference: str
    period: str
    bic: float
    loss_component: float
    ilm: float
    orc: float
    currency: str


class ScenarioSummary(BaseModel):
    rows: list[ScenarioSummaryRow]
    total_expected_annual_loss: float
    total_count: int
    approved_count: int
    latest_capital: CapitalSnapshot | None
