from __future__ import annotations

import uuid
from datetime import date, datetime

from app.schemas.common import GraphRef
from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.data_protection import (
    BreachStatus,
    BreachType,
    ConsentStatus,
    DpiaWorkflowStatus,
    DsarStatus,
    DsarType,
)
from app.models.enums import Criticality, LawfulBasis, Severity


# ------------------------------------------------------------------------ DPIA ---
class DpiaBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    processing_activity: str = ""
    description: str = ""
    necessity_justification: str = ""
    risks_identified: str = ""
    mitigations: str = ""
    residual_risk: Criticality = Criticality.low
    status: DpiaWorkflowStatus = DpiaWorkflowStatus.required
    owner: str = ""
    dpo_reviewer: str = ""
    review_date: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class DpiaCreate(DpiaBase):
    pass


class DpiaUpdate(BaseModel):
    title: str | None = None
    processing_activity: str | None = None
    description: str | None = None
    necessity_justification: str | None = None
    risks_identified: str | None = None
    mitigations: str | None = None
    residual_risk: Criticality | None = None
    status: DpiaWorkflowStatus | None = None
    owner: str | None = None
    dpo_reviewer: str | None = None
    review_date: date | None = None
    workflow_status: WorkflowState | None = None


class DpiaRead(DpiaBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime


# ------------------------------------------------------------------------ DSAR ---
class DsarBase(BaseModel):
    subject_name: str = ""
    subject_contact: str = ""
    request_type: DsarType = DsarType.access
    received_date: date | None = None
    due_date: date | None = None
    response_date: date | None = None
    handler: str = ""
    notes: str = ""
    status: DsarStatus = DsarStatus.received
    workflow_status: WorkflowState = WorkflowState.draft


class DsarCreate(DsarBase):
    pass


class DsarUpdate(BaseModel):
    subject_name: str | None = None
    subject_contact: str | None = None
    request_type: DsarType | None = None
    received_date: date | None = None
    due_date: date | None = None
    response_date: date | None = None
    handler: str | None = None
    notes: str | None = None
    status: DsarStatus | None = None
    workflow_status: WorkflowState | None = None


class DsarRead(DsarBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    sla_days: int
    is_overdue: bool
    created_at: datetime


# ---------------------------------------------------------------- data breach ---
class DataBreachBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    breach_type: BreachType = BreachType.confidentiality
    discovered_date: date | None = None
    occurred_date: date | None = None
    records_affected: int = 0
    data_categories: str = ""
    severity: Severity = Severity.low
    reported_to_regulator: bool = False
    regulator_report_date: date | None = None
    notification_required: bool = False
    subjects_notified: bool = False
    status: BreachStatus = BreachStatus.open
    owner: str = ""
    root_cause: str = ""
    remediation: str = ""
    workflow_status: WorkflowState = WorkflowState.draft


class DataBreachCreate(DataBreachBase):
    incident_id: uuid.UUID | None = None
    pass


class DataBreachUpdate(BaseModel):
    incident_id: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    breach_type: BreachType | None = None
    discovered_date: date | None = None
    occurred_date: date | None = None
    records_affected: int | None = None
    data_categories: str | None = None
    severity: Severity | None = None
    reported_to_regulator: bool | None = None
    regulator_report_date: date | None = None
    notification_required: bool | None = None
    subjects_notified: bool | None = None
    status: BreachStatus | None = None
    owner: str | None = None
    root_cause: str | None = None
    remediation: str | None = None
    workflow_status: WorkflowState | None = None


class DataBreachRead(DataBreachBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    incident_id: uuid.UUID | None = None
    incident: GraphRef | None = None
    reference: str
    notification_overdue: bool
    created_at: datetime


# ------------------------------------------------------------- consent record ---
class ConsentRecordBase(BaseModel):
    subject_name: str = ""
    purpose: str = ""
    consent_given: bool = True
    consent_date: date | None = None
    withdrawal_date: date | None = None
    channel: str = ""
    lawful_basis: LawfulBasis = LawfulBasis.consent
    status: ConsentStatus = ConsentStatus.active


class ConsentRecordCreate(ConsentRecordBase):
    pass


class ConsentRecordUpdate(BaseModel):
    subject_name: str | None = None
    purpose: str | None = None
    consent_given: bool | None = None
    consent_date: date | None = None
    withdrawal_date: date | None = None
    channel: str | None = None
    lawful_basis: LawfulBasis | None = None
    status: ConsentStatus | None = None


class ConsentRecordRead(ConsentRecordBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime
