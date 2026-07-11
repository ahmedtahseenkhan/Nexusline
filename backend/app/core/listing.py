"""Shared server-driven list-query support: pagination, safe sorting, and search.

Enterprise tables need the server to page, sort and filter — the client can't hold
100k rows. Endpoints declare an allow-list of sortable columns (so a client can't sort
by an arbitrary/unindexed column) and the columns to search; this module applies them
uniformly and returns the standard ``Page`` envelope with a real total.

Usage in a router::

    from app.core.listing import ListParams, listing, apply_search, apply_sort, paginate

    _SORTABLE = {"name": Asset.name, "created_at": Asset.created_at, ...}

    @router.get("", response_model=Page[AssetListItem])
    async def list_assets(db: DbSession, params: ListParams = Depends(listing)):
        stmt = select(Asset).where(Asset.deleted.is_(False))
        stmt = apply_search(stmt, params, [Asset.name, Asset.hostname])
        stmt = apply_sort(stmt, params, _SORTABLE, default=Asset.name)
        return await paginate(db, stmt, params, serialize=_to_list_item)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Callable, Sequence

from fastapi import Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import Page


@dataclass
class ListParams:
    limit: int
    offset: int
    sort_by: str | None
    sort_dir: str
    q: str | None


def listing(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    q: Annotated[str | None, Query(description="Free-text search")] = None,
) -> ListParams:
    return ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=(q or None))


def apply_search(stmt: Select, params: ListParams, columns: Sequence) -> Select:
    """Case-insensitive OR search across the given text columns."""
    if not params.q or not columns:
        return stmt
    like = f"%{params.q}%"
    return stmt.where(or_(*[c.ilike(like) for c in columns]))


def apply_sort(stmt: Select, params: ListParams, sortable: dict[str, object], default) -> Select:
    """Sort by an allow-listed column only; unknown keys are rejected (not silently
    ignored) so the UI and API stay in agreement."""
    col = default
    if params.sort_by:
        if params.sort_by not in sortable:
            raise HTTPException(status_code=422, detail=f"Cannot sort by '{params.sort_by}'")
        col = sortable[params.sort_by]
    return stmt.order_by(col.desc() if params.sort_dir == "desc" else col.asc())


async def paginate(
    db: AsyncSession,
    stmt: Select,
    params: ListParams,
    serialize: Callable,
) -> Page:
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(params.limit).offset(params.offset))).all()
    return Page(items=[serialize(r) for r in rows], total=total, limit=params.limit, offset=params.offset)
