"""SSO service — OIDC/OAuth2 authorization-code flow with JIT user provisioning."""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_state_token, hash_password
from app.models.identity import Role, User
from app.models.sso import SsoConfig

_TIMEOUT = 8.0


async def get_config(db: AsyncSession) -> SsoConfig | None:
    return await db.scalar(select(SsoConfig))


def authorize_url(cfg: SsoConfig, slug: str, redirect_uri: str) -> str:
    state = create_state_token(slug)
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "scope": cfg.scopes,
        "state": state,
    }
    sep = "&" if "?" in cfg.authorize_url else "?"
    return f"{cfg.authorize_url}{sep}{urlencode(params)}"


async def _exchange_code(cfg: SsoConfig, code: str, redirect_uri: str) -> str:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(cfg.token_url, data=data, headers={"Accept": "application/json"})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Token endpoint unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=401, detail="Token exchange failed")
    token = resp.json().get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="No access token from IdP")
    return token


async def _fetch_userinfo(cfg: SsoConfig, access_token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(cfg.userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Userinfo endpoint unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=401, detail="Userinfo request failed")
    return resp.json()


def _domain_allowed(cfg: SsoConfig, email: str) -> bool:
    allowed = [d.strip().lower() for d in cfg.allowed_domains.split(",") if d.strip()]
    if not allowed:
        return True
    return email.split("@")[-1].lower() in allowed


async def resolve_user(db: AsyncSession, cfg: SsoConfig, tenant_id, code: str, redirect_uri: str) -> User:
    """Run the code->token->userinfo flow and find-or-JIT-provision the matching user."""
    access_token = await _exchange_code(cfg, code, redirect_uri)
    info = await _fetch_userinfo(cfg, access_token)

    email = (info.get(cfg.email_claim) or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail=f"IdP did not return '{cfg.email_claim}'")
    if not _domain_allowed(cfg, email):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email domain not allowed for SSO")

    user = await db.scalar(select(User).where(User.email == email))
    if user is not None:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled")
        return user

    if not cfg.jit_provisioning:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No account for this user (JIT provisioning is off)")

    role = await db.scalar(select(Role).where(Role.name == cfg.default_role))
    user = User(
        tenant_id=tenant_id,
        email=email,
        full_name=info.get(cfg.name_claim) or email.split("@")[0],
        hashed_password=hash_password(secrets.token_urlsafe(24)),  # random; SSO users log in via IdP
        roles=[role] if role else [],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user
