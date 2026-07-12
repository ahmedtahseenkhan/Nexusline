"""Third-Party / Vendor Risk — vendor registry, service contracts, a review cycle and
links to the risks they introduce and assets/data they touch. Vendor self-assessment
questionnaires live in the assessments module. Carries the eramba record envelope."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Column, Date, Float, ForeignKey, String, Table, Text, Uuid
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
from app.models.enums import AssessmentStatus, Criticality, ReviewFrequency, Severity, VendorStatus

vendor_risks = Table(
    "vendor_risks",
    Base.metadata,
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)
vendor_assets = Table(
    "vendor_assets",
    Base.metadata,
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)


class VendorType(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Third-party type taxonomy (e.g. Cloud Provider, Processor, Supplier)."""

    __tablename__ = "vendor_types"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")


class Vendor(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="", index=True)
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vendor_types.id", ondelete="SET NULL"), nullable=True
    )

    # Contacts
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    contact_phone: Mapped[str] = mapped_column(String(60), default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(200), default="")

    criticality: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    status: Mapped[VendorStatus] = mapped_column(
        SAEnum(VendorStatus, name="vendor_status"), default=VendorStatus.active, nullable=False
    )
    risk_rating: Mapped[Severity | None] = mapped_column(SAEnum(Severity, name="severity"), nullable=True)
    shares_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    assessment_status: Mapped[AssessmentStatus] = mapped_column(
        SAEnum(AssessmentStatus, name="assessment_status"),
        default=AssessmentStatus.not_started,
        nullable=False,
    )
    last_assessed_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Lifecycle / review
    onboarded_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    offboarded_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"), default=ReviewFrequency.annual, nullable=False
    )
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    type: Mapped["VendorType | None"] = relationship(lazy="selectin")
    contracts: Mapped[list["ServiceContract"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan", lazy="selectin",
        order_by="ServiceContract.start_date.desc()",
    )
    risks: Mapped[list["Risk"]] = relationship("Risk", secondary=vendor_risks, lazy="selectin",
        secondaryjoin="and_(vendor_risks.c.risk_id == Risk.id, Risk.deleted == False)",
    )  # noqa: F821
    assets: Mapped[list["Asset"]] = relationship("Asset", secondary=vendor_assets, lazy="selectin",
        secondaryjoin="and_(vendor_assets.c.asset_id == Asset.id, Asset.deleted == False)",
    )  # noqa: F821
    # Reverse (read-only) links into the graph.
    incidents: Mapped[list["Incident"]] = relationship(  # noqa: F821
        "Incident", secondary="incident_vendors", lazy="selectin", viewonly=True,
    )
    assessments: Mapped[list["Assessment"]] = relationship(  # noqa: F821
        "Assessment", primaryjoin="Assessment.vendor_id == Vendor.id",
        foreign_keys="Assessment.vendor_id", lazy="selectin", viewonly=True,
    )
    outsourcing_arrangements: Mapped[list["OutsourcingArrangement"]] = relationship(  # noqa: F821
        "OutsourcingArrangement", primaryjoin="OutsourcingArrangement.vendor_id == Vendor.id",
        foreign_keys="OutsourcingArrangement.vendor_id", lazy="selectin", viewonly=True,
    )

    @property
    def contract_count(self) -> int:
        return len(self.contracts)

    @property
    def active_contract_value(self) -> float:
        return sum((c.value or 0) for c in self.contracts if not c.is_expired)


class ServiceContract(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, Base):
    """A contract/SLA with a third party."""

    __tablename__ = "service_contracts"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    vendor: Mapped["Vendor"] = relationship(back_populates="contracts")

    @property
    def is_expired(self) -> bool:
        return self.end_date is not None and self.end_date < date.today()
