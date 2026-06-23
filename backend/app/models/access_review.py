"""Account Reviews / Access Certification — periodic campaigns where a reviewer
certifies (keep/revoke) each account's access to a system."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkflowMixin,
)
from app.models.enums import AccessDecision, AccessReviewStatus, ReviewFrequency


class AccessReview(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "access_reviews"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[AccessReviewStatus] = mapped_column(
        SAEnum(AccessReviewStatus, name="access_review_status"),
        default=AccessReviewStatus.draft,
        nullable=False,
    )
    reviewer: Mapped[str] = mapped_column(String(200), default="")
    system_name: Mapped[str] = mapped_column(String(200), default="")
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.quarterly,
        nullable=False,
    )
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    asset: Mapped["Asset | None"] = relationship("Asset", lazy="selectin")  # noqa: F821
    items: Mapped[list["AccessReviewItem"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AccessReviewItem.username",
    )

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def reviewed_count(self) -> int:
        return sum(1 for i in self.items if i.decision != AccessDecision.pending)

    @property
    def keep_count(self) -> int:
        return sum(1 for i in self.items if i.decision == AccessDecision.keep)

    @property
    def revoke_count(self) -> int:
        return sum(1 for i in self.items if i.decision == AccessDecision.revoke)

    @property
    def completion_pct(self) -> float:
        return round(100 * self.reviewed_count / self.total_items, 1) if self.total_items else 0.0

    @property
    def is_overdue(self) -> bool:
        return (
            self.due_date is not None
            and self.due_date < date.today()
            and self.status != AccessReviewStatus.completed
        )


class AccessReviewItem(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "access_review_items"

    review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("access_reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    access: Mapped[str] = mapped_column(Text, default="")  # roles / permissions held
    decision: Mapped[AccessDecision] = mapped_column(
        SAEnum(AccessDecision, name="access_decision"),
        default=AccessDecision.pending,
        nullable=False,
    )
    comment: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str] = mapped_column(String(200), default="")
    decided_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    review: Mapped[AccessReview] = relationship(back_populates="items")
