"""LDAP / Active Directory configuration admin API (one config per tenant)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.ldap_config import LdapConfig
from app.schemas.auth import LdapConfigRead, LdapConfigUpdate

router = APIRouter(prefix="/auth/ldap", tags=["auth"])


def _read(cfg: LdapConfig) -> LdapConfigRead:
    data = LdapConfigRead.model_validate(cfg)
    data.bind_password_set = bool(cfg.bind_password)
    return data


@router.get("/config", response_model=LdapConfigRead, dependencies=[Depends(require("role:read"))])
async def get_ldap_config(db: DbSession, user: CurrentUser) -> LdapConfigRead:
    cfg = await db.scalar(select(LdapConfig))
    if cfg is None:
        # Return defaults (disabled) so the admin UI has something to render.
        return LdapConfigRead(
            enabled=False, host="", port=389, use_ssl=False, start_tls=True,
            bind_dn="", base_dn="", user_filter="(userPrincipalName={username})",
            email_attribute="mail", name_attribute="displayName", default_role="Viewer",
            bind_password_set=False,
        )
    return _read(cfg)


@router.put("/config", response_model=LdapConfigRead, dependencies=[Depends(require("role:write"))])
async def put_ldap_config(body: LdapConfigUpdate, db: DbSession, user: CurrentUser) -> LdapConfigRead:
    cfg = await db.scalar(select(LdapConfig))
    if cfg is None:
        cfg = LdapConfig(tenant_id=user.tenant_id)
        db.add(cfg)

    for field in (
        "enabled", "host", "port", "use_ssl", "start_tls", "bind_dn", "base_dn",
        "user_filter", "email_attribute", "name_attribute", "default_role",
    ):
        setattr(cfg, field, getattr(body, field))
    # Only overwrite the stored bind password when a new one is supplied.
    if body.bind_password is not None:
        cfg.bind_password = body.bind_password

    await db.flush()
    return _read(cfg)
