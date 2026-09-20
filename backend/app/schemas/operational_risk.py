from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from app.schemas.common import GraphRef, LookupRef, UnitRef, UserRef
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.base import WorkflowState
from app.models.enums import (
    BaselEventType,
    ControlEffectiveness,
    KriDirection,
    KriStatus,
    LossEventStatus,
    RcsaStatus,
    ReviewFrequency,
)

# Phase 1 picker fields: each ``*_id`` wins over the legacy text field it sits beside when
# both are sent. The text is still accepted this release (older clients, CSV import) and
# is matched to an id when it names exactly one active record; on read it holds the
# picked record's display name, or the unmatched text.
_WF_OWNER = "User who owns the approval workflow. `workflow_status` changes only through the workflow endpoints."
_ACTION_OWNER = "User who owns the action; wins over `action_owner` text."
_RISK_CATEGORY = "Value from the `risk_category` lookup list; wins over `category` text."
_ASSESSOR = "User running the assessment; wins over `assessor` text."
_RCSA_UNIT = "Business unit assessed; wins over `business_unit` text."
_PROCESS = "Process assessed (GET /processes); wins over `process` text."
_KRI_OWNER = "User who owns the indicator; wins over `owner` text."
_KRI_UNIT = "Business unit the indicator measures; wins over `business_area` text."
_KRI_CATEGORY = "Value from the `kri_category` lookup list; wins over `category` text."
_LOSS_UNIT = "Business unit (line) that suffered the loss; wins over `business_line` text."
# Phase 2 (F-14): what the indicator is, where its number comes from, how it is judged.
_DEFINITION = "What the indicator measures and why it signals the risk."
_NUMERATOR = "Numerator of the formula (e.g. 'failed wire transfers in the period')."
_DENOMINATOR = "Denominator of the formula (e.g. 'wire transfers in the period'); empty for a count."
_DATA_SOURCE = "System or report the value is taken from."
_DATA_PROVIDER = "User who supplies the value each period."
_INDICATOR_TYPE = "leading (warns before the loss) or lagging (confirms it after)."
_DIRECTION = (
    "higher_is_worse: amber at/above the warning, red at/above the limit (warning < limit). "
    "lower_is_worse: amber at/below the warning, red at/below the limit (warning > limit). "
    "within_range: green inside [lower_bound, upper_bound]; amber outside it; red once the "
    "reading is `limit_threshold` (the tolerance) or more beyond the nearer bound, or as soon "
    "as it leaves the range when no tolerance is set. `warning_threshold` stays empty."
)
_LOWER = "within_range only: lowest acceptable value (required, below upper_bound)."
_UPPER = "within_range only: highest acceptable value (required, above lower_bound)."
_WARNING = "Amber threshold (not used for within_range)."
_LIMIT = "Red threshold; for within_range, the tolerance beyond the range before it turns red."
_APPETITE = "Risk appetite (GET /risk-appetites) this indicator measures."
IndicatorType = Literal["leading", "lagging"]
EscalationLevel = Literal["amber", "red"]


# ------------------------------------------------------------- RCSA risk lines ---
class RcsaRiskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    category: str = ""
    category_id: uuid.UUID | None = Field(default=None, description=_RISK_CATEGORY)
    inherent_likelihood: int = Field(default=1, ge=1, le=5)
    inherent_impact: int = Field(default=1, ge=1, le=5)
    control_description: str = ""
    control_effectiveness: ControlEffectiveness = ControlEffectiveness.not_assessed
    residual_likelihood: int = Field(default=1, ge=1, le=5)
    residual_impact: int = Field(default=1, ge=1, le=5)
    action: str = ""
    action_owner: str = ""
    action_owner_id: uuid.UUID | None = Field(default=None, description=_ACTION_OWNER)
    due_date: date | None = None


class RcsaRiskCreate(RcsaRiskBase):
    risk_id: uuid.UUID | None = None
    control_id: uuid.UUID | None = None


class RcsaRiskUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = Field(default=None, description=_RISK_CATEGORY)
    inherent_likelihood: int | None = Field(default=None, ge=1, le=5)
    inherent_impact: int | None = Field(default=None, ge=1, le=5)
    control_description: str | None = None
    control_effectiveness: ControlEffectiveness | None = None
    residual_likelihood: int | None = Field(default=None, ge=1, le=5)
    residual_impact: int | None = Field(default=None, ge=1, le=5)
    action: str | None = None
    action_owner: str | None = None
    action_owner_id: uuid.UUID | None = Field(default=None, description=_ACTION_OWNER)
    due_date: date | None = None
    risk_id: uuid.UUID | None = None
    control_id: uuid.UUID | None = None


class RcsaRiskRead(RcsaRiskBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    assessment_id: uuid.UUID
    inherent_score: int
    residual_score: int
    risk_id: uuid.UUID | None = None
    control_id: uuid.UUID | None = None
    risk: GraphRef | None = None
    control: GraphRef | None = None
    category_ref: LookupRef | None = None
    action_owner_ref: UserRef | None = None
    created_at: datetime
    # Phase 4E: self-ratings from a reviewed control self-assessment questionnaire.
    self_design_rating: str | None = None
    self_operation_rating: str | None = None
    self_assessment_id: uuid.UUID | None = None


# --------------------------------------------------------------- RCSA campaigns ---
class RcsaBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    business_unit: str = ""
    business_unit_id: uuid.UUID | None = Field(default=None, description=_RCSA_UNIT)
    process: str = ""
    process_id: uuid.UUID | None = Field(default=None, description=_PROCESS)
    assessor: str = ""
    assessor_id: uuid.UUID | None = Field(default=None, description=_ASSESSOR)
    status: RcsaStatus = RcsaStatus.planned
    period: str = ""
    due_date: date | None = None
    completed_date: date | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class RcsaCreate(RcsaBase):
    pass


class RcsaUpdate(BaseModel):
    title: str | None = None
    business_unit: str | None = None
    business_unit_id: uuid.UUID | None = Field(default=None, description=_RCSA_UNIT)
    process: str | None = None
    process_id: uuid.UUID | None = Field(default=None, description=_PROCESS)
    assessor: str | None = None
    assessor_id: uuid.UUID | None = Field(default=None, description=_ASSESSOR)
    status: RcsaStatus | None = None
    period: str | None = None
    due_date: date | None = None
    completed_date: date | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class RcsaRead(RcsaBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    business_unit_ref: UnitRef | None = None
    process_ref: UnitRef | None = None
    assessor_ref: UserRef | None = None
    workflow_owner_ref: UserRef | None = None
    risk_count: int
    is_overdue: bool
    created_at: datetime
    risks: list[RcsaRiskRead] = []


# --------------------------------------------------------------- KRI measurements ---
class MeasurementCreate(BaseModel):
    value: float
    as_of_date: date | None = Field(default=None, description="Defaults to today; may not be in the future.")
    notes: str = ""


class MeasurementFeed(BaseModel):
    """One reading posted by an integration with the KRI's feed token."""

    value: float
    as_of_date: date | None = Field(default=None, description="Defaults to today; may not be in the future.")
    notes: str = Field(default="", max_length=2000)


class FeedTokenIssued(BaseModel):
    """Returned once when a feed token is generated; only its SHA-256 is stored."""

    kri_id: uuid.UUID
    token: str
    endpoint: str
    header: str
    note: str


class FeedResult(BaseModel):
    """What the feed endpoint tells an integration: no names, emails or history."""

    kri_id: uuid.UUID
    reference: str
    measurement_id: uuid.UUID
    status: KriStatus
    current_value: float | None
    last_measured_date: date | None
    escalated: EscalationLevel | None = None


# ------------------------------------------------------------------ KRI escalations ---
_ESC_TO = "User told when the KRI reaches this level."
_ESC_ROLE = "Role told when the KRI reaches this level (a role name, e.g. 'CRO')."
_ESC_ACTION = "What the person or role must do."


class KriEscalationCreate(BaseModel):
    level: EscalationLevel
    escalate_to_id: uuid.UUID | None = Field(default=None, description=_ESC_TO)
    escalate_to_role: str = Field(default="", max_length=64, description=_ESC_ROLE)
    action: str = Field(min_length=1, max_length=4000, description=_ESC_ACTION)

    @model_validator(mode="after")
    def _someone(self):
        if self.escalate_to_id is None and not self.escalate_to_role.strip():
            raise ValueError("Name a person (escalate_to_id) or a role (escalate_to_role) to escalate to.")
        if not self.action.strip():
            raise ValueError("action: say what must be done when the KRI reaches this level.")
        return self


class KriEscalationUpdate(BaseModel):
    level: EscalationLevel | None = None
    escalate_to_id: uuid.UUID | None = Field(default=None, description=_ESC_TO)
    escalate_to_role: str | None = Field(default=None, max_length=64, description=_ESC_ROLE)
    action: str | None = Field(default=None, max_length=4000, description=_ESC_ACTION)


class KriEscalationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kri_id: uuid.UUID
    level: str
    escalate_to_id: uuid.UUID | None = None
    escalate_to_ref: UserRef | None = None
    escalate_to_role: str = ""
    action: str = ""
    created_at: datetime


class KriAppetiteRef(BaseModel):
    """The risk appetite a KRI measures, with its category's label."""

    id: uuid.UUID
    category_id: uuid.UUID
    category_label: str = ""
    appetite_score: int
    tolerance_score: int
    statement: str = ""


class MeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    value: float
    as_of_date: date | None
    notes: str
    created_at: datetime


# ------------------------------------------------------------------------- KRIs ---
class KriBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    category: str = ""
    category_id: uuid.UUID | None = Field(default=None, description=_KRI_CATEGORY)
    business_area: str = ""
    business_unit_id: uuid.UUID | None = Field(default=None, description=_KRI_UNIT)
    owner: str = ""
    owner_id: uuid.UUID | None = Field(default=None, description=_KRI_OWNER)
    unit: str = ""
    frequency: ReviewFrequency = ReviewFrequency.monthly
    direction: KriDirection = Field(default=KriDirection.higher_is_worse, description=_DIRECTION)
    warning_threshold: float | None = Field(default=None, description=_WARNING)
    limit_threshold: float | None = Field(default=None, description=_LIMIT)
    lower_bound: float | None = Field(default=None, description=_LOWER)
    upper_bound: float | None = Field(default=None, description=_UPPER)
    current_value: float | None = None
    last_measured_date: date | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    definition: str = Field(default="", description=_DEFINITION)
    numerator: str = Field(default="", description=_NUMERATOR)
    denominator: str = Field(default="", description=_DENOMINATOR)
    data_source: str = Field(default="", description=_DATA_SOURCE)
    data_provider_id: uuid.UUID | None = Field(default=None, description=_DATA_PROVIDER)
    indicator_type: IndicatorType | None = Field(default=None, description=_INDICATOR_TYPE)
    appetite_id: uuid.UUID | None = Field(default=None, description=_APPETITE)


class KriCreate(KriBase):
    risk_ids: list[uuid.UUID] = []


class KriUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = Field(default=None, description=_KRI_CATEGORY)
    business_area: str | None = None
    business_unit_id: uuid.UUID | None = Field(default=None, description=_KRI_UNIT)
    owner: str | None = None
    owner_id: uuid.UUID | None = Field(default=None, description=_KRI_OWNER)
    unit: str | None = None
    frequency: ReviewFrequency | None = None
    direction: KriDirection | None = Field(default=None, description=_DIRECTION)
    warning_threshold: float | None = Field(default=None, description=_WARNING)
    limit_threshold: float | None = Field(default=None, description=_LIMIT)
    lower_bound: float | None = Field(default=None, description=_LOWER)
    upper_bound: float | None = Field(default=None, description=_UPPER)
    current_value: float | None = None
    last_measured_date: date | None = None
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    definition: str | None = Field(default=None, description=_DEFINITION)
    numerator: str | None = Field(default=None, description=_NUMERATOR)
    denominator: str | None = Field(default=None, description=_DENOMINATOR)
    data_source: str | None = Field(default=None, description=_DATA_SOURCE)
    data_provider_id: uuid.UUID | None = Field(default=None, description=_DATA_PROVIDER)
    indicator_type: IndicatorType | None = Field(default=None, description=_INDICATOR_TYPE)
    appetite_id: uuid.UUID | None = Field(default=None, description=_APPETITE)
    risk_ids: list[uuid.UUID] | None = None


class KriRead(KriBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    owner_ref: UserRef | None = None
    business_unit_ref: UnitRef | None = None
    category_ref: LookupRef | None = None
    workflow_owner_ref: UserRef | None = None
    data_provider_ref: UserRef | None = None
    appetite_ref: KriAppetiteRef | None = None
    status: KriStatus
    is_breached: bool
    has_feed_token: bool = False
    created_at: datetime
    risks: list[GraphRef] = []
    measurements: list[MeasurementRead] = []
    escalations: list[KriEscalationRead] = []


# ------------------------------------------------------------------ loss events ---
_BASEL_L2 = (
    "Basel II level-2 event category (GET /loss-events-taxonomy); must belong to "
    "`basel_event_type`. Blank = not categorised at level 2."
)
_LOSS_CURRENCY = (
    "ISO 4217 code of the amounts; blank = the organisation's reporting currency. Totals convert "
    "at the accounting date (else discovery, else occurrence)."
)


def _loss_currency(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return ""
    from app.schemas.tenant_settings import validate_currency

    return validate_currency(text)


class LossEventBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    basel_event_type: BaselEventType = BaselEventType.execution_delivery_process_management
    basel_event_type_l2: str = Field(default="", max_length=64, description=_BASEL_L2)
    business_line: str = ""
    business_unit_id: uuid.UUID | None = Field(default=None, description=_LOSS_UNIT)
    gross_loss: float = 0
    recovery: float = 0
    currency: str = Field(default="", description=_LOSS_CURRENCY)
    status: LossEventStatus = LossEventStatus.open
    occurrence_date: date | None = None
    discovery_date: date | None = None
    accounting_date: date | None = None
    root_cause: str = ""
    action_owner: str = ""
    action_owner_id: uuid.UUID | None = Field(default=None, description=_ACTION_OWNER)
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)


class LossEventCreate(LossEventBase):
    incident_id: uuid.UUID | None = None
    risk_ids: list[uuid.UUID] = []

    _ccy = field_validator("currency")(_loss_currency)

    @model_validator(mode="after")
    def _l2_under_l1(self):
        from app.models.operational_risk import basel_l2_error

        self.basel_event_type_l2 = (self.basel_event_type_l2 or "").strip()
        error = basel_l2_error(self.basel_event_type, self.basel_event_type_l2)
        if error:
            raise ValueError(error)
        return self


class LossEventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    basel_event_type: BaselEventType | None = None
    basel_event_type_l2: str | None = Field(default=None, max_length=64, description=_BASEL_L2)
    business_line: str | None = None
    business_unit_id: uuid.UUID | None = Field(default=None, description=_LOSS_UNIT)
    gross_loss: float | None = None
    recovery: float | None = None
    currency: str | None = Field(default=None, description=_LOSS_CURRENCY)
    status: LossEventStatus | None = None
    occurrence_date: date | None = None
    discovery_date: date | None = None
    accounting_date: date | None = None
    root_cause: str | None = None
    action_owner: str | None = None
    action_owner_id: uuid.UUID | None = Field(default=None, description=_ACTION_OWNER)
    workflow_owner_id: uuid.UUID | None = Field(default=None, description=_WF_OWNER)
    incident_id: uuid.UUID | None = None
    risk_ids: list[uuid.UUID] | None = None

    _ccy = field_validator("currency")(_loss_currency)


class LossEventRead(LossEventBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    workflow_status: WorkflowState = WorkflowState.draft
    workflow_owner: str = ""
    business_unit_ref: UnitRef | None = None
    action_owner_ref: UserRef | None = None
    workflow_owner_ref: UserRef | None = None
    net_loss: float
    incident_id: uuid.UUID | None = None
    incident: GraphRef | None = None
    risks: list[GraphRef] = []
    created_at: datetime
