"""Risk Quantification (FAIR / Monte Carlo) — PKR loss-exposure on the risk register.

Where the qualitative register scores risk on ordinal LxI scales, this module puts a
money figure on a loss scenario. A **RiskQuantification** frames the scenario with two
triangular-distributed inputs — Threat Event Frequency (events/year) and Loss Magnitude
per event (PKR) — and a Monte Carlo simulation estimates the Annualised Loss Exposure
(ALE) distribution: P10 / P50 (median) / P90 / mean / max. The last run is cached on the
record so dashboards and the loss roll-up can read it without re-simulating. Each record
optionally links back to a qualitative risk in the register.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkflowMixin,
)


# ------------------------------------------------------------------ local enums ---
class QuantStatus(str, enum.Enum):
    """Lifecycle of a quantification record (LOCAL to this module)."""

    draft = "draft"
    simulated = "simulated"
    approved = "approved"


# =========================================================== risk quantification ===
class RiskQuantification(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "risk_quantifications"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scenario: Mapped[str] = mapped_column(Text, default="")

    # OPTIONAL link to the qualitative risk register (cross-module FK by table name).
    risk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("risks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    asset_at_risk: Mapped[str] = mapped_column(String(255), default="")

    # Threat Event Frequency — events/year (triangular: min / most-likely / max).
    tef_min: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    tef_likely: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    tef_max: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)

    # Loss Magnitude per event — PKR (triangular: min / most-likely / max).
    lm_min: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    lm_likely: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    lm_max: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    iterations: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    owner: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    # Cache of the last Monte Carlo run (drives dashboards without re-simulating).
    last_mean_ale: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    last_p90: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    last_simulated: Mapped[date | None] = mapped_column(Date, nullable=True)

    status: Mapped[QuantStatus] = mapped_column(
        SAEnum(QuantStatus, name="risk_quant_status"), default=QuantStatus.draft, nullable=False
    )

    @property
    def ale_point(self) -> float:
        """Deterministic point estimate — most-likely frequency × most-likely magnitude."""
        return float(self.tef_likely or 0) * float(self.lm_likely or 0)
