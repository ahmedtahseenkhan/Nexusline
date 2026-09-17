"""Per-organisation settings: locale and data-retention choices.

One row per tenant, created on first read. Kept apart from ``RiskSetting`` (the risk
methodology) because these are organisation-wide presentation and housekeeping choices
every module reads: which currency money is shown in, which timezone a date belongs to,
how long an archived record is kept before it is purged.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
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
    # Phase 3: the modules this organisation has switched on, within its licence. NULL =
    # every licensed module (organisations that predate the choice keep everything).
    enabled_modules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Role names that must use MFA here. NULL = the deployment default (MFA_REQUIRED_ROLES).
    mfa_required_roles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
