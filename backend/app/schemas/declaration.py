from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import WorkflowState
from app.models.declaration import CampaignStatus, DeclarationStatus, DeclarationType
from app.schemas.tenant_settings import currency_or_default


# ------------------------------------------------------ declarations (submissions) ---
class DeclarationBase(BaseModel):
    declarant_name: str = ""
    declarant_role: str = ""
    business_unit: str = ""
    has_disclosure: bool = False
    disclosure_details: str = ""
    amount: float | None = None
    currency: str = "PKR"
    submitted_date: date | None = None
    status: DeclarationStatus = DeclarationStatus.pending
    reviewer: str = ""
    review_notes: str = ""


class DeclarationCreate(DeclarationBase):
    _ccy = field_validator("currency")(currency_or_default)


class DeclarationUpdate(BaseModel):
    declarant_name: str | None = None
    declarant_role: str | None = None
    business_unit: str | None = None
    has_disclosure: bool | None = None
    disclosure_details: str | None = None
    amount: float | None = None
    currency: str | None = None
    submitted_date: date | None = None
    status: DeclarationStatus | None = None
    reviewer: str | None = None
    review_notes: str | None = None

    _ccy = field_validator("currency")(currency_or_default)


class DeclarationRead(DeclarationBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    campaign_id: uuid.UUID
    reference: str
    created_at: datetime
    # The campaign's reference and title, filled on the flat list (GET /declarations)
    # so each row can name its campaign however many campaigns there are.
    campaign_reference: str = ""
    campaign_title: str = ""


# ------------------------------------------------------------ declaration campaigns ---
class CampaignBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    declaration_type: DeclarationType = DeclarationType.conflict_of_interest
    period: str = ""
    due_date: date | None = None
    owner: str = ""
    status: CampaignStatus = CampaignStatus.draft


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    declaration_type: DeclarationType | None = None
    period: str | None = None
    due_date: date | None = None
    owner: str | None = None
    status: CampaignStatus | None = None


class CampaignRead(CampaignBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    declaration_count: int
    disclosure_count: int
    created_at: datetime
    declarations: list[DeclarationRead] = []
