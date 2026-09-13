from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReviewFrequency


class AttestationCreate(BaseModel):
    #: Ignored for records that carry their own review cycle (risk, policy, vendor, asset): the
    #: cadence comes from the record's ``review_frequency`` so there is one clock.
    frequency: ReviewFrequency = ReviewFrequency.annual
    comment: str = ""
    #: What is being certified. Blank means the entity type's default statement.
    statement: str = Field(default="", max_length=2000)
    #: What the signer looked at (period, sample, documents). Optional.
    scope: str = Field(default="", max_length=2000)


class AttestationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    attested_by_id: uuid.UUID | None = None
    attested_by_email: str
    attested_at: date
    comment: str
    frequency: ReviewFrequency
    next_due: date | None
    statement: str = ""
    scope: str = ""
    confirmed_by_id: uuid.UUID | None = None
    #: Resolved from ``confirmed_by_id`` by the endpoint; not a column.
    confirmed_by_email: str | None = None
    confirmed_at: date | None = None
    created_at: datetime


class AttestationStatus(BaseModel):
    status: str  # never | current | overdue
    last_attested_at: date | None = None
    last_by: str | None = None
    next_due: date | None = None
    frequency: ReviewFrequency | None = None
    history: list[AttestationRead]
    #: True when the record carries its own review cycle; the panel then shows that
    #: cycle instead of offering a separate attestation frequency.
    native_review: bool = False
    #: The statement the panel pre-fills for this entity type.
    default_statement: str = ""
    #: Whether the *current user* may attest this record now, decided by the server with
    #: the attest call's own gates in its order: write permission, the owner / draft rule,
    #: then four-eyes against whoever entered the record. The panel never infers it.
    can_attest: bool = False
    #: Why not, when ``can_attest`` is false — the sentence the attest call would refuse
    #: with (a friendlier one for a missing permission). ``None`` when the user may attest.
    blocked_reason: str | None = None
