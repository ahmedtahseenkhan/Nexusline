"""Data Privacy — GDPR Records of Processing Activities (RoPA / Article 30):
purpose, lawful basis, data subjects, retention, controller/processor/DPO, cross-border
transfers, DPIA, and links to the assets/risks involved."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Column, Date, ForeignKey, String, Table, Text, Uuid
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
from app.models.enums import DpiaStatus, LawfulBasis, ReviewFrequency, RopaStatus

ropa_assets = Table(
    "ropa_assets",
    Base.metadata,
    Column("ropa_id", Uuid, ForeignKey("processing_activities.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)
ropa_risks = Table(
    "ropa_risks",
    Base.metadata,
    Column("ropa_id", Uuid, ForeignKey("processing_activities.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)
ropa_processes = Table(
    "ropa_processes",
    Base.metadata,
    Column("ropa_id", Uuid, ForeignKey("processing_activities.id", ondelete="CASCADE"), primary_key=True),
    Column("process_id", Uuid, ForeignKey("processes.id", ondelete="CASCADE"), primary_key=True),
)
ropa_policies = Table(
    "ropa_policies",
    Base.metadata,
    Column("ropa_id", Uuid, ForeignKey("processing_activities.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)


class ProcessingActivity(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "processing_activities"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[RopaStatus] = mapped_column(
        SAEnum(RopaStatus, name="ropa_status"), default=RopaStatus.draft, nullable=False
    )

    lawful_basis: Mapped[LawfulBasis] = mapped_column(
        SAEnum(LawfulBasis, name="lawful_basis"), default=LawfulBasis.consent, nullable=False
    )
    data_subjects: Mapped[str] = mapped_column(Text, default="")  # whose data
    data_categories: Mapped[str] = mapped_column(Text, default="")  # what data
    data_types: Mapped[str] = mapped_column(Text, default="")  # personal data types collected
    collection_methods: Mapped[str] = mapped_column(Text, default="")  # how data is collected
    volume: Mapped[str] = mapped_column(String(255), default="")  # data subject volume
    special_category: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retention_period: Mapped[str] = mapped_column(String(255), default="")
    archiving_driver: Mapped[str] = mapped_column(Text, default="")  # why retention period chosen
    recipients: Mapped[str] = mapped_column(Text, default="")  # who receives the data
    security_measures: Mapped[str] = mapped_column(Text, default="")
    accuracy: Mapped[str] = mapped_column(Text, default="")  # how accuracy is maintained

    # GDPR data-subject rights — how each is handled
    right_to_be_informed: Mapped[str] = mapped_column(Text, default="")
    right_to_access: Mapped[str] = mapped_column(Text, default="")
    right_to_rectification: Mapped[str] = mapped_column(Text, default="")
    right_to_erasure: Mapped[str] = mapped_column(Text, default="")
    right_to_portability: Mapped[str] = mapped_column(Text, default="")
    right_to_object: Mapped[str] = mapped_column(Text, default="")

    # Roles
    controller: Mapped[str] = mapped_column(String(200), default="")
    processor: Mapped[str] = mapped_column(String(200), default="")
    dpo: Mapped[str] = mapped_column(String(200), default="")
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Cross-border transfers (data flow)
    cross_border_transfer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    origin: Mapped[str] = mapped_column(String(255), default="")
    transfer_destinations: Mapped[str] = mapped_column(Text, default="")
    transfer_safeguard: Mapped[str] = mapped_column(String(255), default="")  # SCCs / adequacy

    # DPIA
    dpia_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dpia_status: Mapped[DpiaStatus] = mapped_column(
        SAEnum(DpiaStatus, name="dpia_status"), default=DpiaStatus.not_required, nullable=False
    )

    review_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"), default=ReviewFrequency.annual, nullable=False
    )
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    business_unit: Mapped["BusinessUnit | None"] = relationship(  # noqa: F821
        "BusinessUnit", lazy="selectin"
    )
    assets: Mapped[list["Asset"]] = relationship(secondary=ropa_assets, lazy="selectin")  # noqa: F821
    risks: Mapped[list["Risk"]] = relationship(secondary=ropa_risks, lazy="selectin")  # noqa: F821
    processes: Mapped[list["Process"]] = relationship(secondary=ropa_processes, lazy="selectin")  # noqa: F821
    policies: Mapped[list["Policy"]] = relationship(secondary=ropa_policies, lazy="selectin")  # noqa: F821

    @property
    def has_transfer_gap(self) -> bool:
        """Cross-border transfer without a documented safeguard = compliance gap."""
        return self.cross_border_transfer and not self.transfer_safeguard.strip()

    @property
    def dpia_outstanding(self) -> bool:
        return self.dpia_required and self.dpia_status != DpiaStatus.completed
