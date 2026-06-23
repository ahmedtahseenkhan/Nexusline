"""Review / attestation engine — polymorphic periodic sign-off on any record.

Each POST appends an Attestation row (an immutable audit trail). A record's current
review state is derived from its most recent attestation's ``next_due`` vs today."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, String, Text, Uuid
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
