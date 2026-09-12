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
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
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
issue_risks = Table(
    "issue_risks",
    Base.metadata,
    Column("issue_id", Uuid, ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)

issue_controls = Table(
    "issue_controls",
    Base.metadata,
    Column("issue_id", Uuid, ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True),
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
)

issue_requirements = Table(
    "issue_requirements",
    Base.metadata,
    Column("issue_id", Uuid, ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True),
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
)

issue_assets = Table(
    "issue_assets",
    Base.metadata,
    Column("issue_id", Uuid, ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)

issue_vendors = Table(
    "issue_vendors",
    Base.metadata,
    Column("issue_id", Uuid, ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True),
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
)


class Issue(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A single tracked finding/gap with a corrective-action plan."""

    __tablename__ = "issues"
    # Phase 2: root cause and independent validation before closure.
    root_cause_category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # root_cause_category list
    validated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # validator; must differ from the owner
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_result: Mapped[str | None] = mapped_column(String(16), nullable=True)  # effective | not_effective
    validation_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

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
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: governed lookup value; replaces free-text `category`
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.medium, nullable=False
    )
    status: Mapped[IssueStatus2] = mapped_column(
        SAEnum(IssueStatus2, name="issue_status"), default=IssueStatus2.open, nullable=False
    )

    # ---- ownership / timing ----
    owner: Mapped[str] = mapped_column(String(200), default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `owner`
    business_unit: Mapped[str] = mapped_column(String(200), default="")
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: business unit; replaces free-text `business_unit`
    identified_date: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Turnaround-time clock, derived from the tenant's SLA policy for this severity by
    # ``services.sla``. Distinct from any agreed ``due_date``: this is what the policy
    # allows, that is what was promised. ``tat_breached_at`` records the first day the
    # window lapsed.
    tat_due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    tat_breached_at: Mapped[date | None] = mapped_column(Date, nullable=True)
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
    due_date_changes: Mapped[list["IssueDueDateChange"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
        order_by="IssueDueDateChange.created_at",
    )

    # Phase 2 typed links (``issue_risks`` …). ``viewonly`` + ``noload``: loading an issue
    # never drags in each target's own eager graph (every core record selectin-loads its
    # links). The API reads them with one lean query per kind
    # (``services.issue_closure.link_refs``) and writes the link tables directly; ask for
    # ``selectinload(Issue.risks)`` explicitly where ORM objects are wanted (CSV export).
    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary=issue_risks, viewonly=True, lazy="noload",
        secondaryjoin="and_(issue_risks.c.risk_id == Risk.id, Risk.deleted == False)",
    )
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        "Control", secondary=issue_controls, viewonly=True, lazy="noload",
        secondaryjoin="and_(issue_controls.c.control_id == Control.id, Control.deleted == False)",
    )
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        "Requirement", secondary=issue_requirements, viewonly=True, lazy="noload",
        secondaryjoin="and_(issue_requirements.c.requirement_id == Requirement.id, Requirement.deleted == False)",
    )
    assets: Mapped[list["Asset"]] = relationship(  # noqa: F821
        "Asset", secondary=issue_assets, viewonly=True, lazy="noload",
        secondaryjoin="and_(issue_assets.c.asset_id == Asset.id, Asset.deleted == False)",
    )
    vendors: Mapped[list["Vendor"]] = relationship(  # noqa: F821
        "Vendor", secondary=issue_vendors, viewonly=True, lazy="noload",
        secondaryjoin="and_(issue_vendors.c.vendor_id == Vendor.id, Vendor.deleted == False)",
    )

    @property
    def due_date_moves(self) -> int:
        """How many times the agreed date actually moved (approved changes of a date)."""
        return sum(1 for c in self.due_date_changes if c.status == "approved" and c.old_due_date is not None)

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
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `owner`
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
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: picked from the user list; replaces free-text `author`
    update_date: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    status_change: Mapped[str] = mapped_column(String(64), default="")

    issue: Mapped[Issue] = relationship(back_populates="updates")


class IssueDueDateChange(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Phase 2: every move of an issue's due date, with who asked, why, and who approved.
    Regulators track slippage ("how many times was the date moved")."""

    __tablename__ = "issue_due_date_changes"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="approved", nullable=False)  # pending|approved|rejected
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # who asked for the new date
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # who approved it
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
