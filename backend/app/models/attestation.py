"""Review / attestation engine — polymorphic periodic sign-off on any record.

Each POST appends an Attestation row (an immutable audit trail). A record's current
review state is derived from its most recent *complete* attestation's ``next_due`` vs
today.

Decision 9 (2026-09-20) — an attestation is the record owner's own certification:

* The owner is the expected signer. When somebody else signs instead, the row records
  whose certification it stands in for (``on_behalf_of_id`` / ``on_behalf_of_name``), so
  the record and every export read "attested by X on behalf of Y".
* Independence comes from the approval (decision 6) and from the second signature. On a
  high-stakes record — a key control, a critical or high residual risk, a material
  outsourcing arrangement or third party, any policy — that second signature is
  **required**: ``confirmation_required`` is set when the attestation is written, and
  until ``confirmed_by_id`` is filled the attestation is signed but not complete, so the
  record's review clock has not reset.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ReviewFrequency


class Attestation(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "attestations"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    attested_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    attested_by_email: Mapped[str] = mapped_column(String(255), default="")
    attested_at: Mapped[date] = mapped_column(Date, nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="")
    frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual,
        nullable=False,
    )
    next_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    # What was certified, in words, and over what — an attestation that says nothing
    # about what the signer looked at proves nothing to an examiner.
    statement: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Second signature: an independent person confirming the attestation. Required —
    # the attestation is not complete without it — when ``confirmation_required`` is set.
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    confirmed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmation_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Decision 9: the record owner whose certification this stands in for, when someone
    # else signed. Null when the signer is the owner (or the record names no owner).
    on_behalf_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    #: The owner's name as it read when the attestation was signed, so the trail and
    #: exports say who it was for without a join (and keep saying so if they leave).
    on_behalf_of_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    def complete(self) -> bool:
        """Whether this attestation counts: signed, and confirmed when confirmation is
        required. Only a complete attestation resets the record's review clock."""
        return not self.confirmation_required or self.confirmed_by_id is not None
