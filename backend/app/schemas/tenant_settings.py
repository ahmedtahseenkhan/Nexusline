"""Organisation settings (``/settings/organisation``): locale and retention choices.

The validators are plain functions so they can be unit-tested and reused (the CSV
importer and any form that offers a currency select should accept exactly the same
values). Each raises ``ValueError`` with a message a person can act on; Pydantic turns
that into a 422 naming the field.
"""
from __future__ import annotations

import re
import uuid
import zoneinfo
from datetime import datetime
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.settings import DATE_FORMATS

#: ISO 4217 codes offered in every currency select, with the name people read.
#: The frontend ships the same list (``frontend/lib/format.ts`` ``CURRENCIES``); keep the
#: two in step. Banks in the region report in PKR and the Gulf currencies; the majors are
#: there for correspondent banking and vendor contracts.
CURRENCIES: dict[str, str] = {
    "PKR": "Pakistani Rupee",
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "Pound Sterling",
    "AED": "UAE Dirham",
    "SAR": "Saudi Riyal",
    "OMR": "Omani Rial",
    "QAR": "Qatari Riyal",
    "KWD": "Kuwaiti Dinar",
    "BHD": "Bahraini Dinar",
    "CNY": "Chinese Yuan",
    "JPY": "Japanese Yen",
    "INR": "Indian Rupee",
    "BDT": "Bangladeshi Taka",
    "LKR": "Sri Lankan Rupee",
    "AFN": "Afghan Afghani",
    "IRR": "Iranian Rial",
    "TRY": "Turkish Lira",
    "EGP": "Egyptian Pound",
    "JOD": "Jordanian Dinar",
    "MYR": "Malaysian Ringgit",
    "IDR": "Indonesian Rupiah",
    "SGD": "Singapore Dollar",
    "HKD": "Hong Kong Dollar",
    "CHF": "Swiss Franc",
    "CAD": "Canadian Dollar",
    "AUD": "Australian Dollar",
    "NZD": "New Zealand Dollar",
    "SEK": "Swedish Krona",
    "NOK": "Norwegian Krone",
    "DKK": "Danish Krone",
    "ZAR": "South African Rand",
    "KES": "Kenyan Shilling",
    "NGN": "Nigerian Naira",
    "RUB": "Russian Rouble",
    "KRW": "South Korean Won",
    "THB": "Thai Baht",
    "BRL": "Brazilian Real",
    "MXN": "Mexican Peso",
}

RETENTION_MIN_DAYS = 30
RETENTION_MAX_DAYS = 3650

#: Shown while nothing has been saved yet, and used to create the row on first read.
DEFAULTS: dict[str, object] = {
    "currency": "PKR",
    "timezone": "Asia/Karachi",
    "date_format": "DD/MM/YYYY",
    "fiscal_year_start_month": 1,
    "phone_country": "PK",
    "retention_days": 90,
}


@lru_cache(maxsize=1)
def timezone_names() -> frozenset[str]:
    """Every IANA timezone this server's tz database knows."""
    return frozenset(zoneinfo.available_timezones())


def validate_currency(code: str) -> str:
    value = (code or "").strip().upper()
    if value not in CURRENCIES:
        raise ValueError(
            f"'{code}' is not a supported currency; use a three-letter ISO 4217 code such as PKR or USD."
        )
    return value


def validate_timezone(name: str) -> str:
    value = (name or "").strip()
    if value in timezone_names():
        return value
    # A slim image may ship a trimmed tz database listing; a name it can still load is fine.
    try:
        if value and "/" in value:
            zoneinfo.ZoneInfo(value)
            return value
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        pass
    raise ValueError(f"'{name}' is not a known timezone; use an IANA name such as Asia/Karachi.")


def validate_date_format(fmt: str) -> str:
    if fmt not in DATE_FORMATS:
        raise ValueError(f"Date format must be one of: {', '.join(DATE_FORMATS)}.")
    return fmt


def validate_month(month: int) -> int:
    if not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12:
        raise ValueError("Fiscal year start month must be between 1 (January) and 12 (December).")
    return month


def validate_phone_country(code: str) -> str:
    value = (code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise ValueError("Phone country must be a two-letter ISO 3166 country code such as PK.")
    return value


def validate_retention_days(days: int) -> int:
    if not isinstance(days, int) or isinstance(days, bool) or not (
        RETENTION_MIN_DAYS <= days <= RETENTION_MAX_DAYS
    ):
        raise ValueError(
            f"Retention must be between {RETENTION_MIN_DAYS} and {RETENTION_MAX_DAYS} days."
        )
    return days


class TenantSettingsRead(BaseModel):
    """The organisation's settings as every page reads them."""

    model_config = ConfigDict(from_attributes=True)
    currency: str
    timezone: str
    date_format: str
    fiscal_year_start_month: int
    phone_country: str
    retention_days: int
    updated_at: datetime | None = None
    id: uuid.UUID | None = None
    # Phase 3: first-run setup and the organisation's module choice (None = all licensed).
    onboarding_completed_at: datetime | None = None
    enabled_modules: list[str] | None = None
    # Roles that must use MFA here; None = the deployment default. Changed only through
    # PUT /settings/organisation/security/mfa-roles, which validates the role names.
    mfa_required_roles: list[str] | None = None


class TenantSettingsUpdate(BaseModel):
    """Partial update — send only the fields that change."""

    currency: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    fiscal_year_start_month: int | None = None
    phone_country: str | None = None
    retention_days: int | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str | None) -> str | None:
        return None if v is None else validate_currency(v)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v: str | None) -> str | None:
        return None if v is None else validate_timezone(v)

    @field_validator("date_format")
    @classmethod
    def _date_format(cls, v: str | None) -> str | None:
        return None if v is None else validate_date_format(v)

    @field_validator("fiscal_year_start_month")
    @classmethod
    def _month(cls, v: int | None) -> int | None:
        return None if v is None else validate_month(v)

    @field_validator("phone_country")
    @classmethod
    def _phone_country(cls, v: str | None) -> str | None:
        return None if v is None else validate_phone_country(v)

    @field_validator("retention_days")
    @classmethod
    def _retention(cls, v: int | None) -> int | None:
        return None if v is None else validate_retention_days(v)


class CurrencyOption(BaseModel):
    code: str
    name: str


class TenantSettingsOptions(BaseModel):
    """Choices the settings form offers."""

    currencies: list[CurrencyOption]
    date_formats: list[str]
    timezones: list[str]
    retention_min_days: int = RETENTION_MIN_DAYS
    retention_max_days: int = RETENTION_MAX_DAYS
