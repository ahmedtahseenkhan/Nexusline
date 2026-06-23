"""Account Reviews / Access Certification API."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.access_review import AccessReview, AccessReviewItem
from app.models.enums import AccessDecision, AccessReviewStatus
from app.schemas.access_review import (
    ItemCreate,
    ItemDecision,
    ItemUpdate,
    ReviewCreate,
    ReviewRead,
    ReviewUpdate,
)
from app.schemas.common import Page
from app.services import audit
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/access-reviews", tags=["access reviews"])


async def _load(db, review_id: uuid.UUID) -> AccessReview:
    obj = await db.scalar(select(AccessReview).where(AccessReview.id == review_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return obj


async def _fresh(db, review_id: uuid.UUID) -> AccessReview:
    return await db.scalar(
        select(AccessReview).where(AccessReview.id == review_id).execution_options(populate_existing=True)
    )


async def _item_or_404(db, review_id, item_id) -> AccessReviewItem:
    obj = await db.scalar(
        select(AccessReviewItem).where(
            AccessReviewItem.id == item_id, AccessReviewItem.review_id == review_id
        )
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return obj


async def _next_ref(db) -> str:
    count = await db.scalar(select(func.count()).select_from(AccessReview)) or 0
    return f"AR-{count + 1:03d}"


@router.get("", response_model=Page[ReviewRead], dependencies=[Depends(require("review:read"))])
async def list_reviews(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ReviewRead]:
    stmt = select(AccessReview).where(AccessReview.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(AccessReview.created_at.desc()).limit(limit).offset(offset))
    ).all()
    return Page(items=[ReviewRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ReviewRead, status_code=201, dependencies=[Depends(require("review:write"))])
async def create_review(body: ReviewCreate, db: DbSession, user: CurrentUser) -> ReviewRead:
    obj = AccessReview(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db)
    obj.next_review_date = next_review_date(obj.frequency)
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="access_review", entity_id=obj.id,
        summary=f"Created access review {obj.reference}: {obj.name}",
    )
    return ReviewRead.model_validate(await _fresh(db, obj.id))


@router.get("/{review_id}", response_model=ReviewRead, dependencies=[Depends(require("review:read"))])
async def get_review(review_id: uuid.UUID, db: DbSession) -> ReviewRead:
    return ReviewRead.model_validate(await _load(db, review_id))


@router.patch("/{review_id}", response_model=ReviewRead, dependencies=[Depends(require("review:write"))])
async def update_review(review_id: uuid.UUID, body: ReviewUpdate, db: DbSession) -> ReviewRead:
    obj = await _load(db, review_id)
    data = body.model_dump(exclude_unset=True)
    for f, v in data.items():
        setattr(obj, f, v)
    if "frequency" in data:
        obj.next_review_date = next_review_date(obj.frequency)
    await db.flush()
    return ReviewRead.model_validate(await _fresh(db, obj.id))


@router.delete("/{review_id}", status_code=204, dependencies=[Depends(require("review:write"))])
async def delete_review(review_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, review_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)


# -------------------------------------------------------------------- items
@router.post("/{review_id}/items", response_model=ReviewRead, status_code=201, dependencies=[Depends(require("review:write"))])
async def add_item(review_id: uuid.UUID, body: ItemCreate, db: DbSession, user: CurrentUser) -> ReviewRead:
    review = await _load(db, review_id)
    db.add(AccessReviewItem(tenant_id=user.tenant_id, review_id=review_id, **body.model_dump()))
    if review.status == AccessReviewStatus.draft:
        review.status = AccessReviewStatus.in_progress
    await db.flush()
    return ReviewRead.model_validate(await _fresh(db, review_id))


@router.patch("/{review_id}/items/{item_id}", response_model=ReviewRead, dependencies=[Depends(require("review:write"))])
async def decide_item(
    review_id: uuid.UUID, item_id: uuid.UUID, body: ItemDecision, db: DbSession, user: CurrentUser
) -> ReviewRead:
    item = await _item_or_404(db, review_id, item_id)
    item.decision = body.decision
    item.comment = body.comment
    item.decided_by = user.email
    item.decided_at = date.today() if body.decision != AccessDecision.pending else None
    await db.flush()
    return ReviewRead.model_validate(await _fresh(db, review_id))


@router.put("/{review_id}/items/{item_id}", response_model=ReviewRead, dependencies=[Depends(require("review:write"))])
async def update_item(
    review_id: uuid.UUID, item_id: uuid.UUID, body: ItemUpdate, db: DbSession
) -> ReviewRead:
    """Edit a line item's username / display name / access / comment (not its decision)."""
    item = await _item_or_404(db, review_id, item_id)
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(item, f, v)
    await db.flush()
    return ReviewRead.model_validate(await _fresh(db, review_id))


@router.delete("/{review_id}/items/{item_id}", status_code=204, dependencies=[Depends(require("review:write"))])
async def delete_item(review_id: uuid.UUID, item_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _item_or_404(db, review_id, item_id))


@router.post(
    "/{review_id}/complete",
    response_model=ReviewRead,
    dependencies=[Depends(require("review:write"))],
    summary="Mark the certification complete (all accounts must be decided)",
)
async def complete_review(review_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ReviewRead:
    review = await _load(db, review_id)
    pending = [i for i in review.items if i.decision == AccessDecision.pending]
    if pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{len(pending)} account(s) still pending a decision",
        )
    review.status = AccessReviewStatus.completed
    review.completed_at = date.today()
    review.next_review_date = next_review_date(review.frequency, date.today())
    await db.flush()
    await audit.record(
        db, actor=user, action="complete", entity_type="access_review", entity_id=review.id,
        summary=f"Completed access review {review.reference} ({review.revoke_count} revoked)",
    )
    return ReviewRead.model_validate(await _fresh(db, review_id))
