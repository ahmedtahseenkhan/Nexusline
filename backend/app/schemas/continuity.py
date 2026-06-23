from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import ContinuityStatus, Criticality, ReviewFrequency, TestResult


class Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


# ------------------------------------------------------------------- tasks (5W)
class TaskBase(BaseModel):
    step: int = 0
    action: str = Field(min_length=1)
    actor: str = ""
    timing: str = ""
    location: str = ""
    method: str = ""


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    step: int | None = None
    action: str | None = Field(default=None, min_length=1)
    actor: str | None = None
    timing: str | None = None
    location: str | None = None
    method: str | None = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    plan_id: uuid.UUID


# -------------------------------------------------------------------- tests
class TestCreate(BaseModel):
    result: TestResult = TestResult.not_assessed
    planned_date: date | None = None
    conducted_date: date | None = None
    result_description: str = ""
    tester: str = ""


class TestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    plan_id: uuid.UUID
    result: TestResult
    planned_date: date | None
    conducted_date: date | None
    result_description: str
    tester: str
    created_at: datetime


# --------------------------------------------------------------------- plans
class PlanBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    bia: str = ""
    invocation: str = ""
    status: ContinuityStatus = ContinuityStatus.draft
    workflow_status: WorkflowState = WorkflowState.draft
    owner: str = ""
    business_unit_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None
    max_tolerable_downtime_hours: int | None = Field(default=None, ge=0)
    rto_hours: int | None = Field(default=None, ge=0)
    rpo_hours: int | None = Field(default=None, ge=0)
    criticality: Criticality = Criticality.high
    test_frequency: ReviewFrequency = ReviewFrequency.annual


class PlanCreate(PlanBase):
    pass


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    bia: str | None = None
    invocation: str | None = None
    status: ContinuityStatus | None = None
    workflow_status: WorkflowState | None = None
    owner: str | None = None
    business_unit_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None
    max_tolerable_downtime_hours: int | None = Field(default=None, ge=0)
    rto_hours: int | None = Field(default=None, ge=0)
    rpo_hours: int | None = Field(default=None, ge=0)
    criticality: Criticality | None = None
    test_frequency: ReviewFrequency | None = None


class PlanRead(PlanBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    next_test_date: date | None
    last_test_date: date | None
    task_count: int
    test_count: int
    last_test_result: TestResult | None
    is_test_overdue: bool
    business_unit: Ref | None = None
    process: Ref | None = None
    tasks: list[TaskRead] = []
    tests: list[TestRead] = []
    created_at: datetime
