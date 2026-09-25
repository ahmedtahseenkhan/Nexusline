from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import WorkflowState
from app.schemas.fx import UnconvertedAmount
from app.models.enums import BaselEventType
from app.models.scenario import CapitalStatus, ScenarioStatus
from app.schemas.tenant_settings import currency_or_default


# ----------------------------------------------------------- scenario analysis ---
class ScenarioBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    basel_event_type: BaselEventType = BaselEventType.execution_delivery_process_management
    business_line: str = ""
    description: str = ""
    frequency_per_year: float = 0
    typical_loss: float = 0
    worst_case_loss: float = 0
    currency: str = "PKR"
    confidence_level: str = ""
    participants: str = ""
    assumptions: str = ""
    owner: str = ""
    status: ScenarioStatus = ScenarioStatus.draft
    review_date: date | None = None


class ScenarioCreate(ScenarioBase):
    _ccy = field_validator("currency")(currency_or_default)


class ScenarioUpdate(BaseModel):
    title: str | None = None
    basel_event_type: BaselEventType | None = None
    business_line: str | None = None
    description: str | None = None
    frequency_per_year: float | None = None
    typical_loss: float | None = None
    worst_case_loss: float | None = None
    currency: str | None = None
    confidence_level: str | None = None
    participants: str | None = None
    assumptions: str | None = None
    owner: str | None = None
    status: ScenarioStatus | None = None
    review_date: date | None = None

    _ccy = field_validator("currency")(currency_or_default)


class ScenarioRead(ScenarioBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    expected_annual_loss: float
    created_at: datetime


# --------------------------------------------------------- capital calculation ---
class CapitalBase(BaseModel):
    period: str = ""
    business_indicator: float = Field(default=0, ge=0)
    avg_annual_loss: float = Field(default=0, ge=0)
    currency: str = "PKR"
    notes: str = ""
    status: CapitalStatus = CapitalStatus.draft


class CapitalCreate(CapitalBase):
    _ccy = field_validator("currency")(currency_or_default)


class CapitalUpdate(BaseModel):
    period: str | None = None
    business_indicator: float | None = Field(default=None, ge=0)
    avg_annual_loss: float | None = Field(default=None, ge=0)
    currency: str | None = None
    notes: str | None = None
    status: CapitalStatus | None = None

    _ccy = field_validator("currency")(currency_or_default)


class CapitalRead(CapitalBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    created_at: datetime
    # Computed by ``api.v1.scenario._capital_read`` (``models.scenario.sma_capital``).
    # BIC / ILM / ORC are null when the Basel bucket edges cannot be expressed in the
    # record's currency (no exchange rate): ``threshold_note`` says what is missing.
    bucket: int | None = None
    bic: float | None = None
    loss_component: float = 0
    #: Rounded to 4 dp for display; ORC is computed from the unrounded value.
    ilm: float | None = None
    orc: float | None = None
    #: The BI bucket edges applied, in the record's currency (EUR 1bn / 30bn converted).
    bucket_1_threshold: float | None = None
    bucket_2_threshold: float | None = None
    #: How the edges were obtained, e.g. "Basel CRE25 EUR 1bn / EUR 30bn at 1 EUR = 310.5 PKR (rate of 2026-09-01)".
    threshold_basis: str = ""
    threshold_note: str = ""
    #: True once final: the figures, edges and rate above are the snapshot taken when the
    #: calculation was finalised, not today's recomputation.
    basis_frozen: bool = False
    #: Units of the record's currency per 1 EUR used for the edges (1 for EUR).
    fx_factor: float | None = None
    final_at: datetime | None = None
    final_by: str = ""
    #: Set on a calculation finalised before snapshots existed: its figures are live.
    frozen_note: str = ""


class CapitalReopen(BaseModel):
    """Why a final (filed) calculation is being put back to draft. Kept in the audit trail
    with the figures that were frozen, so the restatement is explainable to an examiner."""

    reason: str = Field(min_length=10, max_length=2000)


# ------------------------------------------------------------------ summary ---
class ScenarioSummaryRow(BaseModel):
    basel_event_type: str
    count: int
    expected_annual_loss: float


class CapitalSnapshot(BaseModel):
    reference: str
    period: str
    bucket: int | None = None
    bic: float | None = None
    loss_component: float
    ilm: float | None = None
    orc: float | None = None
    currency: str
    threshold_note: str = ""
    basis_frozen: bool = False
    final_at: datetime | None = None


class ScenarioSummary(BaseModel):
    rows: list[ScenarioSummaryRow]
    total_expected_annual_loss: float
    total_count: int
    approved_count: int
    latest_capital: CapitalSnapshot | None
    #: Decision 4: the currency the expected losses above are in (converted at today's rate).
    reporting_currency: str = "PKR"
    #: Scenarios whose currency has no exchange rate; left out of the totals.
    unconverted: list[UnconvertedAmount] = []
