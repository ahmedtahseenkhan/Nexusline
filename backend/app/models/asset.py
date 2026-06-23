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
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AssetReviewStatus, Criticality, ReviewFrequency, WorkflowStatus

_CRIT_RANK = {Criticality.low: 1, Criticality.medium: 2, Criticality.high: 3, Criticality.critical: 4}


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
    """A reusable handling label (e.g. Public, Confidential, PII)."""

    __tablename__ = "asset_labels"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="")


# --- The Asset ---
class Asset(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "assets"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")

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

    # Quick CIA (kept for risk scoring; the classifications M2M is the rich scheme)
    confidentiality: Mapped[Criticality] = mapped_column(SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False)
    integrity: Mapped[Criticality] = mapped_column(SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False)
    availability: Mapped[Criticality] = mapped_column(SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False)
    criticality: Mapped[Criticality] = mapped_column(SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False)

    potential_liabilities: Mapped[str] = mapped_column(Text, default="")

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

    classifications: Mapped[list["AssetClassification"]] = relationship(
        secondary=asset_classification_links, lazy="selectin"
    )
    processes: Mapped[list["Process"]] = relationship(secondary=assets_processes, lazy="selectin")  # noqa: F821
    legals: Mapped[list["Legal"]] = relationship(secondary=assets_legals, lazy="selectin")  # noqa: F821
    requirements: Mapped[list["Requirement"]] = relationship(secondary=assets_requirements, lazy="selectin")  # noqa: F821
    incidents: Mapped[list["Incident"]] = relationship(secondary=assets_incidents, lazy="selectin")  # noqa: F821
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(secondary=assets_exceptions, lazy="selectin")  # noqa: F821
    related_assets: Mapped[list["Asset"]] = relationship(
        secondary=assets_related,
        primaryjoin=lambda: Asset.id == assets_related.c.asset_id,
        secondaryjoin=lambda: Asset.id == assets_related.c.related_id,
        lazy="selectin",
    )
    reviews: Mapped[list["AssetReview"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", lazy="selectin",
        order_by="AssetReview.scheduled_date.desc()",
    )
    risks: Mapped[list["Risk"]] = relationship(  # noqa: F821
        "Risk", secondary="risk_assets", lazy="selectin", viewonly=True,
    )

    @property
    def classification(self) -> Criticality:
        return max((self.confidentiality, self.integrity, self.availability), key=lambda c: _CRIT_RANK[c])

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
