from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import GraphRef

from app.models.base import WorkflowState
from app.models.compliance import FRAMEWORK_KINDS
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
_KIND_HELP = (
    "compliance | maturity | guidance. A compliance framework's clauses are obligations and "
    "feed the compliance percentage; maturity and guidance frameworks (ISO 31000, ISO 27005) "
    "are self-assessed and never counted as non-compliant."
)


def _check_kind(value: str | None) -> str | None:
    if value is None:
        return value
    value = value.strip().lower()
    if value not in FRAMEWORK_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(FRAMEWORK_KINDS)}")
    return value


class FrameworkBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="compliance", description=_KIND_HELP)
    version: str = ""
    authority: str = ""
    regulator: str = ""
    scope: str = ""
    description: str = ""


class FrameworkCreate(FrameworkBase):
    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        return _check_kind(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class FrameworkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(default=None, description=_KIND_HELP)
    version: str | None = None
    authority: str | None = None
    regulator: str | None = None
    scope: str | None = None
    description: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str | None) -> str | None:
        return _check_kind(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class FrameworkPostureRead(BaseModel):
    """Three numbers side by side, so mapping visibly counts without faking compliance
    (``services/compliance_posture.py``). Percentages are of the applicable clauses."""

    model_config = ConfigDict(from_attributes=True)
    total: int = 0
    applicable: int = 0
    #: Assessed as compliant (``Requirement.status``). Mapping never moves this.
    compliant: int = 0
    #: At least one control mapped.
    mapped: int = 0
    #: Backed by a control whose test says it works (effective / partially effective).
    assured: int = 0
    unassessed: int = 0
    failing: int = 0
    #: Phase 4C: not tested directly but covered by a tested control of an equivalent or
    #: containing clause in another framework. Never part of ``mapped`` or ``assured``.
    via_crosswalk: int = 0
    compliant_pct: float = 0.0
    mapped_pct: float = 0.0
    assured_pct: float = 0.0
    via_crosswalk_pct: float = 0.0
    #: "0% assessed compliant · 62% mapped · 8% tested".
    line: str = ""


class FrameworkRead(FrameworkBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    requirement_count: int
    compliant_count: int = 0
    posture: FrameworkPostureRead | None = None
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
    #: Statement of Applicability: why the clause is in or out of scope. Required when
    #: the clause is excluded (treatment or status "not applicable").
    applicability_justification: str = ""
    domain: str = ""
    audit_questionnaire: str = ""
    status: ComplianceStatus = ComplianceStatus.not_assessed
    treatment: ComplianceTreatment | None = None
    owner: str = ""
    efficacy: int | None = Field(default=None, ge=0, le=100)
    implementation: str = ""
    legal_id: uuid.UUID | None = None


class RequirementCreate(RequirementBase):
    control_ids: list[uuid.UUID] = Field(default_factory=list)
    risk_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)


class RequirementUpdate(BaseModel):
    reference: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    applicability_justification: str | None = None
    domain: str | None = None
    audit_questionnaire: str | None = None
    status: ComplianceStatus | None = None
    treatment: ComplianceTreatment | None = None
    owner: str | None = None
    efficacy: int | None = Field(default=None, ge=0, le=100)
    implementation: str | None = None
    legal_id: uuid.UUID | None = None
    control_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None


class RequirementRead(RequirementBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    framework_id: uuid.UUID
    controls: list[ControlRef] = []
    risks: list[CompRef] = []
    policies: list[CompRef] = []
    # Reverse links (read-only).
    assets: list[GraphRef] = []
    exceptions: list[GraphRef] = []
    audit_findings: list[GraphRef] = []
    vendors: list[GraphRef] = []
    # Live rollup: health of the controls evidencing this requirement.
    control_health: str = "none"
    legal: CompRef | None = None
    findings: list[ComplianceFindingRead] = []
    is_covered: bool
    #: unmapped | unassessed | failing | assured. Mapped-but-untested is not coverage.
    coverage: str = "unmapped"
    #: Why this requirement counts as a gap, or "" when it does not. Carried on the row
    #: so the requirements table can explain a gap in place, rather than the page having
    #: to render a second list of the same requirements underneath it.
    gap_reason: str = ""
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
    #: Phase 4C, read from the requirement asked about: equivalent | subset (it is
    #: contained in this one) | superset (it contains this one) | intersects | related.
    relationship: str = "related"
    rationale: str = ""
    source: str = ""
    origin: str = "manual"
    content_version: str = ""
    confidence: float | None = None
    approved_by: str = ""
    approved_at: datetime | None = None


class ViaCrosswalkControlRead(BaseModel):
    id: uuid.UUID
    reference: str = ""
    name: str = ""
    effectiveness: str = ""


class ViaCrosswalkRead(BaseModel):
    """Why a clause counts as covered via crosswalk: the clause whose tested control
    covers it, and how the two relate. Not a direct mapping."""

    via_requirement_id: uuid.UUID
    via_reference: str
    via_title: str = ""
    via_framework: str = ""
    #: Read from the covered clause: equivalent | subset.
    relationship: str
    source: str = ""
    #: "mapped via ISO/IEC 27001:2022 A.8.5".
    label: str
    controls: list[ViaCrosswalkControlRead] = []


# ----------------------------------------------------------------- Gap analysis
class GapItem(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    status: ComplianceStatus
    is_covered: bool
    coverage: str = "unmapped"
    reason: str
    #: "mapped via ISO/IEC 27001:2022 A.8.5" when a crosswalk covers it (still a gap).
    via_crosswalk: str = ""


class GapAnalysis(BaseModel):
    framework_id: uuid.UUID
    framework_name: str
    total_requirements: int
    by_status: dict[str, int]
    #: Mapped to at least one control (the old meaning of covered, kept for the API).
    covered: int
    uncovered: int
    #: Coverage that a gap analysis may rely on — a mapped control that is effective
    #: or partially effective — and the two ways a mapped clause falls short of it.
    assured: int = 0
    unassessed: int = 0
    failing: int = 0
    compliant_pct: float
    gaps: list[GapItem]
    #: compliance | maturity | guidance. For a non-compliance kind ``compliant_pct`` is
    #: not a compliance score; show ``assessed`` of ``total_requirements`` instead.
    kind: str = "compliance"
    #: Requirements with a status other than not assessed (self-assessment progress).
    assessed: int = 0
    #: Assessed compliant / mapped / tested, of the applicable clauses (F-19).
    posture: FrameworkPostureRead | None = None


class FrameworkSummary(BaseModel):
    framework_id: uuid.UUID
    name: str
    kind: str = "compliance"
    total_requirements: int
    compliant: int
    compliant_pct: float
    assessed: int = 0
    posture: FrameworkPostureRead | None = None


class ComplianceSummary(BaseModel):
    total_frameworks: int
    total_requirements: int
    #: Across compliance-kind frameworks only: a maturity self-assessment (ISO 31000)
    #: is not an obligation and does not move the compliance percentage.
    overall_compliant_pct: float
    #: Same scope as ``overall_compliant_pct``: applicable clauses with a control mapped,
    #: and backed by a tested, working control.
    overall_mapped_pct: float = 0.0
    overall_assured_pct: float = 0.0
    #: Covered via crosswalk only, same scope; never part of mapped or tested.
    overall_via_crosswalk_pct: float = 0.0
    frameworks: list[FrameworkSummary]


# ----------------------------------------------------- Statement of Applicability
class SoaControlRead(BaseModel):
    id: uuid.UUID
    reference: str = ""
    name: str = ""
    effectiveness: str = "not_assessed"
    status: str = ""
    last_test_date: date | None = None
    last_test_result: str | None = None


class SoaRowRead(BaseModel):
    requirement_id: uuid.UUID
    reference: str
    title: str
    domain: str = ""
    #: False when the clause's treatment or status is "not applicable".
    applicable: bool
    justification: str = ""
    #: The clause's compliance status (not assessed … compliant).
    implementation_status: str
    treatment: str | None = None
    #: unmapped | unassessed | failing | assured.
    coverage: str = "unmapped"
    controls: list[SoaControlRead] = []
    #: The most recent test across the implementing controls.
    last_test_date: date | None = None
    last_test_result: str | None = None
    #: Phase 4C: covered via crosswalk (shown apart from the implementing controls).
    via_crosswalk: ViaCrosswalkRead | None = None


class SoaSummary(BaseModel):
    total: int = 0
    applicable: int = 0
    excluded: int = 0
    #: Applicable clauses with no implementing control.
    no_control: int = 0
    #: Exclusions recorded before the rule existed, with no justification.
    missing_justification: int = 0
    #: Applicable clauses with a control (the complement of ``no_control``), and those
    #: whose control is tested and working — the framework page's "mapped" / "tested".
    mapped: int = 0
    assured: int = 0
    #: Applicable clauses covered via crosswalk only.
    via_crosswalk: int = 0


class StatementOfApplicabilityRead(BaseModel):
    framework_id: uuid.UUID
    framework_name: str
    version: str = ""
    organisation: str = ""
    generated_at: datetime
    summary: SoaSummary
    rows: list[SoaRowRead]


class ApplicabilityUpdate(BaseModel):
    """Include or exclude a clause. Excluding needs a justification (ISO/IEC 27001
    6.1.3 d); including without one clears a previous exclusion reason."""

    applicable: bool
    justification: str | None = Field(default=None, max_length=4000)


# ------------------------------------------------------ Suggested requirements (D-03)
class RequirementSuggestionRead(BaseModel):
    requirement_id: uuid.UUID
    framework_id: uuid.UUID | None = None
    framework: str
    reference: str
    title: str
    #: 0-1; higher is a stronger match. Deterministic for the same data.
    score: float
    #: Why it was suggested: synonym match, shared keywords, crosswalk, shared scenarios.
    reasons: list[str] = []


class AcceptSuggestionsBody(BaseModel):
    requirement_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class AcceptSuggestionsResult(BaseModel):
    #: Links written (already-linked requirements are skipped, not counted).
    linked: int
    requirement_ids: list[uuid.UUID] = []


class BulkSuggestBody(BaseModel):
    control_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    min_score: float = Field(default=0.5, ge=0, le=1)
    #: Suggestions per control.
    limit: int = Field(default=5, ge=1, le=25)


class ControlSuggestionsRead(BaseModel):
    control_id: uuid.UUID
    reference: str = ""
    name: str = ""
    suggestions: list[RequirementSuggestionRead] = []


class SuggestionPair(BaseModel):
    control_id: uuid.UUID
    requirement_id: uuid.UUID


class BulkAcceptBody(BaseModel):
    pairs: list[SuggestionPair] = Field(min_length=1, max_length=5000)


class BulkAcceptResult(BaseModel):
    linked: int
    #: Controls that gained at least one link.
    controls: int


# ------------------------------------------------ Review all suggestions (F-19)
class SuggestionFrameworkCount(BaseModel):
    framework_id: uuid.UUID | None = None
    framework: str
    #: Suggestions for this framework in the scanned controls, and how many are strong.
    suggestions: int = 0
    strong: int = 0


class SuggestionReviewPage(BaseModel):
    """One page of the register-wide review: controls in reference order, scored in
    pages so a large catalogue never hits a request limit. Keep calling with
    ``offset = next_offset`` until it is null."""

    #: unmapped (controls with no clause linked yet) | all.
    scope: str
    framework_id: uuid.UUID | None = None
    #: Controls in scope across the whole register, and where this page sits.
    total_controls: int
    offset: int
    page_size: int
    scanned: int
    next_offset: int | None = None
    #: Only controls with at least one suggestion are listed.
    groups: list[ControlSuggestionsRead] = []
    suggestion_count: int = 0
    strong_count: int = 0
    frameworks: list[SuggestionFrameworkCount] = []


class PendingSuggestionsRead(BaseModel):
    """The hint on the controls register and the compliance page: controls with no clause
    mapped that have strong suggestions waiting."""

    framework_id: uuid.UUID | None = None
    unmapped_controls: int = 0
    #: How many of the unmapped controls were scored (capped on very large registers).
    scanned: int = 0
    capped: bool = False
    controls_with_strong: int = 0
    strong_suggestions: int = 0
    #: When the count was taken (phase 4: served from a per-organisation cache while the
    #: controls, clauses and mappings it read are unchanged).
    computed_at: datetime | None = None
    cached: bool = False
