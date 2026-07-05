"""Unified Issues & Actions (CAPA) — the connective-tissue module.

Aggregates findings and remediation actions raised anywhere in the platform
(internal audit, compliance, RCSA, Shariah reviews, assessments, incidents and
external / SBP inspections) into ONE issue universe with a full remediation
lifecycle.

* **Issue** — a single tracked finding/gap with its source, severity, owner, due
  date and RAG-style status, plus a corrective/preventive-action plan.
* **IssueAction** — a CAPA line (corrective or preventive) under an issue, with
  its own owner, due date and completion tracking.
* **IssueUpdate** — a chronological progress-log entry on an issue.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, Uuid
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
from app.models.enums import Severity


# ============================================================= local enums ===
class IssueSource(str, enum.Enum):
    """Where the issue originated — every other module feeds into this."""

    internal_audit = "internal_audit"
    compliance = "compliance"
    rcsa = "rcsa"
    shariah = "shariah"
    assessment = "assessment"
    incident = "incident"
    external_inspection = "external_inspection"
    risk_assessment = "risk_assessment"
    self_identified = "self_identified"
    other = "other"


class IssueStatus2(str, enum.Enum):
    """Remediation lifecycle of an issue (db type name: ``issue_status``).

    Named ``IssueStatus2`` to avoid clashing with the existing
    IncidentStatus / FindingStatus classes elsewhere in the codebase.
    """

    open = "open"
    in_progress = "in_progress"
    remediated = "remediated"
    closed = "closed"
    risk_accepted = "risk_accepted"


class CapaType(str, enum.Enum):
    """Corrective vs preventive action (CAPA)."""

    corrective = "corrective"
    preventive = "preventive"


class ActionStatus(str, enum.Enum):
    """Lifecycle of a single CAPA action line."""

    open = "open"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


# ================================================================== issues ===
class Issue(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A single tracked finding/gap with a corrective-action plan."""

    __tablename__ = "issues"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")

    # ---- classification / source ----
    source_type: Mapped[IssueSource] = mapped_column(
        SAEnum(IssueSource, name="issue_source"),
        default=IssueSource.self_identified, nullable=False,
    )
    source_reference: Mapped[str] = mapped_column(String(255), default="")  # e.g. "AUD-004 finding 3"
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # optional link to originating record
    category: Mapped[str] = mapped_column(String(120), default="")
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.medium, nullable=False
    )
    status: Mapped[IssueStatus2] = mapped_column(
        SAEnum(IssueStatus2, name="issue_status"), default=IssueStatus2.open, nullable=False
    )

    # ---- ownership / timing ----
    owner: Mapped[str] = mapped_column(String(200), default="")
    business_unit: Mapped[str] = mapped_column(String(200), default="")
    identified_date: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ---- remediation narrative / flags ----
    root_cause: Mapped[str] = mapped_column(Text, default="")
    management_response: Mapped[str] = mapped_column(Text, default="")
    repeat_finding: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    regulator_related: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    actions: Mapped[list["IssueAction"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", lazy="selectin",
        order_by="IssueAction.created_at",
    )
    updates: Mapped[list["IssueUpdate"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", lazy="selectin",
        order_by="IssueUpdate.created_at",
    )

    @property
    def action_count(self) -> int:
        return len(self.actions)

    @property
    def open_action_count(self) -> int:
        return sum(1 for a in self.actions if a.status in (ActionStatus.open, ActionStatus.in_progress))

    @property
    def is_overdue(self) -> bool:
        return (
            self.status not in (IssueStatus2.closed, IssueStatus2.remediated, IssueStatus2.risk_accepted)
            and self.due_date is not None
            and self.due_date < date.today()
        )

    @property
    def age_days(self) -> int:
        if self.identified_date is None:
            return 0
        return (date.today() - self.identified_date).days


class IssueAction(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single corrective/preventive action (CAPA line) under an issue."""

    __tablename__ = "issue_actions"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    action_type: Mapped[CapaType] = mapped_column(
        SAEnum(CapaType, name="capa_type"), default=CapaType.corrective, nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ActionStatus] = mapped_column(
        SAEnum(ActionStatus, name="issue_action_status"), default=ActionStatus.open, nullable=False
    )
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_note: Mapped[str] = mapped_column(Text, default="")

    issue: Mapped[Issue] = relationship(back_populates="actions")

    @property
    def is_overdue(self) -> bool:
        return (
            self.status not in (ActionStatus.done, ActionStatus.cancelled)
            and self.due_date is not None
            and self.due_date < date.today()
        )


class IssueUpdate(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A chronological progress-log entry on an issue."""

    __tablename__ = "issue_updates"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    update_date: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    status_change: Mapped[str] = mapped_column(String(64), default="")

    issue: Mapped[Issue] = relationship(back_populates="updates")
