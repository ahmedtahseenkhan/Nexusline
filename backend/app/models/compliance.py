"""Compliance Management — frameworks (packages), requirements (package items) and
their implementation record (eramba's ``compliance_management``): treatment strategy,
owner, efficacy, the controls/risks/policies that satisfy it, the legal obligation it
discharges, and compliance audit findings (gaps with deadlines).

A control can satisfy requirements across many frameworks ("map once, comply many").
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Column, Date, ForeignKey, Integer, String, Table, Text, Uuid
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
    ComplianceStatus,
    ComplianceTreatment,
    FindingStatus,
    Severity,
)

requirement_controls = Table(
    "requirement_controls",
    Base.metadata,
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
)

requirement_risks = Table(
    "requirement_risks",
    Base.metadata,
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)

requirement_policies = Table(
    "requirement_policies",
    Base.metadata,
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)

# Crosswalk: equivalent requirements across frameworks (e.g. ISO A.5.15 ≡ SOC2 CC6.1).
requirement_crosswalks = Table(
    "requirement_crosswalks",
    Base.metadata,
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
    Column("related_requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
)


class Framework(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "frameworks"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), default="")
    authority: Mapped[str] = mapped_column(String(200), default="")  # e.g. ISO, AICPA
    regulator: Mapped[str] = mapped_column(String(200), default="")  # body enforcing it
    scope: Mapped[str] = mapped_column(Text, default="")  # scope statement / applicability
    description: Mapped[str] = mapped_column(Text, default="")

    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="framework",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Requirement.reference",
    )

    @property
    def requirement_count(self) -> int:
        return len(self.requirements)

    @property
    def compliant_count(self) -> int:
        return sum(1 for r in self.requirements if r.status == ComplianceStatus.compliant)


class Requirement(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "requirements"

    framework_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(64), default="", index=True)  # "A.5.1"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(120), default="", index=True)
    audit_questionnaire: Mapped[str] = mapped_column(Text, default="")  # how to test compliance
    status: Mapped[ComplianceStatus] = mapped_column(
        SAEnum(ComplianceStatus, name="compliance_status"),
        default=ComplianceStatus.not_assessed,
        nullable=False,
    )

    # --- Implementation record (eramba compliance_management) ---
    treatment: Mapped[ComplianceTreatment | None] = mapped_column(
        SAEnum(ComplianceTreatment, name="compliance_treatment"), nullable=True
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    efficacy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100 %
    implementation: Mapped[str] = mapped_column(Text, default="")  # how we comply
    legal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("legals.id", ondelete="SET NULL"), nullable=True
    )

    framework: Mapped[Framework] = relationship(back_populates="requirements")
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        secondary=requirement_controls, lazy="selectin",
        secondaryjoin="and_(requirement_controls.c.control_id == Control.id, Control.deleted == False)",
    )
    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary=requirement_risks, lazy="selectin",
        secondaryjoin="and_(requirement_risks.c.risk_id == Risk.id, Risk.deleted == False)",
    )
    policies: Mapped[list["Policy"]] = relationship(  # noqa: F821
        "Policy", secondary=requirement_policies, lazy="selectin",
        secondaryjoin="and_(requirement_policies.c.policy_id == Policy.id, Policy.deleted == False)",
    )
    legal: Mapped["Legal | None"] = relationship(lazy="selectin")  # noqa: F821
    findings: Mapped[list["ComplianceFinding"]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan", lazy="selectin",
        order_by="ComplianceFinding.created_at.desc()",
    )

    @property
    def is_covered(self) -> bool:
        return len(self.controls) > 0

    @property
    def open_findings(self) -> int:
        return sum(1 for f in self.findings if f.status == FindingStatus.open)


class ComplianceFinding(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin, Base):
    """A gap/finding raised against a requirement during a compliance audit."""

    __tablename__ = "compliance_findings"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.medium, nullable=False
    )
    status: Mapped[FindingStatus] = mapped_column(
        SAEnum(FindingStatus, name="finding_status"), default=FindingStatus.open, nullable=False
    )
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)

    requirement: Mapped[Requirement] = relationship(back_populates="findings")
