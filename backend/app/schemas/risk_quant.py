from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.risk_quant import QuantStatus


# ----------------------------------------------------------- risk quantification ---
class RiskQuantBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    scenario: str = ""
    risk_id: uuid.UUID | None = None
    asset_at_risk: str = ""
    tef_min: float = 0
    tef_likely: float = 0
    tef_max: float = 0
    lm_min: float = 0
    lm_likely: float = 0
    lm_max: float = 0
    currency: str = "PKR"
    iterations: int = Field(default=10000, ge=100, le=1_000_000)
    owner: str = ""
    notes: str = ""
    status: QuantStatus = QuantStatus.draft
    workflow_status: WorkflowState = WorkflowState.draft


class RiskQuantCreate(RiskQuantBase):
    pass


class RiskQuantUpdate(BaseModel):
    title: str | None = None
    scenario: str | None = None
    risk_id: uuid.UUID | None = None
    asset_at_risk: str | None = None
    tef_min: float | None = None
    tef_likely: float | None = None
    tef_max: float | None = None
    lm_min: float | None = None
    lm_likely: float | None = None
    lm_max: float | None = None
    currency: str | None = None
    iterations: int | None = Field(default=None, ge=100, le=1_000_000)
    owner: str | None = None
    notes: str | None = None
    status: QuantStatus | None = None
    workflow_status: WorkflowState | None = None


class RiskQuantRead(RiskQuantBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    ale_point: float
    last_mean_ale: float
    last_p90: float
    last_simulated: date | None
    created_at: datetime


# ------------------------------------------------------------- monte carlo result ---
class SimulationResult(BaseModel):
    p10: float
    p50: float
    p90: float
    mean: float
    max: float
    iterations: int
