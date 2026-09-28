from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import WorkflowState
from app.schemas.common import GraphRef
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
from app.schemas.tenant_settings import currency_or_default


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


class RulingRead(RulingBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    is_review_overdue: bool
    created_at: datetime
    # Reverse of IslamicProduct.approving_ruling: the products this fatwa approves.
    # Filled on the record endpoints (GET/POST/PATCH by id); empty in list pages.
    products: list[GraphRef] = []


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


class ProductRead(ProductBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime
    approving_ruling: GraphRef | None = None
    # Reverse of ShariahReview.product: the Shariah reviews that covered this product.
    # Filled on the record endpoints (GET/POST/PATCH by id); empty in list pages.
    reviews: list[GraphRef] = []


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


class ReviewRead(ReviewBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    finding_count: int
    open_finding_count: int
    snc_income_total: float
    created_at: datetime
    findings: list[ShariahFindingRead] = []
    product: GraphRef | None = None


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


class CharityCreate(CharityBase):
    _ccy = field_validator("currency")(currency_or_default)


class CharityUpdate(BaseModel):
    description: str | None = None
    amount: float | None = None
    currency: str | None = None
    source_finding_id: uuid.UUID | None = None
    beneficiary: str | None = None
    status: CharityStatus | None = None
    disbursement_date: date | None = None
    notes: str | None = None

    _ccy = field_validator("currency")(currency_or_default)


class CharityRead(CharityBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime
