"""Regulatory Change Management, Obligation Register and Regulatory Returns Calendar.

The #1 compliance-department toolkit for Pakistani banks:

* **RegulatoryChange** — an incoming SBP circular / law / regulation tracked through
  applicability triage → impact assessment → implementation, with an approval lifecycle.
* **Obligation** — the discrete "must-do" requirements distilled from a regulatory change
  (or standalone), mapped to policies/controls, owned and tracked to closure.
* **RegulatoryReturn** — the recurring regulatory-submissions (returns) calendar: what has
  to be filed with the regulator, how often, through which channel, and when it is next due.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Column, Date, ForeignKey, String, Table, Text, Uuid
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
from app.models.enums import Criticality, ReviewFrequency


# ============================================================ local enums ===
class Applicability(str, enum.Enum):
    """Whether an incoming regulatory change applies to this institution."""

    pending = "pending"
    applicable = "applicable"
    not_applicable = "not_applicable"
    under_review = "under_review"


class RegChangeStatus(str, enum.Enum):
    """Lifecycle of a tracked regulatory change from identification to closure."""

    identified = "identified"
    under_assessment = "under_assessment"
    in_implementation = "in_implementation"
    implemented = "implemented"
    closed = "closed"


class ObligationType(str, enum.Enum):
    """Strength of a distilled obligation."""

    mandatory = "mandatory"
    recommended = "recommended"
    conditional = "conditional"


class ObligationStatus(str, enum.Enum):
    """Compliance state of an obligation."""

    open = "open"
    in_progress = "in_progress"
    met = "met"
    not_met = "not_met"
    not_applicable = "not_applicable"


class ReturnStatus(str, enum.Enum):
    """State of a recurring regulatory return / submission."""

    upcoming = "upcoming"
    submitted = "submitted"
    overdue = "overdue"


# ================================================== regulatory changes ===
class RegulatoryChange(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "regulatory_changes"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    regulator: Mapped[str] = mapped_column(String(120), default="SBP")
    circular_ref: Mapped[str] = mapped_column(String(255), default="")  # e.g. "BPRD Circular No. 16 of 2024"
    source_url: Mapped[str] = mapped_column(String(500), default="")
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    applicability: Mapped[Applicability] = mapped_column(
        SAEnum(Applicability, name="reg_applicability"),
        default=Applicability.pending, nullable=False,
    )
    impact_assessment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[RegChangeStatus] = mapped_column(
        SAEnum(RegChangeStatus, name="reg_change_status"),
        default=RegChangeStatus.identified, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    priority: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False,
    )
    department: Mapped[str] = mapped_column(String(200), default="")

    obligations: Mapped[list["Obligation"]] = relationship(
        back_populates="regulatory_change", cascade="all, delete-orphan", lazy="selectin",
        order_by="Obligation.created_at",
    )

    @property
    def obligation_count(self) -> int:
        return len(self.obligations)

    @property
    def days_to_effective(self) -> int | None:
        if self.effective_date is None:
            return None
        return (self.effective_date - date.today()).days

    @property
    def is_overdue(self) -> bool:
        return (self.effective_date is not None
                and self.effective_date < date.today()
                and self.status not in (RegChangeStatus.implemented, RegChangeStatus.closed))


# An obligation maps to the framework requirements / policies / controls that satisfy it
# (replacing the free-text mapped_* columns with real graph edges).
obligation_requirements = Table(
    "obligation_requirements", Base.metadata,
    Column("obligation_id", Uuid, ForeignKey("obligations.id", ondelete="CASCADE"), primary_key=True),
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
)
obligation_policies = Table(
    "obligation_policies", Base.metadata,
    Column("obligation_id", Uuid, ForeignKey("obligations.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)
obligation_controls = Table(
    "obligation_controls", Base.metadata,
    Column("obligation_id", Uuid, ForeignKey("obligations.id", ondelete="CASCADE"), primary_key=True),
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
)


# ============================================================= obligations ===
class Obligation(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A discrete compliance obligation — nested under a regulatory change or standalone."""

    __tablename__ = "obligations"

    regulatory_change_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("regulatory_changes.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    obligation_type: Mapped[ObligationType] = mapped_column(
        SAEnum(ObligationType, name="obligation_type"),
        default=ObligationType.mandatory, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    business_unit: Mapped[str] = mapped_column(String(200), default="")
    mapped_policies: Mapped[str] = mapped_column(Text, default="")
    mapped_controls: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ObligationStatus] = mapped_column(
        SAEnum(ObligationStatus, name="obligation_status"),
        default=ObligationStatus.open, nullable=False,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    regulatory_change: Mapped["RegulatoryChange | None"] = relationship(back_populates="obligations")
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        "Requirement", secondary=obligation_requirements, lazy="selectin",
    )
    policies: Mapped[list["Policy"]] = relationship(  # noqa: F821
        "Policy", secondary=obligation_policies, lazy="selectin",
    )
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        "Control", secondary=obligation_controls, lazy="selectin",
    )


# ====================================================== regulatory returns ===
class RegulatoryReturn(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A recurring regulatory submission (return) tracked on a calendar."""

    __tablename__ = "regulatory_returns"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    regulator: Mapped[str] = mapped_column(String(120), default="SBP")
    description: Mapped[str] = mapped_column(Text, default="")
    frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.quarterly, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    department: Mapped[str] = mapped_column(String(200), default="")
    submission_channel: Mapped[str] = mapped_column(String(255), default="")  # e.g. "SBP Data Acquisition Portal"
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_submitted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ReturnStatus] = mapped_column(
        SAEnum(ReturnStatus, name="reg_return_status"),
        default=ReturnStatus.upcoming, nullable=False,
    )

    @property
    def is_overdue(self) -> bool:
        return (self.next_due_date is not None
                and self.next_due_date < date.today()
                and self.status != ReturnStatus.submitted)

    @property
    def days_to_due(self) -> int | None:
        if self.next_due_date is None:
            return None
        return (self.next_due_date - date.today()).days
