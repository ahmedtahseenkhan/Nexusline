from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import GraphRef, LookupRef, UserRef

from app.models.base import WorkflowState
from app.models.enums import (
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    ReviewFrequency,
    TestResult,
)


class ControlLinkRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


_LEGACY = "Legacy free text, accepted for one release; send the *_id instead. "


class ControlBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    reference: str = ""
    description: str = ""
    objective: str = ""
    # Phase 1: people and the classification are picked. The text columns are kept in
    # step with the keys (and matched onto them when sent alone) — see services.ref_fields.
    owner_id: uuid.UUID | None = Field(default=None, description="Accountable for the control.")
    operator_id: uuid.UUID | None = Field(default=None, description="Performs the control day to day.")
    owner: str = Field(default="", description=_LEGACY + "Matched onto a user by email or name.")
    control_type: ControlType = ControlType.production
    classification_id: uuid.UUID | None = None
    classification: str = Field(default="", description=_LEGACY + "Matched onto a control classification.")
    documentation_url: str = ""
    status: ControlStatus = ControlStatus.planned
    effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    # ``workflow_status`` is not writable: it moves only through the record lifecycle.
    workflow_owner_id: uuid.UUID | None = None
    opex: float | None = Field(default=None, ge=0)
    capex: float | None = Field(default=None, ge=0)
    resource_utilization: int | None = Field(default=None, ge=0, le=100)
    audit_frequency: ReviewFrequency = ReviewFrequency.annual
    audit_metric: str = ""
    audit_success_criteria: str = ""
    maintenance_frequency: ReviewFrequency = ReviewFrequency.quarterly


_SCHEDULE_NOTE = (
    " Only an implemented or operational control has one: for a planned or retired "
    "control the date is always empty and a value sent here is ignored. The clock starts "
    "(a cycle from today) when the control becomes implemented or operational."
)


class ControlCreate(ControlBase):
    # Optional explicit schedule overrides (otherwise derived from the frequency).
    next_audit_date: date | None = Field(
        default=None,
        description="Next control test. Blank = derived from audit_frequency." + _SCHEDULE_NOTE,
    )
    next_maintenance_date: date | None = Field(
        default=None,
        description="Next maintenance. Blank = derived from maintenance_frequency." + _SCHEDULE_NOTE,
    )
    # Relationship inputs.
    policy_ids: list[uuid.UUID] = []
    requirement_ids: list[uuid.UUID] = []
    risk_ids: list[uuid.UUID] = []
    asset_ids: list[uuid.UUID] = []


class ControlUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    reference: str | None = None
    description: str | None = None
    objective: str | None = None
    owner_id: uuid.UUID | None = None
    operator_id: uuid.UUID | None = None
    owner: str | None = Field(default=None, description=_LEGACY)
    control_type: ControlType | None = None
    classification_id: uuid.UUID | None = None
    classification: str | None = Field(default=None, description=_LEGACY)
    documentation_url: str | None = None
    status: ControlStatus | None = None
    effectiveness: ControlEffectiveness | None = None
    workflow_owner_id: uuid.UUID | None = None
    opex: float | None = Field(default=None, ge=0)
    capex: float | None = Field(default=None, ge=0)
    resource_utilization: int | None = Field(default=None, ge=0, le=100)
    audit_frequency: ReviewFrequency | None = None
    audit_metric: str | None = None
    audit_success_criteria: str | None = None
    next_audit_date: date | None = Field(
        default=None,
        description="Next control test. Blank = re-derive from audit_frequency and the last test."
        + _SCHEDULE_NOTE,
    )
    maintenance_frequency: ReviewFrequency | None = None
    next_maintenance_date: date | None = Field(
        default=None,
        description="Next maintenance. Blank = re-derive from maintenance_frequency and the last run."
        + _SCHEDULE_NOTE,
    )
    policy_ids: list[uuid.UUID] | None = None
    requirement_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None


class ControlRead(ControlBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    # Resolved picks (``owner`` / ``classification`` stay as the legacy text).
    owner_ref: UserRef | None = None
    operator_ref: UserRef | None = None
    classification_ref: LookupRef | None = None
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""  # legacy text
    workflow_owner_ref: UserRef | None = None
    next_audit_date: date | None = None
    last_audit_date: date | None = None
    next_maintenance_date: date | None = None
    last_maintenance_date: date | None = None
    audit_count: int = 0
    last_audit_result: TestResult | None = None
    is_audit_overdue: bool = False
    maintenance_count: int = 0
    last_maintenance_result: TestResult | None = None
    is_maintenance_overdue: bool = False
    policies: list[ControlLinkRef] = []
    requirements: list[ControlLinkRef] = []
    risks: list[ControlLinkRef] = []
    # Reverse links (read-only).
    incidents: list[GraphRef] = []
    exceptions: list[GraphRef] = []
    projects: list[GraphRef] = []
    audit_findings: list[GraphRef] = []
    assets: list[GraphRef] = []
    vendors: list[GraphRef] = []


class ControlRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    reference: str


# --------------------------------------------------------------- control tests
def control_test_problems(result: TestResult, conducted: date | None, conclusion: str) -> list[str]:
    """Why a recorded test is not acceptable yet, or ``[]``. A not-assessed placeholder
    needs nothing; a passed or failed result needs the date and the conclusion."""
    if result == TestResult.not_assessed:
        return []
    problems = []
    if conducted is None:
        problems.append(f"A {result.value} test needs the date it was performed (conducted_date).")
    if not (conclusion or "").strip():
        problems.append(f"A {result.value} test needs the tester's conclusion (result_description).")
    return problems


class ControlAuditCreate(BaseModel):
    result: TestResult = TestResult.not_assessed
    #: What the control's effectiveness should be after this test. Optional: the result
    #: decides (passed -> effective, failed -> ineffective) unless the tester says
    #: otherwise — "passed, but only partially".
    effectiveness: ControlEffectiveness | None = None
    planned_date: date | None = None
    conducted_date: date | None = Field(
        default=None, description="When the test was performed. Required for a passed or failed result."
    )
    metric_description: str = ""
    success_criteria: str = ""
    result_description: str = Field(
        default="", description="The tester's conclusion. Required for a passed or failed result."
    )
    improvement: str = ""
    tested_by_id: uuid.UUID | None = Field(
        default=None, description="Who performed the test, picked from the user list."
    )
    auditor: str = Field(
        default="",
        description=_LEGACY + "Who performed the test (name); kept equal to the tester's name.",
    )

    @model_validator(mode="after")
    def _a_result_needs_a_date_and_a_conclusion(self) -> "ControlAuditCreate":
        # A pass or fail is assurance evidence and rewrites the control's effectiveness;
        # an undated, unexplained "passed" is an assertion nobody can support.
        problems = control_test_problems(self.result, self.conducted_date, self.result_description)
        if problems:
            raise ValueError(" ".join(problems))
        return self


class ControlAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    result: TestResult
    planned_date: date | None
    conducted_date: date | None
    metric_description: str
    success_criteria: str
    result_description: str
    improvement: str
    auditor: str  # legacy text: the tester's name
    tested_by_id: uuid.UUID | None = None
    tested_by_ref: UserRef | None = None
    created_at: datetime


class ControlMaintenanceCreate(BaseModel):
    result: TestResult = TestResult.not_assessed
    task: str = ""
    planned_date: date | None = None
    conducted_date: date | None = None
    conclusion: str = ""


class ControlMaintenanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    result: TestResult
    task: str
    planned_date: date | None
    conducted_date: date | None
    conclusion: str
    created_at: datetime
