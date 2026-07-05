"""Scenario Analysis + Basel SMA operational-risk capital.

Completes the Basel operational-risk suite (RCSA / KRI / loss database already
exist). Two record types:

* **ScenarioAnalysis** — forward-looking op-risk scenarios workshopped by the
  business. Each carries an estimated frequency and typical / worst-case loss,
  categorised by Basel event type. ``expected_annual_loss`` = frequency × typical
  loss is the headline figure used for scenario-based capital add-ons.
* **CapitalCalculation** — the Basel III **Standardised Approach (SMA)** for
  operational-risk capital. From the Business Indicator (BI) and the 10-year
  average internal losses it derives the Business Indicator Component (BIC),
  Loss Component (LC), Internal Loss Multiplier (ILM) and, finally, the
  Operational Risk Capital (ORC) — all as computed properties.
"""
from __future__ import annotations

import enum
import math
from datetime import date

from sqlalchemy import Date, Numeric, String, Text
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
from app.models.enums import BaselEventType


# ------------------------------------------------------------- local enums ---
class ScenarioStatus(str, enum.Enum):
    """Scenario workshop lifecycle."""

    draft = "draft"
    workshopped = "workshopped"
    approved = "approved"
    closed = "closed"


class CapitalStatus(str, enum.Enum):
    """Standardised-Approach capital calculation lifecycle."""

    draft = "draft"
    final = "final"


# Basel SMA bucket edges (PKR). Marginal coefficients apply per bucket.
_BI_BUCKET_1 = 8_000_000_000.0     # up to 8bn  → 12%
_BI_BUCKET_2 = 240_000_000_000.0   # 8bn–240bn  → 15% (marginal); above → 18%


# ======================================================= scenario analysis ===
class ScenarioAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A forward-looking operational-risk scenario, Basel event-type categorised."""

    __tablename__ = "scenario_analyses"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    basel_event_type: Mapped[BaselEventType] = mapped_column(
        SAEnum(BaselEventType, name="basel_event_type"),
        default=BaselEventType.execution_delivery_process_management, nullable=False,
    )
    business_line: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    frequency_per_year: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    typical_loss: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    worst_case_loss: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")

    confidence_level: Mapped[str] = mapped_column(String(64), default="")
    participants: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(200), default="")

    status: Mapped[ScenarioStatus] = mapped_column(
        SAEnum(ScenarioStatus, name="scenario_status"),
        default=ScenarioStatus.draft, nullable=False,
    )
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def expected_annual_loss(self) -> float:
        return round(float(self.frequency_per_year or 0) * float(self.typical_loss or 0), 2)


# ===================================================== SMA capital charge ===
class CapitalCalculation(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """Basel III Standardised Approach (SMA) operational-risk capital calculation."""

    __tablename__ = "capital_calculations"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    period: Mapped[str] = mapped_column(String(64), default="", index=True)  # e.g. "FY2026"
    business_indicator: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)  # BI
    avg_annual_loss: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)     # 10-yr avg losses
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[CapitalStatus] = mapped_column(
        SAEnum(CapitalStatus, name="capital_calc_status"),
        default=CapitalStatus.draft, nullable=False,
    )

    @property
    def bic(self) -> float:
        """Business Indicator Component — marginal buckets 12% / 15% / 18%."""
        bi = float(self.business_indicator or 0)
        if bi <= 0:
            return 0.0
        if bi <= _BI_BUCKET_1:
            comp = 0.12 * bi
        elif bi <= _BI_BUCKET_2:
            comp = 0.12 * _BI_BUCKET_1 + 0.15 * (bi - _BI_BUCKET_1)
        else:
            comp = (0.12 * _BI_BUCKET_1
                    + 0.15 * (_BI_BUCKET_2 - _BI_BUCKET_1)
                    + 0.18 * (bi - _BI_BUCKET_2))
        return round(comp, 2)

    @property
    def loss_component(self) -> float:
        """Loss Component = 15 × average annual internal losses."""
        return round(15.0 * float(self.avg_annual_loss or 0), 2)

    @property
    def ilm(self) -> float:
        """Internal Loss Multiplier = ln(e − 1 + (LC / BIC) ** 0.8); 1.0 when BIC ≤ 0."""
        bic = self.bic
        if bic <= 0:
            return 1.0
        return round(math.log(math.e - 1 + (self.loss_component / bic) ** 0.8), 2)

    @property
    def orc(self) -> float:
        """Operational Risk Capital = BIC × ILM."""
        return round(self.bic * self.ilm, 2)
