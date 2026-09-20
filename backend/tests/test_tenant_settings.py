"""Organisation settings: the validators behind ``PATCH /settings/organisation``.

No database: the validators are pure functions and the update schema runs them, so a
bad currency, timezone, date format, month, phone country or retention window is a 422
before anything is written.
"""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.v1.tenant_settings import settings_diff
from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLES
from app.models.settings import DATE_FORMATS
from app.schemas.tenant_settings import (
    CURRENCIES,
    DEFAULTS,
    RETENTION_MAX_DAYS,
    RETENTION_MIN_DAYS,
    TenantSettingsUpdate,
    validate_currency,
    validate_date_format,
    validate_month,
    validate_phone_country,
    validate_retention_days,
    validate_timezone,
)


# ---------------------------------------------------------------- currency ---
@pytest.mark.parametrize(
    "code", ["PKR", "USD", "EUR", "GBP", "AED", "SAR", "OMR", "QAR", "KWD", "BHD", "CNY", "JPY", "INR"]
)
def test_required_currencies_are_offered(code):
    assert code in CURRENCIES
    assert validate_currency(code) == code


def test_currency_is_normalised_to_upper_case():
    assert validate_currency(" pkr ") == "PKR"


@pytest.mark.parametrize("bad", ["", "$", "RS", "PKRX", "XYZ", "rupees"])
def test_unknown_currency_is_refused(bad):
    with pytest.raises(ValueError, match="ISO 4217"):
        validate_currency(bad)


def test_every_currency_code_is_three_letters():
    assert all(len(c) == 3 and c.isupper() for c in CURRENCIES)


# ---------------------------------------------------------------- timezone ---
@pytest.mark.parametrize("tz", ["Asia/Karachi", "Asia/Dubai", "Europe/London", "UTC"])
def test_known_timezones_are_accepted(tz):
    assert validate_timezone(tz) == tz


@pytest.mark.parametrize("bad", ["", "Karachi", "PKT", "Asia/Lahore", "GMT+5"])
def test_unknown_timezone_is_refused(bad):
    with pytest.raises(ValueError, match="timezone"):
        validate_timezone(bad)


# -------------------------------------------------------------- date format ---
@pytest.mark.parametrize("fmt", DATE_FORMATS)
def test_supported_date_formats(fmt):
    assert validate_date_format(fmt) == fmt


@pytest.mark.parametrize("bad", ["", "dd/mm/yyyy", "D/M/Y", "YYYY/MM/DD"])
def test_unsupported_date_format_is_refused(bad):
    with pytest.raises(ValueError, match="Date format"):
        validate_date_format(bad)


# ------------------------------------------------------------------ bounds ---
@pytest.mark.parametrize("month", [1, 7, 12])
def test_fiscal_month_in_range(month):
    assert validate_month(month) == month


@pytest.mark.parametrize("month", [0, 13, -1])
def test_fiscal_month_out_of_range(month):
    with pytest.raises(ValueError):
        validate_month(month)


@pytest.mark.parametrize("days", [RETENTION_MIN_DAYS, 730, 3650, RETENTION_MAX_DAYS])
def test_retention_within_bounds(days):
    assert validate_retention_days(days) == days


@pytest.mark.parametrize("days", [0, 29, 90, 364, RETENTION_MAX_DAYS + 1, -90])
def test_retention_outside_bounds(days):
    with pytest.raises(ValueError, match="Retention"):
        validate_retention_days(days)


def test_retention_bounds_are_one_to_ten_years():
    assert (RETENTION_MIN_DAYS, RETENTION_MAX_DAYS) == (365, 3650)


@pytest.mark.parametrize("code,expected", [("pk", "PK"), ("AE", "AE"), (" gb ", "GB")])
def test_phone_country_two_letters(code, expected):
    assert validate_phone_country(code) == expected


@pytest.mark.parametrize("bad", ["", "PAK", "P", "92", "+92"])
def test_phone_country_refused(bad):
    with pytest.raises(ValueError, match="two-letter"):
        validate_phone_country(bad)


# ---------------------------------------------------------- update schema ---
def test_update_schema_runs_the_validators():
    body = TenantSettingsUpdate(currency="usd", phone_country="ae")
    assert body.currency == "USD" and body.phone_country == "AE"
    for bad in (
        {"currency": "XYZ"},
        {"timezone": "Mars/Olympus"},
        {"date_format": "YY"},
        {"fiscal_year_start_month": 13},
        {"retention_days": 7},
        {"phone_country": "PAK"},
    ):
        with pytest.raises(ValidationError):
            TenantSettingsUpdate(**bad)


def test_partial_update_leaves_other_fields_unset():
    body = TenantSettingsUpdate(retention_days=1825)
    assert body.model_dump(exclude_unset=True) == {"retention_days": 1825}


def test_defaults_are_themselves_valid():
    assert validate_currency(DEFAULTS["currency"]) == "PKR"
    assert validate_timezone(DEFAULTS["timezone"]) == "Asia/Karachi"
    assert validate_date_format(DEFAULTS["date_format"]) in DATE_FORMATS
    assert validate_month(DEFAULTS["fiscal_year_start_month"]) == 1  # calendar year
    assert validate_phone_country(DEFAULTS["phone_country"]) == "PK"
    assert validate_retention_days(DEFAULTS["retention_days"]) == 3650


# ------------------------------------------------------------------- audit ---
def test_diff_records_only_real_changes():
    row = SimpleNamespace(**DEFAULTS)
    diff = settings_diff(row, {"currency": "USD", "timezone": "Asia/Karachi", "retention_days": None})
    assert diff == {"currency": {"from": "PKR", "to": "USD"}}


def test_diff_is_empty_when_nothing_changes():
    assert settings_diff(SimpleNamespace(**DEFAULTS), dict(DEFAULTS)) == {}


# ------------------------------------------------------------- permission ---
def test_settings_permission_is_admin_only_by_default():
    assert "settings:manage" in ALL_PERMISSIONS
    holders = [name for name, (_d, codes) in DEFAULT_ROLES.items() if "settings:manage" in codes]
    assert holders == ["Admin"]
