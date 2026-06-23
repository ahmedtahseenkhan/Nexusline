"""Password hashing and JWT issue/verify helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(
    subject: str,
    tenant_id: str,
    roles: list[str],
    permissions: list[str],
    expires_minutes: int | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "tid": tenant_id,
        "roles": roles,
        "perms": permissions,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode/verify a token. Raises ``jwt.PyJWTError`` on any failure."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def create_state_token(tenant_slug: str, expires_minutes: int = 10) -> str:
    """Short-lived signed CSRF/state token for the SSO redirect round-trip."""
    payload = {
        "purpose": "sso_state",
        "slug": tenant_slug,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_state_token(token: str) -> dict[str, Any]:
    data = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if data.get("purpose") != "sso_state":
        raise jwt.InvalidTokenError("not a state token")
    return data
