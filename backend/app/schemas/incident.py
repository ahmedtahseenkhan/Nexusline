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


class RegReportCreate(BaseModel):
    regulator: str = "SBP"
    report_type: RegulatoryReportType = RegulatoryReportType.initial_notification
    deadline: date | None = None
    status: RegulatoryReportStatus = RegulatoryReportStatus.pending
    submitted_at: date | None = None
    reference: str = ""
    summary: str = ""
    submitted_by: str = ""


class RegReportUpdate(BaseModel):
    regulator: str | None = None
    report_type: RegulatoryReportType | None = None
    deadline: date | None = None
    status: RegulatoryReportStatus | None = None
    submitted_at: date | None = None
    reference: str | None = None
    summary: str | None = None
    submitted_by: str | None = None


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
    classification: str = ""
    severity: Severity = Severity.medium
    status: IncidentStatus = IncidentStatus.open
    workflow_status: WorkflowState = WorkflowState.draft
    assignee: str = ""
    reported_by: str = ""
    impact: str = ""
    root_cause: str = ""
    lessons_learned: str = ""
    cost: float | None = Field(default=None, ge=0)
    detected_at: date | None = None
    occurred_at: date | None = None
    resolved_at: date | None = None
    is_reportable: bool = False
    regulator: str = ""


class IncidentCreate(IncidentBase):
    control_ids: list[uuid.UUID] = Field(default_factory=list)
    vendor_ids: list[uuid.UUID] = Field(default_factory=list)
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    risk_ids: list[uuid.UUID] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    classification: str | None = None
    severity: Severity | None = None
    status: IncidentStatus | None = None
    workflow_status: WorkflowState | None = None
    assignee: str | None = None
    reported_by: str | None = None
    impact: str | None = None
    root_cause: str | None = None
    lessons_learned: str | None = None
    cost: float | None = Field(default=None, ge=0)
    detected_at: date | None = None
    occurred_at: date | None = None
    resolved_at: date | None = None
    is_reportable: bool | None = None
    regulator: str | None = None
    control_ids: list[uuid.UUID] | None = None
    vendor_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None


class IncidentRead(IncidentBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
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
