"""Payloads for the annual audit plan, audit programmes and the assurance calendar."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.audit_plan import AuditPlanStatus


# --------------------------------------------------------------- plan items ---
class PlanItemBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    auditable_unit_id: uuid.UUID | None = None
    rationale: str = ""
    planned_quarter: int = Field(default=1, ge=1, le=4)
    #: Optional month within the quarter, so "twice in March" is expressible.
    planned_month: int | None = Field(default=None, ge=1, le=12)
    budgeted_hours: int = Field(default=0, ge=0, le=100000)
    lead_auditor: str = Field(default="", max_length=200)


class PlanItemCreate(PlanItemBase):
    pass


class PlanItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    auditable_unit_id: uuid.UUID | None = None
    rationale: str | None = None
    planned_quarter: int | None = Field(default=None, ge=1, le=4)
    planned_month: int | None = Field(default=None, ge=1, le=12)
    budgeted_hours: int | None = Field(default=None, ge=0, le=100000)
    lead_auditor: str | None = None
    engagement_id: uuid.UUID | None = None


class PlanItemRead(PlanItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    engagement_id: uuid.UUID | None
    auditable_unit_name: str = ""


# -------------------------------------------------------------------- plans ---
class PlanBase(BaseModel):
    year: int = Field(ge=2000, le=2200)
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    prepared_by: str = Field(default="", max_length=200)
    budget_hours: int = Field(default=0, ge=0, le=1000000)


class PlanCreate(PlanBase):
    pass


class PlanUpdate(BaseModel):
    year: int | None = Field(default=None, ge=2000, le=2200)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    prepared_by: str | None = None
    budget_hours: int | None = Field(default=None, ge=0, le=1000000)
    status: AuditPlanStatus | None = None


class PlanRead(PlanBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    status: AuditPlanStatus
    approval_request_id: uuid.UUID | None
    approved_on: date | None
    planned_count: int
    started_count: int
    coverage_pct: int
    planned_hours: int
    items: list[PlanItemRead] = []
    created_at: datetime


class PlanGenerateRequest(BaseModel):
    """Build a risk-based draft plan from the audit universe.

    The universe already carries an inherent-risk rating and an audit frequency per unit,
    which is exactly the input a risk-based plan is derived from — so the department
    edits a proposal rather than starting from an empty page.
    """

    min_risk: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    only_due: bool = True  # units whose next audit falls in or before the plan year
    default_hours: int = Field(default=80, ge=0, le=10000)
    replace_existing: bool = False


class PlanGenerateResult(BaseModel):
    added: int
    skipped: int
    considered: int


class PlanCoverage(BaseModel):
    planned: int
    started: int
    coverage_pct: int
    planned_hours: int
    budget_hours: int
    by_quarter: list[dict]


# --------------------------------------------------------------- programmes ---
class ProgramStepBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    procedure: str = ""
    expected_evidence: str = ""
    order_index: int = Field(default=0, ge=0, le=10000)
    requirement_id: uuid.UUID | None = None


class ProgramStepCreate(ProgramStepBase):
    pass


class ProgramStepUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    procedure: str | None = None
    expected_evidence: str | None = None
    order_index: int | None = Field(default=None, ge=0, le=10000)


class ProgramStepRead(ProgramStepBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class ProgramBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = Field(default="", max_length=120)


class ProgramCreate(ProgramBase):
    framework_id: uuid.UUID | None = None


class ProgramUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None


class ProgramRead(ProgramBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    framework_id: uuid.UUID | None
    framework_name: str = ""
    step_count: int
    steps: list[ProgramStepRead] = []
    created_at: datetime


class ProgramFromFrameworkRequest(BaseModel):
    name: str = Field(default="", max_length=255)
    domain: str | None = None  # limit to one clause group, e.g. "A.8 Technological"


class ApplyProgramResult(BaseModel):
    added: int
    skipped: int  # steps already present on the engagement, by title
    engagement_reference: str


# ----------------------------------------------------------------- calendar ---
class CalendarEvent(BaseModel):
    """One dated thing the assurance function has to turn up for."""

    kind: str  # planned_audit | fieldwork | finding_due | unit_due | control_test
    date: date
    end_date: date | None = None
    title: str
    reference: str = ""
    severity: str = ""
    link: str
    overdue: bool = False


class AuditCalendar(BaseModel):
    events: list[CalendarEvent]
    from_date: date
    to_date: date
