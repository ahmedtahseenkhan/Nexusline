from __future__ import annotations

import uuid
from datetime import date, datetime

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
    severity_for_score,
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


class RiskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    # Phase 1: the category is picked from the ``risk_category`` list. ``category`` text
    # is kept in step with it (and matched onto it when sent alone) — see services.ref_fields.
    category_id: uuid.UUID | None = None
    category: str = Field(default="", description=_LEGACY + "Matched onto a risk category.")
    status: RiskStatus = RiskStatus.draft
    inherent_likelihood: int = _Scale
    inherent_impact: int = _Scale
    # Residual scoring (after controls) — optional on create, set on assessment too
    residual_likelihood: int | None = _OptionalScale
    residual_impact: int | None = _OptionalScale
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


class RiskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category_id: uuid.UUID | None = None
    category: str | None = Field(default=None, description=_LEGACY)
    status: RiskStatus | None = None
    inherent_likelihood: int | None = _OptionalScale
    inherent_impact: int | None = _OptionalScale
    residual_likelihood: int | None = _OptionalScale
    residual_impact: int | None = _OptionalScale
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


class RiskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    title: str
    description: str
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
        """
        max_score = (info.context or {}).get("max_score", DEFAULT_MAX_SCORE)
        if self.inherent_severity is None:
            self.inherent_severity = severity_for_score(self.inherent_score, max_score)
        if self.residual_severity is None:
            self.residual_severity = severity_for_score(self.residual_score, max_score)
        return self


class RiskSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    appetite_score: int
    tolerance_score: int
    matrix_size: int = 5


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


class RiskMatrixConfig(BaseModel):
    size: int
    max_score: int
    appetite_score: int
    tolerance_score: int
    likelihood_levels: list[MatrixLevel]
    impact_levels: list[MatrixLevel]
    bands: list[MatrixBand]


class RiskMatrixConfigUpdate(BaseModel):
    size: int = Field(ge=MIN_MATRIX_SIZE, le=MAX_MATRIX_SIZE)
    likelihood_levels: list[MatrixLevel] = Field(default_factory=list)
    impact_levels: list[MatrixLevel] = Field(default_factory=list)


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
