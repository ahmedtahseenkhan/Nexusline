"""System administration & health — version/feature info, health checks, license
status, database backups, and the redacted support-bundle download.

These power the on-prem "System" admin view and the low-touch support workflow.
Backups and the support bundle require admin (``role:write``); read views require
``role:read``.
"""
from __future__ import annotations

from urllib.parse import quote

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.models.identity import User
from app.models.risk import Risk
from app.services import backup, license as lic, licence_state, modules as module_service, storage, support_bundle

logger = logging.getLogger("nexusline.system")

router = APIRouter(prefix="/system", tags=["system"])


def _feature_flags() -> dict:
    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "ldap_enabled": settings.ldap_enabled,
        "mfa_required": settings.mfa_required,
        "mfa_required_roles": settings.mfa_required_roles,
        "mfa_grace_days": settings.mfa_grace_days,
        "enforce_segregation_of_duties": settings.enforce_segregation_of_duties,
        "enforce_license": lic.enforcement_enabled(),
        "smtp_configured": bool(settings.smtp_host),
    }


@router.get("/info", dependencies=[Depends(require("role:read"))])
async def system_info() -> dict:
    state = licence_state.current()
    return {
        "app_version": settings.app_version,
        "deployment_mode": settings.deployment_mode,
        "environment": settings.environment,
        "feature_flags": _feature_flags(),
        "license": licence_payload(
            lic.load_current(), state, await _seats_used_or_none() if state.seats_limit else None,
        ),
    }


async def _seats_used_or_none() -> int | None:
    """Active seats, or ``None`` when they cannot be counted (never fails a status read)."""
    try:
        return await licence_state.seats_used()
    except Exception:  # noqa: BLE001
        return None


def licence_payload(info, state, seats_used: int | None) -> dict:
    """The verified licence fields plus its lifecycle state (decision 1)."""
    return {**info.to_public(), "lifecycle": state.to_public(seats_used)}


@router.get("/license", dependencies=[Depends(require("role:read"))])
async def license_status() -> dict:
    info = lic.load_current(refresh=True)
    state = licence_state.current()
    return licence_payload(info, state, await _seats_used_or_none() if state.seats_limit else None)


class LicenceInstall(BaseModel):
    #: The licence token exactly as the vendor issued it (the content of ``license.key``).
    token: str = Field(min_length=1, max_length=20000)


@router.post("/license", dependencies=[Depends(require("role:write"))])
async def install_license(body: LicenceInstall, user: CurrentUser) -> dict:
    """Install a renewed licence without a restart. Verified against the vendor key built
    into this image, written to ``LICENSE_FILE`` (the previous file kept as
    ``.previous``), then the licence state is re-read at once. Allowed in read-only mode.
    Recorded in the activity log of the installing administrator's organisation."""
    from app.core.database import tenant_session
    from app.services import audit

    before = licence_state.current()
    try:
        info = lic.install_token(body.token)
    except lic.LicenceInstallError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"The licence is valid but could not be written to {settings.license_file}: {exc.strerror or exc}",
        ) from exc
    licence_state.reset_daily_check()
    state = licence_state.current()
    try:
        async with tenant_session(user.tenant_id) as db:
            await audit.record(
                db, actor=user, action="licence_install", entity_type="licence", entity_id=None,
                summary=f"Installed a licence for {info.licensed_to} expiring {info.expires or 'never'}"[:500],
                changes={
                    "state": {"from": before.state, "to": state.state},
                    "expires": {"from": before.expires.isoformat() if before.expires else None, "to": info.expires or None},
                    "seats": info.seats, "plan": info.plan,
                },
            )
    except Exception:  # noqa: BLE001 - the licence is installed; a missing log line must not undo that
        logger.exception("Could not record the licence installation in the activity log")
    return licence_payload(info, state, await _seats_used_or_none() if state.seats_limit else None)


def license_banner_state(status: str, enforcing: bool) -> dict:
    """What every signed-in user should be told about the licence.

    ``evaluation_build`` is true for a dev/self-host build running without a licence —
    the one state in which everything is unlocked. It changes nothing about enforcement
    (a release image with no valid licence refuses to start, see ``core/build.py``); it
    exists so nobody mistakes an evaluation build for a production one.
    """
    evaluation = not enforcing and status in ("unlicensed", "unconfigured")
    return {"license_status": status, "evaluation_build": evaluation, "enforce_license": enforcing}


#: Permission that makes a user a licence administrator for banners (expiry, seats).
LICENCE_ADMIN_PERMISSIONS = ("settings:manage", "role:write")


def licence_banner(state, *, is_admin: bool, seats_used: int | None) -> dict | None:
    """What the app shell shows about the licence lifecycle, or ``None``. Pure.

    Everyone sees read-only mode (their writes are refused, they should know why).
    Administrators also see the expiry countdown from 60 days before, the grace period,
    and the seat warning at 90%."""
    seats = licence_state.seat_status(state.seats_limit, seats_used)
    if state.read_only:
        return {"tone": "critical", "state": state.state, "message": state.message}
    if not is_admin:
        return None
    if state.state in ("grace", "read_only"):
        return {"tone": "critical", "state": state.state, "message": state.message}
    if state.state == "expiring":
        tone = "critical" if (state.days_to_expiry or 0) <= 7 else "warning"
        return {"tone": tone, "state": state.state, "message": state.message}
    if state.enforcing and seats["seats_warning"]:
        return {
            "tone": "critical" if seats["seats_full"] else "warning", "state": "seats",
            "message": (
                f"{seats_used} of {state.seats_limit} licensed users are active. "
                + ("New or re-activated users are refused until a seat is freed or more are licensed."
                   if seats["seats_full"] else "Ask your vendor for more seats before the limit is reached.")
            ),
        }
    return None


@router.get("/status")
async def system_status(user: CurrentUser) -> dict:
    """Auth-only deployment status for the app shell: licence state (drives the
    "Unlicensed evaluation build" banner and the licence lifecycle banner) and the
    version. No admin permission — every user sees the banner, so every user may read
    this; seat counts are only included for administrators."""
    info = lic.load_current()
    state = licence_state.current()
    codes = set(getattr(user, "permission_codes", None) or ())
    is_admin = any(p in codes for p in LICENCE_ADMIN_PERMISSIONS)
    seats_used = await _seats_used_or_none() if (is_admin and state.enforcing and state.seats_limit) else None
    lifecycle = state.to_public(seats_used if is_admin else None)
    if not is_admin:
        lifecycle.pop("seats_limit", None)
        lifecycle.pop("licensed_to", None)
    return {
        **license_banner_state(info.status, lic.enforcement_enabled()),
        "licence": lifecycle,
        "licence_banner": licence_banner(state, is_admin=is_admin, seats_used=seats_used),
        "app_version": settings.app_version,
        "deployment_mode": settings.deployment_mode,
    }


@router.get("/modules")
async def module_matrix(user: CurrentUser) -> list[dict]:
    """Module entitlements for the caller's organisation (licence, deployment setting,
    and the organisation's own choice). Auth-only (no admin permission): every user's
    navigation is filtered by this, so all roles may read it."""
    chosen = await module_service.organisation_choice(user.tenant_id)
    return module_service.module_states(chosen)


@router.get("/health", dependencies=[Depends(require("role:read"))])
async def system_health(db: DbSession) -> dict:
    checks: dict[str, dict] = {}

    # Database connectivity
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "detail": str(exc)[:200]}

    # File storage writable
    try:
        from pathlib import Path
        import uuid as _uuid
        root = Path(settings.file_storage_dir)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".healthcheck-{_uuid.uuid4().hex}"
        probe.write_text("ok")
        probe.unlink()
        checks["file_storage"] = {"ok": True, "path": str(root)}
    except Exception as exc:  # noqa: BLE001
        checks["file_storage"] = {"ok": False, "detail": str(exc)[:200]}

    lic_info = lic.load_current()
    lic_state = licence_state.current()
    # Unlicensed is a healthy state only in a dev build; a release image must hold a
    # current license. Grace still works fully but is reported degraded so it is noticed;
    # read-only is degraded.
    lic_ok = lic_state.state in ("active", "expiring", "evaluation")
    checks["license"] = {"ok": lic_ok, "status": lic_info.status, "state": lic_state.state}
    checks["scheduler"] = {"ok": True, "enabled": settings.scheduler_enabled}
    checks["email"] = {"ok": True, "configured": bool(settings.smtp_host)}

    overall = all(c.get("ok", False) for c in checks.values())
    return {"status": "ok" if overall else "degraded", "checks": checks}


@router.get("/backups", dependencies=[Depends(require("role:read"))])
async def list_backups() -> list[dict]:
    return backup.list_backups()


@router.post("/backups", dependencies=[Depends(require("role:write"))], status_code=201)
async def create_backup(user: CurrentUser) -> dict:
    try:
        return await backup.create_backup()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/support-bundle", dependencies=[Depends(require("role:write"))])
async def download_support_bundle(db: DbSession, user: CurrentUser) -> Response:
    # Gather a little RLS-scoped context (counts) for triage.
    user_count = await db.scalar(select(func.count()).select_from(User)) or 0
    risk_count = await db.scalar(
        select(func.count()).select_from(Risk).where(Risk.deleted.is_(False))
    ) or 0
    extra = {
        "tenant_id": str(user.tenant_id),
        "requested_by": user.email,
        "counts": {"users": user_count, "risks": risk_count},
    }
    filename, data = support_bundle.build_bundle(extra)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
