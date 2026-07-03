"""Approval Workflows — a generalized approval inbox. Any record (referenced by
entity_type + entity_id) can be submitted for approval, decided, tracked and audited."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    # Maker-checker: how many independent approvers (checkers) must approve before the
    # request is granted (1 = classic 4-eyes; >1 = 6-eyes / multi-level authorization).
    required_approvals: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decided_by_email: Mapped[str] = mapped_column(String(255), default="")
    decided_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    decision_comment: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    actions: Mapped[list["ApprovalAction"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="ApprovalAction.created_at",
    )

    @property
    def is_overdue(self) -> bool:
        return (
            self.status == ApprovalStatus.pending
            and self.due_date is not None
            and self.due_date < date.today()
        )

    @property
    def approvals_received(self) -> int:
        """Distinct approving checkers recorded so far."""
        return len({a.actor_id for a in self.actions if a.action == "approve"})


class ApprovalAction(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One checker's vote on an approval request (the audit-grade maker-checker log).

    Each distinct approver counts once toward ``required_approvals``; a single reject
    terminates the request. The maker is never allowed to appear here when
    Segregation of Duties is enforced.
    """

    __tablename__ = "approval_actions"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(16), default="approve")  # approve | reject
    comment: Mapped[str] = mapped_column(Text, default="")

    request: Mapped[ApprovalRequest] = relationship(back_populates="actions")
