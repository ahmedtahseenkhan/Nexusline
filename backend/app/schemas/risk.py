from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.base import WorkflowState
from app.schemas.common import GraphRef
from app.models.enums import (
    AcceptanceStatus,
    ReviewFrequency,
    RiskStatus,
    Severity,
    TreatmentStrategy,
)
from app.schemas.asset import AssetRef
from app.schemas.control import ControlRef
from app.schemas.threat import NamedRef
from app.services.risk_scoring import severity_for_score

_Scale = Field(ge=1, le=5)


class RiskLinkRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""


class RiskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = ""
    status: RiskStatus = RiskStatus.draft
    inherent_likelihood: int = _Scale
    inherent_impact: int = _Scale
    # Residual scoring (after controls) — optional on create, set on assessment too
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_impact: int | None = Field(default=None, ge=1, le=5)
    treatment_strategy: TreatmentStrategy | None = None
    treatment_description: str = ""
    treatment_owner: str = ""
    treatment_deadline: date | None = None
    treatment_cost: float | None = Field(default=None, ge=0)
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    owner_id: uuid.UUID | None = None
    # Quantitative (FAIR): events/year and $ per event
    annual_loss_frequency: float | None = Field(default=None, ge=0)
    single_loss_expectancy: float | None = Field(default=None, ge=0)


class RiskCreate(RiskBase):
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    control_ids: list[uuid.UUID] = Field(default_factory=list)
    threat_ids: list[uuid.UUID] = Field(default_factory=list)
    vulnerability_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)
    incident_ids: list[uuid.UUID] = Field(default_factory=list)


class RiskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    status: RiskStatus | None = None
    inherent_likelihood: int | None = Field(default=None, ge=1, le=5)
    inherent_impact: int | None = Field(default=None, ge=1, le=5)
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_impact: int | None = Field(default=None, ge=1, le=5)
    treatment_strategy: TreatmentStrategy | None = None
    treatment_description: str | None = None
    treatment_owner: str | None = None
    treatment_deadline: date | None = None
    treatment_cost: float | None = Field(default=None, ge=0)
    review_frequency: ReviewFrequency | None = None
    workflow_status: WorkflowState | None = None
    workflow_owner: str | None = None
    owner_id: uuid.UUID | None = None
    annual_loss_frequency: float | None = Field(default=None, ge=0)
    single_loss_expectancy: float | None = Field(default=None, ge=0)
    asset_ids: list[uuid.UUID] | None = None
    control_ids: list[uuid.UUID] | None = None
    threat_ids: list[uuid.UUID] | None = None
    vulnerability_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None
    incident_ids: list[uuid.UUID] | None = None


class RiskAssessment(BaseModel):
    """Record residual scoring after considering controls."""

    residual_likelihood: int = _Scale
    residual_impact: int = _Scale


class RiskAcceptanceCreate(BaseModel):
    rationale: str = Field(min_length=1)
    expires_at: date | None = None


class RiskAcceptanceDecision(BaseModel):
    approve: bool
    note: str = ""


class RiskAcceptanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    risk_id: uuid.UUID
    requested_by: uuid.UUID | None
    approver_id: uuid.UUID | None
    rationale: str
    status: AcceptanceStatus
    expires_at: date | None
    decided_at: date | None
    created_at: datetime


class RiskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    title: str
    description: str
    category: str
    status: RiskStatus
    owner_id: uuid.UUID | None

    inherent_likelihood: int
    inherent_impact: int
    inherent_score: int | None
    residual_likelihood: int | None
    residual_impact: int | None
    residual_score: int | None

    annual_loss_frequency: float | None
    single_loss_expectancy: float | None
    annual_loss_expectancy: float | None

    treatment_strategy: TreatmentStrategy | None
    treatment_description: str
    treatment_owner: str
    treatment_deadline: date | None
    treatment_cost: float | None
    review_frequency: ReviewFrequency
    last_review_date: date | None
    next_review_date: date | None
    expired_reviews: int
    workflow_status: WorkflowState
    workflow_owner: str

    assets: list[AssetRef] = []
    controls: list[ControlRef] = []
    threats: list[NamedRef] = []
    vulnerabilities: list[NamedRef] = []
    policies: list[RiskLinkRef] = []
    incidents: list[RiskLinkRef] = []
    acceptances: list[RiskAcceptanceRead] = []

    # Reverse links — records elsewhere that point at this risk (read-only).
    requirements: list[GraphRef] = []
    exceptions: list[GraphRef] = []
    vendors: list[GraphRef] = []
    projects: list[GraphRef] = []
    goals: list[GraphRef] = []
    processing_activities: list[GraphRef] = []
    audit_findings: list[GraphRef] = []
    kris: list[GraphRef] = []
    loss_events: list[GraphRef] = []

    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def inherent_severity(self) -> Severity | None:
        return severity_for_score(self.inherent_score)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def residual_severity(self) -> Severity | None:
        return severity_for_score(self.residual_score)


class RiskSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    appetite_score: int
    tolerance_score: int


class RiskSettingUpdate(BaseModel):
    appetite_score: int = Field(ge=1, le=25)
    tolerance_score: int = Field(ge=1, le=25)


class RiskAggregateRow(BaseModel):
    category: str
    count: int
    max_inherent_score: int | None
    max_residual_score: int | None
    breaches: int
    exposure: float  # sum of annual loss expectancy


class RiskAggregate(BaseModel):
    rows: list[RiskAggregateRow]
    total_exposure: float
    appetite_score: int
    tolerance_score: int
