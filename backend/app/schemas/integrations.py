from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import ReviewFrequency
from app.models.integrations import (
    CcmResult,
    CcmStatus,
    ConnectorStatus,
    ConnectorType,
)


# ----------------------------------------------------------- control test runs ---
class RunBase(BaseModel):
    run_date: date | None = None
    result: CcmResult = CcmResult.not_run
    findings: str = ""
    evidence_ref: str = ""
    pass_rate: float = Field(default=0, ge=0, le=100)


class RunCreate(RunBase):
    pass


class RunRead(RunBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    test_id: uuid.UUID
    created_at: datetime


# ------------------------------------------------------ automated control tests ---
class CctBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    control_ref: str = ""
    connector_id: uuid.UUID | None = None
    description: str = ""
    test_logic: str = ""
    frequency: ReviewFrequency = ReviewFrequency.monthly
    owner: str = ""
    last_run: date | None = None
    last_result: CcmResult = CcmResult.not_run
    pass_rate: float = Field(default=0, ge=0, le=100)
    status: CcmStatus = CcmStatus.active
    workflow_status: WorkflowState = WorkflowState.draft


class CctCreate(CctBase):
    pass


class CctUpdate(BaseModel):
    name: str | None = None
    control_ref: str | None = None
    connector_id: uuid.UUID | None = None
    description: str | None = None
    test_logic: str | None = None
    frequency: ReviewFrequency | None = None
    owner: str | None = None
    last_run: date | None = None
    last_result: CcmResult | None = None
    pass_rate: float | None = Field(default=None, ge=0, le=100)
    status: CcmStatus | None = None
    workflow_status: WorkflowState | None = None


class CctRead(CctBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    run_count: int
    created_at: datetime
    runs: list[RunRead] = []


# ----------------------------------------------------------------- connectors ---
class ConnectorBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    connector_type: ConnectorType = ConnectorType.api
    description: str = ""
    endpoint_url: str = ""
    auth_method: str = ""
    sync_frequency: ReviewFrequency = ReviewFrequency.monthly
    owner: str = ""
    config_note: str = ""
    status: ConnectorStatus = ConnectorStatus.configured
    last_sync: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class ConnectorCreate(ConnectorBase):
    pass


class ConnectorUpdate(BaseModel):
    name: str | None = None
    connector_type: ConnectorType | None = None
    description: str | None = None
    endpoint_url: str | None = None
    auth_method: str | None = None
    sync_frequency: ReviewFrequency | None = None
    owner: str | None = None
    config_note: str | None = None
    status: ConnectorStatus | None = None
    last_sync: date | None = None
    workflow_status: WorkflowState | None = None


class ConnectorRead(ConnectorBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    is_stale: bool
    created_at: datetime
