from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import GraphRef

from app.models.base import WorkflowState
from app.models.enums import AssessmentStatus, Criticality, ReviewFrequency, Severity, VendorStatus


class VendorRefItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


# ----------------------------------------------------------------- vendor types
class VendorTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class VendorTypeRead(VendorTypeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


# -------------------------------------------------------------- service contracts
class ServiceContractCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    value: float | None = Field(default=None, ge=0)
    start_date: date | None = None
    end_date: date | None = None


class ServiceContractRead(ServiceContractCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    is_expired: bool
    created_at: datetime


# ----------------------------------------------------------------------- vendor
class VendorBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = ""
    type_id: uuid.UUID | None = None
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    website: str = ""
    location: str = ""
    criticality: Criticality = Criticality.medium
    status: VendorStatus = VendorStatus.active
    workflow_status: WorkflowState = WorkflowState.draft
    risk_rating: Severity | None = None
    shares_data: bool = False
    assessment_status: AssessmentStatus = AssessmentStatus.not_started
    last_assessed_at: date | None = None
    onboarded_at: date | None = None
    offboarded_at: date | None = None
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    next_review_date: date | None = None


class VendorCreate(VendorBase):
    risk_ids: list[uuid.UUID] = []
    asset_ids: list[uuid.UUID] = []


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    type_id: uuid.UUID | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    website: str | None = None
    location: str | None = None
    criticality: Criticality | None = None
    status: VendorStatus | None = None
    workflow_status: WorkflowState | None = None
    risk_rating: Severity | None = None
    shares_data: bool | None = None
    assessment_status: AssessmentStatus | None = None
    last_assessed_at: date | None = None
    onboarded_at: date | None = None
    offboarded_at: date | None = None
    review_frequency: ReviewFrequency | None = None
    next_review_date: date | None = None
    risk_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None


class VendorRead(VendorBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: VendorTypeRead | None = None
    contracts: list[ServiceContractRead] = []
    risks: list[VendorRefItem] = []
    assets: list[VendorRefItem] = []
    # Reverse links (read-only).
    incidents: list[GraphRef] = []
    assessments: list[GraphRef] = []
    outsourcing_arrangements: list[GraphRef] = []
    contract_count: int = 0
    active_contract_value: float = 0.0
    created_at: datetime
