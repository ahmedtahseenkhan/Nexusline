from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class EvidenceUpdate(BaseModel):
    """Partial update — every field optional; control can be re-pointed."""

    control_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    evidence_type: EvidenceType | None = None
    reference: str | None = None
    status: EvidenceStatus | None = None
    collected_at: date | None = None
    valid_until: date | None = None


class EvidenceRead(EvidenceBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    control: ControlRef | None = None
    is_expired: bool = False
    created_at: datetime

    @model_validator(mode="after")
    def _derive_expiry(self) -> "EvidenceRead":
        # Surface expiry to the UI without a DB column: explicit expired status,
        # or a valid_until date that has already passed.
        self.is_expired = self.status == EvidenceStatus.expired or (
            self.valid_until is not None and self.valid_until < date.today()
        )
        return self
