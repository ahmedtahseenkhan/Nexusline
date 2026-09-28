from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.models.base import WorkflowState
from app.schemas.common import ExceptionRef, GraphRef, LookupRef, UserRef
from app.models.enums import (
    AcceptanceStatus,
    ReviewFrequency,
    RiskStatus,
    Severity,
    TreatmentStrategy,
)
from app.schemas.asset import AssetRef
from app.schemas.control import ControlAssuranceRef
from app.schemas.tenant_settings import currency_or_blank
from app.schemas.threat import NamedRef
from app.services.risk_scoring import (
    DEFAULT_MAX_SCORE,
    MAX_MATRIX_SIZE,
    MIN_MATRIX_SIZE,
    SeverityScale,
    effective_review_frequency,
    is_scored,
    severity_for_score,  # noqa: F401 - re-exported for callers
)

# The widest scale any tenant may configure. The tenant's actual ``matrix_size`` is a
# narrower check applied in the API layer, which is the only place that knows it.
_Scale = Field(ge=1, le=MAX_MATRIX_SIZE)
_OptionalScale = Field(default=None, ge=1, le=MAX_MATRIX_SIZE)


class RiskLinkRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""


_LEGACY = "Legacy free text, accepted for one release; send the *_id instead. "

# ------------------------------------------------------------ phase 2 vocabularies ---
# Fixed lists rather than lookups: they are the methodology's own words, reported on
# and filtered by, and a tenant renaming "emerging" would break every report that
# counts them. The finer taxonomy lives in the (tenant-managed) risk category.

#: What kind of risk this is — the ERM taxonomy's top cut.
RISK_TYPES: tuple[str, ...] = (
    "strategic", "operational", "financial", "compliance", "technology", "emerging",
)
#: How fast the impact is felt once the event happens: within days (``immediate``),
#: weeks, months or years. Two risks with the same score but different velocity get
#: different treatment urgency.
RISK_VELOCITIES: tuple[str, ...] = ("immediate", "weeks", "months", "years")
#: Where the risk was identified. ``generated`` = proposed by the scenario library.
RISK_SOURCES: tuple[str, ...] = (
    "rcsa", "audit", "incident", "generated", "regulatory", "self_identified", "other",
)
#: Which assessment an impact-dimension score belongs to.
IMPACT_BASES: tuple[str, ...] = ("inherent", "residual", "target")
#: A treatment action's lifecycle. ``done`` stamps ``completed_at``.
TREATMENT_ACTION_STATUSES: tuple[str, ...] = ("open", "in_progress", "done", "cancelled")
#: Statuses that still need work — what overdue tracking and the deadline read.
OPEN_ACTION_STATUSES: tuple[str, ...] = ("open", "in_progress")

#: Phase 3 hierarchy: 1 enterprise (what the board reads), 2 category, 3 scenario
#: (what practitioners assess, and where generated risks land). None = not placed.
RISK_LEVELS: dict[int, str] = {1: "enterprise", 2: "category", 3: "scenario"}
_Level = Field(default=None, ge=1, le=3, description="1 enterprise, 2 category, 3 scenario; null = not placed.")

RiskType = Literal["strategic", "operational", "financial", "compliance", "technology", "emerging"]
RiskVelocity = Literal["immediate", "weeks", "months", "years"]
RiskSource = Literal["rcsa", "audit", "incident", "generated", "regulatory", "self_identified", "other"]
ImpactBasis = Literal["inherent", "residual", "target"]
ActionStatus = Literal["open", "in_progress", "done", "cancelled"]


class ImpactDimensionIn(BaseModel):
    """One impact score on one dimension (``impact_dimension`` lookup) for one basis.

    When a request carries dimensions for a basis, that basis' overall impact is derived
    from them (``RiskSetting.impact_mode``) — see ``services.risk_integrity``.
    """

    dimension_id: uuid.UUID
    basis: ImpactBasis = "inherent"
    score: int = _Scale
    rationale: str = ""


class ImpactDimensionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    dimension_id: uuid.UUID
    dimension_ref: LookupRef | None = None
    basis: str
    score: int
    rationale: str = ""


class RiskBase(BaseModel):
    # Blank is allowed on create: the title is then composed from the risk statement
    # ("<event>, caused by <cause>, resulting in <consequence>").
    title: str = Field(default="", max_length=255)
    description: str = ""
    # Phase 2: the structured risk statement (cause → event → consequence).
    cause: str = ""
    event: str = ""
    consequence: str = ""
    risk_type: RiskType | None = None
    velocity: RiskVelocity | None = None
    identified_date: date | None = None
    # Defaults to the creator when not given.
    identified_by_id: uuid.UUID | None = None
    source: RiskSource | None = None
    # Phase 1: the category is picked from the ``risk_category`` list. ``category`` text
    # is kept in step with it (and matched onto it when sent alone) — see services.ref_fields.
    category_id: uuid.UUID | None = None
    category: str = Field(default="", description=_LEGACY + "Matched onto a risk category.")
    status: RiskStatus = RiskStatus.draft
    # Optional on create: a draft may be saved before anyone has scored it (stored as
    # 1x1, "not yet assessed"). Leaving draft needs chosen scores and a rationale.
    inherent_likelihood: int | None = _OptionalScale
    inherent_impact: int | None = _OptionalScale
    # Residual scoring (after controls) — optional on create, set on assessment too
    residual_likelihood: int | None = _OptionalScale
    residual_impact: int | None = _OptionalScale
    # Where treatment should take the risk: target <= residual <= inherent.
    target_likelihood: int | None = _OptionalScale
    target_impact: int | None = _OptionalScale
    # Why the scores are what they are. Required whenever an inherent or residual score
    # changes (except on a draft, whose scores are provisional).
    assessment_rationale: str = ""
    # Why the residual is higher than inherent (or departs from the suggestion). A
    # residual above inherent is refused without it — see services.risk_integrity.
    residual_override_reason: str = ""
    treatment_strategy: TreatmentStrategy | None = None
    treatment_description: str = ""
    treatment_owner_id: uuid.UUID | None = None
    treatment_owner: str = Field(default="", description=_LEGACY + "Matched onto a user by email or name.")
    treatment_deadline: date | None = None
    treatment_cost: float | None = Field(default=None, ge=0)
    review_frequency: ReviewFrequency = ReviewFrequency.annual
    # ``workflow_status`` is not writable here: it moves only through the record
    # lifecycle (``POST /records/risk/{id}/workflow/{action}``). The approval owner is
    # picked (``workflow_owner_id``); its ``workflow_owner`` text is read-only.
    workflow_owner_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    # Quantitative (FAIR): events/year and $ per event
    annual_loss_frequency: float | None = Field(default=None, ge=0)
    single_loss_expectancy: float | None = Field(default=None, ge=0)


class RiskCreate(RiskBase):
    # Segment scoping: which business units and processes this risk sits in. Banks run
    # assessments a segment at a time, so these are what the register is filtered by.
    business_unit_ids: list[uuid.UUID] = Field(default_factory=list)
    process_ids: list[uuid.UUID] = Field(default_factory=list)
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    control_ids: list[uuid.UUID] = Field(default_factory=list)
    threat_ids: list[uuid.UUID] = Field(default_factory=list)
    vulnerability_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_ids: list[uuid.UUID] = Field(default_factory=list)
    incident_ids: list[uuid.UUID] = Field(default_factory=list)
    impact_dimensions: list[ImpactDimensionIn] = Field(default_factory=list)
    # Phase 3 hierarchy. The parent must be a live risk at a higher level (a lower
    # number); the level defaults to the parent's + 1. See services.risk_hierarchy.
    parent_id: uuid.UUID | None = None
    level: int | None = _Level


class RiskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    cause: str | None = None
    event: str | None = None
    consequence: str | None = None
    risk_type: RiskType | None = None
    velocity: RiskVelocity | None = None
    identified_date: date | None = None
    identified_by_id: uuid.UUID | None = None
    source: RiskSource | None = None
    category_id: uuid.UUID | None = None
    category: str | None = Field(default=None, description=_LEGACY)
    status: RiskStatus | None = None
    # Sending null for an inherent score means "not chosen" and leaves it as stored.
    inherent_likelihood: int | None = _OptionalScale
    inherent_impact: int | None = _OptionalScale
    residual_likelihood: int | None = _OptionalScale
    residual_impact: int | None = _OptionalScale
    target_likelihood: int | None = _OptionalScale
    target_impact: int | None = _OptionalScale
    assessment_rationale: str | None = None
    # The full set of dimension scores: rows for a basis not in the list are removed.
    impact_dimensions: list[ImpactDimensionIn] | None = None
    residual_override_reason: str | None = None
    treatment_strategy: TreatmentStrategy | None = None
    treatment_description: str | None = None
    treatment_owner_id: uuid.UUID | None = None
    treatment_owner: str | None = Field(default=None, description=_LEGACY)
    treatment_deadline: date | None = None
    treatment_cost: float | None = Field(default=None, ge=0)
    review_frequency: ReviewFrequency | None = None
    workflow_owner_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    annual_loss_frequency: float | None = Field(default=None, ge=0)
    single_loss_expectancy: float | None = Field(default=None, ge=0)
    business_unit_ids: list[uuid.UUID] | None = None
    process_ids: list[uuid.UUID] | None = None
    asset_ids: list[uuid.UUID] | None = None
    control_ids: list[uuid.UUID] | None = None
    threat_ids: list[uuid.UUID] | None = None
    vulnerability_ids: list[uuid.UUID] | None = None
    policy_ids: list[uuid.UUID] | None = None
    incident_ids: list[uuid.UUID] | None = None
    # Phase 3 hierarchy: null parent_id detaches the risk; an omitted level is kept.
    parent_id: uuid.UUID | None = None
    level: int | None = _Level


class RiskAssessment(BaseModel):
    """Record residual scoring after considering controls."""

    residual_likelihood: int = _Scale
    residual_impact: int = _Scale
    # Required (with ``risk:accept``) only when the residual is above inherent.
    residual_override_reason: str | None = None
    # Required when the residual changes (the risk leaves draft here).
    assessment_rationale: str | None = None


class RiskAcceptanceCreate(BaseModel):
    rationale: str = Field(min_length=1)
    expires_at: date | None = None
    # The exposure being accepted, for a risk with no quantified exposure (a quantified
    # one is taken from the risk; a higher figure typed here wins). Checked against the
    # approver's delegation-of-authority mandate (services.authority_limits).
    exposure_amount: float | None = Field(default=None, ge=0)
    exposure_currency: str = Field(default="", max_length=8)

    _ccy = field_validator("exposure_currency")(currency_or_blank)


class RiskAcceptanceDecision(BaseModel):
    approve: bool
    note: str = ""


class RiskAcceptanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    risk_id: uuid.UUID
    requested_by: uuid.UUID | None
    approver_id: uuid.UUID | None
    rationale: str
    status: AcceptanceStatus
    expires_at: date | None
    decided_at: date | None
    exposure_amount: float | None = None
    exposure_currency: str = ""
    exposure_basis: str = ""
    created_at: datetime


class TreatmentActionBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    owner_id: uuid.UUID | None = None
    due_date: date | None = None
    status: ActionStatus = "open"
    percent_complete: int = Field(default=0, ge=0, le=100)


class TreatmentActionCreate(TreatmentActionBase):
    pass


class TreatmentActionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    owner_id: uuid.UUID | None = None
    due_date: date | None = None
    status: ActionStatus | None = None
    percent_complete: int | None = Field(default=None, ge=0, le=100)


class TreatmentActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    risk_id: uuid.UUID
    title: str
    description: str = ""
    owner_id: uuid.UUID | None = None
    owner_ref: UserRef | None = None
    due_date: date | None = None
    status: str
    percent_complete: int = 0
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    #: Open or in progress and past its due date.
    overdue: bool = False


class TreatmentProgress(BaseModel):
    """``done`` of ``total`` actions; cancelled actions are not part of the plan."""

    done: int = 0
    total: int = 0
    open: int = 0
    overdue: int = 0
    percent: int = 0


class RiskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    title: str
    description: str
    # Phase 2: statement, classification and the assessment trail.
    cause: str = ""
    event: str = ""
    consequence: str = ""
    risk_type: str | None = None
    velocity: str | None = None
    identified_date: date | None = None
    identified_by_id: uuid.UUID | None = None
    identified_by_ref: UserRef | None = None
    source: str | None = None
    target_likelihood: int | None = None
    target_impact: int | None = None
    target_score: int | None = None
    target_severity: Severity | None = None
    assessment_rationale: str = ""
    last_assessed_at: datetime | None = None
    last_assessed_by_id: uuid.UUID | None = None
    last_assessed_by_ref: UserRef | None = None
    # Filled on the single-record read (GET /risks/{id}); empty on the list.
    impact_dimensions: list[ImpactDimensionRead] = []
    treatment_actions: list[TreatmentActionRead] = []
    # Filled on the list and the single read.
    treatment_progress: TreatmentProgress | None = None
    # Appetite and tolerance that apply to this risk: its level-1 category's, else the
    # organisation's (``appetite_category_id`` None). ``appetite_status`` compares the
    # effective score (residual if assessed, else inherent) against them.
    appetite_score: int | None = None
    tolerance_score: int | None = None
    appetite_status: str | None = None
    appetite_category_id: uuid.UUID | None = None
    category: str  # legacy text, kept equal to category_ref.label while both exist
    category_id: uuid.UUID | None = None
    category_ref: LookupRef | None = None
    status: RiskStatus
    owner_id: uuid.UUID | None
    owner_ref: UserRef | None = None

    inherent_likelihood: int
    inherent_impact: int
    inherent_score: int | None
    residual_likelihood: int | None
    residual_impact: int | None
    residual_score: int | None

    annual_loss_frequency: float | None
    single_loss_expectancy: float | None
    annual_loss_expectancy: float | None

    treatment_strategy: TreatmentStrategy | None
    treatment_description: str
    treatment_owner: str  # legacy text
    treatment_owner_id: uuid.UUID | None = None
    treatment_owner_ref: UserRef | None = None
    treatment_deadline: date | None
    treatment_cost: float | None
    review_frequency: ReviewFrequency
    last_review_date: date | None
    next_review_date: date | None
    expired_reviews: int
    workflow_status: WorkflowState
    workflow_owner: str  # legacy text
    workflow_owner_id: uuid.UUID | None = None
    workflow_owner_ref: UserRef | None = None

    business_units: list[NamedRef] = []
    processes: list[NamedRef] = []
    assets: list[AssetRef] = []
    #: How many live assets the risk links. The register reports this and leaves
    #: ``assets`` empty — a risk on the whole estate links thousands, and a list page
    #: carrying each one for every row was a megabyte a page; the record carries them.
    asset_count: int | None = None
    # Each control's rating, its basis and its test record (B2): filled on the
    # single-record read and write responses; null on the list.
    controls: list[ControlAssuranceRef] = []
    threats: list[NamedRef] = []
    vulnerabilities: list[NamedRef] = []
    policies: list[RiskLinkRef] = []
    incidents: list[RiskLinkRef] = []
    acceptances: list[RiskAcceptanceRead] = []

    # Reverse links — records elsewhere that point at this risk (read-only).
    requirements: list[GraphRef] = []
    # Exceptions carry their status and expiry (B3): an exception is not a risk
    # acceptance, and the page says which one it is and when it lapses.
    exceptions: list[ExceptionRef] = []
    vendors: list[GraphRef] = []
    projects: list[GraphRef] = []
    goals: list[GraphRef] = []
    processing_activities: list[GraphRef] = []
    audit_findings: list[GraphRef] = []
    kris: list[GraphRef] = []
    loss_events: list[GraphRef] = []
    # Live issues raised against this risk (issue_risks).
    issues: list[GraphRef] = []
    # Filled on the single-record read only (``_linked_records``): RCSAs with a line that
    # assesses this risk (one entry per RCSA; ``title`` names the lines), FAIR
    # quantifications that size it, and continuity plans that mitigate it.
    rcsa_assessments: list[GraphRef] = []
    quantifications: list[GraphRef] = []
    continuity_plans: list[GraphRef] = []

    # Live rollup: health of the mitigating controls (none | ok | untested | issues).
    control_health: str = "none"

    # False for a draft nobody has scored (``risk_scoring.is_scored``): its stored 1x1 is
    # a placeholder, so the severities and ``appetite_status`` come back null.
    inherent_scored: bool = True
    # The cycle the review clock runs on: the stricter of ``review_frequency`` and the
    # longest interval the current rating allows (``RiskSetting.review_cadence``), and
    # why when the rating decides it ("Monthly — required for Critical risks").
    effective_review_frequency: ReviewFrequency | None = None
    review_frequency_reason: str = ""

    # Phase 3 hierarchy: where the risk sits, the live risk above it and how many live
    # risks sit directly below it (``GET /risks/{id}/rollup`` lists them).
    level: int | None = None
    parent_id: uuid.UUID | None = None
    parent: GraphRef | None = None
    children_count: int = 0

    # Residual suggested by the control-effectiveness engine, and the sign-off trail.
    # A suggestion is never the assessed residual until someone accepts it.
    suggested_residual_likelihood: int | None = None
    suggested_residual_impact: int | None = None
    residual_accepted_at: date | None = None
    residual_override_reason: str = ""

    # Raised when something the risk depended on changed underneath it (an asset was
    # deleted, the scores contradict each other). One reason per line.
    needs_review: bool = False
    review_reason: str = ""

    created_at: datetime
    updated_at: datetime

    # Banded against the tenant's matrix. Populated by the validator below rather than
    # a computed property, because banding depends on the tenant's matrix size — which
    # only the caller knows. Callers pass it as validation context:
    # ``RiskRead.model_validate(risk, context={"max_score": n})``. Without context the
    # default 5x5 bands apply, so every pre-existing call site is unchanged.
    inherent_severity: Severity | None = None
    residual_severity: Severity | None = None

    @model_validator(mode="after")
    def _band_severities(self, info: ValidationInfo) -> "RiskRead":
        """Band the scores, but never re-band an already-banded value.

        FastAPI validates a handler's return value a second time against
        ``response_model``, and that pass carries no context — recomputing there would
        silently reset a 6x6 tenant's severities to the default 5x5 bands. Only the
        first pass (straight off the ORM row, where these fields are still None) does
        the work.

        Context: ``scale`` (a ``SeverityScale``: configured bands and cell overrides) or
        the older ``max_score``; ``appetite`` (an ``AppetiteBook``) for the per-category
        appetite fields, which stay None without it.
        """
        ctx = info.context or {}
        if self.asset_count is None:
            counts = ctx.get("asset_counts")
            self.asset_count = counts.get(self.id, 0) if counts is not None else len(self.assets)
        scale = ctx.get("scale") or SeverityScale(max_score=ctx.get("max_score", DEFAULT_MAX_SCORE))
        # An unscored draft is never banded or judged against appetite, on either pass:
        # the stored 1x1 would otherwise read as a "low, within appetite" assessment.
        self.inherent_scored = is_scored(self.status, self.last_assessed_at)
        if not self.inherent_scored:
            self.inherent_severity = self.residual_severity = self.target_severity = None
            self.appetite_status = None
        else:
            if self.inherent_severity is None:
                self.inherent_severity = scale.for_cell(self.inherent_likelihood, self.inherent_impact)
            if self.residual_severity is None:
                self.residual_severity = scale.for_cell(self.residual_likelihood, self.residual_impact)
        if self.target_likelihood and self.target_impact:
            if self.target_score is None:
                self.target_score = self.target_likelihood * self.target_impact
            if self.target_severity is None and self.inherent_scored:
                self.target_severity = scale.for_cell(self.target_likelihood, self.target_impact)
        book = ctx.get("appetite")
        if book is not None and self.tolerance_score is None:
            self.appetite_score, self.tolerance_score = book.thresholds(self.category_id)
            self.appetite_category_id = book.source_of(self.category_id)
            self.appetite_status = book.status(
                self.residual_score if self.residual_score is not None else self.inherent_score,
                self.category_id,
            ) if self.inherent_scored else None
        if self.effective_review_frequency is None:
            severity = self.residual_severity or self.inherent_severity
            self.effective_review_frequency, self.review_frequency_reason = effective_review_frequency(
                self.review_frequency, severity, ctx.get("cadence")
            )
        return self


class RiskRollupNode(BaseModel):
    """One risk in a roll-up or the board tree. ``exposure`` is the residual score when
    assessed, else the inherent score — what the dashboards rank by; ``severity`` its
    band on the tenant's matrix (cell overrides included); ``depth`` 0 is the risk asked
    about, 1 its children."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    level: int | None = None
    parent_id: uuid.UUID | None = None
    depth: int = 0
    status: str = ""
    inherent_score: int | None = None
    residual_score: int | None = None
    exposure: int | None = None
    severity: Severity | None = None
    appetite_status: str | None = None
    #: On the board register (scored, out of Draft, not accepted or closed): counted in
    #: the roll-up's bands, worst exposure and breaches. False = listed, not counted.
    in_figures: bool = True
    #: False for a draft nobody has scored — no score, severity or appetite position.
    scored: bool = True


class RiskRollup(BaseModel):
    """Everything below one risk: its live children, every live descendant, the worst
    residual (assessed descendants only) and worst exposure among them, and counts.
    Worsts, bands and breaches read the board register; ``not_in_figures`` counts the
    descendants listed but left out of them."""

    model_config = ConfigDict(from_attributes=True)
    risk: RiskRollupNode
    children: list[RiskRollupNode] = []
    descendants: list[RiskRollupNode] = []
    worst_residual: RiskRollupNode | None = None
    worst_exposure: RiskRollupNode | None = None
    by_severity: dict[str, int] = Field(default_factory=dict)
    breaches: int = 0
    total: int = 0
    not_in_figures: int = 0


class RiskHierarchyNode(RiskRollupNode):
    """A node of the board view. Counts and ``worst`` cover every live risk below the
    node at any level, including levels the view does not show."""

    children_count: int = 0
    descendants_count: int = 0
    worst: RiskRollupNode | None = None
    by_severity: dict[str, int] = Field(default_factory=dict)
    breaches: int = 0
    #: Risks below the node left out of its figures (drafts, unscored, accepted, closed).
    not_in_figures: int = 0
    children: list["RiskHierarchyNode"] = []


class RiskHierarchy(BaseModel):
    max_level: int
    roots: list[RiskHierarchyNode] = []
    #: Live risks with no level yet.
    unplaced: int = 0
    #: Live risks per level, as strings "1".."3".
    by_level: dict[str, int] = Field(default_factory=dict)


class RiskSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    appetite_score: int
    tolerance_score: int
    matrix_size: int = 5
    impact_mode: str = "max"
    # Severity -> the longest review cycle a risk of that rating may have: the
    # organisation's value where set, else the product default (critical monthly, high
    # quarterly, medium twice a year, low annual).
    review_cadence: dict[str, str] = Field(default_factory=dict)
    review_cadence_defaults: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _fill_cadence(self) -> "RiskSettingRead":
        from app.services.risk_scoring import DEFAULT_REVIEW_CADENCE, review_cadence

        self.review_cadence = {k: v.value for k, v in review_cadence(self.review_cadence).items()}
        self.review_cadence_defaults = {k: v.value for k, v in DEFAULT_REVIEW_CADENCE.items()}
        return self


class RiskSettingUpdate(BaseModel):
    # Upper bound is the largest score the widest configurable matrix can produce. A
    # value above the tenant's own matrix maximum is rejected in the API, where the size
    # is known.
    appetite_score: int = Field(ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    tolerance_score: int = Field(ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    # Optional on the PUT so an older client that sends only the thresholds keeps working.
    review_cadence: dict[str, str] | None = None


class RiskSettingPatch(BaseModel):
    """``PATCH /risk-settings``: change only what is sent. ``review_cadence`` replaces
    the stored map; a severity left out takes the product default."""

    appetite_score: int | None = Field(default=None, ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    tolerance_score: int | None = Field(default=None, ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    review_cadence: dict[str, str] | None = None


# ----------------------------------------------------------- matrix config ---
class MatrixLevel(BaseModel):
    """One rung of a scale, in the bank's own words."""

    level: int = Field(ge=1, le=MAX_MATRIX_SIZE)
    label: str = Field(default="", max_length=60)
    definition: str = ""


class MatrixBand(BaseModel):
    """A severity band, derived from the matrix size rather than configured."""

    severity: Severity
    min_score: int
    max_score: int


class SeverityBands(BaseModel):
    """Configured band thresholds: the highest score that is low, medium and high."""

    low_max: int = Field(ge=1)
    medium_max: int = Field(ge=1)
    high_max: int = Field(ge=1)


class MatrixCellBand(BaseModel):
    """One cell of the matrix and the band it is coloured — its override, or its score's."""

    likelihood: int
    impact: int
    score: int
    band: Severity
    overridden: bool = False


class RiskMatrixConfig(BaseModel):
    size: int
    max_score: int
    appetite_score: int
    tolerance_score: int
    likelihood_levels: list[MatrixLevel]
    impact_levels: list[MatrixLevel]
    bands: list[MatrixBand]
    # Phase 2: configured thresholds (None = derived from the matrix size), per-cell
    # overrides, every cell's effective band, and how impact dimensions combine.
    severity_bands: SeverityBands | None = None
    matrix_cells: dict[str, str] = Field(default_factory=dict)
    cells: list[MatrixCellBand] = Field(default_factory=list)
    impact_mode: str = "max"


class RiskMatrixConfigUpdate(BaseModel):
    size: int = Field(ge=MIN_MATRIX_SIZE, le=MAX_MATRIX_SIZE)
    likelihood_levels: list[MatrixLevel] = Field(default_factory=list)
    impact_levels: list[MatrixLevel] = Field(default_factory=list)
    # Omitted = unchanged. ``severity_bands: null`` returns to the derived bands;
    # ``matrix_cells: {}`` removes every override.
    severity_bands: SeverityBands | None = None
    matrix_cells: dict[str, str] | None = None
    impact_mode: Literal["max", "average"] | None = None


# ------------------------------------------------------- appetite per category ---
class RiskAppetiteCreate(BaseModel):
    """Appetite and tolerance for one top-level risk category."""

    category_id: uuid.UUID
    appetite_score: int = Field(ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    tolerance_score: int = Field(ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    statement: str = ""


class RiskAppetiteUpdate(BaseModel):
    appetite_score: int | None = Field(default=None, ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    tolerance_score: int | None = Field(default=None, ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    statement: str | None = None


class RiskAppetiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category_id: uuid.UUID
    category_ref: LookupRef | None = None
    appetite_score: int
    tolerance_score: int
    statement: str = ""
    created_at: datetime
    updated_at: datetime
    # Live risks under the category (and its children), and how many breach tolerance.
    risks: int = 0
    breaches: int = 0


# -------------------------------------------------------- residual engine ---
class ResidualPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    enabled: bool
    weight_effective: int
    weight_partially_effective: int
    weight_ineffective: int
    weight_not_assessed: int
    applies_to: str
    max_reduction: int


class ResidualPolicyUpdate(BaseModel):
    enabled: bool = True
    weight_effective: int = Field(ge=0, le=5)
    weight_partially_effective: int = Field(ge=0, le=5)
    weight_ineffective: int = Field(ge=0, le=5)
    weight_not_assessed: int = Field(ge=0, le=5)
    applies_to: str = Field(pattern="^(likelihood|impact|both)$")
    max_reduction: int = Field(ge=0, le=5)


class SuggestedResidual(BaseModel):
    """A proposal the risk owner may accept or override — never applied on its own."""

    likelihood: int
    impact: int
    score: int
    reduction: int
    rationale: list[str]
    inherent_score: int
    current_residual_score: int | None
    matches_current: bool
    #: The appetite band the *suggested* score would fall in for this risk's category —
    #: within_appetite | elevated | breach — judged exactly as ``RiskRead.appetite_status``
    #: judges the recorded score (B12). None when there is nothing to judge.
    appetite_status: str | None = None
    #: The linked controls whose credit the suggestion takes, in link order — empty when
    #: the suggestion equals inherent. Accepting the suggestion relies on exactly these
    #: ratings (B6), so a page lists them from here instead of re-deriving the weights.
    credited_control_ids: list[uuid.UUID] = []
    #: Whether accepting the suggestion as it stands needs ``ResidualAcceptance.note``:
    #: a credited control is rated by hand or by override, or has no reviewed test on
    #: file. The same rule ``POST /accept-residual`` enforces with a 422 (B6).
    note_required: bool = False


#: Refusal when a suggestion leans on a control rating no reviewed test supports and the
#: owner has not said why they accept it anyway (B6).
UNTESTED_CREDIT_NOTE_NEEDED = "Accepting credit from an untested control rating needs a note"


class ResidualAcceptance(BaseModel):
    """Accept the suggestion as-is, or record a different judgement with a reason.

    ``note`` is the owner's word on accepting the suggestion. It is required (422) when
    any control that earns credit is rated by hand or by override, or has no reviewed
    test on file; it is appended to the stored rationale as "; owner's note: …".
    """

    likelihood: int | None = _OptionalScale
    impact: int | None = _OptionalScale
    override_reason: str = ""
    note: str = ""


class RiskAggregateRow(BaseModel):
    category: str
    count: int
    max_inherent_score: int | None
    max_residual_score: int | None
    breaches: int
    exposure: float  # sum of annual loss expectancy


class RiskAggregate(BaseModel):
    rows: list[RiskAggregateRow]
    total_exposure: float
    appetite_score: int
    tolerance_score: int


class OrphanedRisk(BaseModel):
    """A live risk whose linked assets were all deleted and that reaches nothing else live."""

    id: uuid.UUID
    reference: str
    title: str
    category: str
    status: str
    inherent_score: int | None
    deleted_asset_names: list[str]
    # Live records still linked, per kind (``services.risk_integrity.LINK_KINDS``). Zero
    # for everything listed; shown so the reviewer can see it rather than trust it.
    live_links: dict[str, int] = Field(default_factory=dict)
    live_link_total: int = 0


class OrphanedRiskPage(BaseModel):
    items: list[OrphanedRisk]
    total: int
    # Risks whose assets were all deleted but that still link to something live, so
    # are not listed and cannot be archived from here.
    kept_with_links: int = 0


class OrphanPurgeRequest(BaseModel):
    """Archive exactly these risks, for a stated reason.

    ``risk_ids`` is required and must name at least one risk: there is no "archive every
    orphan" form. Ids that are not orphaned at purge time are skipped, never archived —
    the server re-derives the orphan set, so a stale preview cannot archive a risk that
    meanwhile gained a live link. ``reason`` is written to the audit trail on every
    archived risk.
    """

    risk_ids: list[uuid.UUID] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give a reason for archiving these risks")
        return v


class OrphanPurgeResult(BaseModel):
    archived: int
    references: list[str]
    # Requested ids left alone because they are no longer orphaned.
    skipped: int = 0
