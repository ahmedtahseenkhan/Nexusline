"""Policy Management — document repository with document types, versioning, a review
cycle, acknowledgments (portal), related documents, and links to the controls /
requirements / risks the policy supports. Carries the eramba record envelope."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, String, Table, Text, UniqueConstraint, Uuid
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
from app.models.enums import PolicyDocType, PolicyStatus, ReviewFrequency

policies_related = Table(
    "policies_related",
    Base.metadata,
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
    Column("related_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)


class Policy(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "policies"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)  # eramba "index"
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(255), default="")  # short_description
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1024), default="")  # external document link
    category: Mapped[str] = mapped_column(String(100), default="", index=True)
    document_type: Mapped[PolicyDocType] = mapped_column(
        SAEnum(PolicyDocType, name="policy_doc_type"), default=PolicyDocType.policy, nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    status: Mapped[PolicyStatus] = mapped_column(
        SAEnum(PolicyStatus, name="policy_status"), default=PolicyStatus.draft, nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    label_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("asset_labels.id", ondelete="SET NULL"), nullable=True
    )
    use_attachments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    review_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"), default=ReviewFrequency.annual, nullable=False
    )
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expired_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    label: Mapped["AssetLabel | None"] = relationship(lazy="selectin")  # noqa: F821
    acknowledgments: Mapped[list["PolicyAcknowledgment"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan", lazy="selectin"
    )
    reviews: Mapped[list["PolicyReview"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan", lazy="selectin",
        order_by="PolicyReview.planned_date.desc()",
    )
    related: Mapped[list["Policy"]] = relationship(
        secondary=policies_related,
        primaryjoin=lambda: Policy.id == policies_related.c.policy_id,
        secondaryjoin=lambda: (policies_related.c.related_id == Policy.id) & (Policy.deleted == False),
        lazy="selectin",
    )
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        "Control", secondary="control_policies", lazy="selectin", viewonly=True,
        secondaryjoin="and_(control_policies.c.control_id == Control.id, Control.deleted == False)",
    )
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        "Requirement", secondary="requirement_policies", lazy="selectin", viewonly=True,
        secondaryjoin="and_(requirement_policies.c.requirement_id == Requirement.id, Requirement.deleted == False)",
    )
    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary="risk_policies", lazy="selectin", viewonly=True,
        secondaryjoin="and_(risk_policies.c.risk_id == Risk.id, Risk.deleted == False)",
    )

    @property
    def acknowledgment_count(self) -> int:
        return len(self.acknowledgments)

    @property
    def is_review_overdue(self) -> bool:
        return self.next_review_date is not None and self.next_review_date < date.today()


class PolicyReview(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, Base):
    """A scheduled/completed review in a policy's review cycle."""

    __tablename__ = "policy_reviews"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    planned_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(200), default="")
    comments: Mapped[str] = mapped_column(Text, default="")

    policy: Mapped[Policy] = relationship(back_populates="reviews")


class PolicyAcknowledgment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "policy_acknowledgments"
    __table_args__ = (
        UniqueConstraint("policy_id", "user_id", name="uq_policy_ack_user"),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), default="")

    policy: Mapped[Policy] = relationship(back_populates="acknowledgments")
