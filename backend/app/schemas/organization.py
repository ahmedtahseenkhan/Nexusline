from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import Criticality
from app.schemas.common import LookupRef, UserRef

_LEGACY = "Legacy free text, accepted for one release; send the *_id instead. "


class Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


# ----------------------------------------------------------------- Business unit
class BusinessUnitBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    # Phase 1: the unit head is picked; ``manager`` text is kept in step with the key
    # (and matched onto it when sent alone) — see services.ref_fields.
    manager_id: uuid.UUID | None = None
    manager: str = Field(default="", description=_LEGACY + "Matched onto a user by email or name.")
    email: str = ""
    location: str = ""
    parent_id: uuid.UUID | None = None
    # ``workflow_status`` is not writable: it moves only through the record lifecycle.
    # The approval owner is picked; its ``workflow_owner`` text is read-only.
    workflow_owner_id: uuid.UUID | None = None


class BusinessUnitCreate(BusinessUnitBase):
    legal_ids: list[uuid.UUID] = []


class BusinessUnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    manager_id: uuid.UUID | None = None
    manager: str | None = Field(default=None, description=_LEGACY)
    email: str | None = None
    location: str | None = None
    parent_id: uuid.UUID | None = None
    workflow_owner_id: uuid.UUID | None = None
    legal_ids: list[uuid.UUID] | None = None


class BusinessUnitRead(BusinessUnitBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    manager_ref: UserRef | None = None
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""  # legacy text
    workflow_owner_ref: UserRef | None = None
    parent_name: str | None = None
    legals: list[Ref] = []


# ----------------------------------------------------------------------- Process
class ProcessBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    business_unit_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    owner: str = Field(default="", description=_LEGACY + "Matched onto a user by email or name.")
    criticality: Criticality = Criticality.medium
    rto_hours: int | None = Field(default=None, ge=0)  # recovery time objective (hours)
    rpo_hours: int | None = Field(default=None, ge=0)  # recovery point objective (hours)
    rpd_hours: int | None = Field(default=None, ge=0)  # max tolerable downtime (hours)
    workflow_owner_id: uuid.UUID | None = None


class ProcessCreate(ProcessBase):
    asset_ids: list[uuid.UUID] = []


class ProcessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    business_unit_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    owner: str | None = Field(default=None, description=_LEGACY)
    criticality: Criticality | None = None
    rto_hours: int | None = Field(default=None, ge=0)
    rpo_hours: int | None = Field(default=None, ge=0)
    rpd_hours: int | None = Field(default=None, ge=0)
    workflow_owner_id: uuid.UUID | None = None
    asset_ids: list[uuid.UUID] | None = None


class ProcessRead(ProcessBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    owner_ref: UserRef | None = None
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""  # legacy text
    workflow_owner_ref: UserRef | None = None
    business_unit: Ref | None = None
    assets: list[Ref] = []


# ------------------------------------------------------------------------- Legal
class LegalBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category_id: uuid.UUID | None = None
    category: str = Field(default="", description=_LEGACY + "Matched onto a legal category.")
    jurisdiction: str = ""
    reference: str = ""
    countries: str = ""  # CSV of applicable countries
    risk_magnifier: float = Field(default=1.0, ge=0)
    workflow_owner_id: uuid.UUID | None = None


class LegalCreate(LegalBase):
    business_unit_ids: list[uuid.UUID] = []
    asset_ids: list[uuid.UUID] = []


class LegalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category_id: uuid.UUID | None = None
    category: str | None = Field(default=None, description=_LEGACY)
    jurisdiction: str | None = None
    reference: str | None = None
    countries: str | None = None
    risk_magnifier: float | None = Field(default=None, ge=0)
    workflow_owner_id: uuid.UUID | None = None
    business_unit_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None


class LegalRead(LegalBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category_ref: LookupRef | None = None
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""  # legacy text
    workflow_owner_ref: UserRef | None = None
    business_units: list[Ref] = []
    assets: list[Ref] = []
