from __future__ import annotations

import uuid
from datetime import date
from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_risks: int
    total_controls: int
    total_assets: int
    risks_by_status: dict[str, int]
    risks_by_inherent_severity: dict[str, int]
    risks_by_residual_severity: dict[str, int]
    overdue_reviews: int
    pending_acceptances: int
    # Risk appetite program
    appetite_score: int
    tolerance_score: int
    risks_within_appetite: int
    risks_elevated: int
    risks_in_breach: int
    total_exposure: float


# --------------------------------------------------------------------------- overview
# The redesigned dashboard's single payload. Sections follow the questions a risk
# function is judged on, in the order a board asks them: are we within appetite; are
# the controls working; are we compliant; what is overdue or needs a decision; what
# happened. Each number links back to the register that produced it.
class HealthComponent(BaseModel):
    key: str
    label: str
    value: float
    weight: float
    detail: str


class Health(BaseModel):
    score: int
    band: str
    components: list[HealthComponent]


class TopRisk(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    score: int | None
    severity: str | None
    appetite_status: str | None
    owner: str
    business_units: list[str]
    status: str
    treatment_strategy: str | None
    next_review_date: date | None
    review_overdue: bool
    control_count: int


class Posture(BaseModel):
    total_risks: int
    appetite_score: int
    tolerance_score: int
    within_appetite: int
    elevated: int
    breach: int
    by_inherent_severity: dict[str, int]
    by_residual_severity: dict[str, int]
    top_risks: list[TopRisk]


class Assurance(BaseModel):
    total: int
    effective: int
    partially_effective: int
    ineffective: int
    not_assessed: int
    tests_overdue: int
    tests_due_30d: int
    last_test_failed: int
    tests_in_period: int


class FrameworkPosture(BaseModel):
    id: uuid.UUID
    name: str
    total: int
    applicable: int
    assured: int
    unassessed: int
    failing: int
    unmapped: int
    compliant_pct: float
    gaps: int


class CompliancePosture(BaseModel):
    frameworks: list[FrameworkPosture]
    overall_assured_pct: float


class ActionItem(BaseModel):
    key: str
    label: str
    count: int
    href: str
    #: critical | warning | info — how loudly the page should say it.
    tone: str


class IncidentsPosture(BaseModel):
    open: int
    open_by_severity: dict[str, int]
    reportable_open: int
    opened_in_period: int
    opened_prior_period: int
    tat_breached: int


class KriItem(BaseModel):
    id: uuid.UUID
    reference: str
    name: str
    current_value: float | None
    warning_threshold: float | None
    limit_threshold: float | None
    unit: str
    owner: str
    status: str


class KriPosture(BaseModel):
    green: int
    amber: int
    red: int
    no_data: int
    red_items: list[KriItem]


class ThirdParties(BaseModel):
    total: int
    by_rating: dict[str, int]
    assessments_overdue: int
    critical: int


class SegmentRow(BaseModel):
    id: uuid.UUID
    name: str
    risks: int
    breach: int
    elevated: int
    critical: int


class Movement(BaseModel):
    period_days: int
    risks_created: int
    risks_closed: int
    acceptances_lapsed: int
    tests_recorded: int
    incidents_opened: int
    issues_closed: int


class DashboardOverview(BaseModel):
    as_of: date
    period_days: int
    health: Health
    posture: Posture
    assurance: Assurance
    compliance: CompliancePosture
    actions: list[ActionItem]
    incidents: IncidentsPosture
    kris: KriPosture
    third_parties: ThirdParties
    segments: list[SegmentRow]
    movement: Movement
