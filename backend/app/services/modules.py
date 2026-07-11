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

API enforcement lives in ``require_module`` (attached per-router in
``app/api/v1/router.py``); the frontend mirrors it from ``GET /system/modules``.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.modules import ALL_MODULE_KEYS, MODULES, expand_modules
from app.services import license as lic


def licensed_modules() -> set[str]:
    """Module keys the current license entitles. Everything when unlicensed/
    unconfigured (dev, self-host) or when the license predates packaging."""
    info = lic.load_current()
    if info.status in ("unlicensed", "unconfigured"):
        return set(ALL_MODULE_KEYS)
    if not info.valid:
        # Expired/invalid license with enforcement off: platform stays up but
        # optional modules lock until a valid license is installed.
        return set()
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


def require_module(key: str):
    """Router-level dependency: reject requests to a module that this
    installation has not licensed/enabled. Attach in api/v1/router.py."""

    async def checker() -> None:
        if not is_enabled(key):
            title = MODULES.get(key, {}).get("title", key)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"The {title} module is not enabled on this installation. "
                    "Contact your vendor to update the license."
                ),
            )

    return checker


def module_states() -> list[dict]:
    """Full matrix for the System admin view and the frontend nav/route guard."""
    licensed = licensed_modules()
    disabled = config_disabled_modules()
    states = []
    for key, meta in MODULES.items():
        states.append(
            {
                "key": key,
                "title": meta["title"],
                "category": meta["category"],
                "description": meta["description"],
                "routes": meta["routes"],
                "licensed": key in licensed,
                "disabled_by_config": key in disabled,
                "enabled": key in licensed and key not in disabled,
            }
        )
    return states
