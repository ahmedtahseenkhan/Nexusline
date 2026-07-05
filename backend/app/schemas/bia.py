from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.bia import BiaStatus, DependencyType
from app.models.enums import Criticality


# --------------------------------------------------------------- dependencies ---
class BiaDependencyBase(BaseModel):
    dependency_type: DependencyType = DependencyType.application
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    criticality: Criticality = Criticality.medium
    rto_hours: int | None = None
    single_point_of_failure: bool = False


class BiaDependencyCreate(BiaDependencyBase):
    pass


class BiaDependencyUpdate(BaseModel):
    dependency_type: DependencyType | None = None
    name: str | None = None
    description: str | None = None
    criticality: Criticality | None = None
    rto_hours: int | None = None
    single_point_of_failure: bool | None = None


class BiaDependencyRead(BiaDependencyBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    bia_id: uuid.UUID
    created_at: datetime


# ------------------------------------------------------------- BIA assessments ---
class BiaBase(BaseModel):
    process_name: str = Field(min_length=1, max_length=255)
    business_unit: str = ""
    owner: str = ""
    description: str = ""
    criticality: Criticality = Criticality.medium
    rto_hours: int | None = None
    rpo_hours: int | None = None
    mtpd_hours: int | None = None
    peak_periods: str = ""
    financial_impact_24h: float = 0
    financial_impact_1week: float = 0
    currency: str = "PKR"
    operational_impact: str = ""
    reputational_impact: str = ""
    regulatory_impact: str = ""
    legal_impact: str = ""
    minimum_resources: str = ""
    recovery_strategy: str = ""
    workaround: str = ""
    status: BiaStatus = BiaStatus.draft
    assessment_date: date | None = None
    next_review_date: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class BiaCreate(BiaBase):
    pass


class BiaUpdate(BaseModel):
    process_name: str | None = None
    business_unit: str | None = None
    owner: str | None = None
    description: str | None = None
    criticality: Criticality | None = None
    rto_hours: int | None = None
    rpo_hours: int | None = None
    mtpd_hours: int | None = None
    peak_periods: str | None = None
    financial_impact_24h: float | None = None
    financial_impact_1week: float | None = None
    currency: str | None = None
    operational_impact: str | None = None
    reputational_impact: str | None = None
    regulatory_impact: str | None = None
    legal_impact: str | None = None
    minimum_resources: str | None = None
    recovery_strategy: str | None = None
    workaround: str | None = None
    status: BiaStatus | None = None
    assessment_date: date | None = None
    next_review_date: date | None = None
    workflow_status: WorkflowState | None = None


class BiaRead(BiaBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    dependency_count: int
    is_review_overdue: bool
    rto_band: str
    created_at: datetime
    dependencies: list[BiaDependencyRead] = []
