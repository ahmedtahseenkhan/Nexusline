from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import ExceptionRef, GraphRef, LookupRef, UserRef

from app.models.base import WorkflowState
from app.models.enums import (
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    EvidenceType,
    ReviewFrequency,
    TestResult,
)


# ------------------------------------------------------------ control attributes
#: COSO / ISO 27002 nature of a control: what it does about an event.
Nature = Literal["preventive", "detective", "corrective", "directive"]
#: How the control is performed. "IT-dependent manual": a person acts on system output
#: (reviewing an exception report), so the report's integrity is part of the test.
Automation = Literal["manual", "it_dependent_manual", "automated"]
#: How often the control *operates* — distinct from how often it is tested
#: (``audit_frequency``). Drives the sample size an operating test needs.
OperatingFrequency = Literal[
    "continuous", "daily", "weekly", "monthly", "quarterly", "semiannual", "annual",
    "per_event", "ad_hoc",
]
NATURES: tuple[str, ...] = Nature.__args__
AUTOMATIONS: tuple[str, ...] = Automation.__args__
OPERATING_FREQUENCIES: tuple[str, ...] = OperatingFrequency.__args__

#: ISO/IEC 27002:2022 §4.2 attribute vocabulary: attribute -> its values, in the
#: standard's order. Stored lower-case without the ``#`` ("#Asset_management" ->
#: "asset_management"); both spellings are accepted on input.
ISO27002_VOCABULARY: dict[str, tuple[str, ...]] = {
    "control_type": ("preventive", "detective", "corrective"),
    "security_properties": ("confidentiality", "integrity", "availability"),
    "cybersecurity_concepts": ("identify", "protect", "detect", "respond", "recover"),
    "operational_capabilities": (
        "governance", "asset_management", "information_protection",
        "human_resource_security", "physical_security", "system_and_network_security",
        "application_security", "secure_configuration", "identity_and_access_management",
        "threat_and_vulnerability_management", "continuity",
        "supplier_relationships_security", "legal_and_compliance",
        "information_security_event_management", "information_security_assurance",
    ),
    "security_domains": ("governance_and_ecosystem", "protection", "defence", "resilience"),
}


def _iso_token(value: object) -> str:
    return str(value).strip().lstrip("#").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_iso27002(attrs: dict | None) -> dict[str, list[str]]:
    """Validate and normalise ISO 27002 attributes: known attributes only, known values
    only, de-duplicated, in the standard's order; empty attributes dropped. Raises
    ``ValueError`` naming the first unknown attribute or value."""
    if not attrs:
        return {}
    if not isinstance(attrs, dict):
        raise ValueError("iso27002_attributes must be an object of attribute -> list of values.")
    out: dict[str, list[str]] = {}
    for raw_key, raw_values in attrs.items():
        key = _iso_token(raw_key)
        allowed = ISO27002_VOCABULARY.get(key)
        if allowed is None:
            raise ValueError(
                f"iso27002_attributes: unknown attribute '{raw_key}'. "
                f"Use {', '.join(ISO27002_VOCABULARY)}."
            )
        if raw_values is None:
            continue
        if isinstance(raw_values, str):
            raw_values = raw_values.replace(",", " ").split()
        values = {_iso_token(v) for v in raw_values if str(v).strip()}
        unknown = sorted(values - set(allowed))
        if unknown:
            raise ValueError(
                f"iso27002_attributes.{key}: '{unknown[0]}' is not an ISO 27002 value; "
                f"use {', '.join(allowed)}."
            )
        if values:
            out[key] = [v for v in allowed if v in values]
    return out


#: The override text a reason field must carry before a manual rating is accepted.
OVERRIDE_REASON_NEEDED = (
    "Effectiveness is derived from reviewed control tests. To set it by hand, give the "
    "reason for the override (effectiveness_override_reason)."
)


class ControlLinkRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


class RequirementLinkRef(ControlLinkRef):
    """A clause the control implements, with the framework it belongs to (spec B7), so a
    page can say where the clause comes from without guessing from its reference.

    ``Requirement.framework`` is a lazy relationship: reading it off the ORM row inside
    an async session would try to load it and fail. The validator below takes the
    framework only when it is already loaded; the controls API fills the rest with one
    query per page (``api.v1.controls._frameworks_by_requirement``).
    """

    framework: str | None = None
    framework_id: uuid.UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def _never_lazy_load_the_framework(cls, data):
        if isinstance(data, (dict, BaseModel)):
            return data
        framework = getattr(data, "__dict__", {}).get("framework")
        return {
            "id": data.id,
            "reference": getattr(data, "reference", "") or "",
            "title": getattr(data, "title", "") or "",
            "name": getattr(data, "name", "") or "",
            "framework_id": getattr(data, "framework_id", None),
            "framework": getattr(framework, "name", None) if framework is not None else None,
        }


_LEGACY = "Legacy free text, accepted for one release; send the *_id instead. "


class ControlBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    reference: str = ""
    description: str = ""
    objective: str = ""
    # Phase 1: people and the classification are picked. The text columns are kept in
    # step with the keys (and matched onto them when sent alone) — see services.ref_fields.
    owner_id: uuid.UUID | None = Field(default=None, description="Accountable for the control.")
    operator_id: uuid.UUID | None = Field(default=None, description="Performs the control day to day.")
    owner: str = Field(default="", description=_LEGACY + "Matched onto a user by email or name.")
    # Phase 2 attributes. ``control_type`` (design artefact vs operating control) is kept
    # but is no longer the primary classification: nature and automation are.
    nature: Nature | None = None
    automation: Automation | None = None
    is_key: bool = Field(default=False, description="A key control: its failure alone would let a material risk through.")
    operating_frequency: OperatingFrequency | None = None
    iso27002_attributes: dict[str, list[str]] = Field(
        default_factory=dict,
        description="ISO/IEC 27002:2022 attributes: control_type, security_properties, "
        "cybersecurity_concepts, operational_capabilities, security_domains.",
    )
    test_procedure: str = Field(default="", description="How to test the control: the steps a tester follows.")
    evidence_expected: str = Field(default="", description="What evidence a test of this control should produce.")
    control_type: ControlType = ControlType.production
    classification_id: uuid.UUID | None = None
    classification: str = Field(default="", description=_LEGACY + "Matched onto a control classification.")
    documentation_url: str = ""
    status: ControlStatus = ControlStatus.planned
    effectiveness: ControlEffectiveness = Field(
        default=ControlEffectiveness.not_assessed,
        description="The combined rating the rest of the platform reads. Derived from reviewed "
        "tests; setting it by hand is an override and needs effectiveness_override_reason.",
    )
    # ``workflow_status`` is not writable: it moves only through the record lifecycle.
    workflow_owner_id: uuid.UUID | None = None
    opex: float | None = Field(default=None, ge=0)
    capex: float | None = Field(default=None, ge=0)
    resource_utilization: int | None = Field(default=None, ge=0, le=100)
    audit_frequency: ReviewFrequency = ReviewFrequency.annual
    audit_metric: str = ""
    audit_success_criteria: str = ""
    maintenance_frequency: ReviewFrequency = ReviewFrequency.quarterly

    @field_validator("iso27002_attributes", mode="before")
    @classmethod
    def _iso_vocabulary(cls, v):
        return normalize_iso27002(v)


_SCHEDULE_NOTE = (
    " Only an implemented or operational control has one: for a planned or retired "
    "control the date is always empty and a value sent here is ignored. The clock starts "
    "(a cycle from today) when the control becomes implemented or operational."
)


class ControlCreate(ControlBase):
    # Optional explicit schedule overrides (otherwise derived from the frequency).
    next_audit_date: date | None = Field(
        default=None,
        description="Next control test. Blank = derived from audit_frequency." + _SCHEDULE_NOTE,
    )
    next_maintenance_date: date | None = Field(
        default=None,
        description="Next maintenance. Blank = derived from maintenance_frequency." + _SCHEDULE_NOTE,
    )
    # Relationship inputs.
    policy_ids: list[uuid.UUID] = []
    requirement_ids: list[uuid.UUID] = []
    risk_ids: list[uuid.UUID] = []
    asset_ids: list[uuid.UUID] = []
    business_unit_ids: list[uuid.UUID] = Field(default_factory=list, description="Business units the control operates in.")
    process_ids: list[uuid.UUID] = Field(default_factory=list, description="Processes the control sits in.")
    effectiveness_override_reason: str = Field(
        default="", description="Why the effectiveness is set by hand. Required when effectiveness is not not_assessed."
    )

    @model_validator(mode="after")
    def _a_manual_rating_needs_a_reason(self) -> "ControlCreate":
        if self.effectiveness != ControlEffectiveness.not_assessed and not self.effectiveness_override_reason.strip():
            raise ValueError(OVERRIDE_REASON_NEEDED)
        return self


class ControlUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    reference: str | None = None
    description: str | None = None
    objective: str | None = None
    owner_id: uuid.UUID | None = None
    operator_id: uuid.UUID | None = None
    owner: str | None = Field(default=None, description=_LEGACY)
    nature: Nature | None = None
    automation: Automation | None = None
    is_key: bool | None = None
    operating_frequency: OperatingFrequency | None = None
    iso27002_attributes: dict[str, list[str]] | None = None
    test_procedure: str | None = None
    evidence_expected: str | None = None
    control_type: ControlType | None = None
    classification_id: uuid.UUID | None = None
    classification: str | None = Field(default=None, description=_LEGACY)
    documentation_url: str | None = None
    status: ControlStatus | None = None
    effectiveness: ControlEffectiveness | None = Field(
        default=None,
        description="A changed value is a manual override and needs effectiveness_override_reason; "
        "the unchanged value is accepted and ignored.",
    )
    effectiveness_override_reason: str | None = Field(
        default=None, description="Reason for a manual effectiveness. Send \"\" to drop the override."
    )
    workflow_owner_id: uuid.UUID | None = None
    opex: float | None = Field(default=None, ge=0)
    capex: float | None = Field(default=None, ge=0)
    resource_utilization: int | None = Field(default=None, ge=0, le=100)
    audit_frequency: ReviewFrequency | None = None
    audit_metric: str | None = None
    audit_success_criteria: str | None = None
    next_audit_date: date | None = Field(
        default=None,
        description="Next control test. Blank = re-derive from audit_frequency and the last test."
        + _SCHEDULE_NOTE,
    )
    maintenance_frequency: ReviewFrequency | None = None
    next_maintenance_date: date | None = Field(
        default=None,
        description="Next maintenance. Blank = re-derive from maintenance_frequency and the last run."
        + _SCHEDULE_NOTE,
    )
    policy_ids: list[uuid.UUID] | None = None
    requirement_ids: list[uuid.UUID] | None = None
    risk_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None
    business_unit_ids: list[uuid.UUID] | None = None
    process_ids: list[uuid.UUID] | None = None

    @field_validator("iso27002_attributes", mode="before")
    @classmethod
    def _iso_vocabulary(cls, v):
        return None if v is None else normalize_iso27002(v)


class ControlRead(ControlBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    # Resolved picks (``owner`` / ``classification`` stay as the legacy text).
    owner_ref: UserRef | None = None
    operator_ref: UserRef | None = None
    classification_ref: LookupRef | None = None
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""  # legacy text
    workflow_owner_ref: UserRef | None = None
    next_audit_date: date | None = None
    last_audit_date: date | None = None
    next_maintenance_date: date | None = None
    last_maintenance_date: date | None = None
    #: The test log: every test on file ("tests recorded"), and the result of the newest
    #: one recorded (reviewed or not). For the Tests tab only — never a count of assurance.
    audit_count: int = 0
    last_audit_result: TestResult | None = None
    #: Decision 7 (2026-09-17): "tested" means reviewed. The count every rating, page
    #: headline, list column and export reads (= ``reviewed_audit_count``); tests awaiting
    #: a reviewer are ``pending_review_count``, shown beside it.
    tested_count: int = 0
    #: What ratings and reliance read (``control_assurance.latest_counting_test``): tests
    #: that decide a rating — conclusive, and reviewed or recorded before reviews existed.
    #: The same count, result and date a risk sees on this control (``ControlAssuranceRef``)
    #: and the residual engine judges it by; ``pending_review_count`` says how many more
    #: await a reviewer.
    reviewed_audit_count: int = 0
    last_reviewed_result: TestResult | None = None
    last_reviewed_date: date | None = None
    is_audit_overdue: bool = False
    maintenance_count: int = 0
    last_maintenance_result: TestResult | None = None
    is_maintenance_overdue: bool = False
    # Effectiveness, derived (see services.control_assurance.derive_effectiveness).
    design_effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    operating_effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    effectiveness_override_reason: str = ""
    #: Where ``effectiveness`` comes from: "tests" (reviewed tests), "override" (set by
    #: hand with a reason), "manual" (rated by hand before ratings were derived, kept
    #: until the first reviewed test), or "none".
    effectiveness_basis: str = "none"
    #: Open issues linked to the control; while any is open the operating rating is at
    #: most partially effective.
    open_issues: list[GraphRef] = []
    #: True when an open issue actually lowered the operating rating (effective →
    #: partially effective; ``DerivedEffectiveness.capped``). The combined rating reflects
    #: it only when its basis is "tests": an override or a manual rating is never capped.
    operating_capped: bool = False
    pending_review_count: int = 0
    business_units: list[GraphRef] = []
    processes: list[GraphRef] = []
    policies: list[ControlLinkRef] = []
    #: Each clause carries its framework's name and id (B7).
    requirements: list[RequirementLinkRef] = []
    risks: list[ControlLinkRef] = []
    # Reverse links (read-only). Exceptions carry their status and expiry (B3).
    incidents: list[GraphRef] = []
    exceptions: list[ExceptionRef] = []
    projects: list[GraphRef] = []
    audit_findings: list[GraphRef] = []
    assets: list[GraphRef] = []
    vendors: list[GraphRef] = []


class ControlRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    reference: str


class ControlAssuranceRef(ControlRef):
    """A control as a record that relies on it sees it: who it is, and how far its rating
    can be trusted (spec B2, on ``GET /risks/{id}``).

    The assurance fields are ``None`` wherever they were not computed (the risk list):
    they are never read off the ORM row, whose ``audit_count`` and ``last_audit_result``
    count tests nobody has reviewed yet. Where they are filled
    (``api.v1.risks.control_assurance_ref``):

    * ``effectiveness`` is the stored combined rating — what the residual engine credits.
    * ``effectiveness_basis`` is where it comes from: tests | override | manual | none
      (``services.control_assurance.derive_effectiveness``).
    * ``audit_count``, ``last_audit_result`` and ``last_audit_date`` count only tests that
      decide a rating: conclusive, and independently reviewed (or recorded before reviews
      existed). A test awaiting review is the tester's claim, not assurance.
    * ``next_audit_date`` / ``is_audit_overdue`` are the control's test clock (none while
      planned or retired).
    * ``pending_review_count`` counts tests awaiting a reviewer (not counted above).
    * ``open_finding_count`` counts open audit findings against the control.
    * ``open_issue_count`` counts open issues linked to the control.

    The residual engine withholds credit on the same facts
    (``control_assurance.reliance_note``): the latest counted test failed, the test is
    overdue, or an audit finding is open — so the page and the suggestion cannot
    disagree. A viewer without ``control:read`` gets identity only, and one without
    ``issue:read`` no ``open_issue_count`` (``api.v1.risks._assured_controls``).
    """

    effectiveness: ControlEffectiveness | None = None
    effectiveness_basis: str | None = None
    audit_count: int | None = None
    last_audit_result: TestResult | None = None
    last_audit_date: date | None = None
    next_audit_date: date | None = None
    is_audit_overdue: bool | None = None
    pending_review_count: int | None = None
    open_finding_count: int | None = None
    open_issue_count: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _identity_only_from_the_row(cls, data):
        if isinstance(data, (dict, BaseModel)):
            return data
        return {"id": data.id, "name": data.name, "reference": getattr(data, "reference", "") or ""}


class EffectivenessOverride(BaseModel):
    """A manual effectiveness rating. The reason is recorded on the control and in the
    activity trail; the derived design/operating ratings stay visible beside it."""

    effectiveness: ControlEffectiveness
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Give the reason for the override.")
        return v.strip()


# --------------------------------------------------------------- control tests
ControlTestType = Literal["design", "operating"]
TEST_TYPES: tuple[str, ...] = ControlTestType.__args__
#: How the sample was drawn. "full_population" = every item was tested.
SampleMethod = Literal["", "random", "systematic", "judgemental", "haphazard", "block", "full_population"]
SAMPLE_METHODS: tuple[str, ...] = tuple(m for m in SampleMethod.__args__ if m)
#: Results that are assurance evidence (as opposed to a not-assessed placeholder).
CONCLUSIVE_RESULTS: tuple[TestResult, ...] = (
    TestResult.passed, TestResult.passed_with_exceptions, TestResult.failed,
)
#: Review states of a test. "legacy" marks tests recorded before reviews existed.
REVIEW_PENDING, REVIEW_REVIEWED, REVIEW_RETURNED, REVIEW_LEGACY = "pending", "reviewed", "returned", "legacy"


def control_test_problems(result: TestResult, conducted: date | None, conclusion: str) -> list[str]:
    """Why a recorded test is not acceptable yet, or ``[]``. A not-assessed placeholder
    needs nothing; a conclusive result needs the date and the conclusion."""
    if result == TestResult.not_assessed:
        return []
    problems = []
    if conducted is None:
        problems.append(f"A {result.value} test needs the date it was performed (conducted_date).")
    if not (conclusion or "").strip():
        problems.append(
            f"A {result.value} test needs the tester's conclusion (conclusion, formerly result_description)."
        )
    return problems


def workpaper_problems(
    result: TestResult,
    *,
    test_type: str | None,
    period_start: date | None,
    period_end: date | None,
    evidence_count: int,
) -> list[str]:
    """What a conclusive test still lacks before it can be recorded, or ``[]``.

    Kept apart from the schema's own validator because the evidence count is only known
    once the evidence ids have been checked against the database. The date and the
    conclusion are checked by :func:`control_test_problems`.
    """
    if result not in CONCLUSIVE_RESULTS:
        return []
    problems = []
    if test_type not in TEST_TYPES:
        problems.append(
            "Say what kind of test this was (test_type): design — is the control designed to "
            "work — or operating — did it work over a period."
        )
    if test_type == "operating" and (period_start is None or period_end is None):
        problems.append(
            "An operating test covers a period: give period_start and period_end "
            "(the window the sample was drawn from)."
        )
    if evidence_count < 1:
        problems.append(
            f"A {result.value} test needs at least one evidence item: attach existing evidence "
            "(evidence_ids) or add it with the test (new_evidence)."
        )
    return problems


class NewTestEvidence(BaseModel):
    """Evidence created together with the test it supports."""

    title: str = Field(min_length=1, max_length=255)
    evidence_type: EvidenceType = EvidenceType.document
    reference: str = Field(default="", max_length=500, description="URL or location of the artefact.")
    description: str = ""
    collected_at: date | None = Field(default=None, description="Defaults to the test date.")


class ControlAuditCreate(BaseModel):
    """A control test workpaper.

    Server rules (422 otherwise): a conclusive result (passed, passed with exceptions,
    failed) needs the test date, a conclusion, the test type, a period for an operating
    test and at least one evidence item; the period starts on or before it ends; the
    sample is no larger than the population; *passed with exceptions* records at least
    one exception. The test starts ``pending`` review and changes nothing until an
    independent reviewer approves it.
    """

    result: TestResult = TestResult.not_assessed
    test_type: ControlTestType | None = Field(
        default=None, description="design (is the control designed to work?) or operating (did it work over the period?). Required for a conclusive result."
    )
    planned_date: date | None = None
    conducted_date: date | None = Field(
        default=None, description="When the test was performed. Required for a conclusive result."
    )
    period_start: date | None = Field(default=None, description="Start of the period tested. Required for an operating test.")
    period_end: date | None = Field(default=None, description="End of the period tested. Required for an operating test.")
    population_size: int | None = Field(default=None, ge=0, description="Occurrences of the control in the period.")
    sample_size: int | None = Field(default=None, ge=0, description="Occurrences tested; no more than the population.")
    sample_method: SampleMethod = ""
    exceptions_count: int = Field(default=0, ge=0, description="Sample items where the control did not work.")
    exceptions_detail: str = ""
    metric_description: str = ""
    success_criteria: str = ""
    conclusion: str = Field(default="", description="The tester's conclusion. Required for a conclusive result.")
    result_description: str = Field(
        default="", description="Former name of ``conclusion``, accepted for one release; kept equal to it."
    )
    improvement: str = ""
    tested_by_id: uuid.UUID | None = Field(
        default=None, description="Who performed the test, picked from the user list. Defaults to whoever records it."
    )
    auditor: str = Field(
        default="",
        description=_LEGACY + "Who performed the test (name); kept equal to the tester's name.",
    )
    evidence_ids: list[uuid.UUID] = Field(
        default_factory=list, description="Existing evidence of this control that supports the test."
    )
    new_evidence: list[NewTestEvidence] = Field(
        default_factory=list, description="Evidence to create with the test (files can be added to it afterwards)."
    )

    @model_validator(mode="after")
    def _a_workpaper_is_coherent(self) -> "ControlAuditCreate":
        # ``conclusion`` replaces ``result_description``; either spelling fills both.
        text = (self.conclusion or "").strip() or (self.result_description or "").strip()
        self.conclusion = self.result_description = text
        # A pass or fail is assurance evidence; an undated, unexplained "passed" is an
        # assertion nobody can support.
        problems = control_test_problems(self.result, self.conducted_date, text)
        if self.period_start and self.period_end and self.period_start > self.period_end:
            problems.append("The period tested must start on or before it ends (period_start ≤ period_end).")
        if (
            self.sample_size is not None and self.population_size is not None
            and self.sample_size > self.population_size
        ):
            problems.append("The sample cannot be larger than the population (sample_size ≤ population_size).")
        if self.result == TestResult.passed_with_exceptions and self.exceptions_count < 1:
            problems.append(
                "Passed with exceptions needs the number of exceptions found (exceptions_count ≥ 1); "
                "with none, the result is passed."
            )
        if problems:
            raise ValueError(" ".join(problems))
        return self


class ControlTestRef(BaseModel):
    """A control test as other records (evidence, issues) point at it."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    test_type: str | None = None
    result: TestResult
    conducted_date: date | None = None
    review_status: str = REVIEW_LEGACY


class ControlAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    result: TestResult
    test_type: str | None = None
    planned_date: date | None
    conducted_date: date | None
    period_start: date | None = None
    period_end: date | None = None
    population_size: int | None = None
    sample_size: int | None = None
    sample_method: str = ""
    exceptions_count: int = 0
    exceptions_detail: str = ""
    metric_description: str
    success_criteria: str
    conclusion: str = ""
    result_description: str
    improvement: str
    auditor: str  # legacy text: the tester's name
    tested_by_id: uuid.UUID | None = None
    tested_by_ref: UserRef | None = None
    # Four-eyes review.
    review_status: str = REVIEW_LEGACY
    reviewed_by_id: uuid.UUID | None = None
    reviewed_by_ref: UserRef | None = None
    reviewed_at: datetime | None = None
    review_note: str = ""
    raised_issue_id: uuid.UUID | None = None
    raised_issue: GraphRef | None = None
    evidence: list[GraphRef] = []
    #: For the signed-in user: may they approve/return it, or edit and resubmit it?
    can_review: bool = False
    review_blocked_reason: str = ""
    can_edit: bool = False
    created_at: datetime

    @model_validator(mode="after")
    def _conclusion_falls_back_to_the_legacy_text(self) -> "ControlAuditRead":
        if not self.conclusion:
            self.conclusion = self.result_description or ""
        return self


class ControlTestReview(BaseModel):
    """An independent reviewer's decision on a pending test."""

    decision: Literal["approve", "return"]
    note: str = Field(default="", max_length=4000, description="Required when returning the test to the tester.")

    @model_validator(mode="after")
    def _a_return_says_why(self) -> "ControlTestReview":
        if self.decision == "return" and not self.note.strip():
            raise ValueError("Say what the tester needs to fix (note) when returning a test.")
        return self


class ControlMaintenanceCreate(BaseModel):
    result: TestResult = TestResult.not_assessed
    task: str = ""
    planned_date: date | None = None
    conducted_date: date | None = None
    conclusion: str = ""


class ControlMaintenanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    control_id: uuid.UUID
    result: TestResult
    task: str
    planned_date: date | None
    conducted_date: date | None
    conclusion: str
    created_at: datetime
