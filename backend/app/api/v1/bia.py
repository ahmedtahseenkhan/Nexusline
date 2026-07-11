"""Business Impact Analysis API — per-process BIA driving business continuity planning."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.bia import BiaAssessment, BiaDependency, BiaStatus
from app.models.enums import Criticality
from app.schemas.bia import (
    BiaCreate,
    BiaDependencyCreate,
    BiaDependencyRead,
    BiaDependencyUpdate,
    BiaRead,
    BiaUpdate,
)
from app.schemas.common import Page
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["business impact analysis"])

_READ = Depends(require("bia:read"))
_WRITE = Depends(require("bia:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _load_bia(db, bid) -> BiaAssessment:
    obj = await db.scalar(
        select(BiaAssessment).where(BiaAssessment.id == bid, BiaAssessment.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="BIA not found")
    return obj


# ============================================================ BIA assessments ===
_BIA_SORTABLE = {
    "reference": BiaAssessment.reference,
    "process_name": BiaAssessment.process_name,
    "business_unit": BiaAssessment.business_unit,
    "criticality": BiaAssessment.criticality,
    "status": BiaAssessment.status,
    "rto_hours": BiaAssessment.rto_hours,
    "rpo_hours": BiaAssessment.rpo_hours,
    "next_review_date": BiaAssessment.next_review_date,
    "created_at": BiaAssessment.created_at,
}


@router.get("/bia", response_model=Page[BiaRead], dependencies=[_READ])
async def list_bia(
    db: DbSession,
    search: str | None = None,
    criticality: Annotated[Criticality | None, Query()] = None,
    status_filter: Annotated[BiaStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[BiaRead]:
    stmt: Select = select(BiaAssessment).where(BiaAssessment.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            BiaAssessment.process_name.ilike(like) | BiaAssessment.reference.ilike(like)
        )
    if criticality is not None:
        stmt = stmt.where(BiaAssessment.criticality == criticality)
    if status_filter is not None:
        stmt = stmt.where(BiaAssessment.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _BIA_SORTABLE, default=BiaAssessment.created_at)
    else:
        stmt = stmt.order_by(BiaAssessment.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[BiaRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/bia", response_model=BiaRead, status_code=201, dependencies=[_WRITE])
async def create_bia(body: BiaCreate, db: DbSession, user: CurrentUser) -> BiaRead:
    obj = BiaAssessment(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, BiaAssessment, "BIA")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="bia_assessment",
                           entity_id=obj.id, summary=f"Opened BIA {obj.reference}: {obj.process_name}")
    return BiaRead.model_validate(await _load_bia(db, obj.id))


@router.get("/bia/{bid}", response_model=BiaRead, dependencies=[_READ])
async def get_bia(bid: uuid.UUID, db: DbSession) -> BiaRead:
    return BiaRead.model_validate(await _load_bia(db, bid))


@router.patch("/bia/{bid}", response_model=BiaRead, dependencies=[_WRITE])
async def update_bia(bid: uuid.UUID, body: BiaUpdate, db: DbSession) -> BiaRead:
    obj = await _load_bia(db, bid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return BiaRead.model_validate(await _load_bia(db, bid))


@router.delete("/bia/{bid}", status_code=204, dependencies=[_WRITE])
async def delete_bia(bid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_bia(db, bid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()
    await audit_log.record(db, actor=user, action="delete", entity_type="bia_assessment",
                         entity_id=obj.id, summary=f"Archived BIA {obj.reference}")
    await db.flush()


# --------------------------------------------------------------- dependencies ---
@router.post("/bia/{bid}/dependencies", response_model=BiaRead, status_code=201, dependencies=[_WRITE])
async def add_dependency(bid: uuid.UUID, body: BiaDependencyCreate, db: DbSession, user: CurrentUser) -> BiaRead:
    await _load_bia(db, bid)
    db.add(BiaDependency(tenant_id=user.tenant_id, bia_id=bid, **body.model_dump()))
    await db.flush()
    return BiaRead.model_validate(await _load_bia(db, bid))


@router.patch("/bia-dependencies/{line_id}", response_model=BiaDependencyRead, dependencies=[_WRITE])
async def update_dependency(line_id: uuid.UUID, body: BiaDependencyUpdate, db: DbSession) -> BiaDependencyRead:
    obj = await _get(db, BiaDependency, line_id, "Dependency")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return BiaDependencyRead.model_validate(obj)


@router.delete("/bia-dependencies/{line_id}", status_code=204, dependencies=[_WRITE])
async def delete_dependency(line_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(BiaDependency).where(BiaDependency.id == line_id))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


# -------------------------------------------------------------------- summary ---
class BiaSummary(BaseModel):
    total: int
    by_criticality: dict[str, int]
    rto_within_24h: int
    rto_within_4h: int
    total_financial_exposure: float
    spof_dependencies: int
    review_overdue: int


@router.get("/bia-summary", response_model=BiaSummary, dependencies=[_READ],
            summary="Business impact analysis roll-up for the BCP dashboard")
async def bia_summary(db: DbSession) -> BiaSummary:
    rows = (await db.scalars(select(BiaAssessment).where(BiaAssessment.deleted.is_(False)))).all()
    by_crit: dict[str, int] = defaultdict(int)
    rto_24h = rto_4h = review_overdue = 0
    exposure = 0.0
    for r in rows:
        by_crit[r.criticality.value] += 1
        if r.rto_hours is not None and r.rto_hours <= 24:
            rto_24h += 1
        if r.rto_hours is not None and r.rto_hours <= 4:
            rto_4h += 1
        if r.is_review_overdue:
            review_overdue += 1
        exposure += float(r.financial_impact_24h or 0) + float(r.financial_impact_1week or 0)

    spof = await db.scalar(
        select(func.count())
        .select_from(BiaDependency)
        .join(BiaAssessment, BiaAssessment.id == BiaDependency.bia_id)
        .where(BiaAssessment.deleted.is_(False), BiaDependency.single_point_of_failure.is_(True))
    ) or 0

    return BiaSummary(
        total=len(rows),
        by_criticality=dict(by_crit),
        rto_within_24h=rto_24h,
        rto_within_4h=rto_4h,
        total_financial_exposure=round(exposure, 2),
        spof_dependencies=spof,
        review_overdue=review_overdue,
    )
