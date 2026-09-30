"""Nexusline API application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.v1.router import api_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexusline")


async def _initialise_database() -> None:
    """Schema, row-level security, seed and data repairs — run by one worker per boot."""
    from app.db.init_db import init_models
    from app.db.provisioning import reconcile_permissions
    from app.db.seed import seed_if_empty

    await init_models()
    await seed_if_empty()
    # Grant newly-added module permissions to existing tenants' system roles
    # (no-op on a fresh seed; fixes 403s after modules are added to an existing DB).
    granted = await reconcile_permissions()
    if granted:
        logger.info("Reconciled permissions: added %s role grants", granted)
    # Backfill baseline lookups (media types, vendor types, labels) for tenants
    # created before reference data moved out of the demo seeder.
    from app.db.reference_data import reconcile_reference_data

    lookups = await reconcile_reference_data()
    if lookups:
        logger.info("Reconciled reference data: added %s lookup rows", lookups)
    # Bring data written before the product-review rules into line with them
    # (duplicate frameworks and tiles, test clocks on planned controls, residual
    # above inherent), then add the unique indexes those rules rely on.
    from app.db.data_repairs import repair_data

    repaired = await repair_data()
    if repaired.any():
        logger.info("Data repairs: %s", repaired)


async def _initialise_with_retry(attempts: int = 3) -> None:
    """Initialise, retrying when the schema changes lose a lock race (a deadlock, or
    the lock timeout) — traffic finishing on the old container, a scheduled sweep.
    Each attempt is one transaction, so a failed one leaves nothing half-applied."""
    import asyncio

    from sqlalchemy.exc import DBAPIError

    for attempt in range(1, attempts + 1):
        try:
            await _initialise_database()
            return
        except DBAPIError as exc:
            text = str(exc).lower()
            if attempt == attempts or not ("deadlock" in text or "lock timeout" in text):
                raise
            logger.warning("Start-up initialisation lost a lock race (attempt %s of %s); retrying", attempt, attempts)
            await asyncio.sleep(3 * attempt)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: ensure schema + RLS + seed exist on boot. In production,
    # disable by setting SEED_DATA=false and manage schema with Alembic.
    from app.db.init_db import mark_initialised, startup_lock
    from app.services import license as lic
    from app.services import scheduler

    # Offline license gate (fail-closed only when enforcement is on — banking mode).
    lic.enforce_on_startup()

    try:
        async with startup_lock() as initialise:
            if initialise:
                await _initialise_with_retry()
                mark_initialised()
            else:
                logger.info("Start-up initialisation done by another worker")
    except Exception:  # noqa: BLE001
        logger.exception("Startup DB initialization failed")
        raise

    # Time-driven reminder/chasing sweep (notifications + email digests).
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="Nexusline API",
    version="0.1.0",
    description="Modern multi-tenant Governance, Risk & Compliance platform.",
    lifespan=lifespan,
)

# Constraint violations are refused input (duplicate, missing, dangling link), not 500s.
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.exc import TimeoutError as PoolTimeoutError  # noqa: E402

from app.core.db_errors import integrity_error_handler, pool_timeout_handler  # noqa: E402

app.add_exception_handler(IntegrityError, integrity_error_handler)
app.add_exception_handler(PoolTimeoutError, pool_timeout_handler)

# Read-only mode after the licence grace period (decision 1). Added before CORS so CORS
# stays the outer layer and a refused write still carries the CORS headers the browser
# needs to read the message.
from app.core.licence_guard import LicenceReadOnlyMiddleware  # noqa: E402

app.add_middleware(LicenceReadOnlyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Exports name their file server-side (Content-Disposition). A browser on another
    # origin — the dev server, or a web tier on its own host — cannot read that header
    # unless it is exposed, and silently falls back to "download.pdf".
    expose_headers=["Content-Disposition", "X-Error-Code"],
)
# Compress list/detail JSON payloads (nested-collection responses are large at scale).
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(api_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    # Public, unauthenticated liveness probe (used by container healthchecks).
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": settings.app_version,
    }


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"service": "nexusline", "docs": "/docs", "health": "/health"}
