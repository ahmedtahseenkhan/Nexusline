from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ProjectStatus


class Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


# --------------------------------------------------------------------- tasks
class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    due_date: date | None = None
    completion: int = Field(default=0, ge=0, le=100)
    order_index: int = 0
    assignee: str = ""


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    completion: int | None = Field(default=None, ge=0, le=100)
    order_index: int | None = None
    assignee: str | None = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    is_overdue: bool


# ------------------------------------------------------------------- expenses
class ExpenseCreate(BaseModel):
    amount: float = Field(ge=0)
    description: str = ""
    expense_date: date | None = None


class ExpenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    amount: float
    description: str
    expense_date: date | None


# -------------------------------------------------------------------- projects
class ProjectBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    status: ProjectStatus = ProjectStatus.planned
    owner: str = ""
    start_date: date | None = None
    deadline: date | None = None
    budget: float | None = Field(default=None, ge=0)


class ProjectCreate(ProjectBase):
    risk_ids: list[uuid.UUID] = Field(default_factory=list)
    control_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: ProjectStatus | None = None
    owner: str | None = None
    start_date: date | None = None
    deadline: date | None = None
    budget: float | None = Field(default=None, ge=0)
    risk_ids: list[uuid.UUID] | None = None
    control_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    spent: float
    over_budget: bool
    progress: int
    open_tasks: int
    is_overdue: bool
    tasks: list[TaskRead] = []
    expenses: list[ExpenseRead] = []
    risks: list[Ref] = []
    controls: list[Ref] = []
    policies: list[Ref] = []
    created_at: datetime
