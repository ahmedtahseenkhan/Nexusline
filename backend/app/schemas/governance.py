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
class CommitteeBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    committee_type: CommitteeType = CommitteeType.board
    charter: str = ""
    chairperson: str = ""
    secretary: str = ""
    members: str = ""
    meeting_frequency: ReviewFrequency = ReviewFrequency.quarterly
    status: CommitteeStatus = CommitteeStatus.active
    workflow_status: WorkflowState = WorkflowState.draft


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
    workflow_status: WorkflowState | None = None


class CommitteeRead(CommitteeBase):
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
