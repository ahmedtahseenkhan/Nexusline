"""Board & Committee Governance — the corporate-governance backbone banks run.

* **Committee** — a board or management committee (board, audit, risk, ALCO, Shariah,
  IT steering, …) with its charter, chair/secretary, membership and meeting cadence.
* **Meeting** — a convened sitting of a committee: agenda, minutes, attendance and
  whether quorum was met, moving through scheduled → held → minuted.
* **MeetingDecision** — the decision / action / resolution log for a meeting, with an
  owner, due date and an overdue flag that powers the enterprise action tracker.
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
from app.models.enums import ReviewFrequency


# ============================================================ local enums ===
class CommitteeType(str, enum.Enum):
    """The board / management committee taxonomy common to Pakistani banks."""

    board = "board"
    audit = "audit"
    risk = "risk"
    credit = "credit"
    hr = "hr"
    it_steering = "it_steering"
    shariah = "shariah"
    alco = "alco"
    compliance = "compliance"
    other = "other"


class CommitteeStatus(str, enum.Enum):
    active = "active"
    dissolved = "dissolved"


class MeetingStatus(str, enum.Enum):
    """Lifecycle of a committee sitting."""

    scheduled = "scheduled"
    held = "held"
    cancelled = "cancelled"
    minuted = "minuted"


class DecisionType(str, enum.Enum):
    """What a minute item is — a decision, a follow-up action or a formal resolution."""

    decision = "decision"
    action = "action"
    resolution = "resolution"


class DecisionStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
    deferred = "deferred"


# ============================================================= committees ===
class Committee(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "committees"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    committee_type: Mapped[CommitteeType] = mapped_column(
        SAEnum(CommitteeType, name="committee_type"), default=CommitteeType.board, nullable=False
    )
    charter: Mapped[str] = mapped_column(Text, default="")
    chairperson: Mapped[str] = mapped_column(String(200), default="")
    secretary: Mapped[str] = mapped_column(String(200), default="")
    members: Mapped[str] = mapped_column(Text, default="")
    meeting_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.quarterly, nullable=False,
    )
    status: Mapped[CommitteeStatus] = mapped_column(
        SAEnum(CommitteeStatus, name="committee_status"), default=CommitteeStatus.active, nullable=False
    )

    meetings: Mapped[list["Meeting"]] = relationship(
        back_populates="committee", cascade="all, delete-orphan", lazy="selectin",
        order_by="Meeting.created_at.desc()",
    )

    @property
    def meeting_count(self) -> int:
        return len(self.meetings)


class Meeting(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single sitting of a committee (agenda / minutes / attendance)."""

    __tablename__ = "committee_meetings"

    committee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("committees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    meeting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    location: Mapped[str] = mapped_column(String(200), default="")
    agenda: Mapped[str] = mapped_column(Text, default="")
    minutes: Mapped[str] = mapped_column(Text, default="")
    attendees: Mapped[str] = mapped_column(Text, default="")
    quorum_met: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[MeetingStatus] = mapped_column(
        SAEnum(MeetingStatus, name="meeting_status"), default=MeetingStatus.scheduled, nullable=False
    )

    committee: Mapped[Committee] = relationship(back_populates="meetings")
    decisions: Mapped[list["MeetingDecision"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="selectin",
        order_by="MeetingDecision.created_at",
    )

    @property
    def decision_count(self) -> int:
        return len(self.decisions)


class MeetingDecision(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A decision / action / resolution logged against a meeting."""

    __tablename__ = "meeting_decisions"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("committee_meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    decision_type: Mapped[DecisionType] = mapped_column(
        SAEnum(DecisionType, name="gov_decision_type"), default=DecisionType.decision, nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[DecisionStatus] = mapped_column(
        SAEnum(DecisionStatus, name="gov_decision_status"), default=DecisionStatus.open, nullable=False
    )
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="decisions")

    @property
    def is_overdue(self) -> bool:
        return (self.status in (DecisionStatus.open, DecisionStatus.in_progress)
                and self.due_date is not None and self.due_date < date.today())
