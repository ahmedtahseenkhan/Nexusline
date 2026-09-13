from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.schemas.common import LookupRef, UserRef
from app.models.outsourcing import (
    CloudModel,
    OutsourcingCategory,
    OutsourcingMateriality,
    OutsourcingReviewStatus,
    OutsourcingStatus,
    SbpApprovalStatus,
)


# --------------------------------------------------------- outsourcing reviews ---
class OutsourcingReviewBase(BaseModel):
    review_date: date | None = None
    reviewer: str = ""
    outcome: str = ""
    sla_met: bool = True
    issues_noted: str = ""
    status: OutsourcingReviewStatus = OutsourcingReviewStatus.planned


class OutsourcingReviewCreate(OutsourcingReviewBase):
    pass


class OutsourcingReviewUpdate(BaseModel):
    review_date: date | None = None
    reviewer: str | None = None
    outcome: str | None = None
    sla_met: bool | None = None
    issues_noted: str | None = None
    status: OutsourcingReviewStatus | None = None


class OutsourcingReviewRead(OutsourcingReviewBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    arrangement_id: uuid.UUID
    reference: str
    created_at: datetime


# ---------------------------------------------------- outsourcing arrangements ---
_OWNER_ID = "Accountable owner (a user); wins over the legacy `owner` text. Read back as `owner_ref`."
_OWNER = "Legacy free-text owner. Written with the picked user's name; text alone is matched to a user."
_COUNTRY_ID = "Country where the data / service is located, from the `country` list. Read back as `country_ref`."
_COUNTRY = "Legacy free-text country. Written with the picked country's name; text alone is matched to the list."


class OutsourcingArrangementBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    service_provider: str = ""
    service_description: str = ""
    vendor_id: uuid.UUID | None = None
    category: OutsourcingCategory = OutsourcingCategory.it_infrastructure
    materiality: OutsourcingMateriality = OutsourcingMateriality.material
    materiality_assessment: str = ""
    is_cloud: bool = False
    cloud_model: CloudModel = CloudModel.not_applicable
    data_offshored: bool = False
    country: str = Field(default="", description=_COUNTRY)
    country_id: uuid.UUID | None = Field(default=None, description=_COUNTRY_ID)
    sbp_approval_required: bool = False
    sbp_approval_status: SbpApprovalStatus = SbpApprovalStatus.not_required
    sbp_approval_ref: str = ""
    contract_start: date | None = None
    contract_end: date | None = None
    exit_plan: str = ""
    exit_plan_tested: bool = False
    concentration_note: str = ""
    status: OutsourcingStatus = OutsourcingStatus.proposed
    owner: str = Field(default="", description=_OWNER)
    owner_id: uuid.UUID | None = Field(default=None, description=_OWNER_ID)


class OutsourcingArrangementCreate(OutsourcingArrangementBase):
    pass


class OutsourcingArrangementUpdate(BaseModel):
    title: str | None = None
    service_provider: str | None = None
    service_description: str | None = None
    vendor_id: uuid.UUID | None = None
    category: OutsourcingCategory | None = None
    materiality: OutsourcingMateriality | None = None
    materiality_assessment: str | None = None
    is_cloud: bool | None = None
    cloud_model: CloudModel | None = None
    data_offshored: bool | None = None
    country: str | None = Field(default=None, description=_COUNTRY)
    country_id: uuid.UUID | None = Field(default=None, description=_COUNTRY_ID)
    sbp_approval_required: bool | None = None
    sbp_approval_status: SbpApprovalStatus | None = None
    sbp_approval_ref: str | None = None
    contract_start: date | None = None
    contract_end: date | None = None
    exit_plan: str | None = None
    exit_plan_tested: bool | None = None
    concentration_note: str | None = None
    status: OutsourcingStatus | None = None
    owner: str | None = Field(default=None, description=_OWNER)
    owner_id: uuid.UUID | None = Field(default=None, description=_OWNER_ID)


class OutsourcingArrangementRead(OutsourcingArrangementBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    review_count: int
    is_contract_expiring: bool
    created_at: datetime
    reviews: list[OutsourcingReviewRead] = []
    owner_ref: UserRef | None = None
    country_ref: LookupRef | None = None
