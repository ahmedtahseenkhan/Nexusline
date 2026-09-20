from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import (
    BaselEventType,
    IncidentStatus,
    RegulatoryReportStatus,
    RegulatoryReportType,
    Severity,
    StageStatus,
)
from app.schemas.common import GraphRef, LookupRef, UserRef

# Phase 1 picker fields: each ``<name>_id`` wins over the legacy ``<name>`` text when both
# are sent. The text is still accepted this release (older clients, CSV import) and is
# matched to an id when it names exactly one active record; on read it holds the picked
# record's display name, or the unmatched text.
_SUBMITTER = "User who submitted the report; wins over `submitted_by` text."
_ASSIGNEE = "User handling the incident; wins over `assignee` text."
_REPORTER = "User who reported the incident; wins over `reported_by` text."
_CATEGORY = "Value from the `incident_type` lookup list; wins over `category` text."
_CLASSIFICATION = "Value from the `incident_classification` lookup list; wins over `classification` text."
_REGULATOR = "Value from the `regulator` lookup list; wins over `regulator` text."
_WF_OWNER = "User who owns the approval workflow. `workflow_status` changes only through the workflow endpoints."

# Phase 2: the incident timeline and the regulator's clock are timestamps. Send ISO 8601
# with an offset ("2026-09-01T14:30:00+05:00"); a value without one — including a bare
# date ("2026-09-01", taken as 00:00) — is read in the organisation's timezone.
_TS = "Timestamp (ISO 8601). Without an offset — or as a bare date, meaning 00:00 — it is read in the organisation's timezone."
_OCCURRED = "When the incident happened. " + _TS
_DETECTED = "When it was detected; starts the regulator's clock. " + _TS
_CONTAINED = "When it was contained. Stamped automatically when the status moves to contained. " + _TS
_RESOLVED = "When it was resolved. Stamped automatically when the status moves to resolved/closed. " + _TS
_NEAR_MISS = "Nothing was lost: a near miss carries no cost and is left out of loss totals."
_PDB = "Personal data was breached: the first time this is set a linked data-breach record is created and the DPO notified."
_REPORTABLE = "Owed to a regulator: setting it creates the initial and final reports with deadlines from detection."
_REPORT_REGULATOR = "Value from the `regulator` lookup list; wins over `regulator` text."


class RegReportCreate(BaseModel):
    regulator: str = "SBP"
    regulator_id: uuid.UUID | None = Field(default=None, description=_REPORT_REGULATOR)
    report_type: RegulatoryReportType = RegulatoryReportType.initial_notification
    deadline: datetime | None = Field(default=None, description=_TS)
    status: RegulatoryReportStatus = RegulatoryReportStatus.pending
    submitted_at: datetime | None = Field(default=None, description=_TS)
    reference: str = ""
    summary: str = ""
    submitted_by: str = ""
    submitted_by_id: uuid.UUID | None = Field(default=None, description=_SUBMITTER)


class RegReportUpdate(BaseModel):
    regulator: str | None = None
    regulator_id: uuid.UUID | None = Field(default=None, description=_REPORT_REGULATOR)
    report_type: RegulatoryReportType | None = None
    deadline: datetime | None = Field(default=None, description=_TS)
    status: RegulatoryReportStatus | None = None
    submitted_at: datetime | None = Field(default=None, description=_TS)
    reference: str | None = None
    summary: str | None = None
    submitted_by: str | None = None
    submitted_by_id: uuid.UUID | None = Field(default=None, description=_SUBMITTER)


class RegReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    regulator: str
    regulator_id: uuid.UUID | None = None
    regulator_ref: LookupRef | None = None
    report_type: RegulatoryReportType
    deadline: datetime | None
    status: RegulatoryReportStatus
    submitted_at: datetime | None
    reference: str
    summary: str
    submitted_by: str
    submitted_by_id: uuid.UUID | None = None
    submitted_by_ref: UserRef | None = None
    is_overdue: bool
    created_at: datetime


class IncRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


class IncidentLossRef(BaseModel):
    """A loss event raised from the incident (``Incident.loss_events``)."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    status: str = ""
    gross_loss: float = 0
    recovery: float = 0
    net_loss: float = 0
    currency: str = ""
    occurrence_date: date | None = None


class StageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    order_index: int = 0


class StageUpdate(BaseModel):
    status: StageStatus | None = None
    notes: str | None = None


class StageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    name: str
    order_index: int
    status: StageStatus
    notes: str
    completed_at: date | None


class IncidentBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = ""
    category_id: uuid.UUID | None = Field(default=None, description=_CATEGORY)
    classification: str = ""
    classification_id: uuid.UUID | None = Field(default=None, description=_CLASSIFICATION)
    severity: Severity = Severity.medium
    status: IncidentStatus = IncidentStatus.open
    assignee: str = ""
    assignee_id: uuid.UUID | None = Field(default=None, description=_ASSIGNEE)
    reported_by: str = ""
    reported_by_id: uuid.UUID | None = Field(default=None, description=_REPORTER)
    impact: str = ""
    root_cause: str = ""
    lessons_learned: str = ""
    cost: float | None = Field(default=None, ge=0)
    detected_at: datetime | None = Field(default=None, description=_DETECTED)
    occurred_at: datetime | None = Field(default=None, description=_OCCURRED)
    contained_at: datetime | None = Field(default=None, description=_CONTAINED)
    resolved_at: datetime | None = Field(default=None, description=_RESOLVED)
    customers_affected: int | None = Field(default=None, ge=0)
    records_affected: int | None = Field(default=None, ge=0)
    near_miss: bool = Field(default=False, description=_NEAR_MISS)
    personal_data_breach: bool = Field(default=False, description=_PDB)
    is_reportable: bool = Field(default=False, description=_REPORTABLE)
    regulator: str = ""
    regulator_id: uuid.UUID | None = Field(default=None, description=_REGULATOR)
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


_NOTIFIED = ("When the regulator was notified: the initial report's submission time (marks it submitted; "
             "null reopens it). Needs a reportable incident. " + _TS)
_REG_REF = "The regulator's acknowledgement reference, kept on the initial report."


class IncidentCreate(IncidentBase):
    notified_at: datetime | None = Field(default=None, description=_NOTIFIED)
    regulator_reference: str | None = Field(default=None, max_length=120, description=_REG_REF)
    control_ids: list[uuid.UUID] = Field(default_factory=list)
    vendor_ids: list[uuid.UUID] = Field(default_factory=list)
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    risk_ids: list[uuid.UUID] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = Field(default=None, description=_CATEGORY)
    classification: str | None = None
    classification_id: uuid.UUID | None = Field(default=None, description=_CLASSIFICATION)
    severity: Severity | None = None
    status: IncidentStatus | None = None
    assignee: str | None = None
    assignee_id: uuid.UUID | None = Field(default=None, description=_ASSIGNEE)
    reported_by: str | None = None
    reported_by_id: uuid.UUID | None = Field(default=None, description=_REPORTER)
    impact: str | None = None
    root_cause: str | None = None
    lessons_learned: str | None = None
    cost: float | None = Field(default=None, ge=0)
    detected_at: datetime | None = Field(default=None, description=_DETECTED)
    occurred_at: datetime | None = Field(default=None, description=_OCCURRED)
    contained_at: datetime | None = Field(default=None, description=_CONTAINED)
    resolved_at: datetime | None = Field(default=None, description=_RESOLVED)
    customers_affected: int | None = Field(default=None, ge=0)
    records_affected: int | None = Field(default=None, ge=0)
    near_miss: bool | None = Field(default=None, description=_NEAR_MISS)
    personal_data_breach: bool | None = Field(default=None, description=_PDB)
    is_reportable: bool | None = Field(default=None, description=_REPORTABLE)
    regulator: str | None = None
    regulator_id: uuid.UUID | None = Field(default=None, description=_REGULATOR)
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    notified_at: datetime | None = Field(default=None, description=_NOTIFIED)
    regulator_reference: str | None = Field(default=None, max_length=120, description=_REG_REF)
    control_ids: list[uuid.UUID] | None = None
    vendor_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None


class IncidentRead(IncidentBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    assignee_ref: UserRef | None = None
    reported_by_ref: UserRef | None = None
    category_ref: LookupRef | None = None
    classification_ref: LookupRef | None = None
    regulator_ref: LookupRef | None = None
    workflow_owner_ref: UserRef | None = None
    stage_count: int
    completed_stages: int
    lifecycle_complete: bool
    current_stage: str | None
    stages: list[StageRead] = []
    regulatory_reports: list[RegReportRead] = []
    controls: list[IncRef] = []
    vendors: list[IncRef] = []
    assets: list[IncRef] = []
    risks: list[IncRef] = []
    loss_events: list[IncidentLossRef] = []
    data_breaches: list[GraphRef] = []
    # Regulator-notification clock, read off the initial report (services.incident_clock).
    notification_deadline: datetime | None = None
    notified_at: datetime | None = None
    regulator_reference: str | None = None
    hours_to_deadline: float | None = Field(
        default=None, description="Hours left to the notification deadline (to the submission once made); negative when late."
    )
    notified_on_time: bool | None = Field(
        default=None, description="True/False once notified; False once the deadline passes unnotified; otherwise None."
    )
    # Response times in hours: detected − occurred, contained − detected, resolved − detected.
    mttd_hours: float | None = None
    mttc_hours: float | None = None
    mttr_hours: float | None = None
    created_at: datetime


class IncidentAverages(BaseModel):
    """Mean response times in hours over the incidents that recorded both ends."""

    mttd_hours: float | None = None
    mttd_count: int = 0
    mttc_hours: float | None = None
    mttc_count: int = 0
    mttr_hours: float | None = None
    mttr_count: int = 0


class IncidentSummary(BaseModel):
    total: int
    open: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    reportable: int
    notifications_pending: int
    notifications_overdue: int
    notified_on_time: int
    notified_late: int
    near_misses: int
    personal_data_breaches: int
    customers_affected: int
    records_affected: int
    #: Estimated cost of incidents, near misses excluded (they carry no loss).
    total_cost: float
    response_times: IncidentAverages


class LossFromIncident(BaseModel):
    """Optional overrides for ``POST /incidents/{id}/loss-event``; anything left out is
    taken from the incident (title, cost, dates, owner, root cause) or, for the business
    unit, from its linked assets/risks when they name exactly one."""

    title: str | None = Field(default=None, max_length=255)
    basel_event_type: BaselEventType | None = None
    business_unit_id: uuid.UUID | None = None
    gross_loss: float | None = Field(default=None, ge=0)
    recovery: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
