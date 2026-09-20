"""Outsourcing & Cloud Risk — the SBP regulatory outsourcing layer.

The third-party / vendor module tracks vendors and their contracts; this module adds
the State Bank of Pakistan (SBP) **outsourcing & cloud** regulatory overlay that
supervisors expect banks to maintain for every material arrangement:

* **OutsourcingArrangement** — the outsourcing register entry: materiality
  determination, cloud model (IaaS/PaaS/SaaS) and data-offshoring, SBP approval / NOC
  tracking, contract window, documented exit plan (and whether it has been tested) and
  a concentration-risk note. Optionally links to the existing vendor register.
* **OutsourcingReview** — periodic monitoring reviews of an arrangement (SLA met,
  outcome, issues noted) on a planned/completed lifecycle.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, Text, Uuid
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


# =============================================================== enums (local) ===
class OutsourcingCategory(str, enum.Enum):
    """The kind of service being outsourced."""

    it_infrastructure = "it_infrastructure"
    cloud = "cloud"
    application = "application"
    business_process = "business_process"
    call_center = "call_center"
    payment_processing = "payment_processing"
    data_processing = "data_processing"
    other = "other"


class OutsourcingMateriality(str, enum.Enum):
    """SBP materiality determination — material arrangements carry heavier obligations."""

    material = "material"
    non_material = "non_material"


class CloudModel(str, enum.Enum):
    """Cloud service model where the arrangement is cloud-based."""

    iaas = "iaas"
    paas = "paas"
    saas = "saas"
    not_applicable = "not_applicable"


class SbpApprovalStatus(str, enum.Enum):
    """Status of the SBP approval / No-Objection Certificate (NOC), where required."""

    not_required = "not_required"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class OutsourcingStatus(str, enum.Enum):
    """Lifecycle of an outsourcing arrangement."""

    proposed = "proposed"
    active = "active"
    under_review = "under_review"
    terminated = "terminated"


class OutsourcingReviewStatus(str, enum.Enum):
    """Lifecycle of a monitoring review."""

    planned = "planned"
    completed = "completed"


#: How hard the service is to move elsewhere (``substitutability``). "none" means no
#: realistic alternative provider.
SUBSTITUTABILITY: tuple[str, ...] = ("easy", "moderate", "difficult", "none")
#: Substitutability that makes a tested exit plan urgent.
HARD_TO_SUBSTITUTE: frozenset[str] = frozenset({"difficult", "none"})
#: Reliance on the provider across the bank (``concentration_level``).
CONCENTRATION_LEVELS: tuple[str, ...] = ("low", "medium", "high")
#: Statuses past "proposed" that a material arrangement may only reach once its
#: materiality rationale, exit plan and substitutability are on file.
LIVE_STATUSES: frozenset[OutsourcingStatus] = frozenset({OutsourcingStatus.active, OutsourcingStatus.under_review})
#: (field, plain name) a material arrangement needs before it goes live.
ACTIVATION_FIELDS: tuple[tuple[str, str], ...] = (
    ("materiality_assessment", "materiality rationale"),
    ("exit_plan", "exit plan"),
    ("substitutability", "substitutability"),
)


def missing_for_activation(materiality, fields: dict) -> list[str]:
    """What a material arrangement still lacks before it can be active; ``[]`` for a
    non-material one or when everything is on file. Pure."""
    if getattr(materiality, "value", materiality) != OutsourcingMateriality.material.value:
        return []
    return [label for name, label in ACTIVATION_FIELDS if not str(fields.get(name) or "").strip()]


# ====================================================== outsourcing register ===
class OutsourcingArrangement(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """An SBP outsourcing / cloud arrangement with materiality, approval and exit tracking."""

    __tablename__ = "outsourcing_arrangements"
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 2: accountable owner
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Phase 2: country list; data location

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    service_provider: Mapped[str] = mapped_column(String(200), default="")
    service_description: Mapped[str] = mapped_column(Text, default="")
    # Optional link to the existing vendor register (SET NULL keeps the arrangement if the vendor is removed).
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[OutsourcingCategory] = mapped_column(
        SAEnum(OutsourcingCategory, name="outsourcing_category"),
        default=OutsourcingCategory.it_infrastructure, nullable=False,
    )
    materiality: Mapped[OutsourcingMateriality] = mapped_column(
        SAEnum(OutsourcingMateriality, name="outsourcing_materiality"),
        default=OutsourcingMateriality.material, nullable=False,
    )
    materiality_assessment: Mapped[str] = mapped_column(Text, default="")
    is_cloud: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cloud_model: Mapped[CloudModel] = mapped_column(
        SAEnum(CloudModel, name="cloud_model"),
        default=CloudModel.not_applicable, nullable=False,
    )
    data_offshored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    country: Mapped[str] = mapped_column(String(120), default="")
    sbp_approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sbp_approval_status: Mapped[SbpApprovalStatus] = mapped_column(
        SAEnum(SbpApprovalStatus, name="sbp_approval_status"),
        default=SbpApprovalStatus.not_required, nullable=False,
    )
    sbp_approval_ref: Mapped[str] = mapped_column(String(120), default="")
    contract_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Decision 4: the arrangement's contract value in its own currency ("" = the
    # organisation's reporting currency, as on vendor contracts).
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    contract_currency: Mapped[str] = mapped_column(String(3), default="", nullable=False)
    exit_plan: Mapped[str] = mapped_column(Text, default="")
    exit_plan_tested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    concentration_note: Mapped[str] = mapped_column(Text, default="")
    # How hard it is to move the service elsewhere: easy / moderate / difficult / none.
    substitutability: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    # Reliance on this provider across the bank's services: low / medium / high.
    concentration_level: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    status: Mapped[OutsourcingStatus] = mapped_column(
        SAEnum(OutsourcingStatus, name="outsourcing_status"),
        default=OutsourcingStatus.proposed, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")

    reviews: Mapped[list["OutsourcingReview"]] = relationship(
        back_populates="arrangement", cascade="all, delete-orphan", lazy="selectin",
        order_by="OutsourcingReview.created_at",
    )

    @property
    def missing_for_activation(self) -> list[str]:
        return missing_for_activation(
            self.materiality, {name: getattr(self, name, "") for name, _ in ACTIVATION_FIELDS},
        )

    @property
    def review_count(self) -> int:
        return len(self.reviews)

    @property
    def is_contract_expiring(self) -> bool:
        """True when a live contract ends within the next 90 days (SBP renewal watch)."""
        if self.status == OutsourcingStatus.terminated or self.contract_end is None:
            return False
        return 0 <= (self.contract_end - date.today()).days <= 90


# ======================================================== outsourcing reviews ===
class OutsourcingReview(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A periodic monitoring review of an outsourcing arrangement (SLA / issues)."""

    __tablename__ = "outsourcing_reviews"

    arrangement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("outsourcing_arrangements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(200), default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    sla_met: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    issues_noted: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[OutsourcingReviewStatus] = mapped_column(
        SAEnum(OutsourcingReviewStatus, name="outsourcing_review_status"),
        default=OutsourcingReviewStatus.planned, nullable=False,
    )

    arrangement: Mapped[OutsourcingArrangement] = relationship(back_populates="reviews")
