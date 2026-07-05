from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.esg import EnvRiskCategory, EsgPillar, EsgStatus


# ---------------------------------------------------------------- ESG assessments ---
class EsgAssessmentBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    pillar: EsgPillar = EsgPillar.environmental
    category: str = ""
    metric: str = ""
    target_value: str = ""
    current_value: str = ""
    unit: str = ""
    status: EsgStatus = EsgStatus.not_started
    owner: str = ""
    period: str = ""
    sbp_green_banking_ref: str = ""
    workflow_status: WorkflowState = WorkflowState.draft


class EsgAssessmentCreate(EsgAssessmentBase):
    pass


class EsgAssessmentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    pillar: EsgPillar | None = None
    category: str | None = None
    metric: str | None = None
    target_value: str | None = None
    current_value: str | None = None
    unit: str | None = None
    status: EsgStatus | None = None
    owner: str | None = None
    period: str | None = None
    sbp_green_banking_ref: str | None = None
    workflow_status: WorkflowState | None = None


class EsgAssessmentRead(EsgAssessmentBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    progress_note: str
    created_at: datetime


# ----------------------------------------------------- environmental risk ratings ---
class EnvRatingBase(BaseModel):
    entity_name: str = Field(min_length=1, max_length=255)
    sector: str = ""
    risk_category: EnvRiskCategory = EnvRiskCategory.low
    assessment: str = ""
    mitigation: str = ""
    rating_date: date | None = None
    assessor: str = ""


class EnvRatingCreate(EnvRatingBase):
    pass


class EnvRatingUpdate(BaseModel):
    entity_name: str | None = None
    sector: str | None = None
    risk_category: EnvRiskCategory | None = None
    assessment: str | None = None
    mitigation: str | None = None
    rating_date: date | None = None
    assessor: str | None = None


class EnvRatingRead(EnvRatingBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime
