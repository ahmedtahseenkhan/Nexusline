"""Per-organisation settings: locale and data-retention choices.

One row per tenant, created on first read. Kept apart from ``RiskSetting`` (the risk
methodology) because these are organisation-wide presentation and housekeeping choices
every module reads: which currency money is shown in, which timezone a date belongs to,
how long an archived record is kept before it is purged.
"""
from __future__ import annotations

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

#: Supported ``date_format`` values, as shown to people. The frontend formats with them.
DATE_FORMATS: tuple[str, ...] = ("DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD", "DD MMM YYYY")


class TenantSettings(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "tenant_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_settings_tenant"),)

    currency: Mapped[str] = mapped_column(String(3), default="PKR", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Karachi", nullable=False)
    date_format: Mapped[str] = mapped_column(String(16), default="DD/MM/YYYY", nullable=False)
    # Pakistani banks report on the calendar year (financial statements to 31 December).
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    phone_country: Mapped[str] = mapped_column(String(2), default="PK", nullable=False)
    # Days an archived record is kept before the scheduler purges it for good.
    retention_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
