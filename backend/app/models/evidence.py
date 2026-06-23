"""Evidence collection — artifacts attached to controls for audit-readiness.

Because controls are reused across requirements/frameworks, evidence collected once
on a control demonstrates every requirement that control maps to ("collect once,
satisfy many").
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EvidenceStatus, EvidenceType


class Evidence(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "evidence"

    control_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("controls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    evidence_type: Mapped[EvidenceType] = mapped_column(
        SAEnum(EvidenceType, name="evidence_type"), default=EvidenceType.document, nullable=False
    )
    reference: Mapped[str] = mapped_column(String(500), default="")  # URL or location
    status: Mapped[EvidenceStatus] = mapped_column(
        SAEnum(EvidenceStatus, name="evidence_status"),
        default=EvidenceStatus.valid,
        nullable=False,
    )
    collected_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    control: Mapped["Control"] = relationship(lazy="selectin")  # noqa: F821
