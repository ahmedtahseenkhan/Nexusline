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


# ------------------------------------------------------- modules & onboarding (phase 3)
from datetime import datetime, timezone  # noqa: E402

from fastapi import HTTPException, status  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.services import modules as module_service  # noqa: E402


class ModuleChoice(BaseModel):
    """The modules the organisation uses. ``None`` = every module the licence allows."""

    enabled: list[str] | None


class OnboardingStatus(BaseModel):
    completed_at: datetime | None
    frameworks_installed: int
    users: int
    modules_chosen: bool
    locale_set: bool


def module_choice_problem(requested: list[str] | None, available: set[str]) -> str | None:
    """Why a module choice can't be saved, or None. Pure."""
    if requested is None:
        return None
    unknown = sorted(set(requested) - set(module_service.MODULES))
    if unknown:
        return f"Unknown modules: {', '.join(unknown)}."
    blocked = sorted(set(requested) - available)
    if blocked:
        titles = ", ".join(module_service.MODULES[k]["title"] for k in blocked)
        return f"Not available on this installation's licence: {titles}."
    return None


@router.get("/organisation/modules")
async def organisation_modules(db: DbSession, user: CurrentUser) -> list[dict]:
    """Every licensable module with what the licence allows, what the organisation has
    chosen, and whether onboarding recommends it. Any signed-in user."""
    row = await get_or_create_settings(db, user.tenant_id)
    return module_service.module_states(row.enabled_modules)


@router.put("/organisation/modules", dependencies=[Depends(require("settings:manage"))])
async def choose_organisation_modules(body: ModuleChoice, db: DbSession, user: CurrentUser) -> list[dict]:
    """Switch modules on or off for the organisation, within the licence. Core platform
    modules (risk register, controls, compliance, policies…) are never switched off.
    Requires ``settings:manage``; audited."""
    available = {s["key"] for s in module_service.module_states() if s["available"]}
    problem = module_choice_problem(body.enabled, available)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
    row = await get_or_create_settings(db, user.tenant_id)
    before = row.enabled_modules
    row.enabled_modules = sorted(set(body.enabled)) if body.enabled is not None else None
    await db.flush()
    module_service.forget_tenant(user.tenant_id)
    turned_on = sorted(set(row.enabled_modules or available) - set(before or available))
    turned_off = sorted(set(before or available) - set(row.enabled_modules or available))
    await audit.record(
        db, actor=user, action="update", entity_type="tenant_settings", entity_id=row.id,
        summary="Changed the organisation's modules"
        + (f"; on: {', '.join(turned_on)}" if turned_on else "")
        + (f"; off: {', '.join(turned_off)}" if turned_off else ""),
        changes={"enabled_modules": {"from": before, "to": row.enabled_modules}},
    )
    return module_service.module_states(row.enabled_modules)


@router.get("/organisation/onboarding", response_model=OnboardingStatus)
async def onboarding_status(db: DbSession, user: CurrentUser) -> OnboardingStatus:
    """How far the organisation's first-run setup has got."""
    from sqlalchemy import func

    from app.models.compliance import Framework
    from app.models.identity import User

    row = await get_or_create_settings(db, user.tenant_id)
    frameworks = await db.scalar(
        select(func.count()).select_from(Framework).where(Framework.deleted.is_(False))
    ) or 0
    users = await db.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    ) or 0
    defaults = {k: v for k, v in DEFAULTS.items()}
    locale_set = any(getattr(row, k) != v for k, v in defaults.items() if k != "retention_days")
    return OnboardingStatus(
        completed_at=row.onboarding_completed_at,
        frameworks_installed=frameworks,
        users=users,
        modules_chosen=row.enabled_modules is not None,
        locale_set=locale_set,
    )


@router.post(
    "/organisation/onboarding/complete",
    response_model=OnboardingStatus,
    dependencies=[Depends(require("settings:manage"))],
)
async def complete_onboarding(db: DbSession, user: CurrentUser) -> OnboardingStatus:
    """Mark first-run setup done (administrators stop being sent to /onboarding)."""
    row = await get_or_create_settings(db, user.tenant_id)
    if row.onboarding_completed_at is None:
        row.onboarding_completed_at = datetime.now(timezone.utc)
        await db.flush()
        await audit.record(
            db, actor=user, action="update", entity_type="tenant_settings", entity_id=row.id,
            summary="Completed organisation onboarding",
        )
    return await onboarding_status(db, user)
