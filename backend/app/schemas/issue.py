from __future__ import annotations

import uuid
from datetime import date, datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import Severity
from app.models.issue import ActionStatus, CapaType, IssueSource, IssueStatus2
from app.schemas.common import GraphRef, LookupRef, UnitRef, UserRef

# Phase 1 picker fields: each ``<name>_id`` is picked from a governed list and wins over
# the legacy ``<name>`` text when both are sent. The text is still accepted this release
# (older clients, CSV import) and is matched to an id when it names exactly one active
# record; on read it holds the picked record's display name, or the unmatched text.
_OWNER = "User who owns this; wins over `owner` text."
_UNIT = "Business unit (GET /business-units); wins over `business_unit` text."
_CATEGORY = "Value from the `issue_category` lookup list; wins over `category` text."
_WF_OWNER = "User who owns the approval workflow. `workflow_status` changes only through the workflow endpoints."
_ROOT_CAUSE = "Value from the `root_cause_category` lookup list; `root_cause` stays the narrative."
_STATUS = (
    "Open states only (open, in_progress). An issue is closed with POST /issues/{id}/validate "
    "and POST /issues/{id}/close; setting a closed state here is a 422. Moving a closed issue "
    "back to an open state reopens it and clears its validation."
)
_DUE = (
    "Changing an existing due date needs `due_date_reason` and is logged. Pushing it later on a "
    "regulator-related, high or critical issue waits for approval "
    "(POST /issues/{id}/due-date-changes/{change_id}/decide) and the date does not move until then."
)
_LINKS = "Live records of this organisation; the list replaces the issue's links of this kind."


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
    root_cause: str = ""
    root_cause_category_id: uuid.UUID | None = Field(default=None, description=_ROOT_CAUSE)
    management_response: str = ""
    repeat_finding: bool = False
    regulator_related: bool = False
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class IssueCreate(IssueBase):
    """A new issue. It is raised open (a closed status is a 422). ``closed_date`` is not
    writable: the server sets it when the issue is closed."""

    status: IssueStatus2 = Field(default=IssueStatus2.open, description=_STATUS)
    risk_ids: list[uuid.UUID] = Field(default_factory=list, description=_LINKS)
    control_ids: list[uuid.UUID] = Field(default_factory=list, description=_LINKS)
    requirement_ids: list[uuid.UUID] = Field(default_factory=list, description=_LINKS)
    asset_ids: list[uuid.UUID] = Field(default_factory=list, description=_LINKS)
    vendor_ids: list[uuid.UUID] = Field(default_factory=list, description="Third parties. " + _LINKS)


class IssueImport(IssueCreate):
    """CSV import row: a register migrated from another tool brings its closed history.
    ``closed_date`` is honoured here only (see ``api.v1.issues.import_issue``)."""

    closed_date: date | None = None


class IssueUpdatePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    source_type: IssueSource | None = None
    source_reference: str | None = None
    source_id: uuid.UUID | None = None
    category: str | None = None
    category_id: uuid.UUID | None = Field(default=None, description=_CATEGORY)
    severity: Severity | None = None
    status: IssueStatus2 | None = Field(default=None, description=_STATUS)
    owner: str | None = None
    owner_id: uuid.UUID | None = Field(default=None, description=_OWNER)
    business_unit: str | None = None
    business_unit_id: uuid.UUID | None = Field(default=None, description=_UNIT)
    identified_date: date | None = None
    due_date: date | None = Field(default=None, description=_DUE)
    due_date_reason: str | None = Field(
        default=None, description="Why the due date is moving; required whenever an existing due date changes."
    )
    root_cause: str | None = None
    root_cause_category_id: uuid.UUID | None = Field(default=None, description=_ROOT_CAUSE)
    management_response: str | None = None
    repeat_finding: bool | None = None
    regulator_related: bool | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    risk_ids: list[uuid.UUID] | None = Field(default=None, description=_LINKS)
    control_ids: list[uuid.UUID] | None = Field(default=None, description=_LINKS)
    requirement_ids: list[uuid.UUID] | None = Field(default=None, description=_LINKS)
    asset_ids: list[uuid.UUID] | None = Field(default=None, description=_LINKS)
    vendor_ids: list[uuid.UUID] | None = Field(default=None, description="Third parties. " + _LINKS)


# ---------------------------------------------------------- validation & closure ---
class IssueValidate(BaseModel):
    """An independent validator's conclusion on the remediation."""

    result: Literal["effective", "not_effective"]
    note: str = Field(default="", description="What was checked and what was found. Required.")


class IssueClose(BaseModel):
    status: Literal["closed", "remediated", "risk_accepted"]
    note: str = Field(
        default="",
        description="Closure note. Required to close as risk_accepted without an approved "
        "acceptance on a linked risk.",
    )


class DueDateDecision(BaseModel):
    approve: bool
    note: str = ""


class IssueDueDateChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    issue_id: uuid.UUID
    old_due_date: date | None = None
    new_due_date: date | None = None
    reason: str = ""
    status: str  # pending | approved | rejected
    requested_by_id: uuid.UUID | None = None
    requested_by_ref: UserRef | None = None
    approved_by_id: uuid.UUID | None = Field(default=None, description="Who decided it (approved or rejected); empty when no approval was needed.")
    approved_by_ref: UserRef | None = None
    approved_at: datetime | None = None
    created_at: datetime


class IssueAssetRef(GraphRef):
    """A linked asset; ``asset_class`` says which register (IT / information) holds it."""

    asset_class: str = ""


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
    root_cause_category_ref: LookupRef | None = None
    closed_date: date | None = Field(default=None, description="Set by the server when the issue closes; cleared on reopen.")
    validated_by_id: uuid.UUID | None = None
    validated_by_ref: UserRef | None = None
    validated_at: datetime | None = None
    validation_result: str | None = None  # effective | not_effective
    validation_note: str = ""
    risks: list[GraphRef] = []
    controls: list[GraphRef] = []
    requirements: list[GraphRef] = []
    assets: list[IssueAssetRef] = []
    vendors: list[GraphRef] = []
    due_date_changes: list[IssueDueDateChangeRead] = []
    due_date_moves: int = 0
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
    due_date_changes_pending: int = 0
