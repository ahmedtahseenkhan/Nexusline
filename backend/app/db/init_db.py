"""Create tables, apply RLS, provision the runtime role, and seed.

Idempotent — safe to run on boot. DDL and role management run as the owner role;
seeding runs through the normal app engine so it exercises RLS like real traffic.
Production should use Alembic migrations + ``app.db.rls`` instead of ``create_all``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings
from app.core.database import Base, json_dumps
from app.db.rls import apply_rls_policies
from app.db.phase4 import all_ddl_statements as phase4_ddl_statements
from app.db.phase5 import all_ddl_statements as phase5_ddl_statements
from app.db.schema_patches import (
    asset_split_ddl_statements,
    authority_amount_ddl_statements,
    risk_methodology_ddl_statements,
    audit_type_ddl_statements,
    fortnightly_ddl_statements,
    platform_admin_ddl_statements,
    phase0_ddl_statements,
    phase1_ddl_statements,
    phase2_ddl_statements,
    phase3_ddl_statements,
    recheck_ddl_statements,
    scenario_control_references_ddl_statements,
    tat_ddl_statements,
)

# Importing the models package registers every table on Base.metadata.
import app.models  # noqa: F401

logger = logging.getLogger("nexusline.init")

# Owner/superuser engine for DDL + role provisioning only.
admin_engine = create_async_engine(
    settings.database_url, pool_pre_ping=True, json_serializer=json_dumps
)


async def wait_for_db(retries: int = 30, delay: float = 1.0) -> None:
    """Block until Postgres accepts connections (handles container start races)."""
    for attempt in range(1, retries + 1):
        try:
            async with admin_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            if attempt == retries:
                raise
            logger.info("Waiting for database (%s/%s): %s", attempt, retries, exc)
            await asyncio.sleep(delay)


async def ensure_app_role(conn: AsyncConnection) -> None:
    """Create the non-superuser runtime role and grant it table DML.

    A freshly created role is NOSUPERUSER and subject to RLS, which is exactly what
    we need: this is the role that all tenant traffic connects as.
    """
    user = settings.app_db_user
    password = settings.app_db_password.replace("'", "''")
    await conn.execute(
        text(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN
                CREATE ROLE {user} LOGIN PASSWORD '{password}';
              END IF;
            END
            $$;
            """
        )
    )
    await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {user}"))
    await conn.execute(
        text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {user}")
    )
    await conn.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {user}"
        )
    )


# Every API worker process starts up, but exactly one may initialise: the DDL takes
# exclusive table locks even when it changes nothing, so a second worker re-running it
# deadlocked against the first one's live traffic. The worker that wins the lock
# initialises; the others wait for it to finish and skip.
_STARTUP_LOCK = 0x4E58_494E  # "NXIN"


# The lock covers workers starting together, not one started later. Uvicorn replaces a
# worker that dies (on a small server, the kernel's out-of-memory killer), and the
# replacement found the lock free, became the leader and re-ran the DDL against the
# surviving worker's live traffic: "deadlock detected" on ALTER TABLE, start-up failed,
# uvicorn stopped the whole API and every page answered 502. So a successful
# initialisation leaves a marker for this server process tree — the uvicorn parent's
# pid and start time — and a replacement worker sees it and skips. A restarted or new
# container starts a new parent, so it initialises as before. A single-process server
# (no worker manager above it) has nothing to replace it and keeps no marker.
_MARKER_DIR = Path(tempfile.gettempdir())


def _parent_identity() -> str | None:
    """The uvicorn parent as ``<pid>-<start time>``: a pid alone could be reused by the
    next container start, which must initialise. None when there is no such parent."""
    ppid = os.getppid()
    if ppid <= 1:
        return None
    try:
        with open(f"/proc/{ppid}/stat", encoding="ascii") as fh:
            started = fh.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None
    return f"{ppid}-{started}"


def _init_marker() -> Path | None:
    parent = _parent_identity()
    return _MARKER_DIR / f"nexusline-initialised-{parent}" if parent else None


def already_initialised() -> bool:
    """Whether a worker of this server process has already initialised the database."""
    marker = _init_marker()
    return marker is not None and marker.exists()


def mark_initialised() -> None:
    marker = _init_marker()
    if marker is None:
        return
    try:
        marker.touch()
    except OSError:  # read-only /tmp: the next replacement worker initialises again
        logger.warning("Could not record start-up initialisation at %s", marker)


@asynccontextmanager
async def startup_lock() -> AsyncIterator[bool]:
    """Yield True in the one worker that should initialise, False in the others (only
    once the initialising worker has finished) and in a worker started to replace one
    that died, once this server has initialised."""
    if already_initialised():
        yield False
        return
    await wait_for_db()
    async with admin_engine.connect() as conn:
        leader = await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": _STARTUP_LOCK})
        await conn.commit()
        if not leader:
            # Wait for the initialising worker, then let go at once.
            await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _STARTUP_LOCK})
        try:
            yield bool(leader) and not already_initialised()
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _STARTUP_LOCK})
            await conn.commit()


async def init_models() -> None:
    await wait_for_db()
    async with admin_engine.begin() as conn:
        # Wait a bounded time for a table lock rather than queueing behind live traffic
        # (and everything queued behind this DDL); the caller retries.
        await conn.execute(text("SET LOCAL lock_timeout = '15s'"))
        await conn.run_sync(Base.metadata.create_all)
        # create_all can't ALTER existing tables — apply the column additions so an
        # existing `assets` table gains asset_class/business_value/etc., and `risks` /
        # `risk_settings` gain the configurable-matrix and residual-suggestion columns.
        for statement in (
            *asset_split_ddl_statements(),
            *risk_methodology_ddl_statements(),
            *tat_ddl_statements(),
            *audit_type_ddl_statements(),
            *fortnightly_ddl_statements(),
            *platform_admin_ddl_statements(),
            *scenario_control_references_ddl_statements(),
            *phase0_ddl_statements(),
            *phase1_ddl_statements(),
            *phase2_ddl_statements(),
            *phase3_ddl_statements(),
            *recheck_ddl_statements(),
            *authority_amount_ddl_statements(),
            *phase4_ddl_statements(),
            *phase5_ddl_statements(),
        ):
            await conn.execute(text(statement))
        await apply_rls_policies(conn)
        await ensure_app_role(conn)


async def main() -> None:
    await init_models()
    from app.core.database import engine
    from app.db.seed import seed_if_empty

    await seed_if_empty()
    await admin_engine.dispose()
    await engine.dispose()
    print("Database initialized.")


if __name__ == "__main__":
    asyncio.run(main())
