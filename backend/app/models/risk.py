"""Risk register — the heart of the platform.

Captures inherent vs residual scoring (matrix size is per-tenant), treatment strategy,
links to controls, assets and the business segments the risk sits in, a risk-acceptance
workflow with expiry, and review scheduling.
``*_score`` columns are Postgres generated columns so they can be sorted/filtered
in the database.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.risk_scale import MAX_MATRIX_SIZE
from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkflowMixin,
)
from app.models.enums import (
    AcceptanceStatus,
    ReviewFrequency,
    RiskStatus,
    TreatmentStrategy,
)

risk_assets = Table(
    "risk_assets",
    Base.metadata,
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)

risk_controls = Table(
    "risk_controls",
    Base.metadata,
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True
    ),
)

# --- segment scoping -------------------------------------------------------
# Banks do not assess risk asset by asset; they assess a *segment* — a business unit, or
# a process running inside it — and the assets are what that segment happens to run on.
# Without these edges the register can be filtered by category and by asset but never by
# "Digital Banking", which is the cut a risk workshop actually convenes around.
#
# Both are many-to-many on purpose. A single owning unit would be simpler, but a control
# failure like "MFA not enforced" genuinely belongs to Retail and Corporate at once, and
# forcing a choice would either duplicate the risk or hide it from one of them.
# The composite primary key already indexes risk_id. These index the other direction,
# which is the one the register actually filters on: "show me Digital Banking's risks".
risk_business_units = Table(
    "risk_business_units",
    Base.metadata,
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "business_unit_id",
        Uuid,
        ForeignKey("business_units.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index("ix_risk_business_units_unit", "business_unit_id"),
)

risk_processes = Table(
    "risk_processes",
    Base.metadata,
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
    Column("process_id", Uuid, ForeignKey("processes.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_risk_processes_process", "process_id"),
)

risk_policies = Table(
    "risk_policies",
    Base.metadata,
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)

risk_incidents = Table(
    "risk_incidents",
    Base.metadata,
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
    Column("incident_id", Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True),
)

# The database can only enforce the widest scale any tenant may configure; the tenant's
# own ``RiskSetting.matrix_size`` is enforced in the API layer, because a check
# constraint cannot vary per row-level-security tenant. Derived from the one constant so
# raising the ceiling never leaves the schema behind the validators.
_SCALE = f"BETWEEN 1 AND {MAX_MATRIX_SIZE}"


class Risk(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "risks"
    __table_args__ = (
        CheckConstraint(f"inherent_likelihood {_SCALE}", name="ck_risk_inh_likelihood"),
        CheckConstraint(f"inherent_impact {_SCALE}", name="ck_risk_inh_impact"),
        CheckConstraint(
            f"residual_likelihood IS NULL OR residual_likelihood {_SCALE}",
            name="ck_risk_res_likelihood",
        ),
        CheckConstraint(
            f"residual_impact IS NULL OR residual_impact {_SCALE}",
            name="ck_risk_res_impact",
        ),
    )

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="", index=True)
    status: Mapped[RiskStatus] = mapped_column(
        SAEnum(RiskStatus, name="risk_status"), default=RiskStatus.draft, nullable=False
    )

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Inherent risk (before controls)
    inherent_likelihood: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    inherent_impact: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    inherent_score: Mapped[int] = mapped_column(
        Integer, Computed("inherent_likelihood * inherent_impact", persisted=True)
    )

    # Residual risk (after controls) — optional until assessed
    residual_likelihood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    residual_impact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    residual_score: Mapped[int | None] = mapped_column(
        Integer, Computed("residual_likelihood * residual_impact", persisted=True)
    )

    # Suggested residual, derived from the linked controls' effectiveness by
    # ``services.residual_engine``. Held separately from the assessed residual above so
    # the tool's proposal and the owner's decision are never confused for one another:
    # nothing here affects reporting until someone accepts it.
    suggested_residual_likelihood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_residual_impact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_residual_rationale: Mapped[str] = mapped_column(Text, default="")
    # Who signed off the residual, and why it differs from the suggestion if it does —
    # the trail an auditor asks for when the number is questioned.
    residual_accepted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    residual_accepted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    residual_override_reason: Mapped[str] = mapped_column(Text, default="")

    # Quantitative (FAIR-style) — optional. ALE = loss event frequency x single loss expectancy.
    annual_loss_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    single_loss_expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_loss_expectancy: Mapped[float | None] = mapped_column(
        Float, Computed("annual_loss_frequency * single_loss_expectancy", persisted=True)
    )

    # Treatment plan
    treatment_strategy: Mapped[TreatmentStrategy | None] = mapped_column(
        SAEnum(TreatmentStrategy, name="treatment_strategy"), nullable=True
    )
    treatment_description: Mapped[str] = mapped_column(Text, default="")
    treatment_owner: Mapped[str] = mapped_column(String(200), default="")
    treatment_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    treatment_cost: Mapped[float | None] = mapped_column(Float, nullable=True)


    # Turnaround-time clock, derived from the tenant's SLA policy for this severity by
    # ``services.sla``. Distinct from any agreed ``due_date``: this is what the policy
    # allows, that is what was promised. ``tat_breached_at`` records the first day the
    # window lapsed.
    tat_due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    tat_breached_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Review scheduling
    review_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual,
        nullable=False,
    )
    last_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    expired_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    assets: Mapped[list["Asset"]] = relationship(  # noqa: F821
        secondary=risk_assets, lazy="selectin",
        secondaryjoin="and_(risk_assets.c.asset_id == Asset.id, Asset.deleted == False)",
    )
    business_units: Mapped[list["BusinessUnit"]] = relationship(  # noqa: F821
        "BusinessUnit", secondary=risk_business_units, lazy="selectin",
        secondaryjoin=(
            "and_(risk_business_units.c.business_unit_id == BusinessUnit.id, "
            "BusinessUnit.deleted == False)"
        ),
    )
    processes: Mapped[list["Process"]] = relationship(  # noqa: F821
        "Process", secondary=risk_processes, lazy="selectin",
        secondaryjoin="and_(risk_processes.c.process_id == Process.id, Process.deleted == False)",
    )
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        secondary=risk_controls, lazy="selectin",
        secondaryjoin="and_(risk_controls.c.control_id == Control.id, Control.deleted == False)",
    )
    threats: Mapped[list["Threat"]] = relationship(  # noqa: F821
        "Threat", secondary="risk_threats", lazy="selectin"
    )
    vulnerabilities: Mapped[list["Vulnerability"]] = relationship(  # noqa: F821
        "Vulnerability", secondary="risk_vulnerabilities", lazy="selectin"
    )
    policies: Mapped[list["Policy"]] = relationship(  # noqa: F821
        "Policy", secondary=risk_policies, lazy="selectin",
        secondaryjoin="and_(risk_policies.c.policy_id == Policy.id, Policy.deleted == False)",
    )
    incidents: Mapped[list["Incident"]] = relationship(  # noqa: F821
        "Incident", secondary=risk_incidents, lazy="selectin",
        secondaryjoin="and_(risk_incidents.c.incident_id == Incident.id, Incident.deleted == False)",
    )

    # Reverse (read-only) links — records elsewhere that point at this risk. These make
    # the risk detail show the *full* graph (eramba-style), not just its outbound links.
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        "Requirement", secondary="requirement_risks", lazy="selectin", viewonly=True,
    )
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(  # noqa: F821
        "ExceptionRecord", secondary="exception_risks", lazy="selectin", viewonly=True,
    )
    vendors: Mapped[list["Vendor"]] = relationship(  # noqa: F821
        "Vendor", secondary="vendor_risks", lazy="selectin", viewonly=True,
    )
    projects: Mapped[list["Project"]] = relationship(  # noqa: F821
        "Project", secondary="project_risks", lazy="selectin", viewonly=True,
    )
    goals: Mapped[list["Goal"]] = relationship(  # noqa: F821
        "Goal", secondary="goal_risks", lazy="selectin", viewonly=True,
    )
    processing_activities: Mapped[list["ProcessingActivity"]] = relationship(  # noqa: F821
        "ProcessingActivity", secondary="ropa_risks", lazy="selectin", viewonly=True,
    )
    audit_findings: Mapped[list["AuditFinding"]] = relationship(  # noqa: F821
        "AuditFinding", secondary="audit_finding_risks", lazy="selectin", viewonly=True,
    )
    kris: Mapped[list["KeyRiskIndicator"]] = relationship(  # noqa: F821
        "KeyRiskIndicator", secondary="kri_risks", lazy="selectin", viewonly=True,
    )
    loss_events: Mapped[list["LossEvent"]] = relationship(  # noqa: F821
        "LossEvent", secondary="loss_event_risks", lazy="selectin", viewonly=True,
    )

    acceptances: Mapped[list["RiskAcceptance"]] = relationship(
        back_populates="risk",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RiskAcceptance.created_at.desc()",
    )

    @property
    def control_health(self) -> str:
        """Live rollup of the mitigating controls' health — the risk-treatment loop.
        A control audit that fails (or an open audit finding, or an overdue audit) makes
        this ``issues`` on the very next read, so the risk register reacts automatically.

        ``none`` = unmitigated · ``ok`` = controls exist and are healthy · ``issues``.
        """
        from app.models.enums import AuditFindingStatus, TestResult

        if not self.controls:
            return "none"
        _open = lambda f: f.status not in (AuditFindingStatus.closed, AuditFindingStatus.risk_accepted)  # noqa: E731
        for c in self.controls:
            if c.last_audit_result == TestResult.failed or c.is_audit_overdue:
                return "issues"
            if any(_open(f) for f in c.audit_findings):
                return "issues"
        return "ok"


class RiskAcceptance(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A formal decision to accept a risk, with an approval step and expiry date."""

    __tablename__ = "risk_acceptances"

    risk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("risks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[AcceptanceStatus] = mapped_column(
        SAEnum(AcceptanceStatus, name="acceptance_status"),
        default=AcceptanceStatus.pending,
        nullable=False,
    )
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    decided_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    risk: Mapped[Risk] = relationship(back_populates="acceptances")


class RiskSetting(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Per-tenant risk appetite, tolerance and matrix size (single row per org)."""

    __tablename__ = "risk_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_risk_settings_tenant"),)

    appetite_score: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    tolerance_score: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    # Size of the likelihood x impact matrix (3..10). Severity bands scale with it, so a
    # bank can baseline the register on whichever scale its methodology (ISO 27005,
    # ISO 31000, its own ERM framework) prescribes.
    matrix_size: Mapped[int] = mapped_column(Integer, default=5, nullable=False)


class RiskMatrixLevel(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One rung of the likelihood or impact scale, in the bank's own words.

    This is the part of a methodology that makes scoring repeatable between assessors:
    "3 = Possible — could occur once in 1-3 years" rather than a bare number. Absent
    rows fall back to generic labels, so the matrix works before anyone configures it.
    """

    __tablename__ = "risk_matrix_levels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "axis", "level", name="uq_risk_matrix_level"),
        CheckConstraint("axis IN ('likelihood', 'impact')", name="ck_risk_matrix_axis"),
        CheckConstraint(f"level {_SCALE}", name="ck_risk_matrix_level"),
    )

    axis: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(60), default="")
    definition: Mapped[str] = mapped_column(Text, default="")


class ResidualPolicy(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """How much residual credit a control earns, per effectiveness rating.

    Configuration for :mod:`app.services.residual_engine`. One row per org. The
    defaults reduce likelihood only and cap total credit, which is the conservative
    reading of ISO 27005; a bank with its own weighting changes these values rather
    than the code. See the module docstring there for why the output is a suggestion
    and never an automatic write.
    """

    __tablename__ = "residual_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_residual_policy_tenant"),
        CheckConstraint(
            "applies_to IN ('likelihood', 'impact', 'both')", name="ck_residual_applies_to"
        ),
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    weight_effective: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    weight_partially_effective: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    weight_ineffective: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weight_not_assessed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applies_to: Mapped[str] = mapped_column(String(16), default="likelihood", nullable=False)
    max_reduction: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
