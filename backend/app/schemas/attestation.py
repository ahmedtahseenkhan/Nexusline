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
    #: Decision 9: this attestation only counts once a second person confirms it.
    confirmation_required: bool = False
    #: Decision 9: the owner this attestation stands in for, when someone else signed it.
    on_behalf_of_id: uuid.UUID | None = None
    on_behalf_of_name: str = ""
    created_at: datetime


class AttestationStatus(BaseModel):
    #: never | current | overdue — judged on the last *complete* attestation, so an
    #: attestation still waiting for its second signature has not reset the clock.
    status: str
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
    #: the attest call's own gates in its order: write permission, the draft rule, the
    #: approval gate, then four-eyes against whoever entered the record where an
    #: administrator configured it. The panel never infers it.
    can_attest: bool = False
    #: Why not, when ``can_attest`` is false — the sentence the attest call would refuse
    #: with (a friendlier one for a missing permission). ``None`` when the user may attest.
    blocked_reason: str | None = None
    # --- decision 9 (2026-09-20): the owner certifies; a second signature makes it count ---
    #: Whether an attestation of *this* record needs an independent second signature.
    confirmation_required: bool = False
    #: Why it does, in words ("Key control"); ``None`` when it does not.
    confirmation_reason: str | None = None
    #: True while the newest attestation is signed but still waiting for that signature.
    awaiting_confirmation: bool = False
    #: Who signed it and when, so the page can say "Attested by X on <date> — awaiting
    #: independent confirmation" in the tenant's own date format.
    awaiting_by: str | None = None
    awaiting_at: date | None = None
    #: The owner the last complete attestation was signed for, when it was not the signer.
    last_on_behalf_of: str | None = None
