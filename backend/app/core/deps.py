"""FastAPI dependencies: token decode, tenant-scoped DB session, current user, RBAC."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import tenant_session
from app.core.security import decode_access_token
from app.models.identity import User
from app.services import mfa_policy
from app.services import modules as module_service

bearer_scheme = HTTPBearer(auto_error=True)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def check_session_scope(payload: dict[str, Any], path: str) -> None:
    """Refuse tokens that are not full session tokens, and narrow enrol-only sessions.

    * A token carrying a ``purpose`` claim is a single-use artefact signed with the same
      key — the MFA challenge issued after the password step, the SSO state token — and
      must never be accepted as a bearer session. Without this check the MFA challenge
      alone opened a full session, i.e. the password was enough.
    * A token carrying the MFA enrol-only claim (see ``services/mfa_policy.py``) may
      reach only the enrolment endpoints, ``/auth/me`` and logout; anything else is a
      403 with ``X-Error-Code: mfa_enrolment_required``.
    """
    if payload.get("purpose"):
        raise _CREDENTIALS_EXC
    if payload.get(mfa_policy.ENROL_ONLY_CLAIM) and not mfa_policy.enrol_only_path_allowed(path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=mfa_policy.ENROL_REQUIRED_DETAIL,
            headers={"X-Error-Code": mfa_policy.ENROL_REQUIRED_CODE},
        )


async def get_token_payload(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> dict[str, Any]:
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError as exc:  # noqa: BLE001
        raise _CREDENTIALS_EXC from exc
    # Every authenticated dependency (session, current user, RBAC) hangs off this one,
    # so the MFA enrol-only restriction cannot be skipped by an endpoint that only asks
    # for a DB session.
    check_session_scope(payload, request.url.path)
    # Shared surfaces keyed by a record type (import/export, custom fields, status rules,
    # filters, comments, attestations, record lifecycle, versions) refuse a module the
    # organisation has not licensed or has switched off — its own routers already do
    # (``require_module``), and hanging the check here covers every endpoint at once.
    await module_service.gate_shared_request(request, _tenant_id(payload))
    return payload


def _tenant_id(payload: dict[str, Any]) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(payload["tid"]))
    except (KeyError, ValueError):
        return None


async def get_db(
    payload: Annotated[dict[str, Any], Depends(get_token_payload)],
) -> AsyncIterator[AsyncSession]:
    """Tenant-scoped DB session for the authenticated request.

    The whole request runs in one transaction with ``app.current_tenant`` set to the
    token's tenant, so RLS confines every query to that org.
    """
    async with tenant_session(payload["tid"]) as session:
        yield session


async def get_current_user(
    payload: Annotated[dict[str, Any], Depends(get_token_payload)],
    db: Annotated[AsyncSession, Depends(get_db, scope="function")],
) -> User:
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _CREDENTIALS_EXC from exc

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
# ``scope="function"`` closes the session — and so commits — before the response is
# sent. With the default request scope the commit ran after the response had gone out:
# a constraint or guard failure at commit rolled the write back while the client had
# already been told 200. (Found in the product review; FastAPI >= 0.121.)
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]


async def require_platform_admin(user: CurrentUser) -> User:
    """Gate the deployment-operator endpoints (organisation provisioning).

    Checked against a column rather than a permission code on purpose: permissions live
    in tenant-scoped ``roles`` rows, so an organisation's own admin could mint themselves
    a role carrying any code they liked. The flag sits outside that blast radius.
    """
    if not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires platform administrator access",
        )
    return user


def require(*required: str):
    """Dependency factory enforcing that the current user holds all ``required`` perms."""

    async def checker(user: CurrentUser) -> User:
        if not set(required).issubset(set(user.permission_codes)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires permission(s): {', '.join(required)}",
            )
        return user

    return checker
