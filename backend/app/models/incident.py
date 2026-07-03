"""Incident Management (Security Operations) — lifecycle tracking of incidents with
a configurable set of response stages (NIST IR phases)."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Column, Date, Float, ForeignKey, Integer, String, Table, Text, Uuid
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
from app.models.enums import (
    IncidentStatus,
    RegulatoryReportStatus,
    RegulatoryReportType,
    Severity,
    StageStatus,
)

# Default response stages created with each incident (NIST 800-61 phases).
DEFAULT_STAGES = ["Identification", "Containment", "Eradication", "Recovery", "Lessons Learned"]

incident_controls = Table(
    "incident_controls",
    Base.metadata,
    Column("incident_id", Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True),
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
)
incident_vendors = Table(
    "incident_vendors",
    Base.metadata,
    Column("incident_id", Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True),
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
)


class Incident(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "incidents"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="", index=True)
    classification: Mapped[str] = mapped_column(String(120), default="")
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.medium, nullable=False
    )
    status: Mapped[IncidentStatus] = mapped_column(
        SAEnum(IncidentStatus, name="incident_status"),
        default=IncidentStatus.open,
        nullable=False,
    )
    assignee: Mapped[str] = mapped_column(String(200), default="")
    reported_by: Mapped[str] = mapped_column(String(200), default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    root_cause: Mapped[str] = mapped_column(Text, default="")
    lessons_learned: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)  # financial impact
    detected_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurred_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolved_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Regulatory reporting (e.g. SBP breach notification obligations).
    is_reportable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    regulator: Mapped[str] = mapped_column(String(64), default="")

    regulatory_reports: Mapped[list["RegulatoryReport"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", lazy="selectin",
        order_by="RegulatoryReport.deadline",
    )

    stages: Mapped[list["IncidentStage"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="IncidentStage.order_index",
    )
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        "Control", secondary=incident_controls, lazy="selectin"
    )
    vendors: Mapped[list["Vendor"]] = relationship(  # noqa: F821
        "Vendor", secondary=incident_vendors, lazy="selectin"
    )
    assets: Mapped[list["Asset"]] = relationship(  # noqa: F821
        "Asset", secondary="assets_incidents", lazy="selectin", viewonly=True
    )
    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary="risk_incidents", lazy="selectin", viewonly=True
    )

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    @property
    def completed_stages(self) -> int:
        return sum(1 for s in self.stages if s.status == StageStatus.done)

    @property
    def lifecycle_complete(self) -> bool:
        return bool(self.stages) and all(s.status == StageStatus.done for s in self.stages)

    @property
    def current_stage(self) -> str | None:
        for s in self.stages:
            if s.status != StageStatus.done:
                return s.name
        return None


class IncidentStage(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "incident_stages"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[StageStatus] = mapped_column(
        SAEnum(StageStatus, name="stage_status"), default=StageStatus.pending, nullable=False
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="stages")


class RegulatoryReport(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A regulator submission tied to an incident, with an SLA deadline and status.

    Models the SBP breach-reporting chain (initial notification → final report), each
    with its own deadline computed from the incident detection date and configurable
    SLA windows.
    """

    __tablename__ = "regulatory_reports"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    regulator: Mapped[str] = mapped_column(String(64), default="SBP")
    report_type: Mapped[RegulatoryReportType] = mapped_column(
        SAEnum(RegulatoryReportType, name="regulatory_report_type"),
        default=RegulatoryReportType.initial_notification, nullable=False,
    )
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[RegulatoryReportStatus] = mapped_column(
        SAEnum(RegulatoryReportStatus, name="regulatory_report_status"),
        default=RegulatoryReportStatus.pending, nullable=False,
    )
    submitted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str] = mapped_column(String(120), default="")  # regulator acknowledgement ref
    summary: Mapped[str] = mapped_column(Text, default="")
    submitted_by: Mapped[str] = mapped_column(String(200), default="")

    incident: Mapped[Incident] = relationship(back_populates="regulatory_reports")

    @property
    def is_overdue(self) -> bool:
        return (
            self.status == RegulatoryReportStatus.pending
            and self.deadline is not None
            and self.deadline < date.today()
        )
