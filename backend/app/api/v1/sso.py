"""SSO API — admin config plus the public OIDC/OAuth2 login + callback flow."""
from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.core.config import settings
from app.core.database import set_session_tenant, system_session
from app.core.deps import DbSession, require
from app.core.security import create_access_token, decode_state_token
from app.models.sso import SsoConfig
from app.models.tenant import Tenant
from app.schemas.auth import TokenResponse
from app.schemas.sso import (
    SsoCallbackRequest,
    SsoConfigRead,
    SsoConfigUpdate,
    SsoLoginResponse,
    SsoStatus,
)
from app.schemas.user import UserRead
from app.services import sso as sso_service

router = APIRouter(prefix="/auth/sso", tags=["sso"])


def _read(cfg: SsoConfig) -> SsoConfigRead:
    out = SsoConfigRead.model_validate(cfg)
    out.client_secret_set = bool(cfg.client_secret)
    return out


# --- Admin configuration (current tenant) ---
@router.get("/config", response_model=SsoConfigRead, dependencies=[Depends(require("sso:manage"))])
async def get_config(db: DbSession) -> SsoConfigRead:
    cfg = await sso_service.get_config(db)
    if cfg is None:
        cfg = SsoConfig()  # unsaved defaults
    return _read(cfg)


@router.put("/config", response_model=SsoConfigRead, dependencies=[Depends(require("sso:manage"))])
async def update_config(body: SsoConfigUpdate, db: DbSession) -> SsoConfigRead:
    cfg = await sso_service.get_config(db)
    data = body.model_dump()
    secret = data.pop("client_secret")
    if cfg is None:
        # tenant_id is set by RLS default? No — set explicitly from session GUC via a fresh row.
        from app.models.identity import User  # local import to avoid cycle

        any_user = await db.scalar(select(User))
        cfg = SsoConfig(tenant_id=any_user.tenant_id)
        db.add(cfg)
    for k, v in data.items():
        setattr(cfg, k, v)
    if secret is not None:
        cfg.client_secret = secret
    await db.flush()
    await db.refresh(cfg)
    return _read(cfg)


# --- Public per-org SSO flow ---
async def _tenant_and_config(slug: str):
    """Resolve tenant by slug and load its SSO config under that tenant's RLS scope."""
    async with system_session() as db:
        tenant = await db.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True)))
        if tenant is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        await set_session_tenant(db, tenant.id)
        cfg = await db.scalar(select(SsoConfig))
        return tenant, cfg


@router.get("/{slug}/status", response_model=SsoStatus)
async def sso_status(slug: str) -> SsoStatus:
    _, cfg = await _tenant_and_config(slug)
    if cfg is None or not cfg.enabled:
        return SsoStatus(enabled=False, provider="")
    return SsoStatus(enabled=True, provider=cfg.provider)


@router.get("/{slug}/login", response_model=SsoLoginResponse)
async def sso_login(slug: str, redirect_uri: str = Query(...)) -> SsoLoginResponse:
    _, cfg = await _tenant_and_config(slug)
    if cfg is None or not cfg.enabled:
        raise HTTPException(status_code=400, detail="SSO is not enabled for this organization")
    return SsoLoginResponse(redirect_url=sso_service.authorize_url(cfg, slug, redirect_uri))


@router.post("/{slug}/callback", response_model=TokenResponse)
async def sso_callback(slug: str, body: SsoCallbackRequest) -> TokenResponse:
    try:
        state = decode_state_token(body.state)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired state") from exc
    if state.get("slug") != slug:
        raise HTTPException(status_code=400, detail="State/organization mismatch")

    async with system_session() as db:
        tenant = await db.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True)))
        if tenant is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        await set_session_tenant(db, tenant.id)
        cfg = await db.scalar(select(SsoConfig))
        if cfg is None or not cfg.enabled:
            raise HTTPException(status_code=400, detail="SSO is not enabled for this organization")

        user = await sso_service.resolve_user(db, cfg, tenant.id, body.code, body.redirect_uri)
        token = create_access_token(
            subject=str(user.id),
            tenant_id=str(tenant.id),
            roles=user.role_names,
            permissions=user.permission_codes,
        )
        return TokenResponse(
            access_token=token,
            expires_in=settings.access_token_expire_minutes * 60,
            user=UserRead.model_validate(user),
        )
