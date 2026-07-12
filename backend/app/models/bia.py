"""Business Impact Analysis (BIA) — the BCP-driving assessment banks run per process.

* **BiaAssessment** — a per-business-process impact analysis: criticality, recovery
  objectives (RTO/RPO/MTPD), quantified financial/operational/reputational/regulatory/
  legal impacts of disruption, minimum resources, and the recovery strategy. Feeds
  business continuity planning (ETGRM / SBP BCP expectations).
* **BiaDependency** — the resources a process depends on (applications, IT & information
  assets, vendors, people, facilities, upstream processes, utilities), each optionally
  flagged as a single point of failure.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkflowMixin,
)
from app.models.enums import Criticality


# ================================================================ local enums ===
class BiaStatus(str, enum.Enum):
    """Business Impact Analysis record lifecycle."""

    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    retired = "retired"


class DependencyType(str, enum.Enum):
    """The kind of resource a process depends on to operate."""

    application = "application"
    it_asset = "it_asset"
    information_asset = "information_asset"
    vendor = "vendor"
    people = "people"
    facility = "facility"
    upstream_process = "upstream_process"
    utility = "utility"


# =========================================================== BIA assessments ===
class BiaAssessment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A per-business-process Business Impact Analysis."""

    __tablename__ = "bia_assessments"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    process_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Optional link to the real business process (process_name kept as fallback/label).
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("processes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    process: Mapped["Process | None"] = relationship("Process", lazy="selectin")  # noqa: F821
    business_unit: Mapped[str] = mapped_column(String(200), default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    criticality: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )

    # Recovery objectives (hours).
    rto_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Recovery Time Objective
    rpo_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Recovery Point Objective
    mtpd_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Maximum Tolerable Period of Disruption
    peak_periods: Mapped[str] = mapped_column(Text, default="")  # e.g. "month-end, Eid, salary days"

    # Quantified financial impact of disruption.
    financial_impact_24h: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    financial_impact_1week: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")

    # Qualitative impacts.
    operational_impact: Mapped[str] = mapped_column(Text, default="")
    reputational_impact: Mapped[str] = mapped_column(Text, default="")
    regulatory_impact: Mapped[str] = mapped_column(Text, default="")
    legal_impact: Mapped[str] = mapped_column(Text, default="")

    # Recovery.
    minimum_resources: Mapped[str] = mapped_column(Text, default="")
    recovery_strategy: Mapped[str] = mapped_column(Text, default="")
    workaround: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[BiaStatus] = mapped_column(
        SAEnum(BiaStatus, name="bia_status"), default=BiaStatus.draft, nullable=False
    )
    assessment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    dependencies: Mapped[list["BiaDependency"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", lazy="selectin",
        order_by="BiaDependency.created_at",
    )

    @property
    def dependency_count(self) -> int:
        return len(self.dependencies)

    @property
    def is_review_overdue(self) -> bool:
        return self.next_review_date is not None and self.next_review_date < date.today()

    @property
    def rto_band(self) -> str:
        if self.rto_hours is None:
            return "n/a"
        h = self.rto_hours
        if h < 4:
            return "<4h"
        if h < 24:
            return "<24h"
        if h < 72:
            return "<72h"
        return ">72h"


class BiaDependency(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single resource dependency of a business process assessed in a BIA."""

    __tablename__ = "bia_dependencies"

    bia_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bia_assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dependency_type: Mapped[DependencyType] = mapped_column(
        SAEnum(DependencyType, name="bia_dependency_type"),
        default=DependencyType.application, nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional links to the real asset / vendor this dependency refers to (name = fallback).
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    asset: Mapped["Asset | None"] = relationship("Asset", lazy="selectin")  # noqa: F821
    vendor: Mapped["Vendor | None"] = relationship("Vendor", lazy="selectin")  # noqa: F821
    description: Mapped[str] = mapped_column(Text, default="")
    criticality: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    rto_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    single_point_of_failure: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    assessment: Mapped[BiaAssessment] = relationship(back_populates="dependencies")
