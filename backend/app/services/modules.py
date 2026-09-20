"""Per-installation module entitlements.

The enabled set is resolved from two layers, checked in order:

1. **License** (what the client bought): a valid license whose payload has a
   ``modules`` list restricts optional modules to that list (edition names and
   module keys expand via :func:`app.core.modules.expand_modules`). Licenses
   without a ``modules`` field — and dev installs with no license at all —
   unlock every module, so nothing breaks for existing deployments.
2. **Deploy config** (what the client wants visible): ``DISABLED_MODULES`` in
   the environment / .env subtracts modules the installation has licensed but
   chooses to hide, without a new license.
3. **Organisation choice** (phase 3): ``TenantSettings.enabled_modules`` — the modules
   an organisation has switched on during onboarding or in its settings, within what
   the first two layers allow. NULL means "everything allowed", so organisations that
   predate the choice keep every module.

API enforcement lives in ``require_module`` (attached per-router in
``app/api/v1/router.py``); the frontend mirrors it from ``GET /system/modules``.
"""
from __future__ import annotations

import time
import uuid

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.modules import ALL_MODULE_KEYS, MODULES, expand_modules
from app.services import license as lic


def licensed_modules() -> set[str]:
    """Module keys the current license entitles. Everything when unlicensed/
    unconfigured (dev, self-host) or when the license predates packaging."""
    info = lic.load_current()
    if info.status in ("unlicensed", "unconfigured"):
        # A release build has no unlicensed mode — startup already refuses one, so
        # reaching here means the gate was tampered with. Grant nothing.
        return set() if lic.enforcement_enabled() else set(ALL_MODULE_KEYS)
    if not lic.signature_ok(info):
        # Forged/unreadable license: optional modules lock until a valid one is installed.
        return set()
    # An expired licence keeps its modules (decision 1): grace, then read-only — the bank
    # must still be able to read every record it holds. Writes are refused elsewhere
    # (core/licence_guard.py).
    if info.modules is None:
        return set(ALL_MODULE_KEYS)
    return expand_modules(info.modules)


def config_disabled_modules() -> set[str]:
    return {
        m.strip().lower().replace("-", "_")
        for m in settings.disabled_modules.split(",")
        if m.strip()
    }


def enabled_modules() -> set[str]:
    return licensed_modules() - config_disabled_modules()


def is_enabled(key: str) -> bool:
    if key not in MODULES:  # unknown keys are never gated (core platform)
        return True
    return key in enabled_modules()


#: Modules a new organisation starts with (onboarding pre-ticks them): what a Pakistani
#: bank's risk function uses from day one. Shariah Governance is added for Islamic banks.
STARTER_MODULES: tuple[str, ...] = (
    "operational_risk", "internal_audit", "continuity", "bia",
    "outsourcing", "regulatory_change", "governance_meetings", "aml",
)

# tenant id -> (expires at, enabled set or None). A short cache: the organisation's
# choice is read on every gated request, and it changes rarely.
_TENANT_CACHE: dict[uuid.UUID, tuple[float, frozenset[str] | None]] = {}
_TENANT_TTL_SECONDS = 30.0


def effective_modules(allowed: set[str], organisation_choice: list[str] | None) -> set[str]:
    """What an organisation can use: the installation's allowed set, narrowed by the
    organisation's own choice when it has made one. Pure."""
    if organisation_choice is None:
        return set(allowed)
    return set(allowed) & {k for k in organisation_choice}


def forget_tenant(tenant_id) -> None:
    """Drop the cached choice after the organisation changes it."""
    _TENANT_CACHE.pop(uuid.UUID(str(tenant_id)), None)


async def organisation_choice(tenant_id) -> frozenset[str] | None:
    """The organisation's enabled list (cached briefly), or None for "everything"."""
    from sqlalchemy import select

    from app.core.database import tenant_session
    from app.models.settings import TenantSettings

    tid = uuid.UUID(str(tenant_id))
    hit = _TENANT_CACHE.get(tid)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    async with tenant_session(tid) as db:
        chosen = await db.scalar(select(TenantSettings.enabled_modules))
    value = frozenset(chosen) if isinstance(chosen, list) else None
    _TENANT_CACHE[tid] = (now + _TENANT_TTL_SECONDS, value)
    return value


def _tenant_of(request: Request) -> uuid.UUID | None:
    """The tenant of a signed-in request, without failing: authentication is the auth
    dependency's job. Token-authenticated feeds (KRI, connectors) carry no session and
    resolve their tenant themselves."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        from app.core.security import decode_access_token

        payload = decode_access_token(header.split(" ", 1)[1].strip())
        return uuid.UUID(str(payload["tid"])) if payload.get("tid") else None
    except Exception:  # noqa: BLE001 - not a session token; let auth decide
        return None


def require_module(key: str):
    """Router-level dependency: reject requests to a module that this installation has
    not licensed/enabled, or that the caller's organisation has switched off. Attach in
    api/v1/router.py."""

    async def checker(request: Request = None) -> None:  # type: ignore[assignment]
        # FastAPI always injects the request; the default only lets tests call it bare.
        title = MODULES.get(key, {}).get("title", key)
        if not is_enabled(key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"The {title} module is not enabled on this installation. "
                    "Contact your vendor to update the license."
                ),
            )
        tenant_id = _tenant_of(request) if request is not None else None
        if tenant_id is None or key not in MODULES:
            return
        chosen = await organisation_choice(tenant_id)
        if chosen is not None and key not in chosen:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"The {title} module is switched off for your organisation. An "
                    "administrator can switch it on under Settings → Organisation."
                ),
            )

    return checker


def module_states(organisation: frozenset[str] | list[str] | None = None) -> list[dict]:
    """Full matrix for the System admin view and the frontend nav/route guard.

    ``organisation`` is the caller's organisation choice (None = everything allowed);
    ``enabled`` is what that organisation can actually use."""
    licensed = licensed_modules()
    disabled = config_disabled_modules()
    states = []
    for key, meta in MODULES.items():
        allowed = key in licensed and key not in disabled
        chosen = organisation is None or key in organisation
        states.append(
            {
                "key": key,
                "title": meta["title"],
                "category": meta["category"],
                "description": meta["description"],
                "routes": meta["routes"],
                "licensed": key in licensed,
                "disabled_by_config": key in disabled,
                "available": allowed,
                "enabled_by_organisation": chosen,
                "starter": key in STARTER_MODULES,
                "enabled": allowed and chosen,
            }
        )
    return states
