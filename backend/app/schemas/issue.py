from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import Severity
from app.models.issue import ActionStatus, CapaType, IssueSource, IssueStatus2


# --------------------------------------------------------------- CAPA actions ---
class IssueActionBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    action_type: CapaType = CapaType.corrective
    owner: str = ""
    due_date: date | None = None
    status: ActionStatus = ActionStatus.open
    completed_date: date | None = None
    evidence_note: str = ""


class IssueActionCreate(IssueActionBase):
    pass


class IssueActionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    action_type: CapaType | None = None
    owner: str | None = None
    due_date: date | None = None
    status: ActionStatus | None = None
    completed_date: date | None = None
    evidence_note: str | None = None


class IssueActionRead(IssueActionBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    issue_id: uuid.UUID
    is_overdue: bool
    created_at: datetime


# ------------------------------------------------------------- progress updates ---
class IssueUpdateCreate(BaseModel):
    note: str = ""
    author: str = ""
    update_date: date | None = None
    status_change: str = ""


class IssueUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    issue_id: uuid.UUID
    note: str
    author: str
    update_date: date | None
    status_change: str
    created_at: datetime


# --------------------------------------------------------------------- issues ---
class IssueBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    source_type: IssueSource = IssueSource.self_identified
    source_reference: str = ""
    source_id: uuid.UUID | None = None
    category: str = ""
    severity: Severity = Severity.medium
    status: IssueStatus2 = IssueStatus2.open
    owner: str = ""
    business_unit: str = ""
    identified_date: date | None = None
    due_date: date | None = None
    closed_date: date | None = None
    root_cause: str = ""
    management_response: str = ""
    repeat_finding: bool = False
    regulator_related: bool = False
    workflow_status: WorkflowState = WorkflowState.draft


class IssueCreate(IssueBase):
    pass


class IssueUpdatePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    source_type: IssueSource | None = None
    source_reference: str | None = None
    source_id: uuid.UUID | None = None
    category: str | None = None
    severity: Severity | None = None
    status: IssueStatus2 | None = None
    owner: str | None = None
    business_unit: str | None = None
    identified_date: date | None = None
    due_date: date | None = None
    closed_date: date | None = None
    root_cause: str | None = None
    management_response: str | None = None
    repeat_finding: bool | None = None
    regulator_related: bool | None = None
    workflow_status: WorkflowState | None = None


class IssueRead(IssueBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    action_count: int
    open_action_count: int
    is_overdue: bool
    age_days: int
    created_at: datetime
    actions: list[IssueActionRead] = []
    updates: list[IssueUpdateRead] = []


# ------------------------------------------------------------------- summary ---
class IssuesSummary(BaseModel):
    by_status: dict[str, int]
    by_source_type: dict[str, int]
    total: int
    total_open: int
    overdue_count: int
    repeat_finding_count: int
    regulator_related_open: int
