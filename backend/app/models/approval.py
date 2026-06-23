"""Approval Workflows — a generalized approval inbox. Any record (referenced by
entity_type + entity_id) can be submitted for approval, decided, tracked and audited."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ApprovalStatus


class ApprovalRequest(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "approval_requests"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status"),
        default=ApprovalStatus.pending,
        nullable=False,
    )

    # What is being approved (optional deep-link to a record)
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    entity_label: Mapped[str] = mapped_column(String(255), default="")
    link: Mapped[str] = mapped_column(String(255), default="")  # frontend path

    approver: Mapped[str] = mapped_column(String(200), default="")  # assigned approver
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    requested_by_email: Mapped[str] = mapped_column(String(255), default="")

    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decided_by_email: Mapped[str] = mapped_column(String(255), default="")
    decided_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    decision_comment: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def is_overdue(self) -> bool:
        return (
            self.status == ApprovalStatus.pending
            and self.due_date is not None
            and self.due_date < date.today()
        )
