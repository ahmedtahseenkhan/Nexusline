"""Human-readable reference generation that survives deletes.

Count-based numbering (``count(*) + 1``) reuses a reference as soon as any row is
deleted — producing duplicate references in registers that hard-delete their rows
(audit findings, model validations, obligations, meetings) and, now that soft-deleted
rows are filtered out of counts, potentially everywhere else. This derives the next
number from the highest existing reference for the prefix instead, so a gap left by a
delete is never refilled.

The query runs inside the request's RLS-scoped session, so numbering is per tenant.

Concurrency: a transaction-scoped Postgres advisory lock, keyed on (tenant, prefix),
serialises reference generation for that key. The lock is held until the request's
transaction commits, so a second concurrent create for the same tenant+prefix waits,
then reads the first request's now-committed row and continues from it — two
simultaneous creates can't mint the same number. The lock is per tenant+prefix, so
unrelated creates never block each other, and it is released automatically on
commit/rollback (no unique constraint or schema migration required).
"""
from __future__ import annotations

import re
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

_TRAILING_NUM = re.compile(r"(\d+)$")

# Transaction-scoped advisory lock over hash( tenant || ':' || prefix ). hashtextextended
# yields a bigint, which pg_advisory_xact_lock(bigint) accepts. current_setting(..., true)
# returns the RLS tenant GUC (empty string for tenant-less bootstrap sessions).
_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended(coalesce(current_setting('app.current_tenant', true), '') || ':' || :prefix, 0))"
)


async def next_reference(db: AsyncSession, model, prefix: str, width: int = 3) -> str:
    await db.execute(_LOCK_SQL, {"prefix": prefix})
    rows = (
        await db.scalars(select(model.reference).where(model.reference.like(f"{prefix}-%")))
    ).all()
    max_n = 0
    for r in rows:
        m = _TRAILING_NUM.search(str(r or ""))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{prefix}-{max_n + 1:0{width}d}"
