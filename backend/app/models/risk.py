"""Risk register — the heart of the platform.

Captures inherent vs residual scoring (5x5 matrix), treatment strategy, links to
controls and assets, a risk-acceptance workflow with expiry, and review scheduling.
``*_score`` columns are Postgres generated columns so they can be sorted/filtered
in the database.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Column,
    Computed,
    Date,
    Float,
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

_SCALE = "BETWEEN 1 AND 5"


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

    acceptances: Mapped[list["RiskAcceptance"]] = relationship(
        back_populates="risk",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RiskAcceptance.created_at.desc()",
    )


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
    """Per-tenant risk appetite and tolerance thresholds (single row per org)."""

    __tablename__ = "risk_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_risk_settings_tenant"),)

    appetite_score: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    tolerance_score: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
