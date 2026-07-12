"""Islamic / Shariah Governance — for Islamic banks and Islamic windows under the
SBP Shariah Governance Framework.

* **ShariahRuling** — the register of Shariah Board fatwas / resolutions.
* **IslamicProduct** — products by Islamic mode of finance, each linked to the ruling
  that approved it.
* **ShariahReview** — Shariah compliance reviews / Shariah audits, with
* **ShariahFinding** — Shariah Non-Compliance (SNC) findings, each carrying any
  tainted income to be purified.
* **CharityDisbursement** — the purification ledger: SNC income routed to charity.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, Uuid
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
    CharityStatus,
    IslamicProductStatus,
    ReviewFrequency,
    Severity,
    ShariahFindingStatus,
    ShariahMode,
    ShariahReviewStatus,
    ShariahRulingStatus,
)


class ShariahRuling(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A Shariah Board ruling / fatwa / resolution."""

    __tablename__ = "shariah_rulings"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    ruling_text: Mapped[str] = mapped_column(Text, default="")
    basis: Mapped[str] = mapped_column(Text, default="")  # Quran/Sunnah/Ijma/Qiyas references
    status: Mapped[ShariahRulingStatus] = mapped_column(
        SAEnum(ShariahRulingStatus, name="shariah_ruling_status"),
        default=ShariahRulingStatus.draft, nullable=False,
    )
    approved_by: Mapped[str] = mapped_column(String(255), default="")  # Shariah Board / RSBM
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual, nullable=False,
    )
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def is_review_overdue(self) -> bool:
        return self.next_review_date is not None and self.next_review_date < date.today()


class IslamicProduct(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "islamic_products"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    shariah_mode: Mapped[ShariahMode] = mapped_column(
        SAEnum(ShariahMode, name="shariah_mode"), default=ShariahMode.murabaha, nullable=False
    )
    structure: Mapped[str] = mapped_column(Text, default="")  # contract structure / flow
    status: Mapped[IslamicProductStatus] = mapped_column(
        SAEnum(IslamicProductStatus, name="islamic_product_status"),
        default=IslamicProductStatus.in_development, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    launch_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    approving_ruling_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shariah_rulings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approving_ruling: Mapped["ShariahRuling | None"] = relationship(lazy="selectin")


class ShariahReview(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A Shariah compliance review / Shariah audit engagement."""

    __tablename__ = "shariah_reviews"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(Text, default="")
    review_type: Mapped[str] = mapped_column(String(64), default="product")  # product|branch|transaction|process
    reviewer: Mapped[str] = mapped_column(String(200), default="")  # Shariah scholar / SCD
    status: Mapped[ShariahReviewStatus] = mapped_column(
        SAEnum(ShariahReviewStatus, name="shariah_review_status"),
        default=ShariahReviewStatus.planned, nullable=False,
    )
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    conclusion: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[Severity | None] = mapped_column(SAEnum(Severity, name="severity"), nullable=True)

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("islamic_products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product: Mapped["IslamicProduct | None"] = relationship(lazy="selectin")
    findings: Mapped[list["ShariahFinding"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", lazy="selectin",
        order_by="ShariahFinding.created_at",
    )

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def open_finding_count(self) -> int:
        return sum(1 for f in self.findings if f.status != ShariahFindingStatus.closed)

    @property
    def snc_income_total(self) -> float:
        return float(sum((f.snc_income_amount or 0) for f in self.findings))


class ShariahFinding(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A Shariah Non-Compliance (SNC) finding, with any tainted income to purify."""

    __tablename__ = "shariah_findings"

    review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shariah_reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.medium, nullable=False
    )
    snc_income_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    management_response: Mapped[str] = mapped_column(Text, default="")
    action_owner: Mapped[str] = mapped_column(String(200), default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[ShariahFindingStatus] = mapped_column(
        SAEnum(ShariahFindingStatus, name="shariah_finding_status"),
        default=ShariahFindingStatus.open, nullable=False,
    )
    closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    review: Mapped[ShariahReview] = relationship(back_populates="findings")

    @property
    def is_overdue(self) -> bool:
        return (
            self.status not in (ShariahFindingStatus.closed, ShariahFindingStatus.remediated)
            and self.due_date is not None
            and self.due_date < date.today()
        )


class CharityDisbursement(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """Purification ledger: Shariah non-compliant income routed to charity."""

    __tablename__ = "charity_disbursements"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    source_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shariah_findings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    beneficiary: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[CharityStatus] = mapped_column(
        SAEnum(CharityStatus, name="charity_status"), default=CharityStatus.pending, nullable=False
    )
    disbursement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
