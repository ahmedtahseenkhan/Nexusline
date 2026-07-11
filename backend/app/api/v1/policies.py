"""Policy Management API — repository, publish, and acknowledgment tracking."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.models.compliance import Requirement, requirement_policies
from app.models.control import Control, control_policies
from app.models.enums import PolicyStatus
from app.models.policy import Policy, PolicyAcknowledgment, PolicyReview
from app.models.risk import Risk, risk_policies


def _loads():
    return (
        selectinload(Policy.related),
        selectinload(Policy.controls),
        selectinload(Policy.requirements),
        selectinload(Policy.risks),
        selectinload(Policy.reviews),
        selectinload(Policy.acknowledgments),
        selectinload(Policy.label),
    )
from app.schemas.common import Page
from app.schemas.policy import (
    PolicyAcknowledgmentRead,
    PolicyCreate,
    PolicyRead,
    PolicyReviewComplete,
    PolicyReviewCreate,
    PolicyReviewRead,
    PolicyUpdate,
)
from app.services.refs import next_reference
from app.services import audit
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/policies", tags=["policies"])


async def _load(db, policy_id: uuid.UUID) -> Policy:
    obj = await db.scalar(
        select(Policy).where(Policy.id == policy_id, Policy.deleted.is_(False))
        .options(*_loads()).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    return obj


async def _load_related(db, ids):
    if not ids:
        return []
    rows = list((await db.scalars(
        select(Policy).where(Policy.id.in_(ids), Policy.deleted.is_(False))
    )).all())
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or archived related policy id(s): {sorted(map(str, missing))}",
        )
    return rows


async def _validate_ids(db, model, ids, label: str) -> None:
    if not ids or ids is _KEEP:
        return
    stmt = select(model.id).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    found = set((await db.scalars(stmt)).all())
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or archived {label} id(s): {sorted(missing)}",
        )


_KEEP = object()  # sentinel: field absent from request -> leave untouched


async def _set_assoc(db, table, self_col: str, other_col: str, self_id, other_ids) -> None:
    """Replace the rows in a 2-column association table for `self_id` with `other_ids`.

    Policy.controls/requirements/risks are viewonly reverse views (the writable side
    lives on Control/Requirement/Risk), so we manage the join tables directly.
    """
    if other_ids is _KEEP or other_ids is None:
        return
    await db.execute(delete(table).where(table.c[self_col] == self_id))
    if other_ids:
        await db.execute(insert(table), [{self_col: self_id, other_col: oid} for oid in other_ids])


async def _apply_related(db, obj, data: dict) -> dict:
    """Assign the writable self-ref `related` (pre-flush ok) and stash the viewonly
    cross-links for `_flush_assoc` to write once the policy has an id."""
    related_ids = data.pop("related_ids", _KEEP)
    if related_ids is not _KEEP and related_ids is not None:
        obj.related = await _load_related(db, related_ids)
    return {
        "controls": data.pop("controls_ids", _KEEP),
        "requirements": data.pop("requirements_ids", _KEEP),
        "risks": data.pop("risks_ids", _KEEP),
    }


async def _flush_assoc(db, policy_id, stash: dict) -> None:
    await _validate_ids(db, Control, stash["controls"], "control")
    await _validate_ids(db, Requirement, stash["requirements"], "requirement")
    await _validate_ids(db, Risk, stash["risks"], "risk")
    await _set_assoc(db, control_policies, "policy_id", "control_id", policy_id, stash["controls"])
    await _set_assoc(db, requirement_policies, "policy_id", "requirement_id", policy_id, stash["requirements"])
    await _set_assoc(db, risk_policies, "policy_id", "risk_id", policy_id, stash["risks"])


async def _next_ref(db) -> str:
    return await next_reference(db, Policy, "POL")


@router.get("", response_model=Page[PolicyRead], dependencies=[Depends(require("policy:read"))])
async def list_policies(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PolicyRead]:
    stmt = select(Policy).where(Policy.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.options(*_loads()).order_by(Policy.reference).limit(limit).offset(offset))
    ).all()
    return Page(
        items=[PolicyRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post(
    "",
    response_model=PolicyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("policy:write"))],
)
async def create_policy(body: PolicyCreate, db: DbSession, user: CurrentUser) -> PolicyRead:
    data = body.model_dump()
    obj = Policy(tenant_id=user.tenant_id)
    stash = await _apply_related(db, obj, data)
    for field, value in data.items():
        setattr(obj, field, value)
    obj.reference = await _next_ref(db)
    obj.next_review_date = next_review_date(obj.review_frequency)
    db.add(obj)
    await db.flush()
    await _flush_assoc(db, obj.id, stash)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="policy", entity_id=obj.id,
        summary=f"Created policy {obj.reference}: {obj.title}",
    )
    return PolicyRead.model_validate(await _load(db, obj.id))


@router.get("/{policy_id}", response_model=PolicyRead, dependencies=[Depends(require("policy:read"))])
async def get_policy(policy_id: uuid.UUID, db: DbSession) -> PolicyRead:
    return PolicyRead.model_validate(await _load(db, policy_id))


@router.patch(
    "/{policy_id}", response_model=PolicyRead, dependencies=[Depends(require("policy:write"))]
)
async def update_policy(
    policy_id: uuid.UUID, body: PolicyUpdate, db: DbSession, user: CurrentUser
) -> PolicyRead:
    obj = await _load(db, policy_id)
    data = body.model_dump(exclude_unset=True)
    stash = await _apply_related(db, obj, data)
    for field, value in data.items():
        setattr(obj, field, value)
    if "review_frequency" in data:
        obj.next_review_date = next_review_date(obj.review_frequency)
    await db.flush()
    await _flush_assoc(db, obj.id, stash)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="policy", entity_id=obj.id,
        summary=f"Updated policy {obj.reference}: {obj.title}",
    )
    return PolicyRead.model_validate(await _load(db, obj.id))


@router.post(
    "/{policy_id}/publish",
    response_model=PolicyRead,
    dependencies=[Depends(require("policy:write"))],
    summary="Publish a policy",
)
async def publish_policy(policy_id: uuid.UUID, db: DbSession, user: CurrentUser) -> PolicyRead:
    obj = await _load(db, policy_id)
    obj.status = PolicyStatus.published
    obj.published_at = date.today()
    await db.flush()
    await audit.record(
        db, actor=user, action="publish", entity_type="policy", entity_id=obj.id,
        summary=f"Published policy {obj.reference}",
    )
    return PolicyRead.model_validate(await _load(db, obj.id))


@router.post(
    "/{policy_id}/acknowledge",
    response_model=PolicyAcknowledgmentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("policy:read"))],
    summary="Acknowledge a policy as the current user",
)
async def acknowledge_policy(
    policy_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> PolicyAcknowledgmentRead:
    await _load(db, policy_id)
    existing = await db.scalar(
        select(PolicyAcknowledgment).where(
            PolicyAcknowledgment.policy_id == policy_id,
            PolicyAcknowledgment.user_id == user.id,
        )
    )
    if existing is not None:
        return PolicyAcknowledgmentRead.model_validate(existing)
    ack = PolicyAcknowledgment(
        tenant_id=user.tenant_id, policy_id=policy_id, user_id=user.id, user_email=user.email
    )
    db.add(ack)
    await db.flush()
    await db.refresh(ack)
    return PolicyAcknowledgmentRead.model_validate(ack)


@router.delete(
    "/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("policy:write"))],
)
async def delete_policy(policy_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, policy_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)


# ----------------------------------------------------------------- review cycle
@router.get(
    "/{policy_id}/reviews", response_model=list[PolicyReviewRead],
    dependencies=[Depends(require("policy:read"))],
)
async def list_policy_reviews(policy_id: uuid.UUID, db: DbSession) -> list[PolicyReviewRead]:
    obj = await _load(db, policy_id)
    return [PolicyReviewRead.model_validate(r) for r in obj.reviews]


@router.post(
    "/{policy_id}/reviews", response_model=PolicyRead, status_code=201,
    dependencies=[Depends(require("policy:write"))],
)
async def schedule_policy_review(policy_id: uuid.UUID, body: PolicyReviewCreate, db: DbSession) -> PolicyRead:
    obj = await _load(db, policy_id)
    db.add(PolicyReview(tenant_id=obj.tenant_id, policy_id=obj.id, planned_date=body.planned_date,
                        reviewer=body.reviewer, comments=body.comments))
    obj.next_review_date = body.planned_date
    await db.flush()
    return PolicyRead.model_validate(await _load(db, obj.id))


@router.post(
    "/{policy_id}/reviews/{review_id}/complete", response_model=PolicyRead,
    dependencies=[Depends(require("policy:write"))],
)
async def complete_policy_review(
    policy_id: uuid.UUID, review_id: uuid.UUID, body: PolicyReviewComplete, db: DbSession, user: CurrentUser
) -> PolicyRead:
    obj = await _load(db, policy_id)
    review = await db.scalar(select(PolicyReview).where(PolicyReview.id == review_id, PolicyReview.policy_id == policy_id))
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    today = date.today()
    review.actual_review_date = today
    if body.comments:
        review.comments = body.comments
    obj.last_review_date = today
    obj.next_review_date = next_review_date(obj.review_frequency, today)
    await audit.record(db, actor=user, action="review", entity_type="policy", entity_id=obj.id,
                       summary=f"Reviewed policy {obj.reference}")
    await db.flush()
    return PolicyRead.model_validate(await _load(db, obj.id))
