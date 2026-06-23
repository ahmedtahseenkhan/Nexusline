from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApprovalStatus


class ApprovalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    entity_type: str = ""
    entity_id: uuid.UUID | None = None
    entity_label: str = ""
    link: str = ""
    approver: str = ""
    due_date: date | None = None


class ApprovalDecision(BaseModel):
    approve: bool
    comment: str = ""


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    title: str
    description: str
    status: ApprovalStatus
    entity_type: str
    entity_id: uuid.UUID | None
    entity_label: str
    link: str
    approver: str
    requested_by_email: str
    decided_by_email: str
    decided_at: date | None
    decision_comment: str
    due_date: date | None
    is_overdue: bool
    created_at: datetime
