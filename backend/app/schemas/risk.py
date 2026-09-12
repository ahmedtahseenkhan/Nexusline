from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.models.base import WorkflowState
from app.schemas.common import GraphRef, LookupRef, UserRef
from app.models.enums import (
    AcceptanceStatus,
    ReviewFrequency,
    RiskStatus,
    Severity,
    TreatmentStrategy,
)
from app.schemas.asset import AssetRef
from app.schemas.control import ControlRef
from app.schemas.threat import NamedRef
from app.services.risk_scoring import (
    DEFAULT_MAX_SCORE,
    MAX_MATRIX_SIZE,
    MIN_MATRIX_SIZE,
    SeverityScale,
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
    controls: list[ControlRef] = []
    threats: list[NamedRef] = []
    vulnerabilities: list[NamedRef] = []
    policies: list[RiskLinkRef] = []
    incidents: list[RiskLinkRef] = []
    acceptances: list[RiskAcceptanceRead] = []

    # Reverse links — records elsewhere that point at this risk (read-only).
    requirements: list[GraphRef] = []
    exceptions: list[GraphRef] = []
    vendors: list[GraphRef] = []
    projects: list[GraphRef] = []
    goals: list[GraphRef] = []
    processing_activities: list[GraphRef] = []
    audit_findings: list[GraphRef] = []
    kris: list[GraphRef] = []
    loss_events: list[GraphRef] = []
    # Live issues raised against this risk (issue_risks).
    issues: list[GraphRef] = []

    # Live rollup: health of the mitigating controls (none | ok | issues).
    control_health: str = "none"

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
        scale = ctx.get("scale") or SeverityScale(max_score=ctx.get("max_score", DEFAULT_MAX_SCORE))
        if self.inherent_severity is None:
            self.inherent_severity = scale.for_cell(self.inherent_likelihood, self.inherent_impact)
        if self.residual_severity is None:
            self.residual_severity = scale.for_cell(self.residual_likelihood, self.residual_impact)
        if self.target_likelihood and self.target_impact:
            if self.target_score is None:
                self.target_score = self.target_likelihood * self.target_impact
            if self.target_severity is None:
                self.target_severity = scale.for_cell(self.target_likelihood, self.target_impact)
        book = ctx.get("appetite")
        if book is not None and self.tolerance_score is None:
            self.appetite_score, self.tolerance_score = book.thresholds(self.category_id)
            self.appetite_category_id = book.source_of(self.category_id)
            self.appetite_status = book.status(
                self.residual_score if self.residual_score is not None else self.inherent_score,
                self.category_id,
            )
        return self


class RiskSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    appetite_score: int
    tolerance_score: int
    matrix_size: int = 5
    impact_mode: str = "max"


class RiskSettingUpdate(BaseModel):
    # Upper bound is the largest score the widest configurable matrix can produce. A
    # value above the tenant's own matrix maximum is rejected in the API, where the size
    # is known.
    appetite_score: int = Field(ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)
    tolerance_score: int = Field(ge=1, le=MAX_MATRIX_SIZE * MAX_MATRIX_SIZE)


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


class ResidualAcceptance(BaseModel):
    """Accept the suggestion as-is, or record a different judgement with a reason."""

    likelihood: int | None = _OptionalScale
    impact: int | None = _OptionalScale
    override_reason: str = ""


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
