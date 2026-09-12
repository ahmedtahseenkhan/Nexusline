from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import (
    IncidentStatus,
    RegulatoryReportStatus,
    RegulatoryReportType,
    Severity,
    StageStatus,
)
from app.schemas.common import LookupRef, UserRef

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


class RegReportCreate(BaseModel):
    regulator: str = "SBP"
    report_type: RegulatoryReportType = RegulatoryReportType.initial_notification
    deadline: date | None = None
    status: RegulatoryReportStatus = RegulatoryReportStatus.pending
    submitted_at: date | None = None
    reference: str = ""
    summary: str = ""
    submitted_by: str = ""
    submitted_by_id: uuid.UUID | None = Field(default=None, description=_SUBMITTER)


class RegReportUpdate(BaseModel):
    regulator: str | None = None
    report_type: RegulatoryReportType | None = None
    deadline: date | None = None
    status: RegulatoryReportStatus | None = None
    submitted_at: date | None = None
    reference: str | None = None
    summary: str | None = None
    submitted_by: str | None = None
    submitted_by_id: uuid.UUID | None = Field(default=None, description=_SUBMITTER)


class RegReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID
    regulator: str
    report_type: RegulatoryReportType
    deadline: date | None
    status: RegulatoryReportStatus
    submitted_at: date | None
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
    detected_at: date | None = None
    occurred_at: date | None = None
    resolved_at: date | None = None
    is_reportable: bool = False
    regulator: str = ""
    regulator_id: uuid.UUID | None = Field(default=None, description=_REGULATOR)
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class IncidentCreate(IncidentBase):
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
    detected_at: date | None = None
    occurred_at: date | None = None
    resolved_at: date | None = None
    is_reportable: bool | None = None
    regulator: str | None = None
    regulator_id: uuid.UUID | None = Field(default=None, description=_REGULATOR)
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
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
    created_at: datetime
