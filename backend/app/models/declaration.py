"""Compliance Declarations — periodic + event-driven staff attestations.

Banks run recurring declaration exercises (conflict of interest, gifts &
entertainment, personal account dealing, outside employment, related-party, code
of conduct) and collect one **Declaration** submission per staff member. A
submission may carry a *disclosure* — a gift received, an outside directorship, a
personal-account trade, a conflict — that the compliance function reviews and then
clears or escalates.

* **DeclarationCampaign** — a declaration exercise for a period / staff population.
* **Declaration** — a single staff member's submission against a campaign.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

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


# ============================================================= local enums ===
class DeclarationType(str, enum.Enum):
    """The kind of attestation a campaign collects."""

    conflict_of_interest = "conflict_of_interest"
    gifts_entertainment = "gifts_entertainment"
    personal_account_dealing = "personal_account_dealing"
    outside_employment = "outside_employment"
    related_party = "related_party"
    code_of_conduct = "code_of_conduct"


class CampaignStatus(str, enum.Enum):
    """Declaration campaign lifecycle."""

    draft = "draft"
    open = "open"
    closed = "closed"


class DeclarationStatus(str, enum.Enum):
    """A single submission's review lifecycle."""

    pending = "pending"
    submitted = "submitted"
    reviewed = "reviewed"
    escalated = "escalated"
    cleared = "cleared"


# ===================================================== declaration campaigns ===
class DeclarationCampaign(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "declaration_campaigns"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    declaration_type: Mapped[DeclarationType] = mapped_column(
        SAEnum(DeclarationType, name="declaration_type"),
        default=DeclarationType.conflict_of_interest, nullable=False,
    )
    period: Mapped[str] = mapped_column(String(64), default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[CampaignStatus] = mapped_column(
        SAEnum(CampaignStatus, name="declaration_campaign_status"),
        default=CampaignStatus.draft, nullable=False,
    )

    declarations: Mapped[list["Declaration"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", lazy="selectin",
        order_by="Declaration.created_at",
    )

    @property
    def declaration_count(self) -> int:
        return len(self.declarations)

    @property
    def disclosure_count(self) -> int:
        return sum(1 for d in self.declarations if d.has_disclosure)


# ============================================================== submissions ===
class Declaration(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single staff member's declaration submission against a campaign."""

    __tablename__ = "declarations"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("declaration_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    declarant_name: Mapped[str] = mapped_column(String(200), default="")
    declarant_role: Mapped[str] = mapped_column(String(200), default="")
    business_unit: Mapped[str] = mapped_column(String(200), default="")
    has_disclosure: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disclosure_details: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)  # e.g. value of a gift
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    submitted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[DeclarationStatus] = mapped_column(
        SAEnum(DeclarationStatus, name="declaration_status"),
        default=DeclarationStatus.pending, nullable=False,
    )
    reviewer: Mapped[str] = mapped_column(String(200), default="")
    review_notes: Mapped[str] = mapped_column(Text, default="")

    campaign: Mapped[DeclarationCampaign] = relationship(back_populates="declarations")
