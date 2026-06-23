from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import GoalAuditResult, GoalStatus, ReviewFrequency


class Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


class GoalAuditCreate(BaseModel):
    result: GoalAuditResult = GoalAuditResult.not_assessed
    planned_date: date | None = None
    conducted_date: date | None = None
    metric_description: str = ""
    success_criteria: str = ""
    result_description: str = ""
    auditor: str = ""


class GoalAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    goal_id: uuid.UUID
    result: GoalAuditResult
    planned_date: date | None
    conducted_date: date | None
    metric_description: str
    success_criteria: str
    result_description: str
    auditor: str
    created_at: datetime


class GoalBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    owner: str = ""
    status: GoalStatus = GoalStatus.not_started
    audit_metric: str = ""
    success_criteria: str = ""
    audit_frequency: ReviewFrequency = ReviewFrequency.annual


class GoalCreate(GoalBase):
    risk_ids: list[uuid.UUID] = Field(default_factory=list)
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    owner: str | None = None
    status: GoalStatus | None = None
    audit_metric: str | None = None
    success_criteria: str | None = None
    audit_frequency: ReviewFrequency | None = None
    risk_ids: list[uuid.UUID] | None = None
    project_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None


class GoalRead(GoalBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    next_audit_date: date | None
    last_audit_date: date | None
    audit_count: int
    last_result: GoalAuditResult | None
    is_audit_overdue: bool
    audits: list[GoalAuditRead] = []
    risks: list[Ref] = []
    projects: list[Ref] = []
    policies: list[Ref] = []
    created_at: datetime
