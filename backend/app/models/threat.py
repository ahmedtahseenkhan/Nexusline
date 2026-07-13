"""Threat & Vulnerability catalogs — reusable libraries linked to risks
(threat exploits vulnerability → risk)."""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, String, Table, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

risk_threats = Table(
    "risk_threats",
    Base.metadata,
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
    Column("threat_id", Uuid, ForeignKey("threats.id", ondelete="CASCADE"), primary_key=True),
)
risk_vulnerabilities = Table(
    "risk_vulnerabilities",
    Base.metadata,
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "vulnerability_id",
        Uuid,
        ForeignKey("vulnerabilities.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# Catalog ↔ asset: which threats/vulnerabilities apply to which assets (asset-based
# risk identification — impossible before, threats only attached after a risk existed).
asset_threats = Table(
    "asset_threats", Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("threat_id", Uuid, ForeignKey("threats.id", ondelete="CASCADE"), primary_key=True),
)
asset_vulnerabilities = Table(
    "asset_vulnerabilities", Base.metadata,
    Column("asset_id", Uuid, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("vulnerability_id", Uuid, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), primary_key=True),
)


class Threat(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "threats"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="", index=True)
    assets: Mapped[list["Asset"]] = relationship(  # noqa: F821
        "Asset", secondary=asset_threats, lazy="selectin",
    )


class Vulnerability(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "vulnerabilities"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="", index=True)
    assets: Mapped[list["Asset"]] = relationship(  # noqa: F821
        "Asset", secondary=asset_vulnerabilities, lazy="selectin",
    )
