from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import Criticality
from app.models.model_risk import (
    ModelStatus,
    ModelType,
    ModelValidationStatus,
    ValidationOutcome,
    ValidationType,
)


# ------------------------------------------------------------- validations ---
class ValidationBase(BaseModel):
    validation_type: ValidationType = ValidationType.periodic
    validator: str = ""
    validation_date: date | None = None
    outcome: ValidationOutcome = ValidationOutcome.not_completed
    findings: str = ""
    performance_metrics: str = ""
    recommendations: str = ""
    status: ModelValidationStatus = ModelValidationStatus.planned


class ValidationCreate(ValidationBase):
    pass


class ValidationUpdate(BaseModel):
    validation_type: ValidationType | None = None
    validator: str | None = None
    validation_date: date | None = None
    outcome: ValidationOutcome | None = None
    findings: str | None = None
    performance_metrics: str | None = None
    recommendations: str | None = None
    status: ModelValidationStatus | None = None


class ValidationRead(ValidationBase):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: uuid.UUID
    model_id: uuid.UUID
    reference: str
    created_at: datetime


# --------------------------------------------------------- model inventory ---
class ModelBase(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str = Field(min_length=1, max_length=255)
    purpose: str = ""
    model_type: ModelType = ModelType.other
    owner: str = ""
    developer: str = ""
    vendor: str = ""
    materiality: Criticality = Criticality.medium
    status: ModelStatus = ModelStatus.development
    regulatory_relevant: bool = False
    ai_ml: bool = False
    methodology: str = ""
    last_validation_date: date | None = None
    next_validation_date: date | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class ModelCreate(ModelBase):
    pass


class ModelUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str | None = None
    purpose: str | None = None
    model_type: ModelType | None = None
    owner: str | None = None
    developer: str | None = None
    vendor: str | None = None
    materiality: Criticality | None = None
    status: ModelStatus | None = None
    regulatory_relevant: bool | None = None
    ai_ml: bool | None = None
    methodology: str | None = None
    last_validation_date: date | None = None
    next_validation_date: date | None = None
    workflow_status: WorkflowState | None = None


class ModelRead(ModelBase):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: uuid.UUID
    reference: str
    validation_count: int
    is_validation_overdue: bool
    created_at: datetime
    validations: list[ValidationRead] = []
