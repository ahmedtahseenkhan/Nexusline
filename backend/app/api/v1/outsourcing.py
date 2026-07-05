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
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.outsourcing import (
    OutsourcingArrangement,
    OutsourcingCategory,
    OutsourcingMateriality,
    OutsourcingReview,
    OutsourcingStatus,
    SbpApprovalStatus,
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
from app.services import audit as audit_log

router = APIRouter(tags=["outsourcing"])

_READ = Depends(require("outsourcing:read"))
_WRITE = Depends(require("outsourcing:write"))


async def _next_ref(db, model, prefix: str) -> str:
    count = await db.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{count + 1:03d}"


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _load_arrangement(db, aid) -> OutsourcingArrangement:
    obj = await db.scalar(
        select(OutsourcingArrangement).where(OutsourcingArrangement.id == aid).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Outsourcing arrangement not found")
    return obj


# ====================================================== outsourcing register ===
@router.get("/outsourcing", response_model=Page[OutsourcingArrangementRead], dependencies=[_READ])
async def list_arrangements(
    db: DbSession,
    search: str | None = None,
    category: OutsourcingCategory | None = None,
    materiality: OutsourcingMateriality | None = None,
    status: OutsourcingStatus | None = None,
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
    rows = (await db.scalars(stmt.order_by(OutsourcingArrangement.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[OutsourcingArrangementRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/outsourcing", response_model=OutsourcingArrangementRead, status_code=201, dependencies=[_WRITE])
async def create_arrangement(body: OutsourcingArrangementCreate, db: DbSession, user: CurrentUser) -> OutsourcingArrangementRead:
    obj = OutsourcingArrangement(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, OutsourcingArrangement, "OUT")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="outsourcing_arrangement",
                           entity_id=obj.id, summary=f"Registered outsourcing arrangement {obj.reference}: {obj.title}")
    return OutsourcingArrangementRead.model_validate(await _load_arrangement(db, obj.id))


@router.get("/outsourcing/{aid}", response_model=OutsourcingArrangementRead, dependencies=[_READ])
async def get_arrangement(aid: uuid.UUID, db: DbSession) -> OutsourcingArrangementRead:
    return OutsourcingArrangementRead.model_validate(await _load_arrangement(db, aid))


@router.patch("/outsourcing/{aid}", response_model=OutsourcingArrangementRead, dependencies=[_WRITE])
async def update_arrangement(aid: uuid.UUID, body: OutsourcingArrangementUpdate, db: DbSession) -> OutsourcingArrangementRead:
    obj = await _load_arrangement(db, aid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return OutsourcingArrangementRead.model_validate(await _load_arrangement(db, aid))


@router.delete("/outsourcing/{aid}", status_code=204, dependencies=[_WRITE])
async def delete_arrangement(aid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_arrangement(db, aid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ======================================================== outsourcing reviews ===
@router.post("/outsourcing/{aid}/reviews", response_model=OutsourcingArrangementRead, status_code=201, dependencies=[_WRITE])
async def add_review(aid: uuid.UUID, body: OutsourcingReviewCreate, db: DbSession, user: CurrentUser) -> OutsourcingArrangementRead:
    await _load_arrangement(db, aid)
    review = OutsourcingReview(tenant_id=user.tenant_id, arrangement_id=aid, **body.model_dump())
    review.reference = await _next_ref(db, OutsourcingReview, "OUR")
    db.add(review)
    await db.flush()
    return OutsourcingArrangementRead.model_validate(await _load_arrangement(db, aid))


@router.patch("/outsourcing-reviews/{rid}", response_model=OutsourcingReviewRead, dependencies=[_WRITE])
async def update_review(rid: uuid.UUID, body: OutsourcingReviewUpdate, db: DbSession) -> OutsourcingReviewRead:
    obj = await _get(db, OutsourcingReview, rid, "Outsourcing review")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return OutsourcingReviewRead.model_validate(obj)


@router.delete("/outsourcing-reviews/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_review(rid: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(OutsourcingReview).where(OutsourcingReview.id == rid))
    if obj is not None:
        await db.delete(obj)


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
    return OutsourcingSummary(
        total=len(rows),
        by_materiality=dict(by_materiality),
        material_count=material_count,
        cloud_count=cloud_count,
        material_cloud_count=material_cloud_count,
        sbp_approvals_pending=sbp_approvals_pending,
        contracts_expiring_90d=contracts_expiring_90d,
        exit_plans_untested=exit_plans_untested,
    )
