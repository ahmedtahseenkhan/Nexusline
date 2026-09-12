from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import GraphRef, LookupRef, UserRef

from app.models.base import WorkflowState
from app.models.enums import PolicyDocType, PolicyStatus, ReviewFrequency


class PolicyRefItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


_LEGACY = "Legacy free text, accepted for one release; send the *_id instead. "
_AUTHORITY = "Board or committee (Governance → committees) that approves the policy."
_EFFECTIVE = (
    "Date the policy takes effect. Left empty, publishing sets it to the publication date; "
    "it can't be earlier than the date the policy was approved."
)
_SUPERSEDES = (
    "The policy this one replaces (not itself, no cycles). Publishing this policy retires "
    "the one it supersedes."
)
_REQUIREMENTS = "Framework requirements the policy addresses (written to requirement_policies)."
_UNITS = "Business units the policy applies to (recorded and reported; users carry no unit)."
_ROLES = "Roles the policy applies to: their members are the people asked to acknowledge it."


class PolicyBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str = ""
    body: str = ""
    url: str = ""
    # Phase 1: category and owner are picked; the text columns are kept in step with the
    # keys (and matched onto them when sent alone) — see services.ref_fields.
    category_id: uuid.UUID | None = None
    category: str = Field(default="", description=_LEGACY + "Matched onto a policy category.")
    document_type: PolicyDocType = PolicyDocType.policy
    version: str = "1.0"
    status: PolicyStatus = PolicyStatus.draft
    # ``workflow_status`` is not writable: it moves only through the record lifecycle.
    workflow_owner_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    owner: str = Field(default="", description=_LEGACY + "Matched onto a user by email or name.")
    label_id: uuid.UUID | None = None
    use_attachments: bool = False
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    # Phase 2: document governance.
    approving_authority_id: uuid.UUID | None = Field(default=None, description=_AUTHORITY)
    effective_date: date | None = Field(default=None, description=_EFFECTIVE)
    supersedes_id: uuid.UUID | None = Field(default=None, description=_SUPERSEDES)


class PolicyCreate(PolicyBase):
    related_ids: list[uuid.UUID] = []
    controls_ids: list[uuid.UUID] = []
    requirements_ids: list[uuid.UUID] = Field(default_factory=list, description=_REQUIREMENTS)
    risks_ids: list[uuid.UUID] = []
    business_unit_ids: list[uuid.UUID] = Field(default_factory=list, description=_UNITS)
    role_ids: list[uuid.UUID] = Field(default_factory=list, description=_ROLES)


class PolicyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = None
    body: str | None = None
    url: str | None = None
    category_id: uuid.UUID | None = None
    category: str | None = Field(default=None, description=_LEGACY)
    document_type: PolicyDocType | None = None
    version: str | None = None
    status: PolicyStatus | None = None
    workflow_owner_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    owner: str | None = Field(default=None, description=_LEGACY)
    label_id: uuid.UUID | None = None
    use_attachments: bool | None = None
    review_frequency: ReviewFrequency | None = None
    approving_authority_id: uuid.UUID | None = Field(default=None, description=_AUTHORITY)
    effective_date: date | None = Field(default=None, description=_EFFECTIVE)
    supersedes_id: uuid.UUID | None = Field(default=None, description=_SUPERSEDES)
    related_ids: list[uuid.UUID] | None = None
    controls_ids: list[uuid.UUID] | None = None
    requirements_ids: list[uuid.UUID] | None = Field(default=None, description=_REQUIREMENTS)
    risks_ids: list[uuid.UUID] | None = None
    business_unit_ids: list[uuid.UUID] | None = Field(default=None, description=_UNITS)
    role_ids: list[uuid.UUID] | None = Field(default=None, description=_ROLES)


class PolicyReviewCreate(BaseModel):
    planned_date: date
    reviewer_id: uuid.UUID | None = None
    reviewer: str = Field(default="", description=_LEGACY + "Matched onto a user by email or name.")
    comments: str = ""


class PolicyReviewComplete(BaseModel):
    comments: str = ""


class PolicyReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    planned_date: date
    actual_review_date: date | None
    reviewer: str  # legacy text: the reviewer's name
    reviewer_id: uuid.UUID | None = None
    reviewer_ref: UserRef | None = None
    comments: str
    created_at: datetime


class PolicyRead(PolicyBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    # Resolved picks (``owner`` / ``category`` stay as the legacy text).
    owner_ref: UserRef | None = None
    category_ref: LookupRef | None = None
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""  # legacy text
    workflow_owner_ref: UserRef | None = None
    next_review_date: date | None
    last_review_date: date | None
    published_at: date | None
    expired_reviews: int
    is_review_overdue: bool
    acknowledgment_count: int
    related: list[PolicyRefItem] = []
    controls: list[PolicyRefItem] = []
    requirements: list[PolicyRefItem] = []
    risks: list[PolicyRefItem] = []
    reviews: list[PolicyReviewRead] = []
    # Reverse links (read-only).
    exceptions: list[GraphRef] = []
    projects: list[GraphRef] = []
    goals: list[GraphRef] = []
    processing_activities: list[GraphRef] = []
    # Phase 2: governance and applicability.
    approving_authority_ref: GraphRef | None = None
    supersedes_ref: GraphRef | None = None
    superseded_by: list[GraphRef] = []
    business_units: list[GraphRef] = []
    roles: list[GraphRef] = []
    created_at: datetime


class PolicyAcknowledgmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    policy_id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    created_at: datetime


class PolicyAckStatusRow(BaseModel):
    user_id: uuid.UUID
    full_name: str = ""
    email: str = ""
    roles: list[str] = []
    acknowledged: bool
    acknowledged_at: datetime | None = None


class PolicyAckStatus(BaseModel):
    """Who is asked to acknowledge a policy, and who has."""

    policy_id: uuid.UUID
    #: ``roles`` — members of the policy's roles; ``everyone`` — no roles are set, so every
    #: active user is in scope.
    scope: str
    roles: list[str] = []
    note: str = ""
    total: int
    acknowledged: int
    pending: int
    #: Acknowledgements from people outside the scope (kept, not counted above).
    outside_scope: int = 0
    users: list[PolicyAckStatusRow] = []


class PolicyOptions(BaseModel):
    """Choices for the policy form that need no other module's permission."""

    committees: list[GraphRef] = []
    roles: list[GraphRef] = []
