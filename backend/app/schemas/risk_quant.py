from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.base import WorkflowState
from app.models.risk_quant import QuantStatus


# ----------------------------------------------------------- input rules ---
#: The inputs a Monte Carlo run is computed from: changing any of them makes the cached
#: result describe a different scenario (``api.v1.risk_quant.update_quantification``).
SIMULATION_INPUTS: tuple[str, ...] = (
    "tef_min", "tef_likely", "tef_max", "lm_min", "lm_likely", "lm_max", "currency", "iterations",
)

_RANGES = (
    ("tef", "Threat event frequency", "events/year"),
    ("lm", "Loss magnitude", "per event"),
)


def range_problem(values: dict) -> str | None:
    """Why a set of estimates cannot describe a triangular distribution, or None.

    Each estimate is a three-point range (FAIR / Open FAIR calibrated estimates): no
    value may be negative and minimum <= most likely <= maximum. ``values`` holds the
    six ``tef_*`` / ``lm_*`` fields (the resulting state, for a partial update).
    """
    for prefix, label, unit in _RANGES:
        low, mode, high = (float(values.get(f"{prefix}_{k}") or 0) for k in ("min", "likely", "max"))
        if min(low, mode, high) < 0:
            return f"{label} cannot be negative."
        if not low <= mode <= high:
            return (
                f"{label} ({unit}) must satisfy minimum <= most likely <= maximum; "
                f"got {low:g} / {mode:g} / {high:g}."
            )
    return None


# ----------------------------------------------------------- risk quantification ---
class RiskQuantBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    scenario: str = ""
    risk_id: uuid.UUID | None = None
    asset_at_risk: str = ""
    tef_min: float = 0
    tef_likely: float = 0
    tef_max: float = 0
    lm_min: float = 0
    lm_likely: float = 0
    lm_max: float = 0
    currency: str = "PKR"
    iterations: int = Field(default=10000, ge=100, le=1_000_000)
    owner: str = ""
    notes: str = ""
    status: QuantStatus = QuantStatus.draft


class RiskQuantCreate(RiskQuantBase):
    @model_validator(mode="after")
    def _ranges(self) -> "RiskQuantCreate":
        problem = range_problem(self.model_dump())
        if problem:
            raise ValueError(problem)
        return self


class RiskQuantUpdate(BaseModel):
    title: str | None = None
    scenario: str | None = None
    risk_id: uuid.UUID | None = None
    asset_at_risk: str | None = None
    tef_min: float | None = None
    tef_likely: float | None = None
    tef_max: float | None = None
    lm_min: float | None = None
    lm_likely: float | None = None
    lm_max: float | None = None
    currency: str | None = None
    iterations: int | None = Field(default=None, ge=100, le=1_000_000)
    owner: str | None = None
    notes: str | None = None
    status: QuantStatus | None = None


class RiskQuantRead(RiskQuantBase):
    # Read-only here: moved by the lifecycle service (services/record_workflow.py).
    workflow_status: WorkflowState
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    ale_point: float
    last_mean_ale: float
    last_p90: float
    last_simulated: date | None
    #: True when there is no simulation of the current inputs (never run, or an input
    #: changed since the last run and cleared it): the figures above are empty.
    needs_simulation: bool = True
    created_at: datetime


# ------------------------------------------------------------- monte carlo result ---
class SimulationResult(BaseModel):
    p10: float
    p50: float
    p90: float
    mean: float
    max: float
    iterations: int
