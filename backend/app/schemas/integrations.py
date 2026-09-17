from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.base import WorkflowState
from app.models.enums import ReviewFrequency
KriMetric = Literal["exceptions", "exception_percent", "population", "pass_rate", "value"]

from app.models.integrations import (  # noqa: E402
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
    # Phase 4: what an executed (or pushed) run observed. The exception sample is on
    # the run detail (GET /control-test-runs/{id}), not on every list.
    source: str = "manual"
    started_at: datetime | None = None
    duration_ms: int | None = None
    population_size: int | None = None
    exceptions_count: int | None = None
    metric_value: float | None = None
    error_message: str = ""
    evidence_id: uuid.UUID | None = None
    issue_id: uuid.UUID | None = None
    kri_measurement_id: uuid.UUID | None = None


class RunDetail(RunRead):
    exceptions_sample: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    test_reference: str = ""
    evidence_title: str | None = None
    issue_reference: str | None = None


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
    # Phase 4: the executable definition.
    control_id: uuid.UUID | None = None
    check_type: str = Field(default="manual", max_length=48)
    parameters: dict[str, Any] = Field(default_factory=dict)
    threshold_max_failures: int | None = Field(default=None, ge=0)
    threshold_max_percent: float | None = Field(default=None, ge=0, le=100)
    population_description: str = ""
    pass_criterion: str = ""
    kri_id: uuid.UUID | None = None
    kri_metric: KriMetric = "exceptions"


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
    control_id: uuid.UUID | None = None
    check_type: str | None = Field(default=None, max_length=48)
    parameters: dict[str, Any] | None = None
    threshold_max_failures: int | None = Field(default=None, ge=0)
    threshold_max_percent: float | None = Field(default=None, ge=0, le=100)
    population_description: str | None = None
    pass_criterion: str | None = None
    kri_id: uuid.UUID | None = None
    kri_metric: KriMetric | None = None


class CctRead(CctBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    reference: str
    run_count: int
    created_at: datetime
    #: The newest runs first (``RECENT_RUNS``); the whole log is GET …/runs.
    runs: list[RunRead] = Field(default=[], validation_alias="recent_runs")
    last_run_at: datetime | None = None
    failing_since: date | None = None
    last_error: str = ""
    issue_id: uuid.UUID | None = None
    is_executable: bool = False
    is_overdue: bool = False


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
    # Phase 4: non-secret settings for the connector type (GET /ccm/connector-types).
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=600)


class SecretsWrite(BaseModel):
    """Write-only secrets: a value replaces, a name in ``clear_secrets`` removes, anything
    not sent is kept. Never returned."""

    secrets: dict[str, str] | None = None
    clear_secrets: list[str] | None = None


class ConnectorCreate(ConnectorBase, SecretsWrite):
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
    config: dict[str, Any] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    secrets: dict[str, str] | None = None
    clear_secrets: list[str] | None = None


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
    #: Phase 4: names of the secrets on file — never their values.
    secrets_set: list[str] = []
    kind: str = ""
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_message: str = ""


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    tested_at: datetime


class RunNowResult(BaseModel):
    result: str
    message: str
    run: RunDetail | None = None
    issue_reference: str = ""
    kri_note: str = ""


class ParamSpecRead(BaseModel):
    name: str
    label: str
    kind: str
    required: bool = False
    default: Any = None
    help: str = ""
    options: list[str] = []


class CheckTypeRead(BaseModel):
    key: str
    label: str
    group: str
    description: str
    connector_types: list[str]
    input: str
    params: list[ParamSpecRead]
    pass_criterion: str
    population: str


class ConnectorKindRead(BaseModel):
    connector_type: str
    kind: str
    config_fields: list[ParamSpecRead]
    secret_fields: list[ParamSpecRead]
    note: str = ""


class MonitoringTestRead(BaseModel):
    id: uuid.UUID
    reference: str
    name: str
    check_type: str
    check_label: str
    status: str
    frequency: str
    connector_name: str = ""
    last_result: str
    last_run: date | None = None
    last_run_at: datetime | None = None
    failing_since: date | None = None
    last_error: str = ""
    recent_runs: int = 0
    recent_pass_rate: float | None = None
    overdue: bool = False
    issue_id: uuid.UUID | None = None
    issue_reference: str | None = None
    latest_run_id: uuid.UUID | None = None
    latest_evidence_id: uuid.UUID | None = None


class ControlMonitoringRead(BaseModel):
    control_id: uuid.UUID
    #: not_monitored | paused | not_run | passing | failing | error | overdue
    state: str
    failing_since: date | None = None
    recent_runs: int = 0
    recent_pass_rate: float | None = None
    tests: list[MonitoringTestRead] = []


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
    #: Phase 4: the issue a failed result opened or updated.
    issue_reference: str | None = None


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
