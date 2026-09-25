"""Outsourcing & Cloud Risk API — the SBP outsourcing/cloud regulatory overlay.

Layered on top of the vendor register, this tracks each outsourcing arrangement's
materiality determination, cloud model / data offshoring, SBP approval (NOC) status,
contract window, documented-and-tested exit plan and concentration risk, plus the
periodic monitoring reviews performed against it. Amounts and terminology follow SBP /
Pakistani-banking conventions.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.vendor import Vendor
from app.models.outsourcing import (
    ACTIVATION_FIELDS,
    HARD_TO_SUBSTITUTE,
    LIVE_STATUSES,
    OutsourcingArrangement,
    OutsourcingCategory,
    OutsourcingMateriality,
    OutsourcingReview,
    OutsourcingStatus,
    SbpApprovalStatus,
    missing_for_activation,
)
from app.schemas.common import Page
from app.schemas.outsourcing import (
    OutsourcingArrangementCreate,
    OutsourcingArrangementRead,
    OutsourcingArrangementUpdate,
    OutsourcingReviewCreate,
    OutsourcingReviewRead,
    OutsourcingReviewUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log
from app.services import lifecycle_gates
from app.services import ref_fields as rf
from app.services import fx
from app.schemas.fx import MoneyTotalRead

router = APIRouter(tags=["outsourcing"])

# Phase 2 picker fields beside the legacy text they replace (services/ref_fields): the
# picked id wins and writes its display text into ``owner`` / ``country``; text sent on
# its own (older clients, CSV import) is matched to a user / country value, and kept as
# typed when nothing matches.
OUTSOURCING_REFS = (
    rf.user("owner_id", "owner"),
    rf.RefField("country_id", "country", "lookup", "country"),
)


async def _arr_reads(db, rows) -> list[OutsourcingArrangementRead]:
    items = [OutsourcingArrangementRead.model_validate(r) for r in rows]
    await rf.fill_refs(db, list(zip(rows, items)), OUTSOURCING_REFS)
    return items


async def _arr_read(db, aid) -> OutsourcingArrangementRead:
    return (await _arr_reads(db, [await _load_arrangement(db, aid)]))[0]


async def _check_vendor(db, vendor_id) -> None:
    if vendor_id is None:
        return
    v = await db.scalar(select(Vendor.id).where(Vendor.id == vendor_id, Vendor.deleted.is_(False)))
    if v is None:
        raise HTTPException(status_code=400, detail=f"Unknown or archived vendor id: {vendor_id}")

def _status(value) -> OutsourcingStatus | None:
    raw = getattr(value, "value", value)
    try:
        return OutsourcingStatus(raw) if raw else None
    except ValueError:
        return None


def activation_error(before: dict | None, after: dict) -> str | None:
    """Why this write would leave a material arrangement live without the facts SBP
    expects on file, or None. Pure.

    ``before`` is the stored arrangement (None on create) and ``after`` the result of the
    write, each with ``status``, ``materiality`` and the :data:`ACTIVATION_FIELDS`. Only a
    write that *brings* the arrangement into that state is refused — moving it past
    proposed, making a live one material, or blanking a required fact on a live material
    one — so editing an arrangement recorded before the rule existed keeps working (its
    open point still shows what is missing)."""
    status_after = _status(after.get("status"))
    if status_after not in LIVE_STATUSES:
        return None
    status_before = _status(before.get("status")) if before is not None else None
    if _awaits_sbp(after) and not (status_before in LIVE_STATUSES and _awaits_sbp(before)):
        # SBP's outsourcing framework: where its approval (NOC) is required, the service
        # does not start before it is granted.
        return (
            f"This arrangement needs SBP's approval (NOC), which is "
            f"{_plain(after.get('sbp_approval_status')) or 'not recorded'}; it can't be "
            f"{status_after.value.replace('_', ' ')} until SBP has approved it. Record the "
            "approval and its reference first."
        )
    missing = missing_for_activation(after["materiality"], after)
    if not missing:
        return None
    if before is not None:
        was_missing = set(missing_for_activation(before["materiality"], before))
        if status_before in LIVE_STATUSES and set(missing) <= was_missing:
            return None
    names = missing[0] if len(missing) == 1 else f"{', '.join(missing[:-1])} and {missing[-1]}"
    verb = "is" if len(missing) == 1 else "are"
    return (
        f"A material outsourcing arrangement can't be {status_after.value.replace('_', ' ')} "
        f"until its {names} {verb} recorded. SBP expects these on file for every material "
        "arrangement; keep it proposed until they are."
    )


def _plain(value) -> str:
    return str(getattr(value, "value", value) or "").replace("_", " ")


def _awaits_sbp(facts: dict | None) -> bool:
    """SBP approval is required and not (yet) granted."""
    if not facts or not facts.get("sbp_approval_required"):
        return False
    return _plain(facts.get("sbp_approval_status")) != SbpApprovalStatus.approved.value


def _facts(obj_or_data) -> dict:
    keys = ("status", "materiality", "sbp_approval_required", "sbp_approval_status") + tuple(
        name for name, _ in ACTIVATION_FIELDS)
    if isinstance(obj_or_data, dict):
        return {k: obj_or_data.get(k) for k in keys}
    return {k: getattr(obj_or_data, k, None) for k in keys}


_READ = Depends(require("outsourcing:read"))
_WRITE = Depends(require("outsourcing:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _load_arrangement(db, aid) -> OutsourcingArrangement:
    obj = await db.scalar(
        select(OutsourcingArrangement).where(OutsourcingArrangement.id == aid, OutsourcingArrangement.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Outsourcing arrangement not found")
    return obj


# ====================================================== outsourcing register ===
_ARRANGEMENT_SORTABLE = {
    "reference": OutsourcingArrangement.reference,
    "title": OutsourcingArrangement.title,
    "service_provider": OutsourcingArrangement.service_provider,
    "category": OutsourcingArrangement.category,
    "materiality": OutsourcingArrangement.materiality,
    "status": OutsourcingArrangement.status,
    "contract_end": OutsourcingArrangement.contract_end,
    "created_at": OutsourcingArrangement.created_at,
}


@router.get("/outsourcing", response_model=Page[OutsourcingArrangementRead], dependencies=[_READ])
async def list_arrangements(
    db: DbSession,
    search: str | None = None,
    category: OutsourcingCategory | None = None,
    materiality: OutsourcingMateriality | None = None,
    status: OutsourcingStatus | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[OutsourcingArrangementRead]:
    stmt = select(OutsourcingArrangement).where(OutsourcingArrangement.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                OutsourcingArrangement.title.ilike(like),
                OutsourcingArrangement.reference.ilike(like),
                OutsourcingArrangement.service_provider.ilike(like),
                OutsourcingArrangement.owner.ilike(like),
            )
        )
    if category is not None:
        stmt = stmt.where(OutsourcingArrangement.category == category)
    if materiality is not None:
        stmt = stmt.where(OutsourcingArrangement.materiality == materiality)
    if status is not None:
        stmt = stmt.where(OutsourcingArrangement.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _ARRANGEMENT_SORTABLE, default=OutsourcingArrangement.created_at)
    else:
        stmt = stmt.order_by(OutsourcingArrangement.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=await _arr_reads(db, rows), total=total, limit=limit, offset=offset)


@router.post("/outsourcing", response_model=OutsourcingArrangementRead, status_code=201, dependencies=[_WRITE])
async def create_arrangement(body: OutsourcingArrangementCreate, db: DbSession, user: CurrentUser) -> OutsourcingArrangementRead:
    await _check_vendor(db, body.vendor_id)
    data = body.model_dump()
    # Going live needs the arrangement's approval first (lifecycle_gates.APPROVED_FIRST):
    # a new arrangement is proposed and approved through its lifecycle.
    lifecycle_gates.enforce_create("outsourcing_arrangement", data)
    error = activation_error(None, _facts(data))
    if error:
        raise HTTPException(status_code=422, detail=error)
    await rf.apply_refs(db, OutsourcingArrangement, data, OUTSOURCING_REFS)
    obj = OutsourcingArrangement(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, OutsourcingArrangement, "OUT")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="outsourcing_arrangement",
                           entity_id=obj.id, summary=f"Registered outsourcing arrangement {obj.reference}: {obj.title}")
    return await _arr_read(db, obj.id)


@router.get("/outsourcing/{aid}", response_model=OutsourcingArrangementRead, dependencies=[_READ])
async def get_arrangement(aid: uuid.UUID, db: DbSession) -> OutsourcingArrangementRead:
    return await _arr_read(db, aid)


@router.patch("/outsourcing/{aid}", response_model=OutsourcingArrangementRead, dependencies=[_WRITE])
async def update_arrangement(
    aid: uuid.UUID, body: OutsourcingArrangementUpdate, db: DbSession, user: CurrentUser
) -> OutsourcingArrangementRead:
    obj = await _load_arrangement(db, aid)
    data = body.model_dump(exclude_unset=True)
    if data.get("vendor_id") is not None and data["vendor_id"] != obj.vendor_id:
        await _check_vendor(db, data["vendor_id"])
    # Enum / NOT NULL columns: a null in a partial update means "unchanged".
    for k in ("title", "category", "materiality", "cloud_model", "sbp_approval_status", "status",
              "is_cloud", "data_offshored", "sbp_approval_required", "exit_plan_tested"):
        if k in data and data[k] is None:
            data.pop(k)
    for k in ("substitutability", "concentration_level"):
        if k in data and data[k] is None:
            data.pop(k)
    lifecycle_gates.enforce_edit("outsourcing_arrangement", obj, data)
    before = _facts(obj)
    error = activation_error(before, {**before, **{k: v for k, v in data.items() if k in before}})
    if error:
        raise HTTPException(status_code=422, detail=error)
    await rf.apply_refs(db, OutsourcingArrangement, data, OUTSOURCING_REFS, record=obj)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    await audit_log.record(db, actor=user, action="update", entity_type="outsourcing_arrangement",
                           entity_id=obj.id, summary=f"Updated outsourcing arrangement {obj.reference}: {obj.title}")
    return await _arr_read(db, aid)


@router.delete("/outsourcing/{aid}", status_code=204, dependencies=[_WRITE])
async def delete_arrangement(aid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_arrangement(db, aid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit_log.record(db, actor=user, action="delete", entity_type="outsourcing_arrangement",
                         entity_id=obj.id, summary=f"Archived outsourcing arrangement {obj.reference}")
    await db.flush()


# ======================================================== outsourcing reviews ===
@router.post("/outsourcing/{aid}/reviews", response_model=OutsourcingArrangementRead, status_code=201, dependencies=[_WRITE])
async def add_review(aid: uuid.UUID, body: OutsourcingReviewCreate, db: DbSession, user: CurrentUser) -> OutsourcingArrangementRead:
    arrangement = await _load_arrangement(db, aid)
    review = OutsourcingReview(tenant_id=user.tenant_id, arrangement_id=aid, **body.model_dump())
    review.reference = await _next_ref(db, OutsourcingReview, "OUR")
    db.add(review)
    await db.flush()
    await audit_log.record(db, actor=user, action="add_review", entity_type="outsourcing_arrangement",
                           entity_id=aid, summary=f"Added monitoring review {review.reference} to {arrangement.reference}")
    return await _arr_read(db, aid)


@router.patch("/outsourcing-reviews/{rid}", response_model=OutsourcingReviewRead, dependencies=[_WRITE])
async def update_review(
    rid: uuid.UUID, body: OutsourcingReviewUpdate, db: DbSession, user: CurrentUser
) -> OutsourcingReviewRead:
    obj = await _get(db, OutsourcingReview, rid, "Outsourcing review")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await audit_log.record(db, actor=user, action="update_review", entity_type="outsourcing_arrangement",
                           entity_id=obj.arrangement_id, summary=f"Updated monitoring review {obj.reference}")
    return OutsourcingReviewRead.model_validate(obj)


@router.delete("/outsourcing-reviews/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_review(rid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await db.scalar(select(OutsourcingReview).where(OutsourcingReview.id == rid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)
    await audit_log.record(db, actor=user, action="delete_review", entity_type="outsourcing_arrangement",
                           entity_id=obj.arrangement_id, summary=f"Removed monitoring review {obj.reference}")


# ================================================================ summary ===
class OutsourcingSummary(BaseModel):
    total: int
    by_materiality: dict[str, int]
    material_count: int
    cloud_count: int
    material_cloud_count: int
    sbp_approvals_pending: int
    contracts_expiring_90d: int
    exit_plans_untested: int
    #: Material arrangements whose service is difficult or impossible to substitute.
    hard_to_substitute: int = 0
    #: ...of which the exit plan is missing or untested (the most urgent gap).
    hard_to_substitute_untested: int = 0
    #: Material arrangements with no substitutability assessed.
    substitutability_unassessed: int = 0
    #: Arrangements recorded as high concentration.
    high_concentration: int = 0
    #: Material arrangements that are live (active / under review) without the
    #: materiality rationale, exit plan and substitutability on file.
    live_missing_facts: int = 0
    #: Decision 4: contract value of arrangements that are not terminated, in the reporting
    #: currency at today's rates; values with no rate are listed in ``unconverted``.
    contract_value: MoneyTotalRead = MoneyTotalRead()


@router.get("/outsourcing-summary", response_model=OutsourcingSummary, dependencies=[_READ],
            summary="Outsourcing dashboard roll-up: materiality, cloud, SBP approvals, expiring contracts and untested exit plans")
async def outsourcing_summary(db: DbSession) -> OutsourcingSummary:
    rows = (await db.scalars(select(OutsourcingArrangement).where(OutsourcingArrangement.deleted.is_(False)))).all()
    by_materiality: dict[str, int] = defaultdict(int)
    material_count = 0
    cloud_count = 0
    material_cloud_count = 0
    sbp_approvals_pending = 0
    contracts_expiring_90d = 0
    exit_plans_untested = 0
    hard = hard_untested = unassessed = high_conc = live_missing = 0
    valued = [a for a in rows if getattr(a, "contract_value", None) is not None
              and a.status != OutsourcingStatus.terminated]
    contract_value = fx.MoneyTotal(await fx.load_rate_book(db) if valued else fx.RateBook(None))
    for a in valued:
        contract_value.add(a.contract_value, a.contract_currency)  # stock figure: today's rate
    for a in rows:
        by_materiality[a.materiality.value] += 1
        is_material = a.materiality == OutsourcingMateriality.material
        if is_material:
            material_count += 1
        if a.is_cloud:
            cloud_count += 1
        if is_material and a.is_cloud:
            material_cloud_count += 1
        if a.sbp_approval_status == SbpApprovalStatus.pending:
            sbp_approvals_pending += 1
        if a.is_contract_expiring:
            contracts_expiring_90d += 1
        if is_material and not a.exit_plan_tested:
            exit_plans_untested += 1
        if a.concentration_level == "high" and a.status != OutsourcingStatus.terminated:
            high_conc += 1
        if not is_material or a.status == OutsourcingStatus.terminated:
            continue
        if a.substitutability in HARD_TO_SUBSTITUTE:
            hard += 1
            if not (a.exit_plan or "").strip() or not a.exit_plan_tested:
                hard_untested += 1
        elif not a.substitutability:
            unassessed += 1
        if a.status in LIVE_STATUSES and a.missing_for_activation:
            live_missing += 1
    return OutsourcingSummary(
        total=len(rows),
        by_materiality=dict(by_materiality),
        material_count=material_count,
        cloud_count=cloud_count,
        material_cloud_count=material_cloud_count,
        sbp_approvals_pending=sbp_approvals_pending,
        contracts_expiring_90d=contracts_expiring_90d,
        exit_plans_untested=exit_plans_untested,
        hard_to_substitute=hard,
        hard_to_substitute_untested=hard_untested,
        substitutability_unassessed=unassessed,
        high_concentration=high_conc,
        live_missing_facts=live_missing,
        # Nothing valued: no rate lookup, and no reporting currency claimed ("" = the organisation's).
        contract_value=MoneyTotalRead(**{**contract_value.as_dict(), **({} if valued else {"reporting_currency": ""})}),
    )
