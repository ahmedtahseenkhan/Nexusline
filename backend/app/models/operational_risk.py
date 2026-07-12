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

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text, Uuid
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
    process: Mapped[str] = mapped_column(String(200), default="")
    assessor: Mapped[str] = mapped_column(String(200), default="")
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
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    assessment: Mapped[RcsaAssessment] = relationship(back_populates="risks")

    @property
    def inherent_score(self) -> int:
        return (self.inherent_likelihood or 0) * (self.inherent_impact or 0)

    @property
    def residual_score(self) -> int:
        return (self.residual_likelihood or 0) * (self.residual_impact or 0)


# =================================================================== KRIs ===
class KeyRiskIndicator(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "key_risk_indicators"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    business_area: Mapped[str] = mapped_column(String(200), default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
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

    measurements: Mapped[list["KriMeasurement"]] = relationship(
        back_populates="kri", cascade="all, delete-orphan", lazy="selectin",
        order_by="KriMeasurement.as_of_date",
    )

    @property
    def status(self) -> KriStatus:
        if self.current_value is None:
            return KriStatus.no_data
        cur = float(self.current_value)
        warn = float(self.warning_threshold) if self.warning_threshold is not None else None
        lim = float(self.limit_threshold) if self.limit_threshold is not None else None
        if self.direction == KriDirection.higher_is_worse:
            if lim is not None and cur >= lim:
                return KriStatus.red
            if warn is not None and cur >= warn:
                return KriStatus.amber
            return KriStatus.green
        # lower_is_worse
        if lim is not None and cur <= lim:
            return KriStatus.red
        if warn is not None and cur <= warn:
            return KriStatus.amber
        return KriStatus.green

    @property
    def is_breached(self) -> bool:
        return self.status == KriStatus.red


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
    business_line: Mapped[str] = mapped_column(String(200), default="")
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

    @property
    def net_loss(self) -> float:
        return float(self.gross_loss or 0) - float(self.recovery or 0)
