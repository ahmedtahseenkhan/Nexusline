from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EvidenceStatus, EvidenceType
from app.schemas.control import ControlRef


NOT_COLLECTED_MESSAGE = (
    "Evidence can only be marked valid once it has been collected. "
    "Set the collected date, or leave the status as pending."
)


def evidence_status_problem(status: EvidenceStatus | None, collected_at: date | None) -> str | None:
    """Why this status/date pair is inconsistent, or None if it is fine.

    "Valid" is a claim that something was gathered and checked; with no collection date
    it is a claim about nothing, and it is what a reviewer sees first in the register.
    """
    if status == EvidenceStatus.valid and collected_at is None:
        return NOT_COLLECTED_MESSAGE
    return None


class EvidenceBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    evidence_type: EvidenceType = EvidenceType.document
    reference: str = ""
    status: EvidenceStatus = EvidenceStatus.pending
    collected_at: date | None = None
    valid_until: date | None = None


class EvidenceCreate(EvidenceBase):
    control_id: uuid.UUID

    @model_validator(mode="after")
    def _valid_needs_collection(self) -> "EvidenceCreate":
        problem = evidence_status_problem(self.status, self.collected_at)
        if problem:
            raise ValueError(problem)
        return self


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
    # What the register should show: "expired", "not_collected" (no collection date, so
    # nothing has been gathered whatever the stored status says), or the stored status.
    display_status: str = ""
    created_at: datetime

    @model_validator(mode="after")
    def _derive_expiry(self) -> "EvidenceRead":
        # Surface expiry to the UI without a DB column: explicit expired status,
        # or a valid_until date that has already passed.
        self.is_expired = self.status == EvidenceStatus.expired or (
            self.valid_until is not None and self.valid_until < date.today()
        )
        if self.is_expired:
            self.display_status = "expired"
        elif self.collected_at is None:
            self.display_status = "not_collected"
        else:
            self.display_status = self.status.value
        return self
