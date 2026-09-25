from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import WorkflowState
from app.models.enums import ExceptionStatus, ExceptionType
from app.schemas.tenant_settings import currency_or_blank


class LinkRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


class ExceptionBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    exception_type: ExceptionType = ExceptionType.risk
    classification: str = ""
    rationale: str = ""
    compensating_controls: str = ""
    business_owner: str = ""
    start_date: date | None = None
    expires_at: date | None = None
    # The exposure the exception leaves uncovered; blank currency = the reporting
    # currency. Checked against the approver's delegation-of-authority mandate.
    exposure_amount: float | None = Field(default=None, ge=0)
    exposure_currency: str = Field(default="", max_length=8)


class ExceptionCreate(ExceptionBase):
    _ccy = field_validator("exposure_currency")(currency_or_blank)

    closure_date: date | None = None
    risk_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)
    requirement_ids: list[uuid.UUID] = Field(default_factory=list)
    control_ids: list[uuid.UUID] = Field(default_factory=list)
    asset_ids: list[uuid.UUID] = Field(default_factory=list)


class ExceptionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    exception_type: ExceptionType | None = None
    classification: str | None = None
    rationale: str | None = None
    compensating_controls: str | None = None
    business_owner: str | None = None
    status: ExceptionStatus | None = None  # manual override; /decision & /close are the primary path
    start_date: date | None = None
    expires_at: date | None = None
    closure_date: date | None = None
    exposure_amount: float | None = Field(default=None, ge=0)
    exposure_currency: str | None = Field(default=None, max_length=8)
    risk_ids: list[uuid.UUID] | None = None

    _ccy = field_validator("exposure_currency")(currency_or_blank)
    policy_ids: list[uuid.UUID] | None = None
    requirement_ids: list[uuid.UUID] | None = None
    control_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None


class ExceptionDecision(BaseModel):
    approve: bool
    note: str = ""


class ExceptionRead(ExceptionBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    status: ExceptionStatus
    closure_date: date | None
    requested_by: uuid.UUID | None
    approver_id: uuid.UUID | None
    decided_at: date | None
    is_expired: bool
    risks: list[LinkRef] = []
    policies: list[LinkRef] = []
    requirements: list[LinkRef] = []
    controls: list[LinkRef] = []
    assets: list[LinkRef] = []
    created_at: datetime
