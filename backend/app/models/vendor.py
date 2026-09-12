"""Third-Party / Vendor Risk — vendor registry, service contracts, a review cycle and
links to the risks they introduce and assets/data they touch. Vendor self-assessment
questionnaires live in the assessments module. Carries the eramba record envelope."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
)
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
# Third-party compliance obligations (SBP outsourcing) + the controls mitigating vendor risk.
vendor_requirements = Table(
    "vendor_requirements",
    Base.metadata,
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
)
vendor_controls = Table(
    "vendor_controls",
    Base.metadata,
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
)


class VendorType(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Third-party type taxonomy (e.g. Cloud Provider, Processor, Supplier)."""

    __tablename__ = "vendor_types"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")


vendor_processes = Table(
    "vendor_processes",
    Base.metadata,
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column("process_id", Uuid, ForeignKey("processes.id", ondelete="CASCADE"), primary_key=True),
)

vendor_subcontractors = Table(
    "vendor_subcontractors",
    Base.metadata,
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column("subcontractor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
)

vendor_data_residency = Table(
    "vendor_data_residency",
    Base.metadata,
    Column("vendor_id", Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column("country_id", Uuid, ForeignKey("lookups.id", ondelete="CASCADE"), primary_key=True),
)


class Vendor(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "vendors"
    # Phase 2: due-diligence and outsourcing facts.
    legal_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    registration_number: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    relationship_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # internal accountable owner
    data_classification_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # highest data classification accessed
    annual_spend: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    spend_currency: Mapped[str] = mapped_column(String(3), default="", nullable=False)
    inherent_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)  # derived from tiering answers
    tier_override_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="", index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: governed lookup value; replaces free-text `category`
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vendor_types.id", ondelete="SET NULL"), nullable=True
    )

    # Contacts
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    contact_phone: Mapped[str] = mapped_column(String(60), default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 1: governed lookup value; replaces free-text `location`

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
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        "Requirement", secondary=vendor_requirements, lazy="selectin",
    )
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        "Control", secondary=vendor_controls, lazy="selectin",
    )
    # Phase 2 due diligence: the business processes the third party supports, the
    # countries its copy of our data sits in, and its own sub-contractors ("fourth
    # parties"). Archived processes / vendors drop out of the lists.
    processes: Mapped[list["Process"]] = relationship(  # noqa: F821
        "Process", secondary=vendor_processes, lazy="selectin",
        secondaryjoin="and_(vendor_processes.c.process_id == Process.id, Process.deleted == False)",
    )
    data_residency_countries: Mapped[list["Lookup"]] = relationship(  # noqa: F821
        "Lookup", secondary=vendor_data_residency, lazy="selectin",
    )
    subcontractors: Mapped[list["Vendor"]] = relationship(
        "Vendor", secondary=vendor_subcontractors, lazy="selectin",
        primaryjoin="Vendor.id == vendor_subcontractors.c.vendor_id",
        secondaryjoin="and_(vendor_subcontractors.c.subcontractor_id == Vendor.id, Vendor.deleted == False)",
    )
    subcontractor_of: Mapped[list["Vendor"]] = relationship(
        "Vendor", secondary=vendor_subcontractors, lazy="selectin", viewonly=True,
        primaryjoin="Vendor.id == vendor_subcontractors.c.subcontractor_id",
        secondaryjoin="and_(vendor_subcontractors.c.vendor_id == Vendor.id, Vendor.deleted == False)",
    )
    certifications: Mapped[list["VendorCertification"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan", lazy="selectin",
        order_by="VendorCertification.expires_on",
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
    currency: Mapped[str] = mapped_column(String(3), default="", nullable=False)  # Phase 2

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


class VendorCertification(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Phase 2: a third party's certification (ISO 27001, SOC 2, PCI DSS …) and when it
    lapses; expiry raises an alert."""

    __tablename__ = "vendor_certifications"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    certificate_number: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    vendor: Mapped["Vendor"] = relationship(back_populates="certifications")

    @property
    def expiry_state(self) -> str:
        return certification_expiry_state(self.expires_on, date.today())

    @property
    def days_to_expiry(self) -> int | None:
        return None if self.expires_on is None else (self.expires_on - date.today()).days


#: A certification starts warning this many days before it lapses (the notice a third
#: party needs to renew an ISO 27001 / SOC 2 report before the old one runs out).
CERT_EXPIRY_WARNING_DAYS = 60


def certification_expiry_state(expires_on: date | None, today: date) -> str:
    """``expired`` once the expiry date has passed, ``expiring`` from
    :data:`CERT_EXPIRY_WARNING_DAYS` days before it (the expiry day itself included),
    ``valid`` before that, ``no_expiry`` when no date is recorded."""
    if expires_on is None:
        return "no_expiry"
    if expires_on < today:
        return "expired"
    if (expires_on - today).days <= CERT_EXPIRY_WARNING_DAYS:
        return "expiring"
    return "valid"
