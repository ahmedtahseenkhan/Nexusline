from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import Criticality


class Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


# ----------------------------------------------------------------- Business unit
class BusinessUnitBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    manager: str = ""
    email: str = ""
    location: str = ""
    parent_id: uuid.UUID | None = None
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""


class BusinessUnitCreate(BusinessUnitBase):
    legal_ids: list[uuid.UUID] = []


class BusinessUnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    manager: str | None = None
    email: str | None = None
    location: str | None = None
    parent_id: uuid.UUID | None = None
    workflow_status: WorkflowState | None = None
    workflow_owner: str | None = None
    legal_ids: list[uuid.UUID] | None = None


class BusinessUnitRead(BusinessUnitBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    parent_name: str | None = None
    legals: list[Ref] = []


# ----------------------------------------------------------------------- Process
class ProcessBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    business_unit_id: uuid.UUID | None = None
    owner: str = ""
    criticality: Criticality = Criticality.medium
    rto_hours: int | None = Field(default=None, ge=0)  # recovery time objective (hours)
    rpo_hours: int | None = Field(default=None, ge=0)  # recovery point objective (hours)
    rpd_hours: int | None = Field(default=None, ge=0)  # max tolerable downtime (hours)
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""


class ProcessCreate(ProcessBase):
    asset_ids: list[uuid.UUID] = []


class ProcessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    business_unit_id: uuid.UUID | None = None
    owner: str | None = None
    criticality: Criticality | None = None
    rto_hours: int | None = Field(default=None, ge=0)
    rpo_hours: int | None = Field(default=None, ge=0)
    rpd_hours: int | None = Field(default=None, ge=0)
    workflow_status: WorkflowState | None = None
    workflow_owner: str | None = None
    asset_ids: list[uuid.UUID] | None = None


class ProcessRead(ProcessBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    business_unit: Ref | None = None
    assets: list[Ref] = []


# ------------------------------------------------------------------------- Legal
class LegalBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = ""
    jurisdiction: str = ""
    reference: str = ""
    countries: str = ""  # CSV of applicable countries
    risk_magnifier: float = Field(default=1.0, ge=0)
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""


class LegalCreate(LegalBase):
    business_unit_ids: list[uuid.UUID] = []
    asset_ids: list[uuid.UUID] = []


class LegalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    jurisdiction: str | None = None
    reference: str | None = None
    countries: str | None = None
    risk_magnifier: float | None = Field(default=None, ge=0)
    workflow_status: WorkflowState | None = None
    workflow_owner: str | None = None
    business_unit_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None


class LegalRead(LegalBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    business_units: list[Ref] = []
    assets: list[Ref] = []
