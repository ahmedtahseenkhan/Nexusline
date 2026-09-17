"""Phase 4B: workspaces (landing by line of defence), the board home, the assurance
workspace and period snapshots."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


# ================================================================ workspaces ===
class WorkspaceOption(BaseModel):
    key: str
    label: str
    href: str
    description: str = ""


class WorkspaceRead(BaseModel):
    #: first_line | second_line | audit | board — from role names, then permissions.
    line: str
    is_admin: bool = False
    #: The workspace the line of defence suggests (among those available).
    default: str
    #: The person's own choice, or None to follow the default.
    preference: str | None = None
    #: Where they land: the preference when still available, else the default.
    landing: str
    landing_href: str
    available: list[WorkspaceOption] = Field(default_factory=list)


class WorkspaceUpdate(BaseModel):
    #: A workspace key, or None to go back to the default for the line of defence.
    workspace: str | None = None


# ================================================================ board home ===
class TrendPoint(BaseModel):
    #: The date the point stands for (a quarter end, or today for the last point).
    date: date
    #: The snapshot behind it; None when no snapshot is near enough (a gap, not a zero).
    as_of: date | None = None
    value: float | None = None


class AppetitePoint(BaseModel):
    date: date
    as_of: date | None = None
    risks: int | None = None
    within: int | None = None
    elevated: int | None = None
    breach: int | None = None


class AppetiteCategory(BaseModel):
    key: str
    label: str
    appetite: int
    tolerance: int
    risks: int
    within: int
    elevated: int
    breach: int
    trend: list[AppetitePoint] = Field(default_factory=list)


class BoardAppetite(BaseModel):
    risks: int
    within: int
    elevated: int
    breach: int
    appetite: int
    tolerance: int
    categories: list[AppetiteCategory] = Field(default_factory=list)
    trend: list[AppetitePoint] = Field(default_factory=list)


class BoardTopRisk(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    score: int | None = None
    severity: str | None = None
    appetite_status: str | None = None
    owner: str = ""
    #: up | down | same | new | unknown — since the quarter began.
    movement: str = "unknown"
    movement_text: str = ""


class BoardHeadline(BaseModel):
    value: float | None = None
    detail: str = ""
    trend: list[TrendPoint] = Field(default_factory=list)


class FrameworkHeadline(BaseModel):
    name: str
    assured_pct: float | None = None
    gaps: int = 0


class KriReading(BaseModel):
    as_of: date | None = None
    value: float


class BoardKri(BaseModel):
    id: uuid.UUID
    reference: str
    name: str
    status: str
    value: float | None = None
    unit: str = ""
    threshold_text: str = ""
    owner: str = ""
    readings: list[KriReading] = Field(default_factory=list)


class BoardIssue(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    severity: str
    owner: str = ""
    due_date: date | None = None
    days_overdue: int = 0
    regulator_related: bool = False


class BoardDecision(BaseModel):
    id: uuid.UUID
    reference: str
    description: str
    decision_type: str
    status: str
    owner: str = ""
    owner_id: uuid.UUID | None = None
    due_date: date | None = None
    overdue: bool = False
    mine: bool = False
    committee: str = ""
    meeting: str = ""
    meeting_date: date | None = None


class BoardMeeting(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    committee: str
    committee_id: uuid.UUID
    meeting_date: date | None = None
    days_away: int | None = None
    #: none | draft | reviewed | released — the latest pack prepared for the meeting.
    pack_state: str = "none"
    mine: bool = False


class BoardPackEntry(BaseModel):
    id: uuid.UUID
    title: str
    committee: str = ""
    meeting: str = ""
    period_start: date | None = None
    period_end: date | None = None
    released_at: datetime | None = None
    has_pdf: bool = False
    has_xlsx: bool = False


class BoardHome(BaseModel):
    as_of: date
    organisation: str
    #: The quarter ends the trends are drawn over, oldest first.
    quarter_ends: list[date] = Field(default_factory=list)
    #: Snapshots exist at all (when not, trends say so instead of drawing nothing).
    has_snapshots: bool = False
    health_score: int | None = None
    health_band: str = ""
    appetite: BoardAppetite
    top_risks: list[BoardTopRisk] = Field(default_factory=list)
    assurance: BoardHeadline
    compliance: BoardHeadline
    frameworks: list[FrameworkHeadline] = Field(default_factory=list)
    kris_red: int = 0
    kris_amber: int = 0
    kris_in_breach: list[BoardKri] = Field(default_factory=list)
    issues_past_due: int = 0
    issues: list[BoardIssue] = Field(default_factory=list)
    governance_enabled: bool = True
    my_committees: list[str] = Field(default_factory=list)
    decisions_overdue: int = 0
    decisions_due: int = 0
    decisions: list[BoardDecision] = Field(default_factory=list)
    meetings: list[BoardMeeting] = Field(default_factory=list)
    packs: list[BoardPackEntry] = Field(default_factory=list)


# ============================================================ assurance home ===
class EngagementRow(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    status: str
    audit_type: str = ""
    lead_auditor: str = ""
    unit: str = ""
    planned_start: date | None = None
    planned_end: date | None = None
    overdue: bool = False
    procedures: int = 0
    procedures_pending: int = 0
    findings_open: int = 0


class AgeBucket(BaseModel):
    key: str
    label: str
    count: int
    overdue: int = 0


class OwnerFollowUp(BaseModel):
    owner: str
    open: int
    overdue: int
    oldest_days: int = 0


class FindingRow(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    rating: str
    status: str
    owner: str = ""
    engagement_id: uuid.UUID
    engagement: str = ""
    due_date: date | None = None
    age_days: int = 0
    days_overdue: int = 0


class LineCoverage(BaseModel):
    #: covered | partial | none | not_applicable
    state: str
    covered: int = 0
    total: int = 0
    pct: float | None = None
    last: date | None = None
    detail: str = ""


class AssuranceMapRow(BaseModel):
    key: str
    label: str
    risks: int
    controls: int
    first_line: LineCoverage
    second_line: LineCoverage
    third_line: LineCoverage
    gaps: list[str] = Field(default_factory=list)


class AssuranceHome(BaseModel):
    as_of: date
    internal_audit_enabled: bool = True
    engagements: list[EngagementRow] = Field(default_factory=list)
    engagements_overdue: int = 0
    findings_open: int = 0
    findings_overdue: int = 0
    age_buckets: list[AgeBucket] = Field(default_factory=list)
    by_owner: list[OwnerFollowUp] = Field(default_factory=list)
    overdue_findings: list[FindingRow] = Field(default_factory=list)
    #: Document (PBC) requests are not modelled yet.
    document_requests_supported: bool = False
    map: list[AssuranceMapRow] = Field(default_factory=list)
    map_windows: dict[str, int] = Field(default_factory=dict)


# ================================================================= snapshots ===
class SnapshotDate(BaseModel):
    as_of: date
    sources: list[str] = Field(default_factory=list)
    keys: int = 0


class SnapshotCaptured(BaseModel):
    as_of: date
    rows: int
