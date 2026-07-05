from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import ControlEffectiveness
from app.models.fraud import (
    FraudCaseStatus,
    FraudChannel,
    FraudControlCategory,
    FraudControlStatus,
    FraudRiskStatus,
    FraudScheme,
    PerpetratorType,
)


# ------------------------------------------------------------- fraud risks ---
class FraudRiskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    scheme: FraudScheme = FraudScheme.asset_misappropriation
    channel: FraudChannel = FraudChannel.branch
    business_line: str = ""
    inherent_likelihood: int = Field(default=1, ge=1, le=5)
    inherent_impact: int = Field(default=1, ge=1, le=5)
    control_description: str = ""
    control_effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    residual_likelihood: int = Field(default=1, ge=1, le=5)
    residual_impact: int = Field(default=1, ge=1, le=5)
    red_flags: str = ""
    owner: str = ""
    status: FraudRiskStatus = FraudRiskStatus.open
    workflow_status: WorkflowState = WorkflowState.draft


class FraudRiskCreate(FraudRiskBase):
    pass


class FraudRiskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    scheme: FraudScheme | None = None
    channel: FraudChannel | None = None
    business_line: str | None = None
    inherent_likelihood: int | None = Field(default=None, ge=1, le=5)
    inherent_impact: int | None = Field(default=None, ge=1, le=5)
    control_description: str | None = None
    control_effectiveness: ControlEffectiveness | None = None
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_impact: int | None = Field(default=None, ge=1, le=5)
    red_flags: str | None = None
    owner: str | None = None
    status: FraudRiskStatus | None = None
    workflow_status: WorkflowState | None = None


class FraudRiskRead(FraudRiskBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    inherent_score: int
    residual_score: int
    created_at: datetime


# ------------------------------------------------------------- fraud cases ---
class FraudCaseBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    scheme: FraudScheme = FraudScheme.asset_misappropriation
    channel: FraudChannel = FraudChannel.branch
    status: FraudCaseStatus = FraudCaseStatus.reported
    reported_date: date | None = None
    discovery_date: date | None = None
    incident_date: date | None = None
    amount_involved: float = 0
    amount_recovered: float = 0
    currency: str = "PKR"
    perpetrator_type: PerpetratorType = PerpetratorType.unknown
    customer_impacted: bool = False
    customers_affected: int = Field(default=0, ge=0)
    reported_to_regulator: bool = False
    regulator_ref: str = ""
    investigator: str = ""
    root_cause: str = ""
    resolution: str = ""
    workflow_status: WorkflowState = WorkflowState.draft


class FraudCaseCreate(FraudCaseBase):
    pass


class FraudCaseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    scheme: FraudScheme | None = None
    channel: FraudChannel | None = None
    status: FraudCaseStatus | None = None
    reported_date: date | None = None
    discovery_date: date | None = None
    incident_date: date | None = None
    amount_involved: float | None = None
    amount_recovered: float | None = None
    currency: str | None = None
    perpetrator_type: PerpetratorType | None = None
    customer_impacted: bool | None = None
    customers_affected: int | None = Field(default=None, ge=0)
    reported_to_regulator: bool | None = None
    regulator_ref: str | None = None
    investigator: str | None = None
    root_cause: str | None = None
    resolution: str | None = None
    workflow_status: WorkflowState | None = None


class FraudCaseRead(FraudCaseBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    net_loss: float
    created_at: datetime


# --------------------------------------------- SBP digital-fraud checklist ---
class FraudControlCheckBase(BaseModel):
    requirement: str = Field(min_length=1)
    sbp_reference: str = ""
    category: FraudControlCategory = FraudControlCategory.behavioral_monitoring
    implemented: bool = False
    status: FraudControlStatus = FraudControlStatus.not_implemented
    owner: str = ""
    evidence_note: str = ""
    target_date: date | None = None


class FraudControlCheckCreate(FraudControlCheckBase):
    pass


class FraudControlCheckUpdate(BaseModel):
    requirement: str | None = None
    sbp_reference: str | None = None
    category: FraudControlCategory | None = None
    implemented: bool | None = None
    status: FraudControlStatus | None = None
    owner: str | None = None
    evidence_note: str | None = None
    target_date: date | None = None


class FraudControlCheckRead(FraudControlCheckBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime
