from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EvidenceStatus, EvidenceType
from app.schemas.control import ControlRef


class EvidenceBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    evidence_type: EvidenceType = EvidenceType.document
    reference: str = ""
    status: EvidenceStatus = EvidenceStatus.valid
    collected_at: date | None = None
    valid_until: date | None = None


class EvidenceCreate(EvidenceBase):
    control_id: uuid.UUID


class EvidenceRead(EvidenceBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    control: ControlRef | None = None
    created_at: datetime
