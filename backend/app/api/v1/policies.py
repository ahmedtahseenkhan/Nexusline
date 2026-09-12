"""Policy Management API — repository, publish, and acknowledgment tracking.

Phase 2 (§2.7) adds document governance and applicability:

* ``approving_authority_id`` — the committee (Governance) that approves the policy.
* ``effective_date`` — may not precede the policy's approval (the latest
  ``workflow_approve`` in its audit trail); left empty, Publish sets it to the
  publication date.
* ``supersedes_id`` — the policy this one replaces: not itself, and no cycles
  (A supersedes B supersedes A). When this policy is published — or when a published
  policy is pointed at another — the superseded one is retired through the lifecycle
  service (a system transition, audited as ``workflow_retire`` naming the successor).
  Reads carry ``supersedes_ref`` and ``superseded_by``.
* ``business_unit_ids`` / ``role_ids`` — who the policy applies to
  (``policy_business_units`` / ``policy_roles``). Users are not linked to business
  units in this model, so acknowledgement targeting (``GET
  /policies/{id}/acknowledgement-status``) reads the roles: members of the policy's roles
  are in scope, or every active user when the policy names no role.
* ``requirements_ids`` — written straight into ``requirement_policies`` (the ORM
  collection on the policy side is view-only), as are controls and risks.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.audit import AuditLog
from app.models.compliance import Requirement, requirement_policies
from app.models.control import Control, control_policies
from app.models.enums import PolicyStatus
from app.models.governance import Committee
from app.models.identity import Role, User
from app.models.organization import BusinessUnit
from app.models.policy import Policy, PolicyAcknowledgment, PolicyReview
from app.models.risk import Risk, risk_policies
from app.schemas.common import GraphRef, Page
from app.schemas.policy import (
    PolicyAckStatus,
    PolicyAckStatusRow,
    PolicyAcknowledgmentRead,
    PolicyCreate,
    PolicyOptions,
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
        selectinload(Policy.business_units),
        selectinload(Policy.roles),
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
    await _fill_governance(db, policies, items)
    return items


async def _fill_governance(db, policies, items) -> None:
    """Approving committee, superseded policy and successors for a page of policies —
    one query for the committees and one for the supersession links."""
    if not policies:
        return
    authority_ids = {p.approving_authority_id for p in policies if p.approving_authority_id}
    committees = {}
    if authority_ids:
        rows = (await db.execute(
            select(Committee.id, Committee.reference, Committee.name).where(Committee.id.in_(authority_ids))
        )).all()
        committees = {r[0]: GraphRef(id=r[0], reference=r[1] or "", name=r[2] or "") for r in rows}
    page_ids = [p.id for p in policies]
    target_ids = {p.supersedes_id for p in policies if p.supersedes_id}
    rows = (await db.execute(
        select(Policy.id, Policy.reference, Policy.title, Policy.supersedes_id).where(
            Policy.deleted.is_(False),
            or_(Policy.id.in_(list(target_ids)), Policy.supersedes_id.in_(page_ids)),
        )
    )).all()
    by_id = {r[0]: GraphRef(id=r[0], reference=r[1] or "", title=r[2] or "") for r in rows}
    successors: dict = defaultdict(list)
    for r in rows:
        if r[3] is not None:
            successors[r[3]].append(by_id[r[0]])
    for p, item in zip(policies, items):
        item.approving_authority_ref = committees.get(p.approving_authority_id)
        item.supersedes_ref = by_id.get(p.supersedes_id) if p.supersedes_id else None
        item.superseded_by = sorted(successors.get(p.id, []), key=lambda g: g.reference)


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
    unit_ids = data.pop("business_unit_ids", _KEEP)
    if unit_ids is not _KEEP and unit_ids is not None:
        obj.business_units = await _load_strict(db, BusinessUnit, unit_ids, "business_unit_ids", "business unit")
    role_ids = data.pop("role_ids", _KEEP)
    if role_ids is not _KEEP and role_ids is not None:
        obj.roles = await _load_strict(db, Role, role_ids, "role_ids", "role")
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


async def _load_strict(db, model, ids, field: str, noun: str) -> list:
    """The records for ``ids`` (deduplicated); 422 naming the field for any unknown or
    archived one."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    rows = list((await db.scalars(stmt)).all())
    missing = [str(i) for i in ids if i not in {r.id for r in rows}]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field}: unknown or archived {noun} id(s): {', '.join(missing)}",
        )
    return rows


# ------------------------------------------------------------- governance rules ---
def supersession_refusal(policy_id, target_id, parents: dict) -> str | None:
    """Why ``policy_id`` may not supersede ``target_id``, or None. Pure.

    ``parents`` maps each policy to the one it supersedes. A policy can't supersede
    itself, nor a policy that (directly or down the chain) already supersedes it —
    that would make each one the other's replacement."""
    if target_id is None:
        return None
    if policy_id is not None and target_id == policy_id:
        return "supersedes_id: a policy can't supersede itself."
    seen = set()
    cur = target_id
    while cur is not None and cur not in seen:
        if policy_id is not None and cur == policy_id:
            return (
                "supersedes_id: that policy already supersedes this one (directly or through "
                "the policies it replaced), so this would be a cycle."
            )
        seen.add(cur)
        cur = parents.get(cur)
    return None


def effective_date_refusal(effective, approved_on) -> str | None:
    """An effective date may not precede the policy's approval. Pure."""
    if effective is None or approved_on is None or effective >= approved_on:
        return None
    return (
        f"effective_date: {effective.isoformat()} is before the policy was approved "
        f"({approved_on.isoformat()}); a policy can't take effect before it is approved."
    )


async def _approved_on(db, policy) -> date | None:
    """The day the policy was last approved (lifecycle approve or an approvals-inbox
    decision), in the organisation's timezone — None when it never was."""
    at = await db.scalar(
        select(func.max(AuditLog.created_at)).where(
            AuditLog.entity_type == "policy",
            AuditLog.entity_id == policy.id,
            AuditLog.action == "workflow_approve",
        )
    )
    if at is None:
        return None
    from app.services import incident_clock

    return incident_clock.local_date(at, await incident_clock.tenant_zone(db, policy.tenant_id))


async def _check_governance(db, data: dict, obj=None) -> None:
    """Validate the committee, the superseded policy and the effective date a write sets."""
    authority = data.get("approving_authority_id")
    if authority is not None and (obj is None or authority != obj.approving_authority_id):
        found = await db.scalar(
            select(Committee.id).where(Committee.id == authority, Committee.deleted.is_(False))
        )
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="approving_authority_id: pick a board or committee from Governance.",
            )
    target = data.get("supersedes_id")
    if target is not None and (obj is None or target != obj.supersedes_id):
        own_id = obj.id if obj is not None else None
        refusal = supersession_refusal(own_id, target, {})
        if refusal is None:
            found = await db.scalar(select(Policy.id).where(Policy.id == target, Policy.deleted.is_(False)))
            if found is None:
                refusal = "supersedes_id: that policy does not exist or is archived."
        if refusal is None and own_id is not None:
            parents = dict((await db.execute(
                select(Policy.id, Policy.supersedes_id).where(Policy.supersedes_id.is_not(None))
            )).all())
            refusal = supersession_refusal(own_id, target, parents)
        if refusal:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=refusal)
    effective = data.get("effective_date")
    if effective is not None and obj is not None and effective != obj.effective_date:
        refusal = effective_date_refusal(effective, await _approved_on(db, obj))
        if refusal:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=refusal)


async def retire_superseded(db, user, policy) -> str | None:
    """Retire the policy ``policy`` supersedes, now that ``policy`` is in force.

    A system transition through the lifecycle service (the old policy's approval is
    not re-decided: it has been replaced), audited on the old policy as
    ``workflow_retire`` naming the successor and who published it. Returns the retired
    policy's reference, or None when there was nothing to retire."""
    from app.services import record_workflow

    if policy.supersedes_id is None:
        return None
    old = await db.scalar(
        select(Policy).where(Policy.id == policy.supersedes_id, Policy.deleted.is_(False))
    )
    if old is None:
        return None
    current = record_workflow.state_value(old.workflow_status)
    if current == record_workflow.RETIRED and old.status == PolicyStatus.retired:
        return None
    await record_workflow._set_state(db, old, record_workflow.RETIRED)
    await audit.record(
        db, actor=user, action=f"{record_workflow.AUDIT_PREFIX}retire", entity_type="policy",
        entity_id=old.id,
        summary=f"Retired: policy {old.reference} — superseded by {policy.reference} (published)",
        changes={"from": current, "to": record_workflow.RETIRED, "via": "supersession",
                 "superseded_by": str(policy.id), "superseded_by_reference": policy.reference},
    )
    return old.reference


def ack_status(policy, users) -> PolicyAckStatus:
    """Who must acknowledge ``policy`` and who has. Pure.

    In scope: active users holding one of the policy's roles — or every active user
    when the policy names no role. Business units don't narrow it (users carry no unit
    in this model); the note says so when units are set."""
    role_ids = {r.id for r in policy.roles}
    acks = {a.user_id: a for a in policy.acknowledgments}
    active = [u for u in users if getattr(u, "is_active", True)]
    if role_ids:
        in_scope = [u for u in active if role_ids & {r.id for r in u.roles}]
        scope = "roles"
        note = "Members of the policy's roles are asked to acknowledge it."
    else:
        in_scope = active
        scope = "everyone"
        note = "The policy names no role, so every active user is asked to acknowledge it."
    if policy.business_units:
        note += (" Business units are recorded but don't narrow the list: users aren't "
                 "linked to business units.")
    rows = []
    for u in in_scope:
        ack = acks.get(u.id)
        rows.append(PolicyAckStatusRow(
            user_id=u.id, full_name=u.full_name or "", email=u.email or "",
            roles=sorted(r.name for r in u.roles), acknowledged=ack is not None,
            acknowledged_at=ack.created_at if ack is not None else None,
        ))
    rows.sort(key=lambda r: (r.acknowledged, (r.full_name or r.email).lower()))
    done = sum(1 for r in rows if r.acknowledged)
    in_ids = {u.id for u in in_scope}
    return PolicyAckStatus(
        policy_id=policy.id, scope=scope, roles=sorted(r.name for r in policy.roles), note=note,
        total=len(rows), acknowledged=done, pending=len(rows) - done,
        outside_scope=sum(1 for uid in acks if uid not in in_ids), users=rows,
    )


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


@router.get(
    "/options", response_model=PolicyOptions, dependencies=[Depends(require("policy:read"))],
    summary="Committees and roles the policy form picks from",
)
async def policy_options(db: DbSession) -> PolicyOptions:
    committees = (await db.execute(
        select(Committee.id, Committee.reference, Committee.name)
        .where(Committee.deleted.is_(False)).order_by(Committee.name)
    )).all()
    roles = (await db.execute(select(Role.id, Role.name).order_by(Role.name))).all()
    return PolicyOptions(
        committees=[GraphRef(id=c[0], reference=c[1] or "", name=c[2] or "") for c in committees],
        roles=[GraphRef(id=r[0], name=r[1]) for r in roles],
    )


@router.post(
    "",
    response_model=PolicyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("policy:write"))],
)
async def create_policy(body: PolicyCreate, db: DbSession, user: CurrentUser) -> PolicyRead:
    data = body.model_dump()
    _check_initial_status(user, data.get("status"))
    await _check_governance(db, data)
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
    await _check_governance(db, data, obj)
    await ref_fields.apply_refs(db, Policy, data, POLICY_REFS, record=obj)
    supersedes_changed = "supersedes_id" in data and data["supersedes_id"] != obj.supersedes_id
    stash = await _apply_related(db, obj, data)
    for field, value in data.items():
        setattr(obj, field, value)
    if "review_frequency" in data:
        obj.next_review_date = next_review_date(obj.review_frequency)
    await db.flush()
    await _flush_assoc(db, obj.id, stash)
    await db.flush()
    # A policy already in force that is pointed at the one it replaces retires it now.
    retired = await retire_superseded(db, user, obj) if supersedes_changed and obj.status == PolicyStatus.published else None
    await audit.record(
        db, actor=user, action="update", entity_type="policy", entity_id=obj.id,
        summary=f"Updated policy {obj.reference}: {obj.title}" + (f" (retired {retired}, which it supersedes)" if retired else ""),
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
    today = date.today()
    if obj.effective_date is not None:
        refusal = effective_date_refusal(obj.effective_date, await _approved_on(db, obj))
        if refusal:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refusal)
    obj.status = PolicyStatus.published
    obj.published_at = today
    if obj.effective_date is None:
        obj.effective_date = today  # takes effect on publication unless dated otherwise
    await db.flush()
    retired = await retire_superseded(db, user, obj)
    await audit.record(
        db, actor=user, action="publish", entity_type="policy", entity_id=obj.id,
        summary=f"Published policy {obj.reference}, effective {obj.effective_date.isoformat()}"
        + (f"; retired {retired}, which it supersedes" if retired else ""),
        changes={"effective_date": obj.effective_date.isoformat(), "retired": retired},
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
    policy = await _load(db, policy_id)
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
    await audit.record(
        db, actor=user, action="acknowledge", entity_type="policy", entity_id=policy_id,
        summary=f"Acknowledged policy {policy.reference} (version {policy.version})",
    )
    return PolicyAcknowledgmentRead.model_validate(ack)


@router.get(
    "/{policy_id}/acknowledgement-status",
    response_model=PolicyAckStatus,
    dependencies=[Depends(require("policy:read"))],
    summary="Who must acknowledge the policy (by its roles) and who has",
)
async def acknowledgement_status(policy_id: uuid.UUID, db: DbSession) -> PolicyAckStatus:
    """Users in scope with acknowledged yes/no and when. In scope: members of the
    policy's roles, or every active user when it names none. Business units do not
    narrow the list — users are not linked to units in this model."""
    obj = await _load(db, policy_id)
    users = (await db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.full_name, User.email)
    )).all()
    return ack_status(obj, users)


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
