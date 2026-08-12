"""Turnaround-time (TAT) policy — how long a record of a given severity may stay open.

A bank's remediation standard is usually written as "critical findings within 15 days,
high within 30". Until that clock exists in the system, the standard lives in a policy
document and nobody knows it has been missed until an auditor counts. One row here per
(record type, severity) turns it into something the platform measures, warns about
before it lapses, and escalates when it does.

This is separate from a record's own ``due_date``: that is the date agreed with the
action owner, while ``tat_due_date`` is what the policy allows. Banks track both, and
the gap between them is itself worth seeing.
"""
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Severity


class SlaPolicy(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "sla_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "severity", name="uq_sla_policy_scope"),
        CheckConstraint("target_days BETWEEN 1 AND 3650", name="ck_sla_target_days"),
        CheckConstraint("warn_at_percent BETWEEN 1 AND 100", name="ck_sla_warn_percent"),
    )

    #: One of ``app.services.sla.ENTITIES`` — risk, issue, audit_finding, incident.
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), nullable=False
    )

    #: Calendar days from the record being raised to it having to be closed.
    target_days: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Raise an early warning once this much of the window has elapsed. 80 means the
    #: owner hears about it with a fifth of the time left, not on the day it lapses.
    warn_at_percent: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    #: Role notified in addition to the owner when the window is breached. Blank = none.
    escalate_to_role: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
