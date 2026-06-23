"""Activity log / audit trail (read-only)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import DbSession, require
from app.models.audit import AuditLog
from app.schemas.audit import AuditRead
from app.schemas.common import Page

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditRead], dependencies=[Depends(require("audit:read"))])
async def list_audit(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditRead]:
    total = await db.scalar(select(func.count()).select_from(AuditLog)) or 0
    rows = (
        await db.scalars(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return Page(
        items=[AuditRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
