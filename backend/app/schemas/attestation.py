from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ReviewFrequency


class AttestationCreate(BaseModel):
    frequency: ReviewFrequency = ReviewFrequency.annual
    comment: str = ""


class AttestationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    attested_by_email: str
    attested_at: date
    comment: str
    frequency: ReviewFrequency
    next_due: date | None
    created_at: datetime


class AttestationStatus(BaseModel):
    status: str  # never | current | overdue
    last_attested_at: date | None = None
    last_by: str | None = None
    next_due: date | None = None
    frequency: ReviewFrequency | None = None
    history: list[AttestationRead]
