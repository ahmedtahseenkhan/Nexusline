"""Approval Workflows API — submit records for approval, decide, cancel."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.approval import ApprovalRequest
from app.models.enums import ApprovalStatus
from app.schemas.approval import ApprovalCreate, ApprovalDecision, ApprovalRead
from app.schemas.common import Page
from app.services import audit

router = APIRouter(prefix="/approvals", tags=["approvals"])


async def _load(db, approval_id: uuid.UUID) -> ApprovalRequest:
    obj = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == approval_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return obj


async def _next_ref(db) -> str:
    count = await db.scalar(select(func.count()).select_from(ApprovalRequest)) or 0
    return f"APR-{count + 1:03d}"


@router.get("", response_model=Page[ApprovalRead], dependencies=[Depends(require("workflow:read"))])
async def list_approvals(
    db: DbSession,
    status_filter: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ApprovalRead]:
    stmt: Select = select(ApprovalRequest)
    if status_filter is not None:
        stmt = stmt.where(ApprovalRequest.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset))
    ).all()
    return Page(items=[ApprovalRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ApprovalRead, status_code=201, dependencies=[Depends(require("workflow:write"))])
async def submit_approval(body: ApprovalCreate, db: DbSession, user: CurrentUser) -> ApprovalRead:
    obj = ApprovalRequest(
        tenant_id=user.tenant_id,
        requested_by=user.id,
        requested_by_email=user.email,
        **body.model_dump(),
    )
    obj.reference = await _next_ref(db)
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="submit", entity_type="approval", entity_id=obj.id,
        summary=f"Submitted approval {obj.reference}: {obj.title}",
    )
    await db.refresh(obj)
    return ApprovalRead.model_validate(obj)


@router.get("/{approval_id}", response_model=ApprovalRead, dependencies=[Depends(require("workflow:read"))])
async def get_approval(approval_id: uuid.UUID, db: DbSession) -> ApprovalRead:
    return ApprovalRead.model_validate(await _load(db, approval_id))


@router.post(
    "/{approval_id}/decision",
    response_model=ApprovalRead,
    dependencies=[Depends(require("workflow:approve"))],
    summary="Approve or reject a pending approval request",
)
async def decide_approval(
    approval_id: uuid.UUID, body: ApprovalDecision, db: DbSession, user: CurrentUser
) -> ApprovalRead:
    obj = await _load(db, approval_id)
    if obj.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Already {obj.status.value}"
        )
    obj.status = ApprovalStatus.approved if body.approve else ApprovalStatus.rejected
    obj.decided_by = user.id
    obj.decided_by_email = user.email
    obj.decided_at = date.today()
    obj.decision_comment = body.comment
    await db.flush()
    await audit.record(
        db, actor=user, action="decide", entity_type="approval", entity_id=obj.id,
        summary=f"{'Approved' if body.approve else 'Rejected'} approval {obj.reference}",
    )
    await db.refresh(obj)
    return ApprovalRead.model_validate(obj)


@router.post(
    "/{approval_id}/cancel",
    response_model=ApprovalRead,
    dependencies=[Depends(require("workflow:write"))],
)
async def cancel_approval(approval_id: uuid.UUID, db: DbSession) -> ApprovalRead:
    obj = await _load(db, approval_id)
    if obj.status != ApprovalStatus.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending can be cancelled")
    obj.status = ApprovalStatus.cancelled
    await db.flush()
    await db.refresh(obj)
    return ApprovalRead.model_validate(obj)


@router.delete("/{approval_id}", status_code=204, dependencies=[Depends(require("workflow:write"))])
async def delete_approval(approval_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _load(db, approval_id))
