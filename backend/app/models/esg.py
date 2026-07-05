"""ESG / Green Banking — SBP Green Banking Guidelines alignment for Pakistani banks.

* **EsgAssessment** — an ESG metric/target tracked against the SBP Green Banking
  Guidelines, split across the environmental / social / governance pillars with a
  target vs current value and an achievement status.
* **EnvironmentalRiskRating** — an environmental risk rating for a credit or vendor
  exposure (a borrower / client / vendor), the E-risk register that feeds the
  environmental due-diligence expected under SBP's green banking regime.
"""
from __future__ import annotations

import enum
from datetime import date

from sqlalchemy import Date, String, Text
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


# ================================================================= enums ===
class EsgPillar(str, enum.Enum):
    """The three ESG pillars."""

    environmental = "environmental"
    social = "social"
    governance = "governance"


class EsgStatus(str, enum.Enum):
    """Achievement status of an ESG metric against its target."""

    not_started = "not_started"
    in_progress = "in_progress"
    achieved = "achieved"
    off_track = "off_track"


class EnvRiskCategory(str, enum.Enum):
    """Environmental risk category for a credit / vendor exposure."""

    high = "high"
    medium = "medium"
    low = "low"


# ====================================================== ESG assessments ===
class EsgAssessment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """An ESG metric/target tracked against the SBP Green Banking Guidelines."""

    __tablename__ = "esg_assessments"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    pillar: Mapped[EsgPillar] = mapped_column(
        SAEnum(EsgPillar, name="esg_pillar"), default=EsgPillar.environmental, nullable=False
    )
    category: Mapped[str] = mapped_column(String(120), default="")  # climate risk, green financing…
    metric: Mapped[str] = mapped_column(String(200), default="")
    target_value: Mapped[str] = mapped_column(String(120), default="")
    current_value: Mapped[str] = mapped_column(String(120), default="")
    unit: Mapped[str] = mapped_column(String(32), default="")  # %, PKR mn, count…
    status: Mapped[EsgStatus] = mapped_column(
        SAEnum(EsgStatus, name="esg_status"), default=EsgStatus.not_started, nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    period: Mapped[str] = mapped_column(String(64), default="")
    sbp_green_banking_ref: Mapped[str] = mapped_column(String(120), default="")

    @property
    def progress_note(self) -> str:
        return {
            EsgStatus.not_started: "Not started",
            EsgStatus.in_progress: "In progress",
            EsgStatus.achieved: "Target achieved",
            EsgStatus.off_track: "Off track — needs attention",
        }.get(self.status, "")


# =============================================== environmental risk ratings ===
class EnvironmentalRiskRating(TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, SoftDeleteMixin, Base):
    """Environmental risk rating for a borrower / client / vendor exposure."""

    __tablename__ = "environmental_risk_ratings"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    entity_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sector: Mapped[str] = mapped_column(String(200), default="")
    risk_category: Mapped[EnvRiskCategory] = mapped_column(
        SAEnum(EnvRiskCategory, name="esg_env_risk"), default=EnvRiskCategory.low, nullable=False
    )
    assessment: Mapped[str] = mapped_column(Text, default="")
    mitigation: Mapped[str] = mapped_column(Text, default="")
    rating_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assessor: Mapped[str] = mapped_column(String(200), default="")
