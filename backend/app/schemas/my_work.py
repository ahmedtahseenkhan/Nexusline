"""My Work (``GET /my/work``) and the approve-from-e-mail pages (``/actions/{token}``)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


# ================================================================== My Work ===
class MyWorkItem(BaseModel):
    """One thing waiting for the signed-in user."""

    kind: str
    #: The item's own id: the approval, the action, the test, the policy …
    id: uuid.UUID
    title: str
    reference: str = ""
    #: Context in words ("Risk R-012 · 40% done"); dates are in the fields below.
    subtitle: str = ""
    due_date: date | None = None
    #: The date being replaced (a due-date extension shows "from → to").
    previous_date: date | None = None
    overdue: bool = False
    #: Due within the look-ahead window (and not overdue).
    due_soon: bool = False
    #: Deep link that opens the record (``/risks?id=…``).
    link: str = ""
    entity_type: str = ""
    entity_id: uuid.UUID | None = None
    #: Quick actions the page may offer on the row: ``acknowledge`` (a policy),
    #: ``mark_done`` (a treatment action). Anything else opens the record.
    actions: list[str] = Field(default_factory=list)
    #: What limits this user's decision, when it is limited but not blocked: "you can
    #: return it; approving it is above your delegation-of-authority mandate …".
    note: str = ""


class MyWorkSection(BaseModel):
    kind: str
    label: str
    hint: str = ""
    count: int = 0
    overdue: int = 0
    #: Items shown (overdue first); ``count`` is the full number.
    items: list[MyWorkItem] = Field(default_factory=list)
    truncated: bool = False
    #: True when ``count`` is only what one capped read returned (show it as "500+").
    count_is_floor: bool = False


class MyWorkRead(BaseModel):
    user_id: uuid.UUID
    as_of: date
    #: How far ahead "due soon" looks, in days.
    horizon_days: int
    total: int
    overdue: int
    counts: dict[str, int] = Field(default_factory=dict)
    sections: list[MyWorkSection] = Field(default_factory=list)


class TreatmentActionDone(BaseModel):
    id: uuid.UUID
    risk_id: uuid.UUID
    status: str
    percent_complete: int
    completed_at: datetime | None = None
    treatment_deadline: date | None = None


# ================================================================ e-mail actions ===
class EmailActionApproval(BaseModel):
    """What an e-mailed link decides — enough to know what you're approving."""

    id: uuid.UUID
    reference: str = ""
    title: str = ""
    description: str = ""
    entity_type: str = ""
    entity_label: str = ""
    approver: str = ""
    requested_by_email: str = ""
    due_date: date | None = None
    required_approvals: int = 1
    approvals_received: int = 0
    created_at: datetime | None = None
    status: str = ""


class EmailActionPreview(BaseModel):
    #: ready | used | expired | not_eligible | decided
    state: str
    message: str = ""
    organisation: str = ""
    user_name: str = ""
    expires_at: datetime | None = None
    approval: EmailActionApproval | None = None
    #: Why this person's Approve would be refused (not ready, or above their delegated
    #: authority) — they can still reject. Empty when approving is open to them.
    approve_blocked_reason: str = ""
    #: The organisation's date format and timezone, so the page shows dates its way.
    date_format: str = "DD/MM/YYYY"
    timezone: str = "Asia/Karachi"


class EmailActionConfirm(BaseModel):
    decision: Literal["approve", "reject"]
    #: Required to reject (as in the app).
    comment: str = Field(default="", max_length=4000)


class EmailActionResult(BaseModel):
    state: str = "decided"
    decision: str
    message: str
    approval: EmailActionApproval
