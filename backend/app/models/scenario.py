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
  Operational Risk Capital (ORC) — computed by :func:`sma_capital`, never stored.

The BI bucket edges are set by Basel (CRE25) in **euro**: EUR 1bn and EUR 30bn. A
record in any other currency is bucketed against those edges converted into its
currency at the organisation's own exchange rates (``api.v1.scenario``), the way
jurisdictions that adopted the SMA restate them in local currency. Hard-coding a
local-currency figure silently mis-buckets every record kept in another currency.

A calculation marked **final** is a filed figure: the exchange rate, bucket edges and
results it used are frozen onto the record (the ``final_*`` columns) at that moment, so
a later rate change never restates capital already reported to the regulator. Going
back to draft is an explicit, reasoned, audited reopen.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text
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


# Basel SMA bucket edges (CRE25.4), in euro. Marginal coefficients apply per bucket:
# BI up to EUR 1bn → 12%; EUR 1bn–30bn → 15%; above EUR 30bn → 18%.
BASEL_THRESHOLD_CURRENCY = "EUR"
BASEL_BI_BUCKET_1 = 1_000_000_000.0
BASEL_BI_BUCKET_2 = 30_000_000_000.0


@dataclass(frozen=True)
class SmaResult:
    """One SMA calculation. ``ilm`` and ``orc`` keep full precision; round for display."""

    bucket: int
    bic: float
    loss_component: float
    ilm: float
    orc: float


def sma_capital(
    business_indicator: float, avg_annual_loss: float, bucket_1: float, bucket_2: float
) -> SmaResult:
    """Basel III SMA operational-risk capital (CRE25) for BI and the 10-year average
    annual loss, with the BI bucket edges already expressed in the record's currency.

    * BIC = 12% of BI up to ``bucket_1``, 15% of the part up to ``bucket_2``, 18% above.
    * LC = 15 × average annual internal losses.
    * ILM = ln(e − 1 + (LC / BIC) ^ 0.8) — but **1 for a bucket-1 bank** (CRE25.9):
      below the first edge internal loss experience does not move the charge.
    * ORC = BIC × ILM, from the unrounded ILM.
    """
    bi = max(float(business_indicator or 0), 0.0)
    lc = 15.0 * max(float(avg_annual_loss or 0), 0.0)
    if bi <= bucket_1:
        bucket, bic = 1, 0.12 * bi
    elif bi <= bucket_2:
        bucket, bic = 2, 0.12 * bucket_1 + 0.15 * (bi - bucket_1)
    else:
        bucket = 3
        bic = 0.12 * bucket_1 + 0.15 * (bucket_2 - bucket_1) + 0.18 * (bi - bucket_2)
    if bucket == 1 or bic <= 0:
        ilm = 1.0
    else:
        ilm = math.log(math.e - 1 + (lc / bic) ** 0.8)
    return SmaResult(bucket=bucket, bic=bic, loss_component=lc, ilm=ilm, orc=bic * ilm)


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
    # BIC / LC / ILM / ORC depend on the bucket edges in this record's currency, which
    # need the organisation's exchange rates: ``api.v1.scenario._capital_read`` computes
    # them with :func:`sma_capital` — live while draft, from the snapshot below once final.

    # Frozen basis, stamped when the calculation becomes final and cleared on reopen.
    # ``final_fx_factor`` is units of this record's currency per 1 EUR (1 for EUR).
    final_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    final_fx_factor: Mapped[float | None] = mapped_column(Numeric(24, 10), nullable=True)
    final_bucket_1: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)
    final_bucket_2: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)
    final_basis: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    final_bucket: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_bic: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)
    final_loss_component: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)
    final_ilm: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    final_orc: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)
