from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssetReviewStatus, Criticality, ReviewFrequency, WorkflowStatus


class LinkRef(BaseModel):
    id: uuid.UUID
    label: str


class ClassificationRef(BaseModel):
    id: uuid.UUID
    name: str
    value: float
    type_name: str


# ---------------------------------------------------------------- lookups
class AssetMediaTypeBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class AssetMediaTypeCreate(AssetMediaTypeBase):
    pass


class AssetMediaTypeRead(AssetMediaTypeBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    editable: bool


class AssetClassificationBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    criteria: str = ""
    value: float = 1.0


class AssetClassificationCreate(AssetClassificationBase):
    type_id: uuid.UUID


class AssetClassificationRead(AssetClassificationBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type_id: uuid.UUID


class AssetClassificationTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class AssetClassificationTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    classifications: list[AssetClassificationRead] = []


class AssetLabelBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    color: str = ""


class AssetLabelCreate(AssetLabelBase):
    pass


class AssetLabelRead(AssetLabelBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


# ---------------------------------------------------------------- reviews
class AssetReviewCreate(BaseModel):
    reviewer: str = ""
    scheduled_date: date
    comments: str = ""


class AssetReviewComplete(BaseModel):
    outcome: str = "passed"
    comments: str = ""


class AssetReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reviewer: str
    scheduled_date: date
    actual_date: date | None
    status: AssetReviewStatus
    outcome: str
    comments: str
    created_at: datetime


# ---------------------------------------------------------------- asset
class AssetWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    media_type_id: uuid.UUID | None = None
    label_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    guardian_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    confidentiality: Criticality = Criticality.medium
    integrity: Criticality = Criticality.medium
    availability: Criticality = Criticality.medium
    criticality: Criticality = Criticality.medium
    potential_liabilities: str = ""
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    next_review_date: date | None = None
    workflow_status: WorkflowStatus = WorkflowStatus.draft
    classification_ids: list[uuid.UUID] = []
    process_ids: list[uuid.UUID] = []
    legal_ids: list[uuid.UUID] = []
    requirement_ids: list[uuid.UUID] = []
    incident_ids: list[uuid.UUID] = []
    exception_ids: list[uuid.UUID] = []
    related_ids: list[uuid.UUID] = []


class AssetCreate(AssetWrite):
    pass


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    media_type_id: uuid.UUID | None = None
    label_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    guardian_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    confidentiality: Criticality | None = None
    integrity: Criticality | None = None
    availability: Criticality | None = None
    criticality: Criticality | None = None
    potential_liabilities: str | None = None
    review_frequency: ReviewFrequency | None = None
    next_review_date: date | None = None
    workflow_status: WorkflowStatus | None = None
    classification_ids: list[uuid.UUID] | None = None
    process_ids: list[uuid.UUID] | None = None
    legal_ids: list[uuid.UUID] | None = None
    requirement_ids: list[uuid.UUID] | None = None
    incident_ids: list[uuid.UUID] | None = None
    exception_ids: list[uuid.UUID] | None = None
    related_ids: list[uuid.UUID] | None = None


class AssetRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    media_type: LinkRef | None = None
    label: LinkRef | None = None
    owner: LinkRef | None = None
    guardian: LinkRef | None = None
    user: LinkRef | None = None
    confidentiality: Criticality
    integrity: Criticality
    availability: Criticality
    criticality: Criticality
    classification: Criticality
    potential_liabilities: str
    review_frequency: ReviewFrequency
    next_review_date: date | None
    last_review_date: date | None
    expired_reviews: int
    review_status: str
    workflow_status: WorkflowStatus
    classifications: list[ClassificationRef] = []
    processes: list[LinkRef] = []
    legals: list[LinkRef] = []
    requirements: list[LinkRef] = []
    incidents: list[LinkRef] = []
    exceptions: list[LinkRef] = []
    related_assets: list[LinkRef] = []
    risks: list[LinkRef] = []
    reviews: list[AssetReviewRead] = []
    risk_count: int = 0
    review_count: int = 0
    created_at: datetime


class AssetRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
