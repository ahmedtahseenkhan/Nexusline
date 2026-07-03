from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import (
    CharityStatus,
    IslamicProductStatus,
    ReviewFrequency,
    Severity,
    ShariahFindingStatus,
    ShariahMode,
    ShariahReviewStatus,
    ShariahRulingStatus,
)


# ------------------------------------------------------------------- rulings ---
class RulingBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    subject: str = ""
    ruling_text: str = ""
    basis: str = ""
    status: ShariahRulingStatus = ShariahRulingStatus.draft
    approved_by: str = ""
    issued_date: date | None = None
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    next_review_date: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class RulingCreate(RulingBase):
    pass


class RulingUpdate(BaseModel):
    title: str | None = None
    subject: str | None = None
    ruling_text: str | None = None
    basis: str | None = None
    status: ShariahRulingStatus | None = None
    approved_by: str | None = None
    issued_date: date | None = None
    review_frequency: ReviewFrequency | None = None
    next_review_date: date | None = None
    workflow_status: WorkflowState | None = None


class RulingRead(RulingBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    is_review_overdue: bool
    created_at: datetime


# ------------------------------------------------------------------ products ---
class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    shariah_mode: ShariahMode = ShariahMode.murabaha
    structure: str = ""
    status: IslamicProductStatus = IslamicProductStatus.in_development
    owner: str = ""
    launch_date: date | None = None
    approving_ruling_id: uuid.UUID | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    shariah_mode: ShariahMode | None = None
    structure: str | None = None
    status: IslamicProductStatus | None = None
    owner: str | None = None
    launch_date: date | None = None
    approving_ruling_id: uuid.UUID | None = None
    workflow_status: WorkflowState | None = None


class ProductRead(ProductBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime


# ------------------------------------------------------------------ findings ---
class ShariahFindingBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    severity: Severity = Severity.medium
    snc_income_amount: float | None = None
    recommendation: str = ""
    management_response: str = ""
    action_owner: str = ""
    due_date: date | None = None
    status: ShariahFindingStatus = ShariahFindingStatus.open


class ShariahFindingCreate(ShariahFindingBase):
    pass


class ShariahFindingUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    severity: Severity | None = None
    snc_income_amount: float | None = None
    recommendation: str | None = None
    management_response: str | None = None
    action_owner: str | None = None
    due_date: date | None = None
    status: ShariahFindingStatus | None = None
    closed_date: date | None = None


class ShariahFindingRead(ShariahFindingBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    review_id: uuid.UUID
    reference: str
    closed_date: date | None
    is_overdue: bool
    created_at: datetime


# ------------------------------------------------------------------- reviews ---
class ReviewBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    scope: str = ""
    review_type: str = "product"
    reviewer: str = ""
    status: ShariahReviewStatus = ShariahReviewStatus.planned
    period_start: date | None = None
    period_end: date | None = None
    planned_date: date | None = None
    conclusion: str = ""
    rating: Severity | None = None
    product_id: uuid.UUID | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class ReviewCreate(ReviewBase):
    pass


class ReviewUpdate(BaseModel):
    title: str | None = None
    scope: str | None = None
    review_type: str | None = None
    reviewer: str | None = None
    status: ShariahReviewStatus | None = None
    period_start: date | None = None
    period_end: date | None = None
    planned_date: date | None = None
    conclusion: str | None = None
    rating: Severity | None = None
    product_id: uuid.UUID | None = None
    workflow_status: WorkflowState | None = None


class ReviewRead(ReviewBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    finding_count: int
    open_finding_count: int
    snc_income_total: float
    created_at: datetime
    findings: list[ShariahFindingRead] = []


# ------------------------------------------------------------------- charity ---
class CharityBase(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    amount: float = 0
    currency: str = "PKR"
    source_finding_id: uuid.UUID | None = None
    beneficiary: str = ""
    status: CharityStatus = CharityStatus.pending
    disbursement_date: date | None = None
    notes: str = ""
    workflow_status: WorkflowState = WorkflowState.draft


class CharityCreate(CharityBase):
    pass


class CharityUpdate(BaseModel):
    description: str | None = None
    amount: float | None = None
    currency: str | None = None
    source_finding_id: uuid.UUID | None = None
    beneficiary: str | None = None
    status: CharityStatus | None = None
    disbursement_date: date | None = None
    notes: str | None = None
    workflow_status: WorkflowState | None = None


class CharityRead(CharityBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime
