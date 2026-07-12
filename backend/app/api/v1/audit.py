"""Activity log / audit trail (read-only)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.core.deps import DbSession, require
from app.models.audit import AuditLog
from app.schemas.audit import AuditRead
from app.schemas.common import Page

router = APIRouter(prefix="/audit", tags=["audit"])

# Columns a client may sort by; created_at is the default (newest first).
_SORTABLE = {
    "created_at": AuditLog.created_at,
    "action": AuditLog.action,
    "entity_type": AuditLog.entity_type,
    "actor_email": AuditLog.actor_email,
}


@router.get("", response_model=Page[AuditRead], dependencies=[Depends(require("audit:read"))])
async def list_audit(
    db: DbSession,
    search: Annotated[str | None, Query(description="Free-text over actor email / summary")] = None,
    entity_type: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    actor: Annotated[str | None, Query(description="Filter by actor email (contains)")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditRead]:
    stmt = select(AuditLog)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(AuditLog.actor_email.ilike(like), AuditLog.summary.ilike(like)))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor:
        stmt = stmt.where(AuditLog.actor_email.ilike(f"%{actor}%"))
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        # Inclusive of the whole `to` day.
        stmt = stmt.where(AuditLog.created_at < date_to + timedelta(days=1))

    # Sort by an allow-listed column only; default to newest first.
    col = _SORTABLE.get(sort_by) if sort_by else None
    if col is None:
        stmt = stmt.order_by(AuditLog.created_at.desc())
    else:
        stmt = stmt.order_by(col.desc() if sort_dir == "desc" else col.asc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(
        items=[AuditRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
