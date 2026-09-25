from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApprovalStatus


class ApprovalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    entity_type: str = ""
    entity_id: uuid.UUID | None = None
    entity_label: str = ""
    link: str = ""
    approver: str = ""
    due_date: date | None = None
    # Number of independent checkers required (1 = 4-eyes, 2 = 6-eyes, …).
    required_approvals: int = Field(default=1, ge=1, le=5)


class ApprovalDecision(BaseModel):
    approve: bool
    comment: str = ""


class ApprovalActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    actor_email: str
    action: str
    comment: str
    created_at: datetime


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    title: str
    description: str
    status: ApprovalStatus
    entity_type: str
    entity_id: uuid.UUID | None
    entity_label: str
    link: str
    approver: str
    #: The maker's user id — lets the UI withhold Approve/Reject from the person who
    #: raised the request (the server refuses it regardless).
    requested_by: uuid.UUID | None = None
    requested_by_email: str
    required_approvals: int
    approvals_received: int
    decided_by_email: str
    decided_at: date | None
    decision_comment: str
    due_date: date | None
    is_overdue: bool
    created_at: datetime
    actions: list[ApprovalActionRead] = []
    #: A route stage assigned to a role: the role, and how many active users other than
    #: the maker hold it. ``approver_role_gap`` says what to do when nobody can decide it
    #: as a holder ("No one holds the Risk Approver role — assign it in Users").
    approver_role: str | None = None
    approver_role_holders: int | None = None
    approver_role_gap: str | None = None
    #: For the user who asked: may they cancel it (maker or administrator), may they
    #: decide it, and if not, why.
    can_cancel: bool = False
    can_decide: bool = False
    decide_blocked_reason: str | None = None
    #: A user who may decide may still be unable to *approve*: when their approval would
    #: finish the record's review and the record is not ready for it (a DPIA not yet
    #: completed) or its amount is above their delegation-of-authority mandate. They can
    #: still reject. ``approve_blocked_reason`` is the text the approval would be refused with.
    can_approve: bool = False
    approve_blocked_reason: str | None = None
