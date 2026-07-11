"""Business Organization — the org backbone that every module links to.

* Business Units (hierarchy + RACI head) — own assets, run processes, hold obligations.
* Processes — business processes with continuity objectives (RTO / RPO / RPD) and criticality.
* Legal — legal/regulatory obligations with a ``risk_magnifier`` and applicable countries.

All three carry the eramba record envelope (workflow status + soft delete).
"""
from __future__ import annotations

import uuid

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Table, Text, Uuid
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
from app.models.enums import Criticality

business_units_legals = Table(
    "business_units_legals",
    Base.metadata,
    Column("business_unit_id", Uuid, ForeignKey("business_units.id", ondelete="CASCADE"), primary_key=True),
    Column("legal_id", Uuid, ForeignKey("legals.id", ondelete="CASCADE"), primary_key=True),
)


class BusinessUnit(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "business_units"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True
    )
    manager: Mapped[str] = mapped_column(String(200), default="")  # BU head / accountable contact
    email: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(200), default="")

    legals: Mapped[list["Legal"]] = relationship(secondary=business_units_legals, lazy="selectin",
        secondaryjoin="and_(business_units_legals.c.legal_id == Legal.id, Legal.deleted == False)",
    )


class Process(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "processes"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    criticality: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    # Business-continuity objectives (hours)
    rto_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # recovery time objective
    rpo_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # recovery point objective
    rpd_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # max tolerable downtime

    business_unit: Mapped["BusinessUnit | None"] = relationship(lazy="selectin")


class Legal(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """Legal / regulatory obligation. ``risk_magnifier`` amplifies linked risk scores."""

    __tablename__ = "legals"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="", index=True)
    jurisdiction: Mapped[str] = mapped_column(String(120), default="")
    reference: Mapped[str] = mapped_column(String(120), default="")
    countries: Mapped[str] = mapped_column(String(512), default="")  # CSV of applicable countries
    risk_magnifier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    business_units: Mapped[list["BusinessUnit"]] = relationship(
        secondary=business_units_legals, lazy="selectin", overlaps="legals",
        secondaryjoin="and_(business_units_legals.c.business_unit_id == BusinessUnit.id, BusinessUnit.deleted == False)",
    )
