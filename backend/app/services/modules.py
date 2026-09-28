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
``app/api/v1/router.py``) and, for the platform surfaces that reach a record by its type
rather than by a module's URL, in :func:`gate_shared_request` (run for every
authenticated request); the frontend mirrors it from ``GET /system/modules``.
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


async def module_refusal(key: str, tenant_id: uuid.UUID | None) -> str | None:
    """Why ``key`` can't be used by this organisation right now, or None when it can.

    The one rule behind every module gate — the per-router ``require_module``, the shared
    surfaces keyed by a record type (:func:`gate_shared_request`) and the listings that
    leave a switched-off module out: licensed and not disabled on the installation, then
    switched on by the organisation. Unknown keys are core platform and never refused.
    """
    if key not in MODULES:
        return None
    title = MODULES[key]["title"]
    if not is_enabled(key):
        return (
            f"The {title} module is not enabled on this installation. "
            "Contact your vendor to update the license."
        )
    if tenant_id is None:
        return None
    chosen = await organisation_choice(tenant_id)
    if chosen is not None and key not in chosen:
        return (
            f"The {title} module is switched off for your organisation. An "
            "administrator can switch it on under Settings → Organisation."
        )
    return None


async def usable_modules(tenant_id: uuid.UUID | None) -> set[str]:
    """Every module this organisation can use now (installation ∩ organisation choice)."""
    allowed = enabled_modules()
    if tenant_id is None:
        return allowed
    return effective_modules(allowed, await organisation_choice(tenant_id))


def require_module(key: str):
    """Router-level dependency: reject requests to a module that this installation has
    not licensed/enabled, or that the caller's organisation has switched off. Attach in
    api/v1/router.py."""

    async def checker(request: Request = None) -> None:  # type: ignore[assignment]
        # FastAPI always injects the request; the default only lets tests call it bare.
        tenant_id = _tenant_of(request) if request is not None else None
        detail = await module_refusal(key, tenant_id)
        if detail:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    return checker


# ---------------------------------------------------- shared, type-keyed surfaces ---
# ``require_module`` guards each module's own routers, but a record is also reachable
# through platform surfaces keyed by its type rather than by URL prefix: import/export
# (``/io/key-risk-indicators/…``), custom fields (``/custom-fields/key_risk_indicator/…``
# and ``{"model": …}`` in a body), status rules, saved filters, comments/tags/files,
# attestations, record lifecycle and version history. Gating only the prefixes left all
# of those open for a module the bank never bought or switched off — a KRI could be
# exported, imported and custom-fielded with Operational Risk off. These maps resolve a
# type key to its module so one check covers every such surface.

#: Permission namespace → the licensable module whose records it guards. Every record
#: type's read permission (``entity_types``, the import registry) lives in exactly one
#: namespace, so a new record type in a gated module is gated with no further change.
PERMISSION_MODULES: dict[str, str] = {
    "shariah": "shariah",
    "aml": "aml",
    "fraud": "fraud",
    "whistle": "whistleblowing",
    "oprisk": "operational_risk",
    "scenario": "scenario_analysis",
    "modelrisk": "model_risk",
    "riskquant": "risk_quantification",
    "icfr": "icfr",
    "bcp": "continuity",
    "bia": "bia",
    "privacy": "privacy",
    "dpo": "data_protection",
    "internal_audit": "internal_audit",
    "review": "access_reviews",
    "declaration": "declarations",
    "governance": "governance_meetings",
    "authority": "authority",
    "awareness": "awareness",
    "esg": "esg",
    "vuln": "vulnerability",
    "ccm": "integrations_ccm",
    "outsourcing": "outsourcing",
    "regchange": "regulatory_change",
}


def module_for_permission(perm: str | None) -> str | None:
    """``"oprisk:read"`` → ``"operational_risk"``; None for core-platform permissions."""
    if not perm:
        return None
    return PERMISSION_MODULES.get(perm.split(":", 1)[0])


def module_for_entity_type(entity_type: str | None) -> str | None:
    """The module a polymorphic entity type (or custom-field key) belongs to, or None
    for core records and unknown keys (the endpoint's own validation answers those)."""
    if not entity_type:
        return None
    from app.models.custom_field import custom_field_entity_type
    from app.services.entity_types import ENTITY_TYPES

    found = ENTITY_TYPES.get(custom_field_entity_type(entity_type))
    return module_for_permission(found.read_perm) if found else None


def module_for_resource(resource: str | None) -> str | None:
    """The module an import/export resource (``key-risk-indicators``) belongs to."""
    if not resource:
        return None
    from app.services.import_registry import REGISTRY

    res = REGISTRY.get(resource)
    return module_for_permission(res.read_perm) if res is not None else None


#: Path shapes that carry a record-type key, as (leading segments, index of the key,
#: resolver). Segments are counted after ``/api/v1``. Non-type words in the key position
#: (``/collab/tags``, ``/attestations/<id>/confirm``, ``/io/resources``) resolve to no
#: module and pass through untouched.
_KEYED_PATHS: tuple[tuple[tuple[str, ...], int, str], ...] = (
    (("io",), 1, "resource"),
    (("custom-fields",), 1, "entity"),
    (("collab",), 1, "entity"),
    (("attestations",), 1, "entity"),
    (("records",), 1, "entity"),
    (("versions", "record"), 2, "entity"),
    (("status-rules", "fields"), 2, "entity"),
    (("status-rules", "evaluate"), 2, "entity"),
    (("filters", "fields"), 2, "entity"),
)
#: Collections whose create/update body (or list query) names the record type in
#: ``model``.
_MODEL_BODY_PATHS: frozenset[str] = frozenset({"custom-fields", "status-rules", "filters"})
_API_PREFIX = "/api/v1/"


def _resolve(kind: str, key: str) -> str | None:
    try:
        return module_for_resource(key) if kind == "resource" else module_for_entity_type(key)
    except Exception:  # noqa: BLE001 - a registry that fails to import gates nothing
        return None


def modules_named_by_path(path: str) -> set[str]:
    """Modules a request path addresses through a type key. Pure apart from the
    registries; the router prefixes of a module are ``require_module``'s job."""
    if not path.startswith(_API_PREFIX):
        return set()
    parts = [p for p in path[len(_API_PREFIX):].split("/") if p]
    out: set[str] = set()
    for lead, index, kind in _KEYED_PATHS:
        if len(parts) > index and tuple(parts[: len(lead)]) == lead:
            module = _resolve(kind, parts[index])
            if module:
                out.add(module)
    return out


async def modules_named_by_request(request: Request) -> set[str]:
    """:func:`modules_named_by_path` plus a ``model`` named in the query string, or in
    the JSON body of a create/update on a type-keyed collection (``POST /custom-fields
    {"model": "key_risk_indicator"}``)."""
    path = request.url.path
    out = modules_named_by_path(path)
    parts = [p for p in path[len(_API_PREFIX):].split("/") if p] if path.startswith(_API_PREFIX) else []
    if not parts or parts[0] not in _MODEL_BODY_PATHS:
        return out
    model = request.query_params.get("model")
    if model:
        out.add(_resolve("entity", model) or "")
    if request.method in ("POST", "PUT", "PATCH") and "json" in request.headers.get("content-type", ""):
        try:
            # Starlette caches the body, so the endpoint still reads it afterwards.
            body = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON is the endpoint's 422 to give
            body = None
        if isinstance(body, dict) and isinstance(body.get("model"), str):
            out.add(_resolve("entity", body["model"]) or "")
    out.discard("")
    return out


async def gate_shared_request(request: Request, tenant_id: uuid.UUID | None) -> None:
    """Refuse (403) a request that reaches a switched-off or unlicensed module's records
    through a shared, type-keyed surface. Called for every authenticated request from
    ``core.deps.get_token_payload``; a request naming no gated type costs a path split."""
    for key in sorted(await modules_named_by_request(request)):
        detail = await module_refusal(key, tenant_id)
        if detail:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def require_entity_module(entity_type: str | None, tenant_id: uuid.UUID | None) -> None:
    """In-code form of the gate, for endpoints that reach a record by an id alone (a file,
    a comment, an attestation) and only learn its type after loading it."""
    key = module_for_entity_type(entity_type)
    detail = await module_refusal(key, tenant_id) if key else None
    if detail:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def entity_type_usable(entity_type: str | None, tenant_id: uuid.UUID | None) -> bool:
    """Whether listings should offer this record type (its module, if any, is usable)."""
    key = module_for_entity_type(entity_type)
    return key is None or await module_refusal(key, tenant_id) is None


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
