from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccessDecision, AccessReviewStatus, ReviewFrequency


class Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class ItemCreate(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    display_name: str = ""
    access: str = ""
    comment: str = ""


class ItemUpdate(BaseModel):
    """Edit a line item's identity/access fields (decisions go through ItemDecision)."""

    username: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = None
    access: str | None = None
    comment: str | None = None


class ItemDecision(BaseModel):
    decision: AccessDecision
    comment: str = ""


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    review_id: uuid.UUID
    username: str
    display_name: str
    access: str
    decision: AccessDecision
    comment: str
    decided_by: str
    decided_at: date | None


class ReviewBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    status: AccessReviewStatus = AccessReviewStatus.draft
    reviewer: str = ""
    system_name: str = ""
    asset_id: uuid.UUID | None = None
    due_date: date | None = None
    frequency: ReviewFrequency = ReviewFrequency.quarterly


class ReviewCreate(ReviewBase):
    pass


class ReviewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: AccessReviewStatus | None = None
    reviewer: str | None = None
    system_name: str | None = None
    asset_id: uuid.UUID | None = None
    due_date: date | None = None
    frequency: ReviewFrequency | None = None


class ReviewRead(ReviewBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    next_review_date: date | None
    completed_at: date | None
    total_items: int
    reviewed_count: int
    keep_count: int
    revoke_count: int
    completion_pct: float
    is_overdue: bool
    asset: Ref | None = None
    items: list[ItemRead] = []
    created_at: datetime
