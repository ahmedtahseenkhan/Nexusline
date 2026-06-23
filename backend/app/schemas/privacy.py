from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import DpiaStatus, LawfulBasis, ReviewFrequency, RopaStatus


class Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str = ""
    title: str = ""
    reference: str = ""


class RopaBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    purpose: str = ""
    status: RopaStatus = RopaStatus.draft
    workflow_status: WorkflowState = WorkflowState.draft
    lawful_basis: LawfulBasis = LawfulBasis.consent
    data_subjects: str = ""
    data_categories: str = ""
    data_types: str = ""
    collection_methods: str = ""
    volume: str = ""
    special_category: bool = False
    retention_period: str = ""
    archiving_driver: str = ""
    recipients: str = ""
    security_measures: str = ""
    accuracy: str = ""
    right_to_be_informed: str = ""
    right_to_access: str = ""
    right_to_rectification: str = ""
    right_to_erasure: str = ""
    right_to_portability: str = ""
    right_to_object: str = ""
    controller: str = ""
    processor: str = ""
    dpo: str = ""
    business_unit_id: uuid.UUID | None = None
    cross_border_transfer: bool = False
    origin: str = ""
    transfer_destinations: str = ""
    transfer_safeguard: str = ""
    dpia_required: bool = False
    dpia_status: DpiaStatus = DpiaStatus.not_required
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    review_date: date | None = None


class RopaCreate(RopaBase):
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    risk_ids: list[uuid.UUID] = Field(default_factory=list)
    process_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)


class RopaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    purpose: str | None = None
    status: RopaStatus | None = None
    workflow_status: WorkflowState | None = None
    lawful_basis: LawfulBasis | None = None
    data_subjects: str | None = None
    data_categories: str | None = None
    data_types: str | None = None
    collection_methods: str | None = None
    volume: str | None = None
    special_category: bool | None = None
    retention_period: str | None = None
    archiving_driver: str | None = None
    recipients: str | None = None
    security_measures: str | None = None
    accuracy: str | None = None
    right_to_be_informed: str | None = None
    right_to_access: str | None = None
    right_to_rectification: str | None = None
    right_to_erasure: str | None = None
    right_to_portability: str | None = None
    right_to_object: str | None = None
    controller: str | None = None
    processor: str | None = None
    dpo: str | None = None
    business_unit_id: uuid.UUID | None = None
    cross_border_transfer: bool | None = None
    origin: str | None = None
    transfer_destinations: str | None = None
    transfer_safeguard: str | None = None
    dpia_required: bool | None = None
    dpia_status: DpiaStatus | None = None
    review_frequency: ReviewFrequency | None = None
    review_date: date | None = None
    asset_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None
    process_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None


class RopaRead(RopaBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    has_transfer_gap: bool
    dpia_outstanding: bool
    business_unit: Ref | None = None
    assets: list[Ref] = []
    risks: list[Ref] = []
    processes: list[Ref] = []
    policies: list[Ref] = []
    created_at: datetime
