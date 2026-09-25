from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import GraphRef

from app.models.base import WorkflowState
from app.models.enums import ControlEffectiveness, ReviewFrequency
from app.models.icfr import (
    ControlNature,
    DeficiencySeverity,
    DeficiencyStatus,
    FinancialAssertion,
    IcfrControlType,
    IcfrProcessStatus,
    IcfrTestResult,
    IcfrTestStatus,
    IcfrTestType,
    derive_effectiveness,
    figures_problem,
)


# ---------------------------------------------------------------- control tests ---
class IcfrTestBase(BaseModel):
    test_type: IcfrTestType = IcfrTestType.operating
    period: str = ""
    tester: str = ""
    sample_size: int = Field(default=0, ge=0)
    exceptions_found: int = Field(default=0, ge=0)
    test_date: date | None = None
    result: IcfrTestResult = IcfrTestResult.not_tested
    conclusion: str = ""
    status: IcfrTestStatus = IcfrTestStatus.planned


class IcfrTestCreate(IcfrTestBase):
    @model_validator(mode="after")
    def _figures_agree(self):
        problem = figures_problem(self.sample_size, self.exceptions_found, self.result)
        if problem:
            raise ValueError(problem)
        return self


class IcfrTestUpdate(BaseModel):
    test_type: IcfrTestType | None = None
    period: str | None = None
    tester: str | None = None
    sample_size: int | None = Field(default=None, ge=0)
    exceptions_found: int | None = Field(default=None, ge=0)
    test_date: date | None = None
    result: IcfrTestResult | None = None
    conclusion: str | None = None
    status: IcfrTestStatus | None = None


class IcfrTestRead(IcfrTestBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    reference: str
    created_at: datetime


# ------------------------------------------------------------------ RCM controls ---
class IcfrControlBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    control_objective: str = ""
    risk_description: str = ""
    assertion: FinancialAssertion = FinancialAssertion.accuracy
    control_type: IcfrControlType = IcfrControlType.preventive
    nature: ControlNature = ControlNature.manual
    frequency: ReviewFrequency = ReviewFrequency.monthly
    is_key: bool = False
    owner: str = ""
    design_effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    operating_effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed


class IcfrControlCreate(IcfrControlBase):
    control_id: uuid.UUID | None = None


class IcfrControlUpdate(BaseModel):
    control_id: uuid.UUID | None = None
    title: str | None = None
    control_objective: str | None = None
    risk_description: str | None = None
    assertion: FinancialAssertion | None = None
    control_type: IcfrControlType | None = None
    nature: ControlNature | None = None
    frequency: ReviewFrequency | None = None
    is_key: bool | None = None
    owner: str | None = None
    design_effectiveness: ControlEffectiveness | None = None
    operating_effectiveness: ControlEffectiveness | None = None


class IcfrControlRead(IcfrControlBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID | None = None
    #: The linked enterprise control (id, reference, name).
    control: GraphRef | None = None
    process_id: uuid.UUID
    reference: str
    test_count: int
    latest_result: IcfrTestResult | None = None
    created_at: datetime
    tests: list[IcfrTestRead] = []
    #: Where each rating comes from: "tests" (the latest conclusive test of that kind),
    #: "design" (operating capped because the design is ineffective) or "manual"
    #: (entered by hand; no conclusive test yet). See ``models.icfr.derive_effectiveness``.
    design_basis: str = "manual"
    operating_basis: str = "manual"

    @model_validator(mode="after")
    def _derive(self):
        # Ratings are read from the tests every time, so a record saved before ratings
        # were derived still shows what its tests say.
        design, operating, self.design_basis, self.operating_basis = derive_effectiveness(
            self.tests, self.design_effectiveness, self.operating_effectiveness)
        self.design_effectiveness, self.operating_effectiveness = design, operating
        return self


# --------------------------------------------------------------------- processes ---
class IcfrProcessBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    cycle: str = ""
    business_unit: str = ""
    owner: str = ""
    description: str = ""
    key_process: bool = False
    status: IcfrProcessStatus = IcfrProcessStatus.active


class IcfrProcessCreate(IcfrProcessBase):
    pass


class IcfrProcessUpdate(BaseModel):
    name: str | None = None
    cycle: str | None = None
    business_unit: str | None = None
    owner: str | None = None
    description: str | None = None
    key_process: bool | None = None
    status: IcfrProcessStatus | None = None


class IcfrProcessRead(IcfrProcessBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    control_count: int
    key_control_count: int
    created_at: datetime
    controls: list[IcfrControlRead] = []


# ------------------------------------------------------------------ deficiencies ---
class IcfrDeficiencyBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    control_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None
    severity: DeficiencySeverity = DeficiencySeverity.deficiency
    status: DeficiencyStatus = DeficiencyStatus.open
    owner: str = ""
    identified_date: date | None = None
    remediation_plan: str = ""
    target_date: date | None = None
    remediated_date: date | None = None


class IcfrDeficiencyCreate(IcfrDeficiencyBase):
    pass


class IcfrDeficiencyUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    control_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None
    severity: DeficiencySeverity | None = None
    status: DeficiencyStatus | None = None
    owner: str | None = None
    identified_date: date | None = None
    remediation_plan: str | None = None
    target_date: date | None = None
    remediated_date: date | None = None


class IcfrDeficiencyRead(IcfrDeficiencyBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime
    # Human labels for the linked process/control, so the edit form's link pickers can
    # render a name instead of a raw UUID. Populated server-side (transient attributes).
    process_label: str | None = None
    control_label: str | None = None
