"""System administration & health — version/feature info, health checks, license
status, database backups, and the redacted support-bundle download.

These power the on-prem "System" admin view and the low-touch support workflow.
Backups and the support bundle require admin (``role:write``); read views require
``role:read``.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.models.identity import User
from app.models.risk import Risk
from app.services import backup, license as lic, modules as module_service, storage, support_bundle

router = APIRouter(prefix="/system", tags=["system"])


def _feature_flags() -> dict:
    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "ldap_enabled": settings.ldap_enabled,
        "mfa_required": settings.mfa_required,
        "enforce_segregation_of_duties": settings.enforce_segregation_of_duties,
        "enforce_license": settings.enforce_license,
        "smtp_configured": bool(settings.smtp_host),
    }


@router.get("/info", dependencies=[Depends(require("role:read"))])
async def system_info() -> dict:
    return {
        "app_version": settings.app_version,
        "deployment_mode": settings.deployment_mode,
        "environment": settings.environment,
        "feature_flags": _feature_flags(),
        "license": lic.load_current().to_public(),
    }


@router.get("/license", dependencies=[Depends(require("role:read"))])
async def license_status() -> dict:
    return lic.load_current(refresh=True).to_public()


@router.get("/modules")
async def module_matrix(user: CurrentUser) -> list[dict]:
    """Per-installation module entitlements. Auth-only (no admin permission):
    every user's navigation is filtered by this, so all roles may read it."""
    return module_service.module_states()


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
    checks["license"] = {"ok": lic_info.valid or lic_info.status in ("unlicensed", "unconfigured"),
                         "status": lic_info.status}
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
