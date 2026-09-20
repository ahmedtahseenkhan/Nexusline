"""Connector secrets at rest.

Secrets (a bind password, an API token) are kept as one Fernet token (AES-128-CBC +
HMAC-SHA256, from ``cryptography``, already a dependency) of their JSON, on
``connectors.secrets_encrypted``; ``connectors.secret_keys`` lists which names are set.
The key is ``settings.connector_secret_key`` when set, else derived from
``settings.secret_key`` with HKDF-SHA256 under a purpose label — so the JWT signing key is
never used directly as an encryption key.

The API never returns a secret: reads carry ``secrets_set`` (names only), writes are
write-only (a name sent with a value replaces it, a name listed in ``clear`` removes it,
anything not sent is kept).
"""
from __future__ import annotations

import base64
import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_PURPOSE = b"nexusline-grc/connector-secrets/v1"
#: What a read shows for a secret that is set.
MASK = "set"


class SecretsUnreadable(Exception):
    """The stored secrets cannot be decrypted with this installation's key."""


@lru_cache(maxsize=4)
def _fernet_for(material: str) -> Fernet:
    raw = material.encode()
    try:
        # A ready Fernet key (44 url-safe base64 chars) is used as is.
        if len(material) == 44 and len(base64.urlsafe_b64decode(raw)) == 32:
            return Fernet(raw)
    except (ValueError, TypeError):
        pass
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_PURPOSE).derive(raw)
    return Fernet(base64.urlsafe_b64encode(key))


def _fernet() -> Fernet:
    from app.core.config import settings

    return _fernet_for(settings.connector_secret_key or settings.secret_key)


def encrypt(values: dict[str, str]) -> str:
    clean = {str(k): str(v) for k, v in (values or {}).items() if v not in (None, "")}
    if not clean:
        return ""
    return _fernet().encrypt(json.dumps(clean, sort_keys=True).encode()).decode()


def decrypt(token: str) -> dict[str, str]:
    if not token:
        return {}
    try:
        data = json.loads(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError) as exc:
        raise SecretsUnreadable(
            "The connector's stored secrets cannot be decrypted with this installation's key "
            "(was SECRET_KEY or CONNECTOR_SECRET_KEY changed?). Enter them again."
        ) from exc
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def merge(current: dict[str, str], incoming: dict[str, str | None] | None, clear: list[str] | None) -> dict[str, str]:
    """Write-only update. Pure. A value replaces; an empty value or a name not sent keeps
    what is stored; a name in ``clear`` removes it."""
    out = dict(current)
    for k, v in (incoming or {}).items():
        if v not in (None, ""):
            out[str(k)] = str(v)
    for k in clear or []:
        out.pop(str(k), None)
    return out


def apply(connector, incoming: dict[str, str | None] | None, clear: list[str] | None) -> list[str]:
    """Update a connector's stored secrets; returns the names that changed (for the
    activity trail, which never records a value)."""
    if not incoming and not clear:
        return []
    try:
        current = decrypt(connector.secrets_encrypted or "")
    except SecretsUnreadable:
        current = {}  # unreadable under this key: what is sent now replaces it
    merged = merge(current, incoming, clear)
    changed = sorted({k for k in set(current) | set(merged) if current.get(k) != merged.get(k)})
    connector.secrets_encrypted = encrypt(merged)
    connector.secret_keys = sorted(merged)
    return changed


def masked(names) -> dict[str, str]:
    return {str(n): MASK for n in (names or [])}
