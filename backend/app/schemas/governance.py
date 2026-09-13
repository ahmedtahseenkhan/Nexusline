from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.governance import (
    CommitteeStatus,
    CommitteeType,
    DecisionStatus,
    DecisionType,
    MeetingStatus,
)
from app.models.enums import ReviewFrequency


# ---------------------------------------------------------- meeting decisions ---
class DecisionBase(BaseModel):
    description: str = Field(min_length=1)
    decision_type: DecisionType = DecisionType.decision
    owner: str = ""
    due_date: date | None = None
    status: DecisionStatus = DecisionStatus.open
    completed_date: date | None = None


class DecisionCreate(DecisionBase):
    pass


class DecisionUpdate(BaseModel):
    description: str | None = None
    decision_type: DecisionType | None = None
    owner: str | None = None
    due_date: date | None = None
    status: DecisionStatus | None = None
    completed_date: date | None = None


class DecisionRead(DecisionBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    reference: str
    is_overdue: bool
    created_at: datetime


class DecisionTrackerRow(DecisionRead):
    """A decision/action enriched with its committee & meeting context for the tracker."""

    committee_id: uuid.UUID | None = None
    committee_reference: str = ""
    committee_name: str = ""
    meeting_reference: str = ""
    meeting_title: str = ""
    meeting_date: date | None = None


# ------------------------------------------------------------------- meetings ---
class MeetingBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    meeting_date: date | None = None
    location: str = ""
    agenda: str = ""
    minutes: str = ""
    attendees: str = ""
    quorum_met: bool = False
    status: MeetingStatus = MeetingStatus.scheduled


class MeetingCreate(MeetingBase):
    pass


class MeetingUpdate(BaseModel):
    title: str | None = None
    meeting_date: date | None = None
    location: str | None = None
    agenda: str | None = None
    minutes: str | None = None
    attendees: str | None = None
    quorum_met: bool | None = None
    status: MeetingStatus | None = None


class MeetingRead(MeetingBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    committee_id: uuid.UUID
    reference: str
    decision_count: int
    created_at: datetime
    decisions: list[DecisionRead] = []


# ----------------------------------------------------------------- committees ---
#: Longest lead time for an automatic board pack: a quarter is the longest sensible gap
#: between a pack and the sitting it is for.
MAX_BOARD_PACK_DAYS = 90


class CommitteeBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    committee_type: CommitteeType = CommitteeType.board
    charter: str = ""
    chairperson: str = ""
    secretary: str = ""
    members: str = ""
    meeting_frequency: ReviewFrequency = ReviewFrequency.quarterly
    status: CommitteeStatus = CommitteeStatus.active
    #: Phase 3: generate the board pack automatically this many days before each
    #: scheduled meeting; None = generate it by hand.
    board_pack_days_before: int | None = Field(default=None, ge=1, le=MAX_BOARD_PACK_DAYS)


class CommitteeCreate(CommitteeBase):
    pass


class CommitteeUpdate(BaseModel):
    name: str | None = None
    committee_type: CommitteeType | None = None
    charter: str | None = None
    chairperson: str | None = None
    secretary: str | None = None
    members: str | None = None
    meeting_frequency: ReviewFrequency | None = None
    status: CommitteeStatus | None = None
    board_pack_days_before: int | None = Field(default=None, ge=1, le=MAX_BOARD_PACK_DAYS)


class CommitteeRead(CommitteeBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    meeting_count: int
    created_at: datetime
    meetings: list[MeetingRead] = []


# -------------------------------------------------------------------- summary ---
class GovernanceSummary(BaseModel):
    committees_total: int
    committees_active: int
    meetings_total: int
    meetings_held: int
    meetings_scheduled: int
    open_actions: int
    overdue_actions: int


# ---------------------------------------------------------------- board packs ---
class BoardPackCreate(BaseModel):
    """Generate a board pack. Every field is optional: with none, the pack covers the
    fiscal quarter to date for the whole organisation, all sections."""

    committee_id: uuid.UUID | None = None
    meeting_id: uuid.UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    #: Section keys (``services.board_pack.SECTION_KEYS``); None = all of them.
    sections: list[str] | None = Field(default=None, max_length=20)
    #: Defaults to one built from the committee, meeting and period.
    title: str | None = Field(default=None, max_length=255)


class BoardPackFile(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int


class BoardPackRead(BaseModel):
    id: uuid.UUID
    committee_id: uuid.UUID | None = None
    committee_name: str = ""
    meeting_id: uuid.UUID | None = None
    meeting_title: str = ""
    meeting_date: date | None = None
    title: str
    period_start: date | None = None
    period_end: date | None = None
    sections: list[str] = []
    #: ready | failed
    status: str
    error: str = ""
    pdf: BoardPackFile | None = None
    xlsx: BoardPackFile | None = None
    generated_by_id: uuid.UUID | None = None
    #: The person who generated it, or "Scheduler" for an automatic pack.
    generated_by: str = ""
    generated_at: datetime | None = None
    created_at: datetime


class BoardPackSection(BaseModel):
    key: str
    title: str
