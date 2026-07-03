from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import (
    AmlScope,
    Criticality,
    ReviewFrequency,
    SarStatus,
    ScreeningCaseStatus,
    ScreeningMatchStatus,
    ScreeningType,
)


# ---------------------------------------------------------------- screening ---
class ScreeningBase(BaseModel):
    subject_name: str = Field(min_length=1, max_length=255)
    subject_type: str = "customer"
    screening_type: ScreeningType = ScreeningType.sanctions
    lists_checked: str = ""
    match_status: ScreeningMatchStatus = ScreeningMatchStatus.no_match
    risk_rating: Criticality = Criticality.low
    screened_date: date | None = None
    disposition: str = ""
    reviewer: str = ""
    status: ScreeningCaseStatus = ScreeningCaseStatus.open
    workflow_status: WorkflowState = WorkflowState.draft


class ScreeningCreate(ScreeningBase):
    pass


class ScreeningUpdate(BaseModel):
    subject_name: str | None = None
    subject_type: str | None = None
    screening_type: ScreeningType | None = None
    lists_checked: str | None = None
    match_status: ScreeningMatchStatus | None = None
    risk_rating: Criticality | None = None
    screened_date: date | None = None
    disposition: str | None = None
    reviewer: str | None = None
    status: ScreeningCaseStatus | None = None
    workflow_status: WorkflowState | None = None


class ScreeningRead(ScreeningBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime


# ---------------------------------------------------------------- STR / SAR ---
class SarBase(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    activity_description: str = ""
    suspicion_reason: str = ""
    amount: float | None = None
    currency: str = "PKR"
    analyst: str = ""
    priority: Criticality = Criticality.medium
    detected_date: date | None = None
    deadline: date | None = None
    filed_date: date | None = None
    fmu_reference: str = ""
    status: SarStatus = SarStatus.draft
    workflow_status: WorkflowState = WorkflowState.draft


class SarCreate(SarBase):
    pass


class SarUpdate(BaseModel):
    subject: str | None = None
    activity_description: str | None = None
    suspicion_reason: str | None = None
    amount: float | None = None
    currency: str | None = None
    analyst: str | None = None
    priority: Criticality | None = None
    detected_date: date | None = None
    deadline: date | None = None
    filed_date: date | None = None
    fmu_reference: str | None = None
    status: SarStatus | None = None
    workflow_status: WorkflowState | None = None


class SarRead(SarBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    is_overdue: bool
    created_at: datetime


# --------------------------------------------------------- risk assessments ---
class AmlRiskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    scope: AmlScope = AmlScope.customer
    subject: str = ""
    inherent_risk: Criticality = Criticality.medium
    mitigating_controls: str = ""
    residual_risk: Criticality = Criticality.medium
    assessor: str = ""
    assessment_date: date | None = None
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    next_review_date: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class AmlRiskCreate(AmlRiskBase):
    pass


class AmlRiskUpdate(BaseModel):
    title: str | None = None
    scope: AmlScope | None = None
    subject: str | None = None
    inherent_risk: Criticality | None = None
    mitigating_controls: str | None = None
    residual_risk: Criticality | None = None
    assessor: str | None = None
    assessment_date: date | None = None
    review_frequency: ReviewFrequency | None = None
    next_review_date: date | None = None
    workflow_status: WorkflowState | None = None


class AmlRiskRead(AmlRiskBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    is_review_overdue: bool
    created_at: datetime
