"""Exceptions Management — formal, time-boxed acceptance of a risk, policy or
compliance gap, with an approval workflow. (Class named ``ExceptionRecord`` to avoid
shadowing the Python builtin ``Exception``.)"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Column, Date, ForeignKey, String, Table, Text, Uuid
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
from app.models.enums import ExceptionStatus, ExceptionType

exception_risks = Table(
    "exception_risks",
    Base.metadata,
    Column("exception_id", Uuid, ForeignKey("exceptions.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)
exception_policies = Table(
    "exception_policies",
    Base.metadata,
    Column("exception_id", Uuid, ForeignKey("exceptions.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)
exception_requirements = Table(
    "exception_requirements",
    Base.metadata,
    Column("exception_id", Uuid, ForeignKey("exceptions.id", ondelete="CASCADE"), primary_key=True),
    Column("requirement_id", Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True),
)
exception_controls = Table(
    "exception_controls",
    Base.metadata,
    Column("exception_id", Uuid, ForeignKey("exceptions.id", ondelete="CASCADE"), primary_key=True),
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
)


class ExceptionRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "exceptions"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    exception_type: Mapped[ExceptionType] = mapped_column(
        SAEnum(ExceptionType, name="exception_type"), default=ExceptionType.risk, nullable=False
    )
    classification: Mapped[str] = mapped_column(String(120), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")  # business justification
    compensating_controls: Mapped[str] = mapped_column(Text, default="")  # interim mitigation
    business_owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[ExceptionStatus] = mapped_column(
        SAEnum(ExceptionStatus, name="exception_status"),
        default=ExceptionStatus.pending,
        nullable=False,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    closure_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decided_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    risks: Mapped[list["Risk"]] = relationship(secondary=exception_risks, lazy="selectin")  # noqa: F821
    policies: Mapped[list["Policy"]] = relationship(  # noqa: F821
        secondary=exception_policies, lazy="selectin"
    )
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        secondary=exception_requirements, lazy="selectin"
    )
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        secondary=exception_controls, lazy="selectin"
    )
    assets: Mapped[list["Asset"]] = relationship(  # noqa: F821
        "Asset", secondary="assets_exceptions", lazy="selectin", viewonly=True
    )

    @property
    def is_expired(self) -> bool:
        return (
            self.status == ExceptionStatus.approved
            and self.expires_at is not None
            and self.expires_at < date.today()
        )
