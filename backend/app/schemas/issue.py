from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import Severity
from app.models.issue import ActionStatus, CapaType, IssueSource, IssueStatus2
from app.schemas.common import LookupRef, UnitRef, UserRef

# Phase 1 picker fields: each ``<name>_id`` is picked from a governed list and wins over
# the legacy ``<name>`` text when both are sent. The text is still accepted this release
# (older clients, CSV import) and is matched to an id when it names exactly one active
# record; on read it holds the picked record's display name, or the unmatched text.
_OWNER = "User who owns this; wins over `owner` text."
_UNIT = "Business unit (GET /business-units); wins over `business_unit` text."
_CATEGORY = "Value from the `issue_category` lookup list; wins over `category` text."
_WF_OWNER = "User who owns the approval workflow. `workflow_status` changes only through the workflow endpoints."


# --------------------------------------------------------------- CAPA actions ---
class IssueActionBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    action_type: CapaType = CapaType.corrective
    owner: str = ""
    owner_id: uuid.UUID | None = Field(default=None, description=_OWNER)
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
    owner_id: uuid.UUID | None = Field(default=None, description=_OWNER)
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
    owner_ref: UserRef | None = None


# ------------------------------------------------------------- progress updates ---
class IssueUpdateCreate(BaseModel):
    note: str = ""
    author: str = ""
    author_id: uuid.UUID | None = Field(
        default=None,
        description="User who wrote the entry; wins over `author` text. "
        "Defaults to the signed-in user when neither is sent.",
    )
    update_date: date | None = None
    status_change: str = ""


class IssueUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    issue_id: uuid.UUID
    note: str
    author: str
    author_id: uuid.UUID | None = None
    author_ref: UserRef | None = None
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
    category_id: uuid.UUID | None = Field(default=None, description=_CATEGORY)
    severity: Severity = Severity.medium
    status: IssueStatus2 = IssueStatus2.open
    owner: str = ""
    owner_id: uuid.UUID | None = Field(default=None, description=_OWNER)
    business_unit: str = ""
    business_unit_id: uuid.UUID | None = Field(default=None, description=_UNIT)
    identified_date: date | None = None
    due_date: date | None = None
    closed_date: date | None = None
    root_cause: str = ""
    management_response: str = ""
    repeat_finding: bool = False
    regulator_related: bool = False
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class IssueCreate(IssueBase):
    pass


class IssueUpdatePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    source_type: IssueSource | None = None
    source_reference: str | None = None
    source_id: uuid.UUID | None = None
    category: str | None = None
    category_id: uuid.UUID | None = Field(default=None, description=_CATEGORY)
    severity: Severity | None = None
    status: IssueStatus2 | None = None
    owner: str | None = None
    owner_id: uuid.UUID | None = Field(default=None, description=_OWNER)
    business_unit: str | None = None
    business_unit_id: uuid.UUID | None = Field(default=None, description=_UNIT)
    identified_date: date | None = None
    due_date: date | None = None
    closed_date: date | None = None
    root_cause: str | None = None
    management_response: str | None = None
    repeat_finding: bool | None = None
    regulator_related: bool | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class IssueRead(IssueBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    owner_ref: UserRef | None = None
    business_unit_ref: UnitRef | None = None
    category_ref: LookupRef | None = None
    workflow_owner_ref: UserRef | None = None
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
