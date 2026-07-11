"""Approval Workflows API — submit records for approval, decide, cancel."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.models.approval import ApprovalAction, ApprovalRequest
from app.models.enums import ApprovalStatus
from app.schemas.approval import ApprovalCreate, ApprovalDecision, ApprovalRead
from app.schemas.common import Page
from app.services.refs import next_reference
from app.services import audit

router = APIRouter(prefix="/approvals", tags=["approvals"])


async def _load(db, approval_id: uuid.UUID) -> ApprovalRequest:
    obj = await db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .options(selectinload(ApprovalRequest.actions))
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return obj


async def _next_ref(db) -> str:
    return await next_reference(db, ApprovalRequest, "APR")


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
        await db.scalars(
            stmt.options(selectinload(ApprovalRequest.actions))
            .order_by(ApprovalRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
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
    return ApprovalRead.model_validate(await _load(db, obj.id))


@router.get("/{approval_id}", response_model=ApprovalRead, dependencies=[Depends(require("workflow:read"))])
async def get_approval(approval_id: uuid.UUID, db: DbSession) -> ApprovalRead:
    return ApprovalRead.model_validate(await _load(db, approval_id))


@router.post(
    "/{approval_id}/decision",
    response_model=ApprovalRead,
    dependencies=[Depends(require("workflow:approve"))],
    summary="Approve or reject a pending approval request (maker-checker enforced)",
)
async def decide_approval(
    approval_id: uuid.UUID, body: ApprovalDecision, db: DbSession, user: CurrentUser
) -> ApprovalRead:
    obj = await _load(db, approval_id)
    if obj.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Already {obj.status.value}"
        )

    # Segregation of Duties: the maker (submitter) can never be a checker (approver).
    if (
        settings.enforce_segregation_of_duties
        and obj.requested_by is not None
        and obj.requested_by == user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Segregation of duties: the maker of a request cannot approve it — an independent checker must decide.",
        )
    # One decision per checker (prevents a single user counting twice toward N-eyes).
    if any(a.actor_id == user.id for a in obj.actions):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already recorded a decision on this request.",
        )
    # A rejection must carry a documented reason (audit requirement).
    if not body.approve and not (body.comment or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A reason is required to reject an approval request.",
        )

    action = ApprovalAction(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        actor_email=user.email,
        action="approve" if body.approve else "reject",
        comment=body.comment,
    )
    obj.actions.append(action)

    if not body.approve:
        obj.status = ApprovalStatus.rejected
        obj.decided_by = user.id
        obj.decided_by_email = user.email
        obj.decided_at = date.today()
        obj.decision_comment = body.comment
        summary = f"Rejected approval {obj.reference}"
    else:
        received = obj.approvals_received  # includes the vote just appended
        if received >= obj.required_approvals:
            obj.status = ApprovalStatus.approved
            obj.decided_by = user.id
            obj.decided_by_email = user.email
            obj.decided_at = date.today()
            obj.decision_comment = body.comment
            summary = f"Approved approval {obj.reference} ({received}/{obj.required_approvals})"
        else:
            summary = (
                f"Recorded approval {received}/{obj.required_approvals} for {obj.reference} "
                f"(awaiting {obj.required_approvals - received} more)"
            )

    await db.flush()
    await audit.record(
        db, actor=user, action="decide", entity_type="approval", entity_id=obj.id, summary=summary
    )
    return ApprovalRead.model_validate(await _load(db, obj.id))


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
