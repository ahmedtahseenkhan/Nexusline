"""Internal Audit — a full audit-management module for assurance functions.

Structure mirrors how bank internal-audit departments work:
* **AuditableUnit** — the *audit universe*: everything that can be audited, each with
  an inherent-risk rating and an audit frequency that drives the risk-based plan.
* **AuditEngagement** — a planned/executed audit with scope, objectives, period,
  lead auditor and a status lifecycle (planned → fieldwork → reporting → closed).
* **AuditProcedure** — a test / working paper performed within an engagement.
* **AuditFinding** — an observation with rating, recommendation, management response
  and an action plan tracked through follow-up to closure.
"""
from __future__ import annotations

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
from app.models.enums import (
    AuditEngagementStatus,
    AuditFindingStatus,
    AuditProcedureResult,
    Criticality,
    ReviewFrequency,
    Severity,
)


class AuditableUnit(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """An entry in the audit universe."""

    __tablename__ = "auditable_units"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    inherent_risk: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    audit_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual, nullable=False,
    )
    last_audited_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_audit_due: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def is_overdue(self) -> bool:
        return self.next_audit_due is not None and self.next_audit_due < date.today()


class AuditEngagement(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "audit_engagements"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(Text, default="")
    objectives: Mapped[str] = mapped_column(Text, default="")

    auditable_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auditable_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lead_auditor: Mapped[str] = mapped_column(String(200), default="")
    audit_team: Mapped[str] = mapped_column(String(400), default="")

    status: Mapped[AuditEngagementStatus] = mapped_column(
        SAEnum(AuditEngagementStatus, name="audit_engagement_status"),
        default=AuditEngagementStatus.planned, nullable=False,
    )
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_end: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    actual_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    conclusion: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[Severity | None] = mapped_column(
        SAEnum(Severity, name="severity"), nullable=True  # overall audit opinion
    )

    auditable_unit: Mapped["AuditableUnit | None"] = relationship(lazy="selectin")
    procedures: Mapped[list["AuditProcedure"]] = relationship(
        back_populates="engagement", cascade="all, delete-orphan", lazy="selectin",
        order_by="AuditProcedure.created_at",
    )
    findings: Mapped[list["AuditFinding"]] = relationship(
        back_populates="engagement", cascade="all, delete-orphan", lazy="selectin",
        order_by="AuditFinding.created_at",
    )

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def open_finding_count(self) -> int:
        return sum(1 for f in self.findings if f.status != AuditFindingStatus.closed)

    @property
    def is_overdue(self) -> bool:
        return (
            self.status not in (AuditEngagementStatus.closed, AuditEngagementStatus.cancelled)
            and self.planned_end is not None
            and self.planned_end < date.today()
        )


class AuditProcedure(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A test / working paper within an engagement."""

    __tablename__ = "audit_procedures"

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")  # test steps
    result: Mapped[AuditProcedureResult] = mapped_column(
        SAEnum(AuditProcedureResult, name="audit_procedure_result"),
        default=AuditProcedureResult.pending, nullable=False,
    )
    conclusion: Mapped[str] = mapped_column(Text, default="")
    workpaper_ref: Mapped[str] = mapped_column(String(120), default="")
    performed_by: Mapped[str] = mapped_column(String(200), default="")
    performed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    engagement: Mapped[AuditEngagement] = relationship(back_populates="procedures")


# Links from an audit finding into the core graph — what the finding is *against*.
audit_finding_controls = Table(
    "audit_finding_controls", Base.metadata,
    Column("audit_finding_id", Uuid, ForeignKey("audit_findings.id", ondelete="CASCADE"), primary_key=True),
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
)
audit_finding_risks = Table(
    "audit_finding_risks", Base.metadata,
    Column("audit_finding_id", Uuid, ForeignKey("audit_findings.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)
audit_finding_requirements = Table(
    "audit_finding_requirements", Base.metadata,
    Column("audit_finding_id", Uuid, ForeignKey("audit_findings.id", ondelete="CASCADE"), primary_key=True),
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
)


class AuditFinding(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """An audit observation tracked through remediation follow-up."""

    __tablename__ = "audit_findings"

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_engagements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.medium, nullable=False
    )
    risk_implication: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    management_response: Mapped[str] = mapped_column(Text, default="")
    action_owner: Mapped[str] = mapped_column(String(200), default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[AuditFindingStatus] = mapped_column(
        SAEnum(AuditFindingStatus, name="audit_finding_status"),
        default=AuditFindingStatus.open, nullable=False,
    )
    closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    engagement: Mapped[AuditEngagement] = relationship(back_populates="findings")

    # What the finding is raised against (writable links into the core graph).
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        "Control", secondary=audit_finding_controls, lazy="selectin",
    )
    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary=audit_finding_risks, lazy="selectin",
    )
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        "Requirement", secondary=audit_finding_requirements, lazy="selectin",
    )

    @property
    def is_overdue(self) -> bool:
        return (
            self.status not in (AuditFindingStatus.closed, AuditFindingStatus.risk_accepted)
            and self.due_date is not None
            and self.due_date < date.today()
        )
