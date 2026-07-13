from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import GraphRef

from app.models.enums import (
    AssetClass,
    AssetDependencyType,
    AssetEnvironment,
    AssetReviewStatus,
    Criticality,
    DiscoverySource,
    ReviewFrequency,
    WorkflowStatus,
)


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


# ---------------------------------------------------------------- IT tags
class AssetTagBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = ""
    description: str = ""
    color: str = ""


class AssetTagCreate(AssetTagBase):
    pass


class AssetTagRead(AssetTagBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


# ---------------------------------------------- information ↔ IT dependency
class AssetDependencyCreate(BaseModel):
    information_asset_id: uuid.UUID
    it_asset_id: uuid.UUID
    relationship_type: AssetDependencyType = AssetDependencyType.hosts
    notes: str = ""


class AssetDependencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    relationship_type: AssetDependencyType
    notes: str
    information_asset: LinkRef | None = None
    it_asset: LinkRef | None = None


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
    asset_class: AssetClass = AssetClass.information_asset
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
    # information-asset (primary) fields
    business_value: Criticality = Criticality.medium
    information_owner: str = ""
    data_categories: str = ""
    records_volume: str = ""
    self_assessed: bool = False
    assessed_by: str = ""
    assessed_date: date | None = None
    # IT-asset (supporting) fields
    replacement_cost: float = 0
    currency: str = "PKR"
    rto_hours: int | None = None
    rpo_hours: int | None = None
    environment: AssetEnvironment = AssetEnvironment.production
    location: str = ""
    hostname: str = ""
    ip_address: str = ""
    serial_number: str = ""
    manufacturer: str = ""
    model_number: str = ""
    os_version: str = ""
    # discovery / automation
    discovery_source: DiscoverySource = DiscoverySource.manual
    external_id: str = ""
    auto_discovered: bool = False
    last_seen: date | None = None
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    next_review_date: date | None = None
    workflow_status: WorkflowStatus = WorkflowStatus.draft
    classification_ids: list[uuid.UUID] = []
    tag_ids: list[uuid.UUID] = []
    process_ids: list[uuid.UUID] = []
    legal_ids: list[uuid.UUID] = []
    requirement_ids: list[uuid.UUID] = []
    incident_ids: list[uuid.UUID] = []
    exception_ids: list[uuid.UUID] = []
    related_ids: list[uuid.UUID] = []
    # Asset.risks is a viewonly reverse view (the writable side lives on Risk.assets);
    # the API writes the risk_assets join table directly when this is provided.
    risk_ids: list[uuid.UUID] = []


class AssetCreate(AssetWrite):
    pass


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    asset_class: AssetClass | None = None
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
    business_value: Criticality | None = None
    information_owner: str | None = None
    data_categories: str | None = None
    records_volume: str | None = None
    self_assessed: bool | None = None
    assessed_by: str | None = None
    assessed_date: date | None = None
    replacement_cost: float | None = None
    currency: str | None = None
    rto_hours: int | None = None
    rpo_hours: int | None = None
    environment: AssetEnvironment | None = None
    location: str | None = None
    hostname: str | None = None
    ip_address: str | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    model_number: str | None = None
    os_version: str | None = None
    discovery_source: DiscoverySource | None = None
    external_id: str | None = None
    auto_discovered: bool | None = None
    last_seen: date | None = None
    review_frequency: ReviewFrequency | None = None
    next_review_date: date | None = None
    workflow_status: WorkflowStatus | None = None
    classification_ids: list[uuid.UUID] | None = None
    tag_ids: list[uuid.UUID] | None = None
    process_ids: list[uuid.UUID] | None = None
    legal_ids: list[uuid.UUID] | None = None
    requirement_ids: list[uuid.UUID] | None = None
    incident_ids: list[uuid.UUID] | None = None
    exception_ids: list[uuid.UUID] | None = None
    related_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None


class AssetRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    asset_class: AssetClass
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
    # information-asset (primary) fields
    business_value: Criticality
    information_owner: str
    data_categories: str
    records_volume: str
    self_assessed: bool
    assessed_by: str
    assessed_date: date | None
    # IT-asset (supporting) fields
    replacement_cost: float
    currency: str
    rto_hours: int | None
    rpo_hours: int | None
    environment: AssetEnvironment
    location: str
    hostname: str
    ip_address: str
    serial_number: str
    manufacturer: str
    model_number: str
    os_version: str
    # discovery / automation
    discovery_source: DiscoverySource
    external_id: str
    auto_discovered: bool
    last_seen: date | None
    # computed criticality (see model properties)
    cost_band: Criticality
    intrinsic_criticality: Criticality
    derived_criticality: Criticality
    effective_criticality: Criticality
    review_frequency: ReviewFrequency
    next_review_date: date | None
    last_review_date: date | None
    expired_reviews: int
    review_status: str
    workflow_status: WorkflowStatus
    classifications: list[ClassificationRef] = []
    tags: list[AssetTagRead] = []
    dependencies: list[AssetDependencyRead] = []
    processes: list[LinkRef] = []
    legals: list[LinkRef] = []
    requirements: list[LinkRef] = []
    incidents: list[LinkRef] = []
    exceptions: list[LinkRef] = []
    related_assets: list[LinkRef] = []
    risks: list[LinkRef] = []
    # Reverse links (read-only).
    vendors: list[GraphRef] = []
    access_reviews: list[GraphRef] = []
    controls: list[GraphRef] = []
    threats: list[GraphRef] = []
    vulnerabilities: list[GraphRef] = []
    reviews: list[AssetReviewRead] = []
    risk_count: int = 0
    review_count: int = 0
    created_at: datetime


class AssetRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
