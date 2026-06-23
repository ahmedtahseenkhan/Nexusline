"""Create tables, apply RLS, provision the runtime role, and seed.

Idempotent — safe to run on boot. DDL and role management run as the owner role;
seeding runs through the normal app engine so it exercises RLS like real traffic.
Production should use Alembic migrations + ``app.db.rls`` instead of ``create_all``.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.db.rls import apply_rls_policies

# Importing the models package registers every table on Base.metadata.
import app.models  # noqa: F401

logger = logging.getLogger("nexusline.init")

# Owner/superuser engine for DDL + role provisioning only.
admin_engine = create_async_engine(settings.database_url, pool_pre_ping=True)


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


async def init_models() -> None:
    await wait_for_db()
    async with admin_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
