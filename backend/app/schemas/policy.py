from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import GraphRef

from app.models.base import WorkflowState
from app.models.enums import PolicyDocType, PolicyStatus, ReviewFrequency


class PolicyRefItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


class PolicyBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str = ""
    body: str = ""
    url: str = ""
    category: str = ""
    document_type: PolicyDocType = PolicyDocType.policy
    version: str = "1.0"
    status: PolicyStatus = PolicyStatus.draft
    workflow_status: WorkflowState = WorkflowState.draft
    owner: str = ""
    label_id: uuid.UUID | None = None
    use_attachments: bool = False
    review_frequency: ReviewFrequency = ReviewFrequency.annual


class PolicyCreate(PolicyBase):
    related_ids: list[uuid.UUID] = []
    controls_ids: list[uuid.UUID] = []
    requirements_ids: list[uuid.UUID] = []
    risks_ids: list[uuid.UUID] = []


class PolicyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = None
    body: str | None = None
    url: str | None = None
    category: str | None = None
    document_type: PolicyDocType | None = None
    version: str | None = None
    status: PolicyStatus | None = None
    workflow_status: WorkflowState | None = None
    owner: str | None = None
    label_id: uuid.UUID | None = None
    use_attachments: bool | None = None
    review_frequency: ReviewFrequency | None = None
    related_ids: list[uuid.UUID] | None = None
    controls_ids: list[uuid.UUID] | None = None
    requirements_ids: list[uuid.UUID] | None = None
    risks_ids: list[uuid.UUID] | None = None


class PolicyReviewCreate(BaseModel):
    planned_date: date
    reviewer: str = ""
    comments: str = ""


class PolicyReviewComplete(BaseModel):
    comments: str = ""


class PolicyReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    planned_date: date
    actual_review_date: date | None
    reviewer: str
    comments: str
    created_at: datetime


class PolicyRead(PolicyBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    next_review_date: date | None
    last_review_date: date | None
    published_at: date | None
    expired_reviews: int
    is_review_overdue: bool
    acknowledgment_count: int
    related: list[PolicyRefItem] = []
    controls: list[PolicyRefItem] = []
    requirements: list[PolicyRefItem] = []
    risks: list[PolicyRefItem] = []
    reviews: list[PolicyReviewRead] = []
    # Reverse links (read-only).
    exceptions: list[GraphRef] = []
    projects: list[GraphRef] = []
    goals: list[GraphRef] = []
    processing_activities: list[GraphRef] = []
    created_at: datetime


class PolicyAcknowledgmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    policy_id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    created_at: datetime
