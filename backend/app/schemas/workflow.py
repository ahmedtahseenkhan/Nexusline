"""Payloads for the workflow designer and the per-record progress strip."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.workflow import (
    ApproverMode,
    StageStatus2,
    TimeoutAction,
    WorkflowInstanceStatus,
)


# ------------------------------------------------------------------ stages ---
class StageBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    #: 0 means "append": the API assigns the next position. A default of 1 would be
    #: indistinguishable from the caller explicitly asking for first place, which is how
    #: a three-stage route ends up with three stage ones.
    order_index: int = Field(default=0, ge=0, le=50)
    approver_mode: ApproverMode = ApproverMode.role
    approver_ref: str = Field(default="", max_length=200)
    required_approvals: int = Field(default=1, ge=1, le=10)
    sla_days: int = Field(default=0, ge=0, le=365)
    on_timeout: TimeoutAction = TimeoutAction.escalate


class StageCreate(StageBase):
    pass


class StageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    order_index: int | None = Field(default=None, ge=1, le=50)
    approver_mode: ApproverMode | None = None
    approver_ref: str | None = None
    required_approvals: int | None = Field(default=None, ge=1, le=10)
    sla_days: int | None = Field(default=None, ge=0, le=365)
    on_timeout: TimeoutAction | None = None


class StageRead(StageBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


# ------------------------------------------------------------- definitions ---
class DefinitionBase(BaseModel):
    entity_type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class DefinitionCreate(DefinitionBase):
    stages: list[StageCreate] = Field(default_factory=list)


class DefinitionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    enabled: bool | None = None


class DefinitionRead(DefinitionBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    enabled: bool
    stage_count: int
    stages: list[StageRead] = []
    created_at: datetime


# ---------------------------------------------------------------- instances ---
class InstanceStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_index: int
    name: str
    approver_label: str
    status: StageStatus2
    approval_request_id: uuid.UUID | None
    due_date: date | None
    decided_at: datetime | None
    decision_comment: str


class InstanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    definition_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    entity_label: str
    status: WorkflowInstanceStatus
    started_by_email: str
    completed_at: datetime | None
    total_stages: int
    completed_stages: int
    steps: list[InstanceStageRead] = []
    created_at: datetime


class StartRequest(BaseModel):
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: uuid.UUID
    entity_label: str = ""
    link: str = ""
    record_owner_email: str = ""


class StartResult(BaseModel):
    """``started=False`` means the record type has no enabled route, which is not an
    error — it is the platform's default behaviour."""

    started: bool
    reason: str = ""
    instance: InstanceRead | None = None
