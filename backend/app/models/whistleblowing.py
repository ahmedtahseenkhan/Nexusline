"""Whistleblowing & Case Management — the confidential-disclosure toolkit banks run.

* **WhistleblowingReport** — a disclosure raised through a whistleblowing channel
  (web portal / hotline / email / in-person / letter), triaged and investigated
  through a confidential case lifecycle. Anonymous reports are masked (name/contact
  hidden) and reachable only through a tokenized ``tracking_code`` two-way channel.
* **WhistleUpdate** — a case-log line (investigation note / status change) on a report.

Every enum name is prefixed ``whistle_*`` so it is globally unique in Postgres.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, Uuid
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
from app.models.enums import Severity


# ================================================================ enums ===
class WhistleCategory(str, enum.Enum):
    """The nature of the disclosure."""

    fraud = "fraud"
    corruption = "corruption"
    harassment = "harassment"
    discrimination = "discrimination"
    safety = "safety"
    financial_misconduct = "financial_misconduct"
    policy_violation = "policy_violation"
    data_privacy = "data_privacy"
    other = "other"


class WhistleChannel(str, enum.Enum):
    """How the disclosure reached the bank."""

    web_portal = "web_portal"
    hotline = "hotline"
    email = "email"
    in_person = "in_person"
    letter = "letter"


class WhistleStatus(str, enum.Enum):
    """Confidential case lifecycle from intake to closure."""

    received = "received"
    triage = "triage"
    investigating = "investigating"
    substantiated = "substantiated"
    unsubstantiated = "unsubstantiated"
    closed = "closed"


# =========================================================== reports ===
class WhistleblowingReport(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A whistleblowing disclosure and its investigation case."""

    __tablename__ = "whistleblowing_reports"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[WhistleCategory] = mapped_column(
        SAEnum(WhistleCategory, name="whistle_category"),
        default=WhistleCategory.other, nullable=False,
    )
    anonymous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reporter_name: Mapped[str] = mapped_column(String(200), default="")
    reporter_contact: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[WhistleChannel] = mapped_column(
        SAEnum(WhistleChannel, name="whistle_channel"),
        default=WhistleChannel.web_portal, nullable=False,
    )
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.medium, nullable=False,
    )
    status: Mapped[WhistleStatus] = mapped_column(
        SAEnum(WhistleStatus, name="whistle_status"),
        default=WhistleStatus.received, nullable=False,
    )
    assigned_to: Mapped[str] = mapped_column(String(200), default="")
    tracking_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    confidentiality_note: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(Text, default="")

    updates: Mapped[list["WhistleUpdate"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", lazy="selectin",
        order_by="WhistleUpdate.update_date",
    )

    @property
    def update_count(self) -> int:
        return len(self.updates)

    @property
    def is_open(self) -> bool:
        return self.status not in (
            WhistleStatus.substantiated,
            WhistleStatus.unsubstantiated,
            WhistleStatus.closed,
        )


class WhistleUpdate(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A case-log entry (investigation note / status change) on a report."""

    __tablename__ = "whistleblowing_updates"

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("whistleblowing_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    update_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_change: Mapped[str] = mapped_column(String(64), default="")

    report: Mapped[WhistleblowingReport] = relationship(back_populates="updates")
