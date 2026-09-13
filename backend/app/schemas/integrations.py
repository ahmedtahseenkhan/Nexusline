from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class CctRead(CctBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
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


class ConnectorRead(ConnectorBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    is_stale: bool
    created_at: datetime
    #: Phase 3: a monitoring-feed token is live (never the token or its hash).
    has_ingest_token: bool = False


# ------------------------------------------------------ monitoring feed (phase 3) ---
#: Largest ``details`` object a monitoring tool may send with one result, as JSON text.
MAX_DETAILS_CHARS = 50_000


class IngestTokenIssued(BaseModel):
    """Returned once when a feed token is generated; only its SHA-256 is stored."""

    connector_id: uuid.UUID
    token: str
    endpoint: str
    header: str
    note: str


class IngestEvidence(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    #: Where the evidence lives: a URL, a ticket, a log location.
    reference: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=500)
    valid_until: date | None = None


class IngestBody(BaseModel):
    """One control-monitoring result pushed by a monitoring tool."""

    control_reference: str | None = Field(default=None, max_length=64)
    control_id: uuid.UUID | None = None
    #: The monitoring test (``CCM-…``) to record the run on, when this connector has more
    #: than one test for the control.
    test_reference: str | None = Field(default=None, max_length=32)
    result: Literal["passed", "failed", "passed_with_exceptions"]
    #: When the check ran. A date alone, or a time without an offset, is taken in the
    #: organisation's timezone. Can't be in the future.
    observed_at: datetime
    summary: str = Field(min_length=1, max_length=2000)
    details: dict[str, Any] | list[Any] | None = None
    #: Share of items that passed (0-100). Defaults to 100 for passed and 0 for failed;
    #: required for passed_with_exceptions.
    pass_rate: float | None = Field(default=None, ge=0, le=100)
    evidence: IngestEvidence | None = None

    @model_validator(mode="after")
    def _control_and_details(self) -> "IngestBody":
        if self.control_id is None and not (self.control_reference or "").strip():
            raise ValueError("Send control_reference or control_id.")
        if self.details is not None and len(json.dumps(self.details, default=str)) > MAX_DETAILS_CHARS:
            raise ValueError(f"details is larger than {MAX_DETAILS_CHARS} characters of JSON; send a summary and a link.")
        if self.result == "passed_with_exceptions" and self.pass_rate is None:
            raise ValueError("pass_rate: say what share of items passed (0-100) for a result with exceptions.")
        return self


class IngestResult(BaseModel):
    """What the feed tells the monitoring tool: what was recorded, no names or history."""

    connector_reference: str
    control_id: uuid.UUID
    control_reference: str
    evidence_id: uuid.UUID
    run_id: uuid.UUID | None = None
    test_reference: str | None = None
    alert_raised: bool = False
    note: str = ""


class IngestLogItem(BaseModel):
    at: datetime
    result: str
    control_id: uuid.UUID | None = None
    control_reference: str = ""
    summary: str = ""
    observed_at: str = ""
    evidence_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    test_reference: str | None = None
    alert_raised: bool = False


class ConnectorFeedRead(BaseModel):
    connector_id: uuid.UUID
    has_token: bool
    endpoint: str
    last_ingest_at: datetime | None = None
    ingests_last_30_days: int = 0
    recent: list[IngestLogItem] = []
