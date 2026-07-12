"""Asset Management — full eramba-parity model.

An Asset carries: a media type, three RACI owners (owner / guardian / user → business
units), a flexible CIA classification scheme, handling labels, a periodic review cycle
(with an expired-review counter), a workflow/approval status, soft-delete, and links to
risks, processes, legal obligations, compliance requirements, incidents, exceptions and
related assets.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AssetClass,
    AssetDependencyType,
    AssetEnvironment,
    AssetReviewStatus,
    Criticality,
    DiscoverySource,
    ReviewFrequency,
    WorkflowStatus,
)

_CRIT_RANK = {Criticality.low: 1, Criticality.medium: 2, Criticality.high: 3, Criticality.critical: 4}
_RANK_CRIT = {v: k for k, v in _CRIT_RANK.items()}


# --- Association (link/join) tables ---
asset_classification_links = Table(
    "asset_classifications_assets",
    Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_classification_id", Uuid, ForeignKey("asset_classifications.id", ondelete="CASCADE"), primary_key=True),
)
assets_processes = Table(
    "assets_processes",
    Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("process_id", Uuid, ForeignKey("processes.id", ondelete="CASCADE"), primary_key=True),
)
assets_legals = Table(
    "assets_legals",
    Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("legal_id", Uuid, ForeignKey("legals.id", ondelete="CASCADE"), primary_key=True),
)
assets_requirements = Table(
    "assets_requirements",
    Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
)
assets_incidents = Table(
    "assets_incidents",
    Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("incident_id", Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True),
)
assets_exceptions = Table(
    "assets_exceptions",
    Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("exception_id", Uuid, ForeignKey("exceptions.id", ondelete="CASCADE"), primary_key=True),
)
assets_related = Table(
    "assets_related",
    Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("related_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)
# IT (supporting) assets carry their OWN operational tag vocabulary — deliberately
# separate from the information-asset handling labels/classifications (stakeholder ask:
# "keep tagging separate for each").
asset_tag_links = Table(
    "asset_tag_links",
    Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_tag_id", Uuid, ForeignKey("asset_tags.id", ondelete="CASCADE"), primary_key=True),
)


# --- Lookup / reference tables ---
class AssetMediaType(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Asset media/type taxonomy (Data Asset, Hardware, Software, People, …)."""

    __tablename__ = "asset_media_types"

    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    editable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AssetClassificationType(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A classification axis, e.g. Confidentiality / Integrity / Availability."""

    __tablename__ = "asset_classification_types"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")

    classifications: Mapped[list["AssetClassification"]] = relationship(
        back_populates="type", cascade="all, delete-orphan", lazy="selectin",
        order_by="AssetClassification.value",
    )


class AssetClassification(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A named value within a classification axis (e.g. Confidential = 3)."""

    __tablename__ = "asset_classifications"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    criteria: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("asset_classification_types.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped["AssetClassificationType"] = relationship(back_populates="classifications", lazy="selectin")


class AssetLabel(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """An INFORMATION-asset handling label (e.g. Public, Internal, Confidential, Restricted, PII).

    Information/handling labels only — the IT side uses ``AssetTag`` instead so the two
    vocabularies never bleed into each other.
    """

    __tablename__ = "asset_labels"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="")


class AssetTag(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """An IT (supporting) asset operational tag (e.g. prod, endpoint, network-device, DC-Karachi).

    Deliberately distinct from ``AssetLabel`` (information classification/handling labels).
    """

    __tablename__ = "asset_tags"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), default="")  # environment, form-factor, location…
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="")


class AssetDependency(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Directional link: an INFORMATION asset is carried by an IT (supporting) asset.

    This is what lets criticality *inherit* — a backup server is critical because of the
    data it stores, not its purchase price. ``derived_criticality`` on the IT asset reads
    these links. Split the modules, but never silo them.
    """

    __tablename__ = "asset_dependencies"

    information_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    it_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_type: Mapped[AssetDependencyType] = mapped_column(
        SAEnum(AssetDependencyType, name="asset_dependency_type"),
        default=AssetDependencyType.hosts, nullable=False,
    )
    notes: Mapped[str] = mapped_column(Text, default="")

    information_asset: Mapped["Asset"] = relationship(
        "Asset", foreign_keys=[information_asset_id], lazy="selectin",
    )
    it_asset: Mapped["Asset"] = relationship(
        "Asset", foreign_keys=[it_asset_id], lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("information_asset_id", "it_asset_id", "relationship_type", name="uq_asset_dependency"),
    )


# --- The Asset ---
class Asset(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "assets"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")

    # The ISO 27005 primary/supporting discriminator — drives which module owns the record,
    # which form is shown, and how criticality is computed.
    asset_class: Mapped[AssetClass] = mapped_column(
        SAEnum(AssetClass, name="asset_class"),
        default=AssetClass.information_asset,
        server_default=AssetClass.information_asset.value,
        nullable=False, index=True,
    )

    media_type_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("asset_media_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    label_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("asset_labels.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # RACI ownership (eramba: owner / guardian / user → business units)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    guardian_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Quick CIA (kept for risk scoring; the classifications M2M is the rich scheme).
    # For INFORMATION assets these express the data's own C/I/A sensitivity.
    confidentiality: Mapped[Criticality] = mapped_column(SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False)
    integrity: Mapped[Criticality] = mapped_column(SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False)
    availability: Mapped[Criticality] = mapped_column(SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False)
    criticality: Mapped[Criticality] = mapped_column(SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False)

    potential_liabilities: Mapped[str] = mapped_column(Text, default="")

    # --- INFORMATION-asset fields (primary asset; business value set by the BUSINESS OWNER) ---
    # Security designs the criteria/form; the business owner attests the value here.
    business_value: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    information_owner: Mapped[str] = mapped_column(String(200), default="")   # the business owner (person/role)
    data_categories: Mapped[str] = mapped_column(Text, default="")           # e.g. "PII, financial, transactional"
    records_volume: Mapped[str] = mapped_column(String(120), default="")     # e.g. "~2.4M customer records"
    # Self-assessment: responsible person completes the selection form; the signed form is
    # attached to this record (central repository) via the standard attachments panel.
    self_assessed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assessed_by: Mapped[str] = mapped_column(String(200), default="")
    assessed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- IT-asset fields (supporting asset; judged by intrinsic COST + AVAILABILITY only) ---
    replacement_cost: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    rto_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpo_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    environment: Mapped[AssetEnvironment] = mapped_column(
        SAEnum(AssetEnvironment, name="asset_environment"),
        default=AssetEnvironment.production, nullable=False,
    )
    location: Mapped[str] = mapped_column(String(200), default="")
    hostname: Mapped[str] = mapped_column(String(200), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    serial_number: Mapped[str] = mapped_column(String(120), default="")
    manufacturer: Mapped[str] = mapped_column(String(120), default="")
    model_number: Mapped[str] = mapped_column(String(120), default="")
    os_version: Mapped[str] = mapped_column(String(120), default="")

    # --- Discovery / automation-ready (manual now; CMDB / AD / scan ingestion later) ---
    discovery_source: Mapped[DiscoverySource] = mapped_column(
        SAEnum(DiscoverySource, name="discovery_source"),
        default=DiscoverySource.manual, nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(200), default="")  # id in the source system
    auto_discovered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Review cycle
    review_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"), default=ReviewFrequency.annual, nullable=False
    )
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expired_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Workflow / approval lifecycle
    workflow_status: Mapped[WorkflowStatus] = mapped_column(
        SAEnum(WorkflowStatus, name="workflow_status"), default=WorkflowStatus.draft, nullable=False
    )
    workflow_owner: Mapped[str] = mapped_column(String(200), default="")

    # Soft delete (eramba common envelope)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Relationships ---
    media_type: Mapped["AssetMediaType | None"] = relationship(lazy="selectin")
    label: Mapped["AssetLabel | None"] = relationship(lazy="selectin")
    owner: Mapped["BusinessUnit | None"] = relationship("BusinessUnit", foreign_keys=[owner_id], lazy="selectin")  # noqa: F821
    guardian: Mapped["BusinessUnit | None"] = relationship("BusinessUnit", foreign_keys=[guardian_id], lazy="selectin")  # noqa: F821
    user: Mapped["BusinessUnit | None"] = relationship("BusinessUnit", foreign_keys=[user_id], lazy="selectin")  # noqa: F821

    tags: Mapped[list["AssetTag"]] = relationship(secondary=asset_tag_links, lazy="selectin")
    # Directional dependency links (this asset as the information side / as the IT side).
    hosted_dependencies: Mapped[list["AssetDependency"]] = relationship(
        "AssetDependency", foreign_keys="AssetDependency.it_asset_id",
        lazy="selectin", viewonly=True,
    )
    hosting_dependencies: Mapped[list["AssetDependency"]] = relationship(
        "AssetDependency", foreign_keys="AssetDependency.information_asset_id",
        lazy="selectin", viewonly=True,
    )

    classifications: Mapped[list["AssetClassification"]] = relationship(
        secondary=asset_classification_links, lazy="selectin"
    )
    processes: Mapped[list["Process"]] = relationship(secondary=assets_processes, lazy="selectin",
        secondaryjoin="and_(assets_processes.c.process_id == Process.id, Process.deleted == False)",
    )  # noqa: F821
    legals: Mapped[list["Legal"]] = relationship(secondary=assets_legals, lazy="selectin")  # noqa: F821
    requirements: Mapped[list["Requirement"]] = relationship(secondary=assets_requirements, lazy="selectin",
        secondaryjoin="and_(assets_requirements.c.requirement_id == Requirement.id, Requirement.deleted == False)",
    )  # noqa: F821
    incidents: Mapped[list["Incident"]] = relationship(secondary=assets_incidents, lazy="selectin",
        secondaryjoin="and_(assets_incidents.c.incident_id == Incident.id, Incident.deleted == False)",
    )  # noqa: F821
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(secondary=assets_exceptions, lazy="selectin",
        secondaryjoin="and_(assets_exceptions.c.exception_id == ExceptionRecord.id, ExceptionRecord.deleted == False)",
    )  # noqa: F821
    related_assets: Mapped[list["Asset"]] = relationship(
        secondary=assets_related,
        primaryjoin=lambda: Asset.id == assets_related.c.asset_id,
        secondaryjoin=lambda: (assets_related.c.related_id == Asset.id) & (Asset.deleted == False),
        lazy="selectin",
    )
    reviews: Mapped[list["AssetReview"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", lazy="selectin",
        order_by="AssetReview.scheduled_date.desc()",
    )
    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary="risk_assets", lazy="selectin", viewonly=True,
        secondaryjoin="and_(risk_assets.c.risk_id == Risk.id, Risk.deleted == False)",
    )
    # Reverse (read-only) links into the graph.
    vendors: Mapped[list["Vendor"]] = relationship(  # noqa: F821
        "Vendor", secondary="vendor_assets", lazy="selectin", viewonly=True,
    )
    access_reviews: Mapped[list["AccessReview"]] = relationship(  # noqa: F821
        "AccessReview", primaryjoin="AccessReview.asset_id == Asset.id",
        foreign_keys="AccessReview.asset_id", lazy="selectin", viewonly=True,
    )

    @property
    def classification(self) -> Criticality:
        return max((self.confidentiality, self.integrity, self.availability), key=lambda c: _CRIT_RANK[c])

    @property
    def cost_band(self) -> Criticality:
        """Map replacement cost (PKR) to a criticality band — an IT-asset *intrinsic* input.

        IT assets are judged by cost + availability only (no business-criticality framing).
        Bands are deliberately coarse; tune per client during onboarding.
        """
        cost = float(self.replacement_cost or 0)
        if cost >= 10_000_000:
            return Criticality.critical
        if cost >= 2_000_000:
            return Criticality.high
        if cost >= 250_000:
            return Criticality.medium
        return Criticality.low

    @property
    def intrinsic_criticality(self) -> Criticality:
        """IT asset's own criticality from cost + availability requirement only."""
        return max((self.cost_band, self.availability), key=lambda c: _CRIT_RANK[c])

    @property
    def derived_criticality(self) -> Criticality:
        """Highest business value among the information assets this IT asset carries.

        This is the "backup server" rule: a device inherits criticality from the DATA it
        stores, not its purchase price. Returns ``low`` when nothing depends on it.
        """
        best = 0
        for dep in self.hosted_dependencies:
            info = dep.information_asset
            if info is not None:
                best = max(best, _CRIT_RANK[info.business_value])
        return _RANK_CRIT.get(best, Criticality.low)

    @property
    def effective_criticality(self) -> Criticality:
        """The criticality that actually matters.

        * Information asset → its business value (set by the business owner).
        * IT asset → max(intrinsic cost+availability, criticality inherited from hosted data).
        """
        if self.asset_class == AssetClass.it_asset:
            return max((self.intrinsic_criticality, self.derived_criticality), key=lambda c: _CRIT_RANK[c])
        return self.business_value

    @property
    def review_status(self) -> str:
        if self.next_review_date is None:
            return "none"
        return "overdue" if self.next_review_date < date.today() else "current"

    @property
    def risk_count(self) -> int:
        return len(self.risks)


class AssetReview(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single review/attestation in an asset's review cycle."""

    __tablename__ = "asset_reviews"

    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer: Mapped[str] = mapped_column(String(200), default="")
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[AssetReviewStatus] = mapped_column(
        SAEnum(AssetReviewStatus, name="asset_review_status"), default=AssetReviewStatus.scheduled, nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(120), default="")
    comments: Mapped[str] = mapped_column(Text, default="")

    asset: Mapped["Asset"] = relationship(back_populates="reviews")
