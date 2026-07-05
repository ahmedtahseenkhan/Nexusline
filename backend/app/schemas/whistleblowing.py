from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import Severity
from app.models.whistleblowing import WhistleCategory, WhistleChannel, WhistleStatus


# --------------------------------------------------------------- case-log updates ---
class WhistleUpdateCreate(BaseModel):
    note: str = ""
    author: str = ""
    update_date: date | None = None
    status_change: str = ""


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
    workflow_status: WorkflowState = WorkflowState.draft


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
    workflow_status: WorkflowState | None = None


class WhistleReportRead(WhistleReportBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    update_count: int
    is_open: bool
    created_at: datetime
    updates: list[WhistleUpdateRead] = []
