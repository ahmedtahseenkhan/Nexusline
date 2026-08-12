"""Annual audit plan and reusable audit programmes (checklists).

Two things an assurance function needs that a bare engagement list cannot provide:

* **The plan.** What the department committed to cover this year, approved by the board
  or its audit committee, and how actual delivery is tracking against it. "Did we do
  what we told the board we would do?" is the question an audit committee asks first,
  and it is unanswerable without the commitment being recorded separately from what
  happened.
* **The programme.** The test steps for a recurring audit, written once. Generating them
  from an installed framework's requirements turns "audit against ISO 27001" from a
  fortnight of authoring into one click, because the clause list is already loaded.

Neither introduces a new approval mechanism: a plan is signed off through the existing
``ApprovalRequest`` inbox, and a programme's steps instantiate as ordinary
``AuditProcedure`` rows on an engagement.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
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
)


class AuditPlanStatus(str, enum.Enum):
    """Lifecycle of the annual plan itself, not of the audits inside it."""

    draft = "draft"
    submitted = "submitted"        # sent to the board / audit committee
    approved = "approved"          # signed off — the commitment is now firm
    active = "active"              # in delivery
    closed = "closed"


class AuditPlan(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "audit_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "title", name="uq_audit_plan_year_title"),
        CheckConstraint("year BETWEEN 2000 AND 2200", name="ck_audit_plan_year"),
    )

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[AuditPlanStatus] = mapped_column(
        SAEnum(AuditPlanStatus, name="audit_plan_status"),
        default=AuditPlanStatus.draft, nullable=False,
    )
    prepared_by: Mapped[str] = mapped_column(String(200), default="")
    budget_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: The approval raised for board/committee sign-off, in the shared approvals inbox.
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approved_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    items: Mapped[list["AuditPlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin",
        order_by="AuditPlanItem.planned_quarter, AuditPlanItem.title",
    )

    @property
    def planned_count(self) -> int:
        return len(self.items)

    @property
    def started_count(self) -> int:
        """Plan lines that have become real engagements — plan-vs-actual coverage."""
        return sum(1 for i in self.items if i.engagement_id is not None)

    @property
    def coverage_pct(self) -> int:
        return round(100 * self.started_count / self.planned_count) if self.items else 0

    @property
    def planned_hours(self) -> int:
        return sum(i.budgeted_hours for i in self.items)


class AuditPlanItem(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One audit the department has committed to performing this year."""

    __tablename__ = "audit_plan_items"
    __table_args__ = (
        CheckConstraint("planned_quarter BETWEEN 1 AND 4", name="ck_audit_plan_item_quarter"),
        CheckConstraint(
            "planned_month IS NULL OR planned_month BETWEEN 1 AND 12",
            name="ck_audit_plan_item_month",
        ),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    auditable_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auditable_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="")  # why it made the plan
    planned_quarter: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: Optional month within the quarter. A plan that commits to two audits of the same
    #: unit in one month needs finer granularity than "Q1", and the calendar places a
    #: line on its month when this is set.
    planned_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budgeted_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lead_auditor: Mapped[str] = mapped_column(String(200), default="")

    #: Set when the planned audit actually starts, linking commitment to delivery.
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("audit_engagements.id", ondelete="SET NULL"), nullable=True, index=True
    )

    plan: Mapped[AuditPlan] = relationship(back_populates="items")
    auditable_unit: Mapped["AuditableUnit | None"] = relationship(lazy="selectin")  # noqa: F821


class AuditProgram(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin, Base):
    """A reusable checklist — the test steps for one kind of audit, written once."""

    __tablename__ = "audit_programs"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="", index=True)
    #: Set when the programme was generated from an installed framework's requirements.
    framework_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("frameworks.id", ondelete="SET NULL"), nullable=True, index=True
    )

    steps: Mapped[list["AuditProgramStep"]] = relationship(
        back_populates="program", cascade="all, delete-orphan", lazy="selectin",
        order_by="AuditProgramStep.order_index",
    )

    @property
    def step_count(self) -> int:
        return len(self.steps)


class AuditProgramStep(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One test step. Instantiates as an ``AuditProcedure`` when applied to an audit."""

    __tablename__ = "audit_program_steps"

    program_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    procedure: Mapped[str] = mapped_column(Text, default="")          # how to test it
    expected_evidence: Mapped[str] = mapped_column(Text, default="")  # what to collect
    #: The clause this step tests, when the programme came from a framework.
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )

    program: Mapped[AuditProgram] = relationship(back_populates="steps")
