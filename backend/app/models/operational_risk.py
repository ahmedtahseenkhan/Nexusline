"""Operational Risk Management (Basel-style) — the op-risk toolkit banks run.

* **RcsaAssessment** / **RcsaRisk** — Risk & Control Self-Assessment campaigns and
  their assessed risk/control lines (inherent vs residual, control effectiveness).
* **KeyRiskIndicator** / **KriMeasurement** — KRIs with warning/limit thresholds, a
  computed RAG status, and a measurement time-series for trend.
* **LossEvent** — the operational-loss database, categorized by Basel event type,
  with gross/recovery/net amounts.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Integer,
    Numeric,
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
    BaselEventType,
    ControlEffectiveness,
    KriDirection,
    KriStatus,
    LossEventStatus,
    RcsaStatus,
    ReviewFrequency,
)


# ================================================================== RCSA ===
class RcsaAssessment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "rcsa_assessments"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    business_unit: Mapped[str] = mapped_column(String(200), default="")
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: business unit; replaces free-text `business_unit`
    process: Mapped[str] = mapped_column(String(200), default="")
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("processes.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: process; replaces free-text `process`
    assessor: Mapped[str] = mapped_column(String(200), default="")
    assessor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `assessor`
    status: Mapped[RcsaStatus] = mapped_column(
        SAEnum(RcsaStatus, name="rcsa_status"), default=RcsaStatus.planned, nullable=False
    )
    period: Mapped[str] = mapped_column(String(64), default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    risks: Mapped[list["RcsaRisk"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", lazy="selectin",
        order_by="RcsaRisk.created_at",
    )

    @property
    def risk_count(self) -> int:
        return len(self.risks)

    @property
    def is_overdue(self) -> bool:
        return (self.status != RcsaStatus.completed and self.due_date is not None
                and self.due_date < date.today())


class RcsaRisk(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single assessed risk/control line inside an RCSA."""

    __tablename__ = "rcsa_risks"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rcsa_assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(120), default="")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: governed lookup value; replaces free-text `category`
    inherent_likelihood: Mapped[int] = mapped_column(Integer, default=1)
    inherent_impact: Mapped[int] = mapped_column(Integer, default=1)
    control_description: Mapped[str] = mapped_column(Text, default="")
    control_effectiveness: Mapped[ControlEffectiveness] = mapped_column(
        SAEnum(ControlEffectiveness, name="control_effectiveness"),
        default=ControlEffectiveness.not_assessed, nullable=False,
    )
    residual_likelihood: Mapped[int] = mapped_column(Integer, default=1)
    residual_impact: Mapped[int] = mapped_column(Integer, default=1)
    action: Mapped[str] = mapped_column(Text, default="")
    action_owner: Mapped[str] = mapped_column(String(200), default="")
    action_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `action_owner`
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Reconcile the RCSA line with the enterprise register + control catalog (Basel loop):
    # optional links to the risk this line assesses and the control that mitigates it.
    risk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("risks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    control_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("controls.id", ondelete="SET NULL"), nullable=True, index=True
    )
    risk: Mapped["Risk | None"] = relationship("Risk", lazy="selectin")  # noqa: F821
    control: Mapped["Control | None"] = relationship("Control", lazy="selectin")  # noqa: F821

    # Phase 4E: the control self-rating from a reviewed questionnaire run of this RCSA
    # (effective | partially_effective | ineffective | not_assessed), per dimension, and
    # the questionnaire assessment it came from. The worse of the two sets
    # ``control_effectiveness``.
    self_design_rating: Mapped[str | None] = mapped_column(String(24), nullable=True)
    self_operation_rating: Mapped[str | None] = mapped_column(String(24), nullable=True)
    self_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assessments.id", ondelete="SET NULL"), nullable=True, index=True
    )

    assessment: Mapped[RcsaAssessment] = relationship(back_populates="risks")

    @property
    def inherent_score(self) -> int:
        return (self.inherent_likelihood or 0) * (self.inherent_impact or 0)

    @property
    def residual_score(self) -> int:
        return (self.residual_likelihood or 0) * (self.residual_impact or 0)


# =================================================================== KRIs ===
# A KRI indicates one or more enterprise risks; a loss event materialises risks and
# often originates from an incident.
kri_risks = Table(
    "kri_risks", Base.metadata,
    Column("kri_id", Uuid, ForeignKey("key_risk_indicators.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)
loss_event_risks = Table(
    "loss_event_risks", Base.metadata,
    Column("loss_event_id", Uuid, ForeignKey("loss_events.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)


class KeyRiskIndicator(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "key_risk_indicators"
    # Phase 2: definition and data lineage.
    definition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    numerator: Mapped[str] = mapped_column(Text, default="", nullable=False)
    denominator: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data_source: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # who supplies the value
    indicator_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # leading | lagging
    lower_bound: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    upper_bound: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    appetite_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("risk_appetites.id", ondelete="SET NULL"), nullable=True, index=True
    )  # the board appetite this KRI measures
    # SHA-256 of the token an integration uses to post measurements; never the token.
    feed_token_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: governed lookup value; replaces free-text `category`
    business_area: Mapped[str] = mapped_column(String(200), default="")
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: business unit; replaces free-text `business_area`
    owner: Mapped[str] = mapped_column(String(200), default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `owner`
    unit: Mapped[str] = mapped_column(String(32), default="")  # %, count, PKR…
    frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.monthly, nullable=False,
    )
    direction: Mapped[KriDirection] = mapped_column(
        SAEnum(KriDirection, name="kri_direction"),
        default=KriDirection.higher_is_worse, nullable=False,
    )
    warning_threshold: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    limit_threshold: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    current_value: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    last_measured_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary=kri_risks, lazy="selectin",
    )
    measurements: Mapped[list["KriMeasurement"]] = relationship(
        back_populates="kri", cascade="all, delete-orphan", lazy="selectin",
        order_by="KriMeasurement.as_of_date",
    )
    # Phase 2: who is told when it turns amber / red, and the appetite it measures.
    escalations: Mapped[list["KriEscalation"]] = relationship(
        back_populates="kri", cascade="all, delete-orphan", lazy="selectin",
        order_by="KriEscalation.level",
    )
    appetite: Mapped["RiskAppetite | None"] = relationship(  # noqa: F821
        "RiskAppetite", lazy="selectin",
    )
    # For CSV export only (read models use ``data_provider_ref``); never read in a handler.
    data_provider: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[data_provider_id], lazy="select",
    )

    @property
    def status(self) -> KriStatus:
        return kri_status(
            self.direction, self.current_value, self.warning_threshold, self.limit_threshold,
            self.lower_bound, self.upper_bound,
        )

    @property
    def is_breached(self) -> bool:
        return self.status == KriStatus.red

    @property
    def has_feed_token(self) -> bool:
        """Whether an integration token is live (the token itself is never stored)."""
        return bool(self.feed_token_hash)


def _num(value) -> float | None:
    return float(value) if value is not None else None


def band_distance(value: float, lower: float | None, upper: float | None) -> float:
    """How far ``value`` lies outside ``[lower, upper]`` (0 inside it). Pure. A missing
    bound leaves that side open."""
    if lower is not None and value < lower:
        return lower - value
    if upper is not None and value > upper:
        return value - upper
    return 0.0


def kri_status(direction, value, warning, limit, lower=None, upper=None) -> KriStatus:
    """RAG status of a KRI reading. Pure.

    * ``higher_is_worse`` — amber at or above the warning threshold, red at or above the
      limit.
    * ``lower_is_worse`` — amber at or below the warning threshold, red at or below the
      limit.
    * ``within_range`` — green inside ``[lower_bound, upper_bound]`` (the bounds count
      as inside). Outside it the reading is amber until its distance from the nearer
      bound reaches the **tolerance**, held in ``limit_threshold``; at or beyond
      ``lower − tolerance`` / ``upper + tolerance`` it is red. With no tolerance any
      reading outside the range is red. ``warning_threshold`` is not used (the API
      refuses one).

    A missing threshold simply removes that step: no warning means no amber zone, no
    limit means the indicator never turns red.
    """
    if value is None:
        return KriStatus.no_data
    cur, warn, lim = float(value), _num(warning), _num(limit)
    if direction == KriDirection.within_range:
        distance = band_distance(cur, _num(lower), _num(upper))
        if distance <= 0:
            return KriStatus.green
        if lim is None or distance >= lim:
            return KriStatus.red
        return KriStatus.amber
    if direction == KriDirection.lower_is_worse:
        if lim is not None and cur <= lim:
            return KriStatus.red
        if warn is not None and cur <= warn:
            return KriStatus.amber
        return KriStatus.green
    # higher_is_worse
    if lim is not None and cur >= lim:
        return KriStatus.red
    if warn is not None and cur >= warn:
        return KriStatus.amber
    return KriStatus.green


class KriMeasurement(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "kri_measurements"

    kri_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("key_risk_indicators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    kri: Mapped[KeyRiskIndicator] = relationship(back_populates="measurements")


# ============================================================ loss events ===
#: Basel II Annex 9 level-1 names, as the Accord prints them.
BASEL_L1_LABELS: dict[str, str] = {
    BaselEventType.internal_fraud.value: "Internal fraud",
    BaselEventType.external_fraud.value: "External fraud",
    BaselEventType.employment_practices.value: "Employment practices and workplace safety",
    BaselEventType.clients_products_business_practices.value: "Clients, products & business practices",
    BaselEventType.damage_to_physical_assets.value: "Damage to physical assets",
    BaselEventType.business_disruption_system_failure.value: "Business disruption and system failures",
    BaselEventType.execution_delivery_process_management.value: "Execution, delivery & process management",
}

#: Basel II Annex 9 level-2 event categories: (key, level-1 parent, name, level-3 examples).
#: Fixed regulatory reference data — not a tenant lookup — so loss data stays comparable
#: with Basel/ORX reporting. Twenty categories; "Theft and fraud" sits under both frauds,
#: hence the prefixed keys.
BASEL_EVENT_TYPES_L2: tuple[tuple[str, str, str, str], ...] = (
    ("unauthorised_activity", "internal_fraud", "Unauthorised activity",
     "Transactions not reported (intentional); transaction type unauthorised (with monetary loss); "
     "mismarking of position (intentional)"),
    ("internal_theft_and_fraud", "internal_fraud", "Theft and fraud",
     "Fraud / credit fraud / worthless deposits; theft / extortion / embezzlement / robbery; "
     "misappropriation of assets; forgery; cheque kiting; smuggling; account take-over / "
     "impersonation; tax non-compliance / evasion (wilful); bribes / kickbacks; insider trading "
     "(not on firm's account)"),
    ("external_theft_and_fraud", "external_fraud", "Theft and fraud",
     "Theft / robbery; forgery; cheque kiting"),
    ("systems_security", "external_fraud", "Systems security",
     "Hacking damage; theft of information (with monetary loss)"),
    ("employee_relations", "employment_practices", "Employee relations",
     "Compensation, benefit, termination issues; organised labour activity"),
    ("safe_environment", "employment_practices", "Safe environment",
     "General liability (slip and fall, etc.); employee health & safety rules events; "
     "workers compensation"),
    ("diversity_discrimination", "employment_practices", "Diversity & discrimination",
     "All discrimination types"),
    ("suitability_disclosure_fiduciary", "clients_products_business_practices",
     "Suitability, disclosure & fiduciary",
     "Fiduciary breaches / guideline violations; suitability / disclosure issues (KYC, etc.); "
     "retail customer disclosure violations; breach of privacy; aggressive sales; account "
     "churning; misuse of confidential information; lender liability"),
    ("improper_business_market_practices", "clients_products_business_practices",
     "Improper business or market practices",
     "Antitrust; improper trade / market practices; market manipulation; insider trading (on "
     "firm's account); unlicensed activity; money laundering"),
    ("product_flaws", "clients_products_business_practices", "Product flaws",
     "Product defects (unauthorised, etc.); model errors"),
    ("selection_sponsorship_exposure", "clients_products_business_practices",
     "Selection, sponsorship & exposure",
     "Failure to investigate client per guidelines; exceeding client exposure limits"),
    ("advisory_activities", "clients_products_business_practices", "Advisory activities",
     "Disputes over performance of advisory activities"),
    ("disasters_other_events", "damage_to_physical_assets", "Disasters and other events",
     "Natural disaster losses; human losses from external sources (terrorism, vandalism)"),
    ("systems", "business_disruption_system_failure", "Systems",
     "Hardware; software; telecommunications; utility outage / disruptions"),
    ("transaction_capture_execution_maintenance", "execution_delivery_process_management",
     "Transaction capture, execution & maintenance",
     "Miscommunication; data entry, maintenance or loading error; missed deadline or "
     "responsibility; model / system misoperation; accounting error / entity attribution error; "
     "other task misperformance; delivery failure; collateral management failure; reference data "
     "maintenance"),
    ("monitoring_reporting", "execution_delivery_process_management", "Monitoring and reporting",
     "Failed mandatory reporting obligation; inaccurate external report (loss incurred)"),
    ("customer_intake_documentation", "execution_delivery_process_management",
     "Customer intake and documentation",
     "Client permissions / disclaimers missing; legal documents missing / incomplete"),
    ("customer_client_account_management", "execution_delivery_process_management",
     "Customer/client account management",
     "Unapproved access given to accounts; incorrect client records (loss incurred); negligent "
     "loss or damage of client assets"),
    ("trade_counterparties", "execution_delivery_process_management", "Trade counterparties",
     "Non-client counterparty misperformance; misc. non-client counterparty disputes"),
    ("vendors_suppliers", "execution_delivery_process_management", "Vendors & suppliers",
     "Outsourcing; vendor disputes"),
)

#: level-2 key -> level-1 parent value.
BASEL_L2_PARENT: dict[str, str] = {key: parent for key, parent, _n, _e in BASEL_EVENT_TYPES_L2}
BASEL_L2_LABELS: dict[str, str] = {key: name for key, _p, name, _e in BASEL_EVENT_TYPES_L2}


def basel_l2_error(l1, l2: str | None) -> str | None:
    """Why ``l2`` cannot be recorded under ``l1``; None when it can (blank is allowed). Pure."""
    key = (l2 or "").strip()
    if not key:
        return None
    parent = BASEL_L2_PARENT.get(key)
    l1_value = getattr(l1, "value", l1)
    if parent is None:
        return f"'{key}' is not a Basel II level-2 event category."
    if parent != l1_value:
        return (
            f"{BASEL_L2_LABELS[key]} belongs under {BASEL_L1_LABELS[parent]}, not "
            f"{BASEL_L1_LABELS.get(l1_value, l1_value)}. Choose a level-2 category of the chosen event type."
        )
    return None


class LossEvent(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """An operational-loss database entry (Basel event type categorized)."""

    __tablename__ = "loss_events"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    basel_event_type: Mapped[BaselEventType] = mapped_column(
        SAEnum(BaselEventType, name="basel_event_type"),
        default=BaselEventType.execution_delivery_process_management, nullable=False,
    )
    # Decision 5: Basel II level-2 category (``BASEL_EVENT_TYPES_L2``); must sit under
    # ``basel_event_type``. Blank = not yet categorised at level 2 (older events stay blank).
    basel_event_type_l2: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    business_line: Mapped[str] = mapped_column(String(200), default="")
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: business unit; replaces free-text `business_line`
    gross_loss: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    recovery: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    status: Mapped[LossEventStatus] = mapped_column(
        SAEnum(LossEventStatus, name="loss_event_status"),
        default=LossEventStatus.open, nullable=False,
    )
    occurrence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    discovery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accounting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    root_cause: Mapped[str] = mapped_column(Text, default="")
    action_owner: Mapped[str] = mapped_column(String(200), default="")
    action_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `action_owner`

    # Loss data calibrates risk scoring and often stems from a logged incident.
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    incident: Mapped["Incident | None"] = relationship("Incident", lazy="selectin")  # noqa: F821
    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary=loss_event_risks, lazy="selectin",
    )

    @property
    def net_loss(self) -> float:
        return float(self.gross_loss or 0) - float(self.recovery or 0)


class KriEscalation(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Phase 2: who is told, and what happens, when a KRI turns amber or red."""

    __tablename__ = "kri_escalations"
    __table_args__ = (UniqueConstraint("kri_id", "level", name="uq_kri_escalation_level"),)

    kri_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("key_risk_indicators.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False)  # amber | red
    escalate_to_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # the person told
    escalate_to_role: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    action: Mapped[str] = mapped_column(Text, default="", nullable=False)

    kri: Mapped[KeyRiskIndicator] = relationship(back_populates="escalations")
