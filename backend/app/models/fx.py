"""Exchange rates to the organisation's reporting currency (plan §11 decision 4).

Every amount keeps the currency it was recorded in; totals are shown in the reporting
currency (``TenantSettings.currency``). On-premises installations usually have no
internet access, so there is no rate feed: the bank enters its own rates (typically the
SBP weighted-average customer rates, or the treasury's month-end revaluation rates) here
or imports them from CSV.

A rate says "1 unit of ``currency`` = ``rate_to_reporting`` units of
``reporting_currency``, from ``effective_date`` until the next rate for that currency".
``reporting_currency`` is stored with each rate so a later change of reporting currency
never silently applies PKR rates to, say, USD totals: conversion only uses rates quoted
into the current reporting currency.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class FxRate(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "currency", "reporting_currency", "effective_date",
            name="uq_fx_rates_tenant_currency_date",
        ),
    )

    #: ISO 4217 code of the foreign currency (e.g. USD).
    currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    #: The currency the rate converts into — the reporting currency when it was entered.
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PKR")
    #: Units of the reporting currency for one unit of ``currency``.
    rate_to_reporting: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: Where the rate came from, e.g. "SBP weighted-average customer rate, 30 Jun 2026".
    source: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
