from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import WorkflowState
from app.models.enums import Severity
from app.models.whistleblowing import WhistleCategory, WhistleChannel, WhistleStatus


# --------------------------------------------------------------- case-log updates ---
class WhistleUpdateCreate(BaseModel):
    note: str = ""
    author: str = ""
    update_date: date | None = None
    # The status this entry moves the case to; none for a plain note. It transitions the
    # report itself (validated against the case lifecycle), not just the log line.
    status_change: WhistleStatus | None = None

    @field_validator("status_change", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if v == "" else v


class WhistleUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    report_id: uuid.UUID
    note: str
    author: str
    update_date: date | None
    status_change: str
    created_at: datetime


# ---------------------------------------------------------- whistleblowing reports ---
class WhistleReportBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: WhistleCategory = WhistleCategory.other
    anonymous: bool = True
    reporter_name: str = ""
    reporter_contact: str = ""
    channel: WhistleChannel = WhistleChannel.web_portal
    received_date: date | None = None
    severity: Severity = Severity.medium
    status: WhistleStatus = WhistleStatus.received
    assigned_to: str = ""
    tracking_code: str = ""
    confidentiality_note: str = ""
    outcome: str = ""


class WhistleReportCreate(WhistleReportBase):
    pass


class WhistleReportUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category: WhistleCategory | None = None
    anonymous: bool | None = None
    reporter_name: str | None = None
    reporter_contact: str | None = None
    channel: WhistleChannel | None = None
    received_date: date | None = None
    severity: Severity | None = None
    status: WhistleStatus | None = None
    assigned_to: str | None = None
    tracking_code: str | None = None
    confidentiality_note: str | None = None
    outcome: str | None = None


class WhistleReportRead(WhistleReportBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    update_count: int
    is_open: bool
    created_at: datetime
    updates: list[WhistleUpdateRead] = []
