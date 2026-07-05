from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.authority import AuthorityCategory, AuthorityStatus, DualControlStatus
from app.models.base import WorkflowState


# ------------------------------------------------------- authority matrix lines ---
class AuthorityMatrixBase(BaseModel):
    activity: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: AuthorityCategory = AuthorityCategory.general
    role_title: str = ""
    approval_level: int = Field(default=1, ge=1)
    amount_from: float = 0
    amount_to: float | None = None
    currency: str = "PKR"
    conditions: str = ""
    effective_date: date | None = None
    status: AuthorityStatus = AuthorityStatus.active
    workflow_status: WorkflowState = WorkflowState.draft


class AuthorityMatrixCreate(AuthorityMatrixBase):
    pass


class AuthorityMatrixUpdate(BaseModel):
    activity: str | None = None
    description: str | None = None
    category: AuthorityCategory | None = None
    role_title: str | None = None
    approval_level: int | None = Field(default=None, ge=1)
    amount_from: float | None = None
    amount_to: float | None = None
    currency: str | None = None
    conditions: str | None = None
    effective_date: date | None = None
    status: AuthorityStatus | None = None
    workflow_status: WorkflowState | None = None


class AuthorityMatrixRead(AuthorityMatrixBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    amount_range_label: str
    created_at: datetime


# -------------------------------------------------- maker-checker / dual control ---
class DualControlRuleBase(BaseModel):
    module: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=120)
    requires_dual_control: bool = True
    maker_role: str = ""
    checker_role: str = ""
    threshold_amount: float | None = None
    currency: str = "PKR"
    description: str = ""
    enabled: bool = True
    status: DualControlStatus = DualControlStatus.active
    workflow_status: WorkflowState = WorkflowState.draft


class DualControlRuleCreate(DualControlRuleBase):
    pass


class DualControlRuleUpdate(BaseModel):
    module: str | None = None
    action: str | None = None
    requires_dual_control: bool | None = None
    maker_role: str | None = None
    checker_role: str | None = None
    threshold_amount: float | None = None
    currency: str | None = None
    description: str | None = None
    enabled: bool | None = None
    status: DualControlStatus | None = None
    workflow_status: WorkflowState | None = None


class DualControlRuleRead(DualControlRuleBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime


# ------------------------------------------------------------------- summary ---
class AuthoritySummary(BaseModel):
    matrix_total: int
    matrix_by_category: dict[str, int]
    matrix_by_level: dict[str, int]
    categories_covered: int
    dual_control_total: int
    dual_control_enabled: int
    modules_covered: int
