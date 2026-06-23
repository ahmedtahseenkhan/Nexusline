from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import WorkflowState
from app.models.enums import (
    ComplianceStatus,
    ComplianceTreatment,
    FindingStatus,
    Severity,
)
from app.schemas.control import ControlRef


class CompRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


# --------------------------------------------------------------------- Framework
class FrameworkBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = ""
    authority: str = ""
    regulator: str = ""
    scope: str = ""
    description: str = ""
    workflow_status: WorkflowState = WorkflowState.draft


class FrameworkCreate(FrameworkBase):
    pass


class FrameworkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    version: str | None = None
    authority: str | None = None
    regulator: str | None = None
    scope: str | None = None
    description: str | None = None
    workflow_status: WorkflowState | None = None


class FrameworkRead(FrameworkBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    requirement_count: int
    compliant_count: int = 0
    created_at: datetime


# ----------------------------------------------------------- Compliance findings
class ComplianceFindingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    recommendation: str = ""
    severity: Severity = Severity.medium
    deadline: date | None = None


class ComplianceFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str
    recommendation: str
    severity: Severity
    status: FindingStatus
    deadline: date | None
    created_at: datetime


# ------------------------------------------------------------------- Requirement
class RequirementBase(BaseModel):
    reference: str = ""
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    domain: str = ""
    audit_questionnaire: str = ""
    status: ComplianceStatus = ComplianceStatus.not_assessed
    treatment: ComplianceTreatment | None = None
    owner: str = ""
    efficacy: int | None = Field(default=None, ge=0, le=100)
    implementation: str = ""
    legal_id: uuid.UUID | None = None
    workflow_status: WorkflowState = WorkflowState.draft


class RequirementCreate(RequirementBase):
    control_ids: list[uuid.UUID] = Field(default_factory=list)
    risk_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)


class RequirementUpdate(BaseModel):
    reference: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    domain: str | None = None
    audit_questionnaire: str | None = None
    status: ComplianceStatus | None = None
    treatment: ComplianceTreatment | None = None
    owner: str | None = None
    efficacy: int | None = Field(default=None, ge=0, le=100)
    implementation: str | None = None
    legal_id: uuid.UUID | None = None
    workflow_status: WorkflowState | None = None
    control_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None


class RequirementRead(RequirementBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    framework_id: uuid.UUID
    controls: list[ControlRef] = []
    risks: list[CompRef] = []
    policies: list[CompRef] = []
    legal: CompRef | None = None
    findings: list[ComplianceFindingRead] = []
    is_covered: bool
    open_findings: int = 0
    evidence_count: int = 0
    crosswalk_count: int = 0


class ControlMapping(BaseModel):
    """Replace the set of controls mapped to a requirement."""

    control_ids: list[uuid.UUID]


class CrosswalkUpdate(BaseModel):
    """Replace the set of equivalent requirements crosswalked to this one."""

    related_requirement_ids: list[uuid.UUID]


class CrosswalkItem(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    status: ComplianceStatus
    framework_id: uuid.UUID
    framework_name: str


# ----------------------------------------------------------------- Gap analysis
class GapItem(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    status: ComplianceStatus
    is_covered: bool
    reason: str


class GapAnalysis(BaseModel):
    framework_id: uuid.UUID
    framework_name: str
    total_requirements: int
    by_status: dict[str, int]
    covered: int
    uncovered: int
    compliant_pct: float
    gaps: list[GapItem]


class FrameworkSummary(BaseModel):
    framework_id: uuid.UUID
    name: str
    total_requirements: int
    compliant: int
    compliant_pct: float


class ComplianceSummary(BaseModel):
    total_frameworks: int
    total_requirements: int
    overall_compliant_pct: float
    frameworks: list[FrameworkSummary]
