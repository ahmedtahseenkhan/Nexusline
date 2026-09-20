"""Exchange rates and converted money totals (plan §11 decision 4)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.tenant_settings import CURRENCIES


def _currency(value: str) -> str:
    code = (value or "").strip().upper()
    if code not in CURRENCIES:
        raise ValueError(
            f"'{value}' is not a supported currency; use a three-letter ISO 4217 code such as USD or EUR."
        )
    return code


class FxRateCreate(BaseModel):
    currency: str = Field(description="ISO 4217 code of the foreign currency, e.g. USD")
    rate_to_reporting: Decimal = Field(
        gt=0, max_digits=20, decimal_places=8,
        description="Units of the reporting currency for one unit of the currency",
    )
    effective_date: date = Field(description="The rate applies to amounts dated on or after this day")
    source: str = Field(default="", max_length=255, description="Where the rate came from")

    _check_currency = field_validator("currency")(_currency)


class FxRateUpdate(BaseModel):
    rate_to_reporting: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    effective_date: date | None = None
    source: str | None = Field(default=None, max_length=255)


class FxRateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    currency: str
    reporting_currency: str
    rate_to_reporting: Decimal
    effective_date: date
    source: str = ""
    created_by_id: uuid.UUID | None = None
    created_by_name: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FxCurrencySummary(BaseModel):
    """One foreign currency's latest rate, for the "Exchange rates" list."""

    currency: str
    name: str = ""
    latest_rate: Decimal
    latest_date: date
    rate_count: int
    #: Days since the latest rate took effect — a rate months old deserves a look.
    age_days: int


class FxRateList(BaseModel):
    reporting_currency: str
    currencies: list[FxCurrencySummary]
    items: list[FxRateRead]
    #: Currencies used on records that have no rate into the reporting currency yet.
    missing: list[str] = []


class CurrencyAmount(BaseModel):
    currency: str
    count: int
    #: Sum in the original currency.
    amount: float
    #: The part of ``amount`` that was converted, in the reporting currency.
    converted: float = 0.0
    latest_rate_date: date | None = None


class UnconvertedAmount(BaseModel):
    currency: str
    count: int
    amount: float


class MoneyTotalRead(BaseModel):
    """A total in the reporting currency. Amounts with no rate are in ``unconverted``,
    never in ``total``."""

    reporting_currency: str = "PKR"
    total: float = 0.0
    count: int = 0
    by_currency: list[CurrencyAmount] = []
    unconverted: list[UnconvertedAmount] = []


class ConversionPreview(BaseModel):
    amount: float
    currency: str
    reporting_currency: str
    converted: float | None
    rate: Decimal | None
    rate_date: date | None
    note: str
