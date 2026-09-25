"""Account Reviews / Access Certification API.

A user-access recertification is evidence an SBP inspection samples (IT Governance and
Cyber Security framework: periodic review of user rights), so every step is on the
activity trail against the review: edits, archive, each account added / changed /
removed, each keep-or-revoke decision with who took it, and completion. A completed
review is the signed-off record; set it back to in progress (itself logged) to change it.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
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
from app.services.refs import next_reference
from app.services import audit
from app.services import lifecycle_gates
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/access-reviews", tags=["access reviews"])


def _plain(value):
    return getattr(value, "value", value)


def _changes(obj, data: dict) -> dict:
    return {k: {"from": _plain(getattr(obj, k)), "to": _plain(v)}
            for k, v in data.items() if getattr(obj, k) != v}


async def _trail(db, user, review, action: str, summary: str, changes: dict | None = None) -> None:
    await audit.record(db, actor=user, action=action, entity_type="access_review", entity_id=review.id,
                       summary=summary[:500], changes=changes or None)


COMPLETED_REFUSAL = ("This access review is completed, so its accounts and decisions are the signed-off "
                     "record. Set the review back to in progress to change them.")


_DECISION_VERB = {"keep": "Kept", "revoke": "Revoked", "pending": "Reset the decision on"}


def _open_or_409(review) -> None:
    if review.status == AccessReviewStatus.completed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=COMPLETED_REFUSAL)


async def _load(db, review_id: uuid.UUID) -> AccessReview:
    obj = await db.scalar(
        select(AccessReview).where(AccessReview.id == review_id, AccessReview.deleted.is_(False))
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return obj


async def _fresh(db, review_id: uuid.UUID) -> AccessReview:
    obj = await db.scalar(
        select(AccessReview)
        .where(AccessReview.id == review_id, AccessReview.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return obj


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
    return await next_reference(db, AccessReview, "AR")


_REVIEW_SORTABLE = {
    "reference": AccessReview.reference,
    "name": AccessReview.name,
    "system_name": AccessReview.system_name,
    "status": AccessReview.status,
    "due_date": AccessReview.due_date,
    "created_at": AccessReview.created_at,
}


@router.get("", response_model=Page[ReviewRead], dependencies=[Depends(require("review:read"))])
async def list_reviews(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ReviewRead]:
    stmt = select(AccessReview).where(AccessReview.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            AccessReview.name.ilike(like)
            | AccessReview.reference.ilike(like)
            | AccessReview.system_name.ilike(like)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _REVIEW_SORTABLE, default=AccessReview.created_at)
    else:
        stmt = stmt.order_by(AccessReview.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[ReviewRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ReviewRead, status_code=201, dependencies=[Depends(require("review:write"))])
async def create_review(body: ReviewCreate, db: DbSession, user: CurrentUser) -> ReviewRead:
    # Completion is the sign-off on a decision for every account, so a review is never
    # created completed (services.lifecycle_gates; the import downgrades it too).
    lifecycle_gates.enforce_create("access_review", {"status": body.status})
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
async def update_review(review_id: uuid.UUID, body: ReviewUpdate, db: DbSession, user: CurrentUser) -> ReviewRead:
    obj = await _load(db, review_id)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items()
            if v is not None or k in ("asset_id", "due_date")}
    changes = _changes(obj, data)
    # Completion checks every account is decided and records the sign-off; an edit of
    # the status field must not skip that (the rule create and import share).
    lifecycle_gates.enforce_edit("access_review", obj, data)
    for f, v in data.items():
        setattr(obj, f, v)
    if "frequency" in data:
        obj.next_review_date = next_review_date(obj.frequency)
    reopened = ("status" in changes and changes["status"]["from"] == AccessReviewStatus.completed.value)
    if reopened:
        obj.completed_at = None
    await db.flush()
    if changes:
        await _trail(db, user, obj, "update",
                     f"{'Reopened' if reopened else 'Updated'} access review {obj.reference}: {', '.join(changes)}",
                     changes)
    return ReviewRead.model_validate(await _fresh(db, obj.id))


@router.delete("/{review_id}", status_code=204, dependencies=[Depends(require("review:write"))])
async def delete_review(review_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, review_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _trail(db, user, obj, "delete",
                 f"Archived access review {obj.reference}: {obj.name} ({_plain(obj.status)}, "
                 f"{obj.reviewed_count}/{obj.total_items} accounts decided)")


# -------------------------------------------------------------------- items
@router.post("/{review_id}/items", response_model=ReviewRead, status_code=201, dependencies=[Depends(require("review:write"))])
async def add_item(review_id: uuid.UUID, body: ItemCreate, db: DbSession, user: CurrentUser) -> ReviewRead:
    review = await _load(db, review_id)
    _open_or_409(review)
    item = AccessReviewItem(tenant_id=user.tenant_id, review_id=review_id, **body.model_dump())
    db.add(item)
    if review.status == AccessReviewStatus.draft:
        review.status = AccessReviewStatus.in_progress
    await db.flush()
    await _trail(db, user, review, "update",
                 f"Added account {item.username} to access review {review.reference}",
                 {"account": item.username, "access": item.access})
    return ReviewRead.model_validate(await _fresh(db, review_id))


@router.patch("/{review_id}/items/{item_id}", response_model=ReviewRead, dependencies=[Depends(require("review:write"))])
async def decide_item(
    review_id: uuid.UUID, item_id: uuid.UUID, body: ItemDecision, db: DbSession, user: CurrentUser
) -> ReviewRead:
    review = await _load(db, review_id)
    _open_or_409(review)
    item = await _item_or_404(db, review_id, item_id)
    before = {"decision": _plain(item.decision), "comment": item.comment, "decided_by": item.decided_by}
    item.decision = body.decision
    item.comment = body.comment
    item.decided_by = user.email
    item.decided_at = date.today() if body.decision != AccessDecision.pending else None
    await db.flush()
    # The certification decision itself: who kept or revoked which account, and why.
    await _trail(db, user, review, "decide",
                 f"{_DECISION_VERB[_plain(body.decision)]} access for {item.username} in access review "
                 f"{review.reference}" + (f": {body.comment}" if body.comment else ""),
                 {"account": item.username, "access": item.access,
                  "decision": {"from": before["decision"], "to": _plain(body.decision)},
                  "comment": body.comment, "previously_decided_by": before["decided_by"] or None})
    return ReviewRead.model_validate(await _fresh(db, review_id))


@router.put("/{review_id}/items/{item_id}", response_model=ReviewRead, dependencies=[Depends(require("review:write"))])
async def update_item(
    review_id: uuid.UUID, item_id: uuid.UUID, body: ItemUpdate, db: DbSession, user: CurrentUser
) -> ReviewRead:
    """Edit a line item's username / display name / access / comment (not its decision)."""
    review = await _load(db, review_id)
    _open_or_409(review)
    item = await _item_or_404(db, review_id, item_id)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    changes = _changes(item, data)
    for f, v in data.items():
        setattr(item, f, v)
    await db.flush()
    if changes:
        await _trail(db, user, review, "update",
                     f"Edited account {item.username} in access review {review.reference}: {', '.join(changes)}",
                     {f"account.{k}": v for k, v in changes.items()})
    return ReviewRead.model_validate(await _fresh(db, review_id))


@router.delete("/{review_id}/items/{item_id}", status_code=204, dependencies=[Depends(require("review:write"))])
async def delete_item(review_id: uuid.UUID, item_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    review = await _load(db, review_id)
    _open_or_409(review)
    item = await _item_or_404(db, review_id, item_id)
    label = f"{item.username} ({_plain(item.decision)})"
    await db.delete(item)
    await db.flush()
    await _trail(db, user, review, "update", f"Removed account {label} from access review {review.reference}",
                 {"account": item.username, "decision": _plain(item.decision)})


@router.post(
    "/{review_id}/complete",
    response_model=ReviewRead,
    dependencies=[Depends(require("review:write"))],
    summary="Mark the certification complete (all accounts must be decided)",
)
async def complete_review(review_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ReviewRead:
    review = await _load(db, review_id)
    _open_or_409(review)
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
        summary=f"Completed access review {review.reference} ({review.keep_count} kept, "
                f"{review.revoke_count} revoked)",
        changes={"kept": review.keep_count, "revoked": review.revoke_count,
                 "revoked_accounts": [i.username for i in review.items if i.decision == AccessDecision.revoke]},
    )
    return ReviewRead.model_validate(await _fresh(db, review_id))
