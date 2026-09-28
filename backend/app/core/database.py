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

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, ORMExecuteState, Session, lazyload

from app.core.config import settings

def _json_default(value: object) -> object:
    """JSON columns (audit-trail changes, snapshots, settings) routinely receive the
    values a request carried — dates, ids, amounts, enum members. Without this every
    update whose changes included one crashed on commit."""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def json_dumps(value: object) -> str:
    return json.dumps(value, default=_json_default)


# Runtime engine connects as the least-privilege app role so RLS is enforced.
engine = create_async_engine(
    settings.app_database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    json_serializer=json_dumps,
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


#: A tighter cap for the code inside :func:`shallow_loads`, else None (the setting).
_EAGER_DEPTH: ContextVar[int | None] = ContextVar("eager_depth", default=None)


@contextmanager
def shallow_loads(depth: int = 1) -> Iterator[None]:
    """Cap eager loading ``depth`` links from each record loaded inside the block.

    For code that loads whole records but reads only their columns and their direct
    links — the alert scan, a workflow transition, an archive or restore. Under the
    default cap such a load walked the link graph: an overdue control brought its
    protected assets and every asset brought its twenty-eight links, so one scan ran
    ~900 statements. At depth 1 a record's own links load and their links do not (read
    one of those and it is a lazy load, which must happen inside ``run_sync``)."""
    token = _EAGER_DEPTH.set(depth)
    try:
        yield
    finally:
        _EAGER_DEPTH.reset(token)


@event.listens_for(Session, "do_orm_execute")
def _cap_eager_depth(state: ORMExecuteState) -> None:
    """Stop eager loading ``settings.orm_eager_depth`` relationships away from the record
    that was asked for.

    Links are mapped ``lazy="selectin"`` so a record arrives with its related records
    ready to serialise. But the links form one connected graph — a policy's risks have
    controls, whose risks have assets, whose risks... — and uncapped, every list or
    detail request walked all of it: 1,600+ queries to list 27 risks, growing with the
    bank's data until pages timed out. Responses read a record's links and, for a few
    computed badges, the links' own links; nothing reads further, so objects loaded at
    the cap load their relationships only if asked.
    """
    if not state.is_relationship_load:
        return
    path = state.loader_strategy_path
    depth = len(path.path) // 2 if path is not None else 0
    cap = _EAGER_DEPTH.get()
    if depth >= (cap if cap is not None else settings.orm_eager_depth):
        # A refresh (populate_existing, re-reading a record after a write) would also
        # repopulate objects already in the session — the signed-in user's roles among
        # them — and the cap would leave their relationships unloaded, so the next
        # permission check did IO outside the async context. Past the cap, objects the
        # session already holds are kept as they are.
        state.statement = state.statement.options(lazyload("*")).execution_options(
            populate_existing=False
        )


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
