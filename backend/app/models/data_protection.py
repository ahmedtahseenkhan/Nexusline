"""Data Protection (Pakistan PDPA readiness) — the operational data-protection layer.

Where the ``privacy`` module is the RoPA (record-of-processing) register, this module
is the *operational* data-protection toolkit a DPO runs day to day:

* **Dpia** — Data Protection Impact Assessments: necessity, risks, mitigations and a
  residual-risk rating with a DPO review lifecycle.
* **Dsar** — Data Subject Access Requests: the 30-day SLA clock, request type, and a
  computed overdue flag.
* **DataBreach** — the breach register: severity, records affected, regulator
  notification, and the 72-hour ("notification overdue") rule.
* **ConsentRecord** — a consent ledger: lawful basis, grant/withdrawal, and status.
"""
from __future__ import annotations

import enum
from datetime import date, timedelta

from sqlalchemy import Boolean, Date, Integer, String, Text
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
from app.models.enums import Criticality, LawfulBasis, Severity


# ============================================================ local enums ===
class DpiaWorkflowStatus(str, enum.Enum):
    """Lifecycle of a Data Protection Impact Assessment."""

    not_required = "not_required"
    required = "required"
    in_progress = "in_progress"
    completed = "completed"
    approved = "approved"


class DsarType(str, enum.Enum):
    """Data-subject request types under the PDPA / GDPR-style rights."""

    access = "access"
    rectification = "rectification"
    erasure = "erasure"
    portability = "portability"
    objection = "objection"
    restriction = "restriction"


class DsarStatus(str, enum.Enum):
    """Fulfilment lifecycle of a data-subject access request."""

    received = "received"
    verifying = "verifying"
    in_progress = "in_progress"
    fulfilled = "fulfilled"
    rejected = "rejected"


class BreachType(str, enum.Enum):
    """CIA classification of a personal-data breach."""

    confidentiality = "confidentiality"
    integrity = "integrity"
    availability = "availability"


class BreachStatus(str, enum.Enum):
    """Lifecycle of a personal-data breach through to closure."""

    open = "open"
    investigating = "investigating"
    contained = "contained"
    notified = "notified"
    closed = "closed"


class ConsentStatus(str, enum.Enum):
    """State of a subject's consent record."""

    active = "active"
    withdrawn = "withdrawn"
    expired = "expired"


# =================================================================== DPIA ===
class Dpia(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A Data Protection Impact Assessment for a processing activity."""

    __tablename__ = "dpias"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    processing_activity: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    necessity_justification: Mapped[str] = mapped_column(Text, default="")
    risks_identified: Mapped[str] = mapped_column(Text, default="")
    mitigations: Mapped[str] = mapped_column(Text, default="")
    residual_risk: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.low, nullable=False
    )
    status: Mapped[DpiaWorkflowStatus] = mapped_column(
        SAEnum(DpiaWorkflowStatus, name="dp_dpia_status"),
        default=DpiaWorkflowStatus.required, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    dpo_reviewer: Mapped[str] = mapped_column(String(200), default="")
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)


# =================================================================== DSAR ===
class Dsar(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A Data Subject Access Request with its statutory SLA clock."""

    __tablename__ = "dsars"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    subject_name: Mapped[str] = mapped_column(String(200), default="", index=True)
    subject_contact: Mapped[str] = mapped_column(String(200), default="")
    request_type: Mapped[DsarType] = mapped_column(
        SAEnum(DsarType, name="dsar_type"), default=DsarType.access, nullable=False
    )
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    response_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    handler: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[DsarStatus] = mapped_column(
        SAEnum(DsarStatus, name="dsar_status"), default=DsarStatus.received, nullable=False
    )

    @property
    def sla_days(self) -> int:
        return 30

    @property
    def is_overdue(self) -> bool:
        return (
            self.status in (DsarStatus.received, DsarStatus.verifying, DsarStatus.in_progress)
            and self.due_date is not None
            and self.due_date < date.today()
        )


# ============================================================ data breach ===
class DataBreach(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A personal-data breach register entry (72-hour notification rule)."""

    __tablename__ = "data_breaches"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    breach_type: Mapped[BreachType] = mapped_column(
        SAEnum(BreachType, name="breach_type"), default=BreachType.confidentiality, nullable=False
    )
    discovered_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurred_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    records_affected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data_categories: Mapped[str] = mapped_column(String(255), default="")
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.low, nullable=False
    )
    reported_to_regulator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    regulator_report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notification_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subjects_notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[BreachStatus] = mapped_column(
        SAEnum(BreachStatus, name="breach_status"), default=BreachStatus.open, nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    root_cause: Mapped[str] = mapped_column(Text, default="")
    remediation: Mapped[str] = mapped_column(Text, default="")

    @property
    def notification_overdue(self) -> bool:
        """True once the 72-hour regulator-notification window has lapsed unmet."""
        return (
            self.notification_required
            and not self.reported_to_regulator
            and self.discovered_date is not None
            and self.discovered_date < date.today() - timedelta(days=3)
        )


# ========================================================= consent record ===
class ConsentRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin, Base):
    """A single subject-consent ledger entry (grant / withdrawal)."""

    __tablename__ = "consent_records"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    subject_name: Mapped[str] = mapped_column(String(200), default="", index=True)
    purpose: Mapped[str] = mapped_column(String(255), default="")
    consent_given: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consent_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    withdrawal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    channel: Mapped[str] = mapped_column(String(120), default="")
    lawful_basis: Mapped[LawfulBasis] = mapped_column(
        SAEnum(LawfulBasis, name="lawful_basis"), default=LawfulBasis.consent, nullable=False
    )
    status: Mapped[ConsentStatus] = mapped_column(
        SAEnum(ConsentStatus, name="consent_status"), default=ConsentStatus.active, nullable=False
    )
