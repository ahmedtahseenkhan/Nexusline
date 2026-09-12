"""Policy Management API — repository, publish, and acknowledgment tracking."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.compliance import Requirement, requirement_policies
from app.models.control import Control, control_policies
from app.models.enums import PolicyStatus
from app.models.policy import Policy, PolicyAcknowledgment, PolicyReview
from app.models.risk import Risk, risk_policies
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
from app.services import delete_guard
from app.services import dual_control
from app.services import ref_fields
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/policies", tags=["policies"])


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

#: The policy's picked fields (phase 1). See services.ref_fields.
POLICY_REFS: tuple[ref_fields.RefField, ...] = (
    ref_fields.user("owner_id", "owner"),
    ref_fields.lookup(Policy, "category_id", "category"),
    ref_fields.WORKFLOW_OWNER,
)
REVIEW_REFS: tuple[ref_fields.RefField, ...] = (ref_fields.user("reviewer_id", "reviewer"),)


async def _reads(db, policies) -> list[PolicyRead]:
    """Serialise a page of policies with every pick resolved — one query per kind for
    the policies and one for all their reviewers, whatever the page size."""
    items = [PolicyRead.model_validate(p) for p in policies]
    await ref_fields.fill_refs(db, list(zip(policies, items)), POLICY_REFS)
    reviews = [pair for p, rd in zip(policies, items) for pair in zip(p.reviews, rd.reviews)]
    await ref_fields.fill_refs(db, reviews, REVIEW_REFS)
    return items


async def _read(db, policy) -> PolicyRead:
    return (await _reads(db, [policy]))[0]


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


_POLICY_SORTABLE = {
    "reference": Policy.reference,
    "title": Policy.title,
    "category": Policy.category,
    "document_type": Policy.document_type,
    "version": Policy.version,
    "status": Policy.status,
    "owner": Policy.owner,
    "next_review_date": Policy.next_review_date,
    "created_at": Policy.created_at,
}


@router.get("", response_model=Page[PolicyRead], dependencies=[Depends(require("policy:read"))])
async def list_policies(
    db: DbSession,
    search: str | None = None,
    owner_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PolicyRead]:
    stmt = select(Policy).where(Policy.deleted.is_(False))
    if search:
        stmt = stmt.where(Policy.title.ilike(f"%{search}%") | Policy.reference.ilike(f"%{search}%"))
    if owner_id is not None:
        stmt = stmt.where(Policy.owner_id == owner_id)
    if category_id is not None:
        stmt = stmt.where(Policy.category_id == category_id)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _POLICY_SORTABLE, default=Policy.reference)
    else:
        stmt = stmt.order_by(Policy.reference)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.options(*_loads()).limit(limit).offset(offset))
    ).all()
    return Page(items=await _reads(db, list(rows)), total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=PolicyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("policy:write"))],
)
async def create_policy(body: PolicyCreate, db: DbSession, user: CurrentUser) -> PolicyRead:
    data = body.model_dump()
    _check_initial_status(user, data.get("status"))
    await ref_fields.apply_refs(db, Policy, data, POLICY_REFS)
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
    return await _read(db, await _load(db, obj.id))


@router.get("/{policy_id}", response_model=PolicyRead, dependencies=[Depends(require("policy:read"))])
async def get_policy(policy_id: uuid.UUID, db: DbSession) -> PolicyRead:
    return await _read(db, await _load(db, policy_id))


@router.patch(
    "/{policy_id}", response_model=PolicyRead, dependencies=[Depends(require("policy:write"))]
)
async def update_policy(
    policy_id: uuid.UUID, body: PolicyUpdate, db: DbSession, user: CurrentUser
) -> PolicyRead:
    obj = await _load(db, policy_id)
    data = body.model_dump(exclude_unset=True)
    refusal = status_edit_refusal(obj.status, data.get("status"))
    if refusal:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=refusal)
    await ref_fields.apply_refs(db, Policy, data, POLICY_REFS, record=obj)
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
    return await _read(db, await _load(db, obj.id))


#: Business statuses a policy reaches only through the approval lifecycle (Submit for
#: review → Approve, then Publish), never by editing the field.
LIFECYCLE_STATUSES = (PolicyStatus.under_review, PolicyStatus.approved, PolicyStatus.published)


def status_edit_refusal(current, wanted) -> str | None:
    """Why an edit may not set this policy status, or None. Pure."""
    if wanted is None or wanted == current or wanted not in LIFECYCLE_STATUSES:
        return None
    step = "Publish" if wanted == PolicyStatus.published else "Submit for review and Approve"
    return f"A policy becomes {wanted.value.replace('_', ' ')} through {step}, not by editing its status."


def publish_refusal(workflow_status, business_status) -> str | None:
    """Why this policy can't be published yet, or None. Pure."""
    state = getattr(workflow_status, "value", workflow_status)
    if state == "approved" or business_status in (PolicyStatus.approved, PolicyStatus.published):
        return None
    return (
        "Approve this policy before publishing it: submit it for review, and an "
        "independent approver approves it."
    )


def _check_initial_status(user, wanted) -> None:
    """A new policy starts as a draft unless the creator could approve it (a migration
    bringing already-approved policies in, say)."""
    if wanted is None or wanted not in LIFECYCLE_STATUSES:
        return
    from app.services.record_workflow import required_permissions

    needed = required_permissions("policy", "approve")
    if not set(needed).issubset(set(user.permission_codes or [])):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"A new policy starts as a draft. Creating one as {wanted.value.replace('_', ' ')} "
                f"needs approval rights ({', '.join(needed)})."
            ),
        )


@router.post(
    "/{policy_id}/publish",
    response_model=PolicyRead,
    dependencies=[Depends(require("policy:write"))],
    summary="Publish a policy",
)
async def publish_policy(policy_id: uuid.UUID, db: DbSession, user: CurrentUser) -> PolicyRead:
    obj = await _load(db, policy_id)
    refusal = publish_refusal(obj.workflow_status, obj.status)
    if refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refusal)
    # Publishing makes the approved policy binding on staff. The author cannot publish
    # their own policy either.
    await dual_control.enforce_record_maker_checker(
        db, module="policy", action="publish", entity_type="policy", entity_id=obj.id,
        checker_id=user.id, subject="policy publication",
    )
    obj.status = PolicyStatus.published
    obj.published_at = date.today()
    await db.flush()
    await audit.record(
        db, actor=user, action="publish", entity_type="policy", entity_id=obj.id,
        summary=f"Published policy {obj.reference}",
    )
    return await _read(db, await _load(db, obj.id))


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
async def delete_policy(policy_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Archive a policy (soft delete, audit-logged).

    **Dual control** ``policy / delete``: while segregation of duties applies, whoever
    entered the policy (``dual_control.maker_of``) cannot also archive it — 403.
    """
    from datetime import datetime, timezone

    obj = await _load(db, policy_id)
    await delete_guard.enforce(db, entity_type="policy", record=obj, user=user, label="policy")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit.record(
        db, actor=user, action="delete", entity_type="policy", entity_id=obj.id,
        summary=f"Archived policy {obj.reference}: {obj.title}",
    )


# ----------------------------------------------------------------- review cycle
@router.get(
    "/{policy_id}/reviews", response_model=list[PolicyReviewRead],
    dependencies=[Depends(require("policy:read"))],
)
async def list_policy_reviews(policy_id: uuid.UUID, db: DbSession) -> list[PolicyReviewRead]:
    obj = await _load(db, policy_id)
    items = [PolicyReviewRead.model_validate(r) for r in obj.reviews]
    await ref_fields.fill_refs(db, list(zip(obj.reviews, items)), REVIEW_REFS)
    return items


@router.post(
    "/{policy_id}/reviews", response_model=PolicyRead, status_code=201,
    dependencies=[Depends(require("policy:write"))],
)
async def schedule_policy_review(
    policy_id: uuid.UUID, body: PolicyReviewCreate, db: DbSession, user: CurrentUser
) -> PolicyRead:
    obj = await _load(db, policy_id)
    fields = body.model_dump()
    await ref_fields.apply_refs(db, PolicyReview, fields, REVIEW_REFS)
    db.add(PolicyReview(tenant_id=obj.tenant_id, policy_id=obj.id, **fields))
    obj.next_review_date = body.planned_date
    await db.flush()
    await audit.record(
        db, actor=user, action="schedule_review", entity_type="policy", entity_id=obj.id,
        summary=f"Scheduled a review of policy {obj.reference} for {body.planned_date}"
        + (f" by {fields['reviewer']}" if fields.get("reviewer") else ""),
    )
    return await _read(db, await _load(db, obj.id))


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
    return await _read(db, await _load(db, obj.id))
