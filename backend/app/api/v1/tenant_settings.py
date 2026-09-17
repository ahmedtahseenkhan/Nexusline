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
* ``GET  /settings/organisation/security`` — ``settings:manage``. The MFA policy: which
  roles must use MFA and why (listed, administrator, approves, everyone), the grace
  period, SSO and e-mail approval links, and the users required but not yet enrolled.
* ``PUT  /settings/organisation/security/mfa-roles`` — ``settings:manage``. The roles
  that must use MFA (validated against the organisation's roles; the administrator
  role is always kept; ``null`` = the deployment default). Audited.
* ``GET  /settings/organisation/governance`` — ``settings:manage``. Segregation-of-duties
  readiness: active users, approval routes and who holds their roles, rules in force.
"""
from __future__ import annotations

import uuid
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

from app.services import default_governance  # noqa: E402
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
    # F-06: maker-checker needs a second person. ``needs_second_user`` is true while
    # segregation of duties is on and only one user is active.
    sod_enforced: bool = True
    needs_second_user: bool = False
    approval_routes_enabled: int = 0
    role_gaps: list[str] = []


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
    governance = await default_governance.governance_status(db)
    return OnboardingStatus(
        completed_at=row.onboarding_completed_at,
        frameworks_installed=frameworks,
        users=users,
        modules_chosen=row.enabled_modules is not None,
        locale_set=locale_set,
        sod_enforced=governance["sod_enforced"],
        needs_second_user=governance["needs_second_user"],
        approval_routes_enabled=sum(1 for r in governance["routes"] if r["enabled"]),
        role_gaps=[g["message"] for g in governance["role_gaps"]],
    )


@router.post(
    "/organisation/onboarding/complete",
    response_model=OnboardingStatus,
    dependencies=[Depends(require("settings:manage"))],
)
async def complete_onboarding(db: DbSession, user: CurrentUser) -> OnboardingStatus:
    """Mark first-run setup done (administrators stop being sent to /onboarding)."""
    row = await get_or_create_settings(db, user.tenant_id)
    # Leave set-up with the segregation-of-duties baseline even if routes or rules were
    # removed along the way (only what is missing is added; nothing is overwritten).
    await default_governance.ensure_default_governance(db, user.tenant_id, actor=user)
    if row.onboarding_completed_at is None:
        row.onboarding_completed_at = datetime.now(timezone.utc)
        await db.flush()
        await audit.record(
            db, actor=user, action="update", entity_type="tenant_settings", entity_id=row.id,
            summary="Completed organisation onboarding",
        )
    return await onboarding_status(db, user)


# ---------------------------------------------- security: MFA by role, SoD readiness (F-06)
from app.core.config import settings as app_settings  # noqa: E402
from app.services import mfa_policy  # noqa: E402


class MfaRoleRow(BaseModel):
    name: str
    is_system: bool
    #: ``everyone`` / ``protected`` / ``listed`` / ``approves`` / ``not_required``
    #: (see ``mfa_policy.role_requirement``).
    requirement: str
    #: Required and switched on in the organisation's list (the toggle's state).
    listed: bool
    #: The toggle cannot be switched off: the administrator role, or MFA for everyone.
    locked: bool
    approve_permissions: list[str]
    active_users: int
    not_enrolled: int


class MfaPendingUser(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    roles: list[str]
    #: ``required`` (grace running, or starts at next sign-in) or ``overdue``.
    status: str
    due: datetime | None


class SecurityPolicyRead(BaseModel):
    mfa_required_for_everyone: bool
    grace_days: int
    deployment_roles: list[str]
    #: The organisation's own list; ``None`` = the deployment default applies.
    organisation_roles: list[str] | None
    effective_roles: list[str]
    protected_roles: list[str]
    sso_enabled: bool
    email_actions_enabled: bool
    roles: list[MfaRoleRow]
    pending_users: list[MfaPendingUser]
    enrolled_users: int
    required_users: int


class MfaRolesUpdate(BaseModel):
    """The roles that must use MFA. ``None`` = go back to the deployment default."""

    required_roles: list[str] | None


class GovernanceStage(BaseModel):
    name: str
    role: str | None
    holders: int | None


class GovernanceRoute(BaseModel):
    id: uuid.UUID
    entity_type: str
    name: str
    enabled: bool
    stages: list[GovernanceStage]


class GovernanceRoleGap(BaseModel):
    role: str
    routes: list[str]
    message: str


class GovernanceStatus(BaseModel):
    sod_enforced: bool
    active_users: int
    needs_second_user: bool
    second_user_message: str | None
    routes: list[GovernanceRoute]
    rules_total: int
    rules_enabled: int
    role_gaps: list[GovernanceRoleGap]


async def _security_policy(db) -> SecurityPolicyRead:
    from sqlalchemy.orm import selectinload

    from app.models.identity import Role, User

    row_roles = await mfa_policy.tenant_required_roles(db)
    effective = mfa_policy.effective_required_roles(row_roles, app_settings.mfa_required_roles)
    everyone = bool(app_settings.mfa_required)
    roles = (await db.scalars(select(Role).order_by(Role.name))).all()
    users = (await db.scalars(
        select(User).where(User.is_active.is_(True))
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .order_by(User.email)
    )).all()
    statuses = await mfa_policy.statuses_for(db, users, app_settings)
    effective_keys = {r.strip().lower() for r in effective}
    role_rows = []
    for role in roles:
        codes = sorted(p.code for p in role.permissions)
        holders = [u for u in users if any(r.id == role.id for r in u.roles)]
        role_rows.append(MfaRoleRow(
            name=role.name,
            is_system=role.is_system,
            requirement=mfa_policy.role_requirement(
                role_name=role.name, permission_codes=codes,
                required_roles=effective, global_required=everyone,
            ),
            listed=role.name.strip().lower() in effective_keys,
            locked=everyone or mfa_policy.is_protected_role(role.name),
            approve_permissions=[c for c in codes if c.endswith(mfa_policy.PRIVILEGED_PERMISSION_SUFFIX)],
            active_users=len(holders),
            not_enrolled=sum(1 for u in holders if statuses[u.id][0] in ("required", "overdue")),
        ))
    pending = [
        MfaPendingUser(
            id=u.id, email=u.email, full_name=u.full_name or "", roles=u.role_names,
            status=statuses[u.id][0], due=statuses[u.id][1],
        )
        for u in users if statuses[u.id][0] in ("required", "overdue")
    ]
    pending.sort(key=lambda p: (p.status != "overdue", p.due is None, p.due or datetime.max.replace(tzinfo=timezone.utc)))
    return SecurityPolicyRead(
        mfa_required_for_everyone=everyone,
        grace_days=app_settings.mfa_grace_days,
        deployment_roles=list(app_settings.mfa_required_roles),
        organisation_roles=row_roles,
        effective_roles=effective,
        protected_roles=[r.name for r in roles if mfa_policy.is_protected_role(r.name)],
        sso_enabled=await mfa_policy.sso_enabled(db),
        email_actions_enabled=bool(app_settings.email_actions_enabled),
        roles=role_rows,
        pending_users=pending,
        enrolled_users=sum(1 for u in users if u.mfa_enabled),
        required_users=sum(
            1 for u in users if mfa_policy.user_requires_mfa(u, app_settings, row_roles)
        ),
    )


@router.get(
    "/organisation/security",
    response_model=SecurityPolicyRead,
    dependencies=[Depends(require("settings:manage"))],
)
async def organisation_security(db: DbSession, user: CurrentUser) -> SecurityPolicyRead:
    """Who must use two-factor authentication here, why, and who has not enrolled yet."""
    return await _security_policy(db)


@router.put(
    "/organisation/security/mfa-roles",
    response_model=SecurityPolicyRead,
    dependencies=[Depends(require("settings:manage"))],
)
async def update_mfa_roles(body: MfaRolesUpdate, db: DbSession, user: CurrentUser) -> SecurityPolicyRead:
    """Choose the roles that must use MFA. Names must be roles of this organisation; the
    administrator role is always kept. ``null`` returns to the deployment default.
    Requires ``settings:manage``; audited."""
    from app.models.identity import Role

    row = await get_or_create_settings(db, user.tenant_id)
    before = row.mfa_required_roles
    if body.required_roles is None:
        after = None
    else:
        names = (await db.scalars(select(Role.name))).all()
        after, problem = mfa_policy.validate_required_roles(body.required_roles, names)
        if problem:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
    if after != before:
        row.mfa_required_roles = after
        await db.flush()
        shown = lambda v: ", ".join(v) if v is not None else "deployment default"  # noqa: E731
        await audit.record(
            db, actor=user, action="update", entity_type="tenant_settings", entity_id=row.id,
            summary=f"Changed the roles that must use MFA: {shown(before)} → {shown(after)}",
            changes={"mfa_required_roles": {"from": before, "to": after}},
        )
    return await _security_policy(db)


@router.get(
    "/organisation/governance",
    response_model=GovernanceStatus,
    dependencies=[Depends(require("settings:manage"))],
)
async def organisation_governance(db: DbSession, user: CurrentUser) -> GovernanceStatus:
    """Segregation-of-duties readiness: active users, approval routes and whether anyone
    holds the roles they are assigned to, and the dual-control rules in force."""
    return GovernanceStatus.model_validate(await default_governance.governance_status(db))
