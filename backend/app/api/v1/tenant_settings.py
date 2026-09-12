"""Organisation settings API — ``/settings/organisation``.

* ``GET  /settings/organisation`` — any signed-in user. Returns the organisation's
  currency, timezone, date format, fiscal-year start month, phone country and retention
  window, creating the row with defaults (PKR, Asia/Karachi, DD/MM/YYYY, July, PK,
  90 days) the first time anyone asks. Every page formats dates and money from this.
* ``PATCH /settings/organisation`` — ``settings:manage`` (Admin). Partial update; each
  field is validated (ISO 4217 currency from the shipped list, IANA timezone, a known
  date format, month 1–12, two-letter phone country, retention 30–3650 days) and every
  change is written to the activity log with before/after values.
* ``GET  /settings/organisation/options`` — any signed-in user. The currencies, date
  formats and timezones the form offers.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.deps import CurrentUser, DbSession, require
from app.models.settings import DATE_FORMATS, TenantSettings
from app.schemas.tenant_settings import (
    CURRENCIES,
    DEFAULTS,
    CurrencyOption,
    TenantSettingsOptions,
    TenantSettingsRead,
    TenantSettingsUpdate,
    timezone_names,
)
from app.services import audit

router = APIRouter(prefix="/settings", tags=["settings"])

FIELDS: tuple[str, ...] = tuple(DEFAULTS)


async def get_or_create_settings(db, tenant_id) -> TenantSettings:
    """The tenant's settings row, inserted with defaults if it does not exist yet.

    ``ON CONFLICT DO NOTHING`` on the per-tenant unique constraint, so two pages loading
    at once after an upgrade cannot race each other into a duplicate-key error. Other
    modules may call this to read the tenant currency or timezone server-side.
    """
    row = await db.scalar(select(TenantSettings).where(TenantSettings.tenant_id == tenant_id))
    if row is not None:
        return row
    await db.execute(
        pg_insert(TenantSettings)
        .values(tenant_id=tenant_id, **DEFAULTS)
        .on_conflict_do_nothing(constraint="uq_tenant_settings_tenant")
    )
    return await db.scalar(
        select(TenantSettings)
        .where(TenantSettings.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )


def settings_diff(row: Any, patch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{field: {"from": old, "to": new}}`` for the fields that actually change."""
    return {
        name: {"from": getattr(row, name), "to": value}
        for name, value in patch.items()
        if name in FIELDS and value is not None and getattr(row, name) != value
    }


@router.get("/organisation", response_model=TenantSettingsRead)
async def read_organisation_settings(db: DbSession, user: CurrentUser) -> TenantSettingsRead:
    """The organisation's locale and retention settings. Any signed-in user."""
    return TenantSettingsRead.model_validate(await get_or_create_settings(db, user.tenant_id))


@router.get("/organisation/options", response_model=TenantSettingsOptions)
async def organisation_settings_options(user: CurrentUser) -> TenantSettingsOptions:
    """The choices the settings form offers (currencies, date formats, timezones)."""
    return TenantSettingsOptions(
        currencies=[CurrencyOption(code=c, name=n) for c, n in CURRENCIES.items()],
        date_formats=list(DATE_FORMATS),
        timezones=sorted(timezone_names() | {DEFAULTS["timezone"]}),  # type: ignore[operator]
    )


@router.patch(
    "/organisation",
    response_model=TenantSettingsRead,
    dependencies=[Depends(require("settings:manage"))],
)
async def update_organisation_settings(
    body: TenantSettingsUpdate, db: DbSession, user: CurrentUser
) -> TenantSettingsRead:
    """Change one or more organisation settings. Requires ``settings:manage``; audited."""
    row = await get_or_create_settings(db, user.tenant_id)
    changes = settings_diff(row, body.model_dump(exclude_unset=True))
    if changes:
        for name, change in changes.items():
            setattr(row, name, change["to"])
        await db.flush()
        await audit.record(
            db,
            actor=user,
            action="update",
            entity_type="tenant_settings",
            entity_id=row.id,
            summary="Changed organisation settings: "
            + ", ".join(f"{k.replace('_', ' ')} {v['from']} → {v['to']}" for k, v in changes.items()),
            changes=changes,
        )
        await db.refresh(row)
    return TenantSettingsRead.model_validate(row)
