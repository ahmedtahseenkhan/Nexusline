"""FastAPI dependencies: token decode, tenant-scoped DB session, current user, RBAC."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import tenant_session
from app.core.security import decode_access_token
from app.models.identity import User

bearer_scheme = HTTPBearer(auto_error=True)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_token_payload(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> dict[str, Any]:
    try:
        return decode_access_token(creds.credentials)
    except jwt.PyJWTError as exc:  # noqa: BLE001
        raise _CREDENTIALS_EXC from exc


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
    db: Annotated[AsyncSession, Depends(get_db)],
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
DbSession = Annotated[AsyncSession, Depends(get_db)]


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
