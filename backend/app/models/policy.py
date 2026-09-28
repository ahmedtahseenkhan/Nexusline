"""Policy Management — document repository with document types, versioning, a review
cycle, acknowledgments (portal), related documents, and links to the controls /
requirements / risks the policy supports. Carries the eramba record envelope."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
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


policy_business_units = Table(
    "policy_business_units",
    Base.metadata,
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
    Column("business_unit_id", Uuid, ForeignKey("business_units.id", ondelete="CASCADE"), primary_key=True),
)

policy_roles = Table(
    "policy_roles",
    Base.metadata,
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Policy(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "policies"
    # Phase 2: document governance.
    approving_authority_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("committees.id", ondelete="SET NULL"), nullable=True, index=True
    )  # board or committee that approves it
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("policies.id", ondelete="SET NULL"), nullable=True, index=True
    )  # the policy this one replaces

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)  # eramba "index"
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(255), default="")  # short_description
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1024), default="")  # external document link
    category: Mapped[str] = mapped_column(String(100), default="", index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: governed lookup value; replaces free-text `category`
    document_type: Mapped[PolicyDocType] = mapped_column(
        SAEnum(PolicyDocType, name="policy_doc_type"), default=PolicyDocType.policy, nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    status: Mapped[PolicyStatus] = mapped_column(
        SAEnum(PolicyStatus, name="policy_status"), default=PolicyStatus.draft, nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `owner`
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
    # Reverse (read-only) links into the graph.
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(  # noqa: F821
        "ExceptionRecord", secondary="exception_policies", lazy="selectin", viewonly=True,
        # An archived exception is not on the register: never show it as a live link.
        secondaryjoin="and_(exception_policies.c.exception_id == ExceptionRecord.id, ExceptionRecord.deleted == False)",
    )
    projects: Mapped[list["Project"]] = relationship(  # noqa: F821
        "Project", secondary="project_policies", lazy="selectin", viewonly=True,
    )
    goals: Mapped[list["Goal"]] = relationship(  # noqa: F821
        "Goal", secondary="goal_policies", lazy="selectin", viewonly=True,
    )
    processing_activities: Mapped[list["ProcessingActivity"]] = relationship(  # noqa: F821
        "ProcessingActivity", secondary="ropa_policies", lazy="selectin", viewonly=True,
    )
    # Regulatory obligations this policy satisfies (set from the obligation's side).
    obligations: Mapped[list["Obligation"]] = relationship(  # noqa: F821
        "Obligation", secondary="obligation_policies", lazy="selectin", viewonly=True,
    )
    # Phase 2: who it applies to. Users are not linked to business units, so the units
    # are recorded (and reported) but acknowledgement targeting reads the roles.
    business_units: Mapped[list["BusinessUnit"]] = relationship(  # noqa: F821
        "BusinessUnit", secondary=policy_business_units, lazy="selectin",
        secondaryjoin="and_(policy_business_units.c.business_unit_id == BusinessUnit.id, BusinessUnit.deleted == False)",
    )
    roles: Mapped[list["Role"]] = relationship(  # noqa: F821
        "Role", secondary=policy_roles, lazy="selectin",
    )
    # For CSV export only: read models expose ``approving_authority_ref`` /
    # ``supersedes_ref`` / ``superseded_by``, filled by the router in one query each, so
    # these are never lazy-loaded in a handler.
    approving_authority: Mapped["Committee | None"] = relationship(  # noqa: F821
        "Committee", foreign_keys=[approving_authority_id], lazy="select",
    )
    supersedes: Mapped["Policy | None"] = relationship(
        "Policy", foreign_keys=[supersedes_id], remote_side="Policy.id", lazy="select",
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
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `reviewer`
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
