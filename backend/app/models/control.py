"""Internal controls — reusable across risks and compliance frameworks, with two
recurring test cycles: **audits** (does the control work?) and **maintenances** (routine
upkeep). Each cycle produces dated pass/fail instances and reschedules the next run."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum as SAEnum,
    Integer,
)
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

#: Controls that are not yet (or no longer) operating have nothing to test or maintain:
#: a planned control carries no test clock until it is implemented, and a retired one
#: stops carrying it. Every "overdue" / "due soon" predicate excludes these statuses.
UNTESTABLE_CONTROL_STATUSES: tuple[ControlStatus, ...] = (ControlStatus.planned, ControlStatus.retired)

control_policies = Table(
    "control_policies",
    Base.metadata,
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)
# A control directly protects assets (eramba edge, reachable otherwise only via risks).
control_assets = Table(
    "control_assets",
    Base.metadata,
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)


control_business_units = Table(
    "control_business_units",
    Base.metadata,
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
    Column("business_unit_id", Uuid, ForeignKey("business_units.id", ondelete="CASCADE"), primary_key=True),
)

control_processes = Table(
    "control_processes",
    Base.metadata,
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
    Column("process_id", Uuid, ForeignKey("processes.id", ondelete="CASCADE"), primary_key=True),
)


class Control(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "controls"
    # Phase 2: control attributes (ISO 27002:2022, COSO). Values are validated in the API.
    nature: Mapped[str | None] = mapped_column(String(16), nullable=True)
    automation: Mapped[str | None] = mapped_column(String(24), nullable=True)
    is_key: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    operating_frequency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    iso27002_attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    design_effectiveness: Mapped[ControlEffectiveness] = mapped_column(
        SAEnum(ControlEffectiveness, name="control_effectiveness"),
        default=ControlEffectiveness.not_assessed, nullable=False,
    )
    operating_effectiveness: Mapped[ControlEffectiveness] = mapped_column(
        SAEnum(ControlEffectiveness, name="control_effectiveness"),
        default=ControlEffectiveness.not_assessed, nullable=False,
    )
    effectiveness_override_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Phase 4 (CCM): the day an active continuous-monitoring test on this control started
    # failing, while one still is; read by ``control_assurance.reliance_note``. Written
    # only by ``services/ccm_runner.py``; never changes effectiveness by itself.
    monitoring_failing_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    test_procedure: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_expected: Mapped[str] = mapped_column(Text, default="", nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(64), default="")  # e.g. "A.5.1" / "AC-2"
    description: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(Text, default="")  # what the control achieves
    owner: Mapped[str] = mapped_column(String(200), default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `owner`
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `owner`
    control_type: Mapped[ControlType] = mapped_column(
        SAEnum(ControlType, name="control_type"), default=ControlType.production, nullable=False
    )
    classification: Mapped[str] = mapped_column(String(120), default="")  # service classification
    classification_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: governed lookup value; replaces free-text `classification`
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
    # Reverse (read-only) links into the graph.
    incidents: Mapped[list["Incident"]] = relationship(  # noqa: F821
        "Incident", secondary="incident_controls", lazy="selectin", viewonly=True,
    )
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(  # noqa: F821
        "ExceptionRecord", secondary="exception_controls", lazy="selectin", viewonly=True,
        # An archived exception is not on the register: never show it as a live link.
        secondaryjoin="and_(exception_controls.c.exception_id == ExceptionRecord.id, ExceptionRecord.deleted == False)",
    )
    projects: Mapped[list["Project"]] = relationship(  # noqa: F821
        "Project", secondary="project_controls", lazy="selectin", viewonly=True,
    )
    audit_findings: Mapped[list["AuditFinding"]] = relationship(  # noqa: F821
        "AuditFinding", secondary="audit_finding_controls", lazy="selectin", viewonly=True,
    )
    assets: Mapped[list["Asset"]] = relationship(  # noqa: F821
        "Asset", secondary=control_assets, lazy="selectin",
    )
    vendors: Mapped[list["Vendor"]] = relationship(  # noqa: F821
        "Vendor", secondary="vendor_controls", lazy="selectin", viewonly=True,
    )
    # Phase 2 scope: where the control operates.
    business_units: Mapped[list["BusinessUnit"]] = relationship(  # noqa: F821
        "BusinessUnit", secondary=control_business_units, lazy="selectin",
    )
    processes: Mapped[list["Process"]] = relationship(  # noqa: F821
        "Process", secondary=control_processes, lazy="selectin",
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

    # What ratings and reliance read (``services.control_assurance``): only tests that
    # decide a rating — conclusive, and independently reviewed (or recorded before
    # reviews existed). ``audit_count`` / ``last_audit_result`` above stay the test log
    # (every test, newest recorded first); ``pending_review_count`` on the read bridges
    # the two.
    @property
    def reviewed_audit_count(self) -> int:
        from app.services import control_assurance

        return sum(1 for t in self.audits if control_assurance.counts_towards_rating(t))

    @property
    def tested_count(self) -> int:
        """Decision 7 (2026-09-17): the number a person reads as "tested" — reviewed tests
        only (``reviewed_audit_count``). ``audit_count`` is the test log's size."""
        return self.reviewed_audit_count

    @property
    def pending_review_count(self) -> int:
        """Tests awaiting a reviewer: shown beside ``tested_count``, never inside it."""
        from app.services import control_assurance

        return control_assurance.pending_review_count(self.audits)

    @property
    def last_reviewed_result(self) -> TestResult | None:
        from app.services import control_assurance

        latest = control_assurance.latest_counting_test(self.audits)
        return latest.result if latest is not None else None

    @property
    def last_reviewed_date(self) -> date | None:
        from app.services import control_assurance

        latest = control_assurance.latest_counting_test(self.audits)
        return control_assurance.performed_on(latest) if latest is not None else None

    @property
    def reliance_note(self) -> str:
        """Why the control cannot be relied on today, or "" (``control_assurance``)."""
        from app.services import control_assurance

        return control_assurance.reliance_note(self, self.audits)

    @property
    def carries_test_clock(self) -> bool:
        """Implemented or operational. Planned and retired controls are never due."""
        return self.status not in UNTESTABLE_CONTROL_STATUSES

    @property
    def is_audit_overdue(self) -> bool:
        return (
            self.carries_test_clock
            and self.next_audit_date is not None
            and self.next_audit_date < date.today()
        )

    @property
    def maintenance_count(self) -> int:
        return len(self.maintenances)

    @property
    def last_maintenance_result(self) -> TestResult | None:
        return self._last_result(self.maintenances)

    @property
    def is_maintenance_overdue(self) -> bool:
        return (
            self.carries_test_clock
            and self.next_maintenance_date is not None
            and self.next_maintenance_date < date.today()
        )


class ControlAudit(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, Base):
    __tablename__ = "control_audits"
    # Phase 2: the test workpaper.
    test_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # design | operating
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    population_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_method: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    exceptions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exceptions_detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    conclusion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # pending | reviewed | returned; "legacy" marks tests recorded before reviews existed.
    review_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # reviewer; must differ from the tester
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raised_issue_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True, index=True
    )  # the issue a failed test opened

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
    tested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `auditor`

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
