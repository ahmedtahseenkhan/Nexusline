"""Fraud Risk Management — SBP's most active enforcement area (digital-fraud circulars).

Distinct from AML/CFT. Three coordinated parts:

* **FraudRisk** — a fraud risk register scoring inherent vs residual fraud exposure by
  scheme (asset misappropriation, card fraud, digital-channel fraud, insider fraud …)
  and channel (branch, ATM, internet/mobile banking, cards, wire/SWIFT …).
* **FraudCase** — fraud case management: reported/investigated incidents with amount
  involved vs recovered (net loss), perpetrator type, customer impact and whether the
  case was reported to the regulator.
* **FraudControlCheck** — an SBP digital-fraud control checklist (e.g. the 2-hour
  restriction on out-of-pattern incoming-fund cash-outs) tracked to implementation.
"""
from __future__ import annotations

import enum
from datetime import date

from sqlalchemy import Boolean, Date, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkflowMixin,
)
from app.models.enums import ControlEffectiveness


# ============================================================ local enums ===
class FraudScheme(str, enum.Enum):
    """Type of fraud scheme (ACFE-style occupational + banking fraud typologies)."""

    asset_misappropriation = "asset_misappropriation"
    corruption = "corruption"
    financial_statement_fraud = "financial_statement_fraud"
    cyber_enabled = "cyber_enabled"
    identity_theft = "identity_theft"
    card_fraud = "card_fraud"
    digital_channel_fraud = "digital_channel_fraud"
    insider_fraud = "insider_fraud"
    external_fraud = "external_fraud"
    cheque_fraud = "cheque_fraud"
    other = "other"


class FraudChannel(str, enum.Enum):
    """Banking channel through which the fraud is perpetrated."""

    branch = "branch"
    atm = "atm"
    internet_banking = "internet_banking"
    mobile_app = "mobile_app"
    cards = "cards"
    wire_swift = "wire_swift"
    call_center = "call_center"
    agent_network = "agent_network"
    other = "other"


class FraudRiskStatus(str, enum.Enum):
    open = "open"
    mitigating = "mitigating"
    monitored = "monitored"
    closed = "closed"


class FraudCaseStatus(str, enum.Enum):
    reported = "reported"
    investigating = "investigating"
    confirmed = "confirmed"
    recovered = "recovered"
    closed = "closed"
    referred_to_authorities = "referred_to_authorities"


class PerpetratorType(str, enum.Enum):
    internal = "internal"
    external = "external"
    collusion = "collusion"
    unknown = "unknown"


class FraudControlCategory(str, enum.Enum):
    """SBP digital-fraud control themes."""

    behavioral_monitoring = "behavioral_monitoring"
    transaction_limits = "transaction_limits"
    customer_authentication = "customer_authentication"
    real_time_alerting = "real_time_alerting"
    complaint_handling = "complaint_handling"
    fraud_detection_system = "fraud_detection_system"
    staff_training = "staff_training"


class FraudControlStatus(str, enum.Enum):
    not_implemented = "not_implemented"
    in_progress = "in_progress"
    implemented = "implemented"


# ========================================================= fraud register ===
class FraudRisk(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A fraud risk register entry — inherent vs residual fraud exposure."""

    __tablename__ = "fraud_risks"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    scheme: Mapped[FraudScheme] = mapped_column(
        SAEnum(FraudScheme, name="fraud_scheme"),
        default=FraudScheme.asset_misappropriation, nullable=False,
    )
    channel: Mapped[FraudChannel] = mapped_column(
        SAEnum(FraudChannel, name="fraud_channel"),
        default=FraudChannel.branch, nullable=False,
    )
    business_line: Mapped[str] = mapped_column(String(200), default="")
    inherent_likelihood: Mapped[int] = mapped_column(Integer, default=1)
    inherent_impact: Mapped[int] = mapped_column(Integer, default=1)
    control_description: Mapped[str] = mapped_column(Text, default="")
    control_effectiveness: Mapped[ControlEffectiveness] = mapped_column(
        SAEnum(ControlEffectiveness, name="control_effectiveness"),
        default=ControlEffectiveness.not_assessed, nullable=False,
    )
    residual_likelihood: Mapped[int] = mapped_column(Integer, default=1)
    residual_impact: Mapped[int] = mapped_column(Integer, default=1)
    red_flags: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[FraudRiskStatus] = mapped_column(
        SAEnum(FraudRiskStatus, name="fraud_risk_status"),
        default=FraudRiskStatus.open, nullable=False,
    )

    @property
    def inherent_score(self) -> int:
        return (self.inherent_likelihood or 0) * (self.inherent_impact or 0)

    @property
    def residual_score(self) -> int:
        return (self.residual_likelihood or 0) * (self.residual_impact or 0)


# ==================================================== fraud case management ===
class FraudCase(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A reported / investigated fraud incident with recovery and regulator tracking."""

    __tablename__ = "fraud_cases"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    scheme: Mapped[FraudScheme] = mapped_column(
        SAEnum(FraudScheme, name="fraud_scheme"),
        default=FraudScheme.asset_misappropriation, nullable=False,
    )
    channel: Mapped[FraudChannel] = mapped_column(
        SAEnum(FraudChannel, name="fraud_channel"),
        default=FraudChannel.branch, nullable=False,
    )
    status: Mapped[FraudCaseStatus] = mapped_column(
        SAEnum(FraudCaseStatus, name="fraud_case_status"),
        default=FraudCaseStatus.reported, nullable=False,
    )
    reported_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    discovery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    incident_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_involved: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    amount_recovered: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    perpetrator_type: Mapped[PerpetratorType] = mapped_column(
        SAEnum(PerpetratorType, name="fraud_perpetrator_type"),
        default=PerpetratorType.unknown, nullable=False,
    )
    customer_impacted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    customers_affected: Mapped[int] = mapped_column(Integer, default=0)
    reported_to_regulator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    regulator_ref: Mapped[str] = mapped_column(String(120), default="")
    investigator: Mapped[str] = mapped_column(String(200), default="")
    root_cause: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str] = mapped_column(Text, default="")

    @property
    def net_loss(self) -> float:
        return float(self.amount_involved or 0) - float(self.amount_recovered or 0)


# ============================================== SBP digital-fraud checklist ===
class FraudControlCheck(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin, Base):
    """A single SBP digital-fraud control requirement tracked to implementation."""

    __tablename__ = "fraud_control_checks"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    requirement: Mapped[str] = mapped_column(Text, default="")
    sbp_reference: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[FraudControlCategory] = mapped_column(
        SAEnum(FraudControlCategory, name="fraud_control_category"),
        default=FraudControlCategory.behavioral_monitoring, nullable=False,
    )
    implemented: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[FraudControlStatus] = mapped_column(
        SAEnum(FraudControlStatus, name="fraud_control_status"),
        default=FraudControlStatus.not_implemented, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    evidence_note: Mapped[str] = mapped_column(Text, default="")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
