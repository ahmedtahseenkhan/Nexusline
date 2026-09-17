"""Compliance Management — frameworks (packages), requirements (package items) and
their implementation record (eramba's ``compliance_management``): treatment strategy,
owner, efficacy, the controls/risks/policies that satisfy it, the legal obligation it
discharges, and compliance audit findings (gaps with deadlines).

A control can satisfy requirements across many frameworks ("map once, comply many").
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Column, Date, ForeignKey, Index, Integer, String, Table, Text, Uuid, event, func, text
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


#: How a framework is scored. ``compliance`` frameworks (ISO 27001, PCI DSS, SBP) are
#: obligations: each clause is met or not and feeds the compliance percentage. ``maturity``
#: and ``guidance`` frameworks (ISO 31000, ISO 27005) describe good practice; a bank
#: self-assesses against them but is never "non-compliant" with them, so they stay out of
#: the compliance percentage and the health score.
FRAMEWORK_KINDS: tuple[str, ...] = ("compliance", "maturity", "guidance")


class Framework(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "frameworks"
    __table_args__ = (
        # One live framework per name per organisation: the same standard loaded twice
        # counts every gap twice. Case-insensitive, and archived rows don't count.
        Index(
            "uq_frameworks_tenant_name",
            "tenant_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("deleted = false"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="compliance", nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="")
    authority: Mapped[str] = mapped_column(String(200), default="")  # e.g. ISO, AICPA
    regulator: Mapped[str] = mapped_column(String(200), default="")  # body enforcing it
    scope: Mapped[str] = mapped_column(Text, default="")  # scope statement / applicability
    description: Mapped[str] = mapped_column(Text, default="")

    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="framework",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Requirement.reference_sort_key",
    )

    @property
    def requirement_count(self) -> int:
        return len(self.requirements)

    @property
    def compliant_count(self) -> int:
        return sum(1 for r in self.requirements if r.status == ComplianceStatus.compliant)

    @property
    def posture(self):
        """Assessed compliant / mapped / tested, side by side (F-19). Mapping never
        makes a clause compliant; this shows what it did achieve."""
        from app.services.compliance_posture import posture

        return posture(self.requirements)


class Requirement(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "requirements"

    framework_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(64), default="", index=True)  # "A.5.1"
    # Natural-order key for ``reference`` (A.5.2 before A.5.10); lists sort on this.
    reference_sort_key: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Statement of Applicability: why a clause is in or out of scope.
    applicability_justification: Mapped[str] = mapped_column(Text, default="", nullable=False)
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
    # Reverse (read-only) links into the graph.
    assets: Mapped[list["Asset"]] = relationship(  # noqa: F821
        "Asset", secondary="assets_requirements", lazy="selectin", viewonly=True,
    )
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(  # noqa: F821
        "ExceptionRecord", secondary="exception_requirements", lazy="selectin", viewonly=True,
        # An archived exception is not on the register: never show it as a live link.
        secondaryjoin="and_(exception_requirements.c.exception_id == ExceptionRecord.id, ExceptionRecord.deleted == False)",
    )
    audit_findings: Mapped[list["AuditFinding"]] = relationship(  # noqa: F821
        "AuditFinding", secondary="audit_finding_requirements", lazy="selectin", viewonly=True,
    )
    vendors: Mapped[list["Vendor"]] = relationship(  # noqa: F821
        "Vendor", secondary="vendor_requirements", lazy="selectin", viewonly=True,
    )

    @property
    def control_health(self) -> str:
        """Live rollup: is the evidence (mitigating controls) behind this requirement
        healthy? A failing/overdue control audit flips this to ``issues`` on read — so a
        control failure automatically puts the requirement at risk (the compliance loop).
        ``none`` = no controls mapped · ``ok`` · ``issues``."""
        from app.models.enums import TestResult

        if not self.controls:
            return "none"
        for c in self.controls:
            # The latest *reviewed* test, as ratings and the residual engine read it.
            if c.last_reviewed_result == TestResult.failed or c.is_audit_overdue:
                return "issues"
        return "ok"

    findings: Mapped[list["ComplianceFinding"]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan", lazy="selectin",
        order_by="ComplianceFinding.created_at.desc()",
    )

    @property
    def is_covered(self) -> bool:
        """Mapped to at least one control. Mapping is not assurance — see ``coverage``."""
        return len(self.controls) > 0

    @property
    def coverage(self) -> str:
        """unmapped | unassessed | failing | assured — the strongest state any mapped
        control reaches. Only ``assured`` is coverage a gap analysis may rely on."""
        from app.services.control_assurance import coverage_state

        return coverage_state(c.effectiveness for c in self.controls)

    @property
    def open_findings(self) -> int:
        return sum(1 for f in self.findings if f.status == FindingStatus.open)


@event.listens_for(Requirement, "before_insert")
@event.listens_for(Requirement, "before_update")
def _fill_reference_sort_key(_mapper, _connection, target: Requirement) -> None:
    """Every ORM write of a requirement — the API, imports, a framework install or
    upgrade — keeps ``reference_sort_key`` in step with ``reference`` (F-16). Rows
    written around the ORM are caught by the boot repair
    (``data_repairs.fill_requirement_sort_keys``)."""
    from app.services.reference_sort import reference_sort_key

    key = reference_sort_key(target.reference)
    if target.reference_sort_key != key:
        target.reference_sort_key = key


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
