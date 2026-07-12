"""Internal controls — reusable across risks and compliance frameworks, with two
recurring test cycles: **audits** (does the control work?) and **maintenances** (routine
upkeep). Each cycle produces dated pass/fail instances and reschedules the next run."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Column, Date, Enum as SAEnum
from sqlalchemy import Float, ForeignKey, String, Table, Text, Uuid
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
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    ReviewFrequency,
    TestResult,
)

control_policies = Table(
    "control_policies",
    Base.metadata,
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)


class Control(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "controls"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(64), default="")  # e.g. "A.5.1" / "AC-2"
    description: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(Text, default="")  # what the control achieves
    owner: Mapped[str] = mapped_column(String(200), default="")
    control_type: Mapped[ControlType] = mapped_column(
        SAEnum(ControlType, name="control_type"), default=ControlType.production, nullable=False
    )
    classification: Mapped[str] = mapped_column(String(120), default="")  # service classification
    documentation_url: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[ControlStatus] = mapped_column(
        SAEnum(ControlStatus, name="control_status"),
        default=ControlStatus.planned,
        nullable=False,
    )
    effectiveness: Mapped[ControlEffectiveness] = mapped_column(
        SAEnum(ControlEffectiveness, name="control_effectiveness"),
        default=ControlEffectiveness.not_assessed,
        nullable=False,
    )
    # Cost / resourcing
    opex: Mapped[float | None] = mapped_column(Float, nullable=True)  # operational cost / yr
    capex: Mapped[float | None] = mapped_column(Float, nullable=True)  # capital cost
    resource_utilization: Mapped[int | None] = mapped_column(nullable=True)  # % FTE

    # Audit cycle (control effectiveness testing)
    audit_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual,
        nullable=False,
    )
    audit_metric: Mapped[str] = mapped_column(Text, default="")
    audit_success_criteria: Mapped[str] = mapped_column(Text, default="")
    next_audit_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_audit_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Maintenance cycle (routine upkeep)
    maintenance_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.quarterly,
        nullable=False,
    )
    next_maintenance_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_maintenance_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    audits: Mapped[list["ControlAudit"]] = relationship(
        back_populates="control",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ControlAudit.created_at.desc()",
    )
    maintenances: Mapped[list["ControlMaintenance"]] = relationship(
        back_populates="control",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ControlMaintenance.created_at.desc()",
    )
    policies: Mapped[list["Policy"]] = relationship(  # noqa: F821
        "Policy", secondary=control_policies, lazy="selectin",
        secondaryjoin="and_(control_policies.c.policy_id == Policy.id, Policy.deleted == False)",
    )
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        "Requirement", secondary="requirement_controls", lazy="selectin", viewonly=True
    )

    @staticmethod
    def _last_result(items) -> TestResult | None:
        assessed = [i for i in items if i.result != TestResult.not_assessed]
        return assessed[0].result if assessed else None

    @property
    def audit_count(self) -> int:
        return len(self.audits)

    @property
    def last_audit_result(self) -> TestResult | None:
        return self._last_result(self.audits)

    @property
    def is_audit_overdue(self) -> bool:
        return self.next_audit_date is not None and self.next_audit_date < date.today()

    @property
    def maintenance_count(self) -> int:
        return len(self.maintenances)

    @property
    def last_maintenance_result(self) -> TestResult | None:
        return self._last_result(self.maintenances)

    @property
    def is_maintenance_overdue(self) -> bool:
        return (
            self.next_maintenance_date is not None
            and self.next_maintenance_date < date.today()
        )


class ControlAudit(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, Base):
    __tablename__ = "control_audits"

    control_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("controls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    conducted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[TestResult] = mapped_column(
        SAEnum(TestResult, name="test_result"), default=TestResult.not_assessed, nullable=False
    )
    metric_description: Mapped[str] = mapped_column(Text, default="")
    success_criteria: Mapped[str] = mapped_column(Text, default="")
    result_description: Mapped[str] = mapped_column(Text, default="")
    improvement: Mapped[str] = mapped_column(Text, default="")  # corrective action from the audit
    auditor: Mapped[str] = mapped_column(String(200), default="")

    control: Mapped[Control] = relationship(back_populates="audits")


class ControlMaintenance(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "control_maintenances"

    control_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("controls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task: Mapped[str] = mapped_column(String(255), default="")
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    conducted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[TestResult] = mapped_column(
        SAEnum(TestResult, name="test_result"), default=TestResult.not_assessed, nullable=False
    )
    conclusion: Mapped[str] = mapped_column(Text, default="")

    control: Mapped[Control] = relationship(back_populates="maintenances")
