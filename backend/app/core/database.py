"""Async database engine, session management, and multi-tenant RLS plumbing.

Tenant isolation is enforced at the *database* layer via PostgreSQL Row-Level
Security (see app/db/rls.py). Application code only has to declare which tenant a
request belongs to; Postgres guarantees a transaction can read/write rows for that
tenant only.

The tenant is communicated to Postgres through a transaction-local GUC,
``app.current_tenant``. We open exactly one transaction per request (or per
``tenant_session`` block) and set the GUC at its start, so the value can never leak
across pooled connections.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Runtime engine connects as the least-privilege app role so RLS is enforced.
engine = create_async_engine(
    settings.app_database_url,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def set_session_tenant(session: AsyncSession, tenant_id: UUID | str | None) -> None:
    """Set the transaction-local tenant GUC that RLS policies read.

    An empty value fails closed: tenant-scoped tables return zero rows. Can be called
    again mid-transaction to switch context (e.g. right after creating a new tenant
    during org registration).
    """
    value = str(tenant_id) if tenant_id else ""
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": value},
    )


@asynccontextmanager
async def tenant_session(tenant_id: UUID | str | None) -> AsyncIterator[AsyncSession]:
    """Open a single-transaction session scoped to ``tenant_id``.

    Commits on success, rolls back on error. Used by request handlers (via the
    ``get_db`` dependency), auth flows, and seed/maintenance scripts. Pass ``None``
    to operate without a tenant (e.g. looking up an org by slug during login);
    tenant-scoped tables will be invisible in that mode.
    """
    async with SessionLocal() as session:
        async with session.begin():
            await set_session_tenant(session, tenant_id)
            yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Tenant-less session for cross-tenant bootstrap reads (e.g. tenant lookup)."""
    async with tenant_session(None) as session:
        yield session
