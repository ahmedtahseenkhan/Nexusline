"""Operational Risk API — RCSA campaigns, Key Risk Indicators and the Basel loss database."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.risk import Risk
from app.models.operational_risk import (
    KeyRiskIndicator,
    KriMeasurement,
    LossEvent,
    RcsaAssessment,
    RcsaRisk,
)
from app.schemas.common import Page
from app.schemas.operational_risk import (
    KriCreate,
    KriRead,
    KriUpdate,
    LossEventCreate,
    LossEventRead,
    LossEventUpdate,
    MeasurementCreate,
    RcsaCreate,
    RcsaRead,
    RcsaRiskCreate,
    RcsaRiskRead,
    RcsaRiskUpdate,
    RcsaUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["operational risk"])

_READ = Depends(require("oprisk:read"))
_WRITE = Depends(require("oprisk:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _resolve(db, model, ids):
    if not ids:
        return []
    return list((await db.scalars(select(model).where(model.id.in_(ids)))).all())


# ==================================================================== RCSA ===
async def _load_rcsa(db, rid) -> RcsaAssessment:
    obj = await db.scalar(select(RcsaAssessment).where(RcsaAssessment.id == rid).execution_options(populate_existing=True))
    if obj is None:
        raise HTTPException(status_code=404, detail="RCSA not found")
    return obj


_RCSA_SORTABLE = {
    "reference": RcsaAssessment.reference,
    "title": RcsaAssessment.title,
    "business_unit": RcsaAssessment.business_unit,
    "status": RcsaAssessment.status,
    "due_date": RcsaAssessment.due_date,
    "created_at": RcsaAssessment.created_at,
}


@router.get("/rcsa", response_model=Page[RcsaRead], dependencies=[_READ])
async def list_rcsa(db: DbSession, search: str | None = None,
                    sort_by: Annotated[str | None, Query()] = None,
                    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                    limit: Annotated[int, Query(ge=1, le=200)] = 100,
                    offset: Annotated[int, Query(ge=0)] = 0) -> Page[RcsaRead]:
    stmt = select(RcsaAssessment).where(RcsaAssessment.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(RcsaAssessment.title.ilike(like), RcsaAssessment.reference.ilike(like),
                             RcsaAssessment.business_unit.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _RCSA_SORTABLE, default=RcsaAssessment.created_at)
    else:
        stmt = stmt.order_by(RcsaAssessment.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[RcsaRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/rcsa", response_model=RcsaRead, status_code=201, dependencies=[_WRITE])
async def create_rcsa(body: RcsaCreate, db: DbSession, user: CurrentUser) -> RcsaRead:
    obj = RcsaAssessment(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, RcsaAssessment, "RCSA")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="rcsa_assessment",
                           entity_id=obj.id, summary=f"Opened RCSA {obj.reference}: {obj.title}")
    return RcsaRead.model_validate(await _load_rcsa(db, obj.id))


@router.get("/rcsa/{rid}", response_model=RcsaRead, dependencies=[_READ])
async def get_rcsa(rid: uuid.UUID, db: DbSession) -> RcsaRead:
    return RcsaRead.model_validate(await _load_rcsa(db, rid))


@router.patch("/rcsa/{rid}", response_model=RcsaRead, dependencies=[_WRITE])
async def update_rcsa(rid: uuid.UUID, body: RcsaUpdate, db: DbSession) -> RcsaRead:
    obj = await _load_rcsa(db, rid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return RcsaRead.model_validate(await _load_rcsa(db, rid))


@router.delete("/rcsa/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_rcsa(rid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_rcsa(db, rid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


@router.post("/rcsa/{rid}/risks", response_model=RcsaRead, status_code=201, dependencies=[_WRITE])
async def add_rcsa_risk(rid: uuid.UUID, body: RcsaRiskCreate, db: DbSession, user: CurrentUser) -> RcsaRead:
    await _load_rcsa(db, rid)
    db.add(RcsaRisk(tenant_id=user.tenant_id, assessment_id=rid, **body.model_dump()))
    await db.flush()
    return RcsaRead.model_validate(await _load_rcsa(db, rid))


@router.patch("/rcsa-risks/{line_id}", response_model=RcsaRiskRead, dependencies=[_WRITE])
async def update_rcsa_risk(line_id: uuid.UUID, body: RcsaRiskUpdate, db: DbSession) -> RcsaRiskRead:
    obj = await _get(db, RcsaRisk, line_id, "RCSA risk")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return RcsaRiskRead.model_validate(obj)


@router.delete("/rcsa-risks/{line_id}", status_code=204, dependencies=[_WRITE])
async def delete_rcsa_risk(line_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(RcsaRisk).where(RcsaRisk.id == line_id))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


# ===================================================================== KRIs ===
async def _load_kri(db, kid) -> KeyRiskIndicator:
    obj = await db.scalar(select(KeyRiskIndicator).where(KeyRiskIndicator.id == kid).execution_options(populate_existing=True))
    if obj is None:
        raise HTTPException(status_code=404, detail="KRI not found")
    return obj


# `status` / `is_breached` are computed from current_value vs thresholds, so they are not
# DB columns and cannot be sorted server-side; current_value is the sortable proxy.
_KRI_SORTABLE = {
    "reference": KeyRiskIndicator.reference,
    "name": KeyRiskIndicator.name,
    "category": KeyRiskIndicator.category,
    "owner": KeyRiskIndicator.owner,
    "current_value": KeyRiskIndicator.current_value,
    "last_measured_date": KeyRiskIndicator.last_measured_date,
    "created_at": KeyRiskIndicator.created_at,
}


@router.get("/kris", response_model=Page[KriRead], dependencies=[_READ])
async def list_kris(db: DbSession, search: str | None = None,
                    sort_by: Annotated[str | None, Query()] = None,
                    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                    limit: Annotated[int, Query(ge=1, le=200)] = 100,
                    offset: Annotated[int, Query(ge=0)] = 0) -> Page[KriRead]:
    stmt = select(KeyRiskIndicator).where(KeyRiskIndicator.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(KeyRiskIndicator.name.ilike(like), KeyRiskIndicator.reference.ilike(like),
                             KeyRiskIndicator.category.ilike(like), KeyRiskIndicator.owner.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _KRI_SORTABLE, default=KeyRiskIndicator.name)
    else:
        stmt = stmt.order_by(KeyRiskIndicator.name)
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[KriRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/kris", response_model=KriRead, status_code=201, dependencies=[_WRITE])
async def create_kri(body: KriCreate, db: DbSession, user: CurrentUser) -> KriRead:
    obj = KeyRiskIndicator(tenant_id=user.tenant_id, **body.model_dump(exclude={"risk_ids"}))
    obj.risks = await _resolve(db, Risk, body.risk_ids)
    obj.reference = await _next_ref(db, KeyRiskIndicator, "KRI")
    db.add(obj)
    await db.flush()
    return KriRead.model_validate(await _load_kri(db, obj.id))


@router.get("/kris/{kid}", response_model=KriRead, dependencies=[_READ])
async def get_kri(kid: uuid.UUID, db: DbSession) -> KriRead:
    return KriRead.model_validate(await _load_kri(db, kid))


@router.patch("/kris/{kid}", response_model=KriRead, dependencies=[_WRITE])
async def update_kri(kid: uuid.UUID, body: KriUpdate, db: DbSession) -> KriRead:
    obj = await _load_kri(db, kid)
    for k, v in body.model_dump(exclude_unset=True, exclude={"risk_ids"}).items():
        setattr(obj, k, v)
    if body.risk_ids is not None:
        obj.risks = await _resolve(db, Risk, body.risk_ids)
    await db.flush()
    return KriRead.model_validate(await _load_kri(db, kid))


@router.delete("/kris/{kid}", status_code=204, dependencies=[_WRITE])
async def delete_kri(kid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_kri(db, kid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


@router.post("/kris/{kid}/measurements", response_model=KriRead, status_code=201, dependencies=[_WRITE])
async def add_measurement(kid: uuid.UUID, body: MeasurementCreate, db: DbSession, user: CurrentUser) -> KriRead:
    kri = await _load_kri(db, kid)
    m = KriMeasurement(tenant_id=user.tenant_id, kri_id=kid, **body.model_dump())
    db.add(m)
    # Only advance the KRI's current value (which drives RAG status) when this measurement
    # is the most recent one — otherwise back-filling an older reading would corrupt the
    # live status and regress last_measured_date.
    as_of = body.as_of_date or date.today()
    if kri.last_measured_date is None or as_of >= kri.last_measured_date:
        kri.current_value = body.value
        kri.last_measured_date = as_of
    await db.flush()
    return KriRead.model_validate(await _load_kri(db, kid))


# =============================================================== loss events ===
# `net_loss` is computed (gross − recovery), not a DB column, so it is not sortable.
_LOSS_SORTABLE = {
    "reference": LossEvent.reference,
    "title": LossEvent.title,
    "basel_event_type": LossEvent.basel_event_type,
    "business_line": LossEvent.business_line,
    "gross_loss": LossEvent.gross_loss,
    "recovery": LossEvent.recovery,
    "status": LossEvent.status,
    "occurrence_date": LossEvent.occurrence_date,
    "created_at": LossEvent.created_at,
}


@router.get("/loss-events", response_model=Page[LossEventRead], dependencies=[_READ])
async def list_loss_events(db: DbSession, search: str | None = None,
                           sort_by: Annotated[str | None, Query()] = None,
                           sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                           limit: Annotated[int, Query(ge=1, le=200)] = 100,
                           offset: Annotated[int, Query(ge=0)] = 0) -> Page[LossEventRead]:
    stmt = select(LossEvent).where(LossEvent.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(LossEvent.title.ilike(like), LossEvent.reference.ilike(like),
                             LossEvent.business_line.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _LOSS_SORTABLE, default=LossEvent.occurrence_date)
    else:
        stmt = stmt.order_by(LossEvent.occurrence_date.is_(None), LossEvent.occurrence_date.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[LossEventRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/loss-events", response_model=LossEventRead, status_code=201, dependencies=[_WRITE])
async def create_loss_event(body: LossEventCreate, db: DbSession, user: CurrentUser) -> LossEventRead:
    obj = LossEvent(tenant_id=user.tenant_id, **body.model_dump(exclude={"risk_ids"}))
    obj.risks = await _resolve(db, Risk, body.risk_ids)
    obj.reference = await _next_ref(db, LossEvent, "LOSS")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="loss_event",
                           entity_id=obj.id, summary=f"Logged loss event {obj.reference}: {obj.title}")
    return LossEventRead.model_validate(await _get(db, LossEvent, obj.id, "Loss event"))


@router.patch("/loss-events/{lid}", response_model=LossEventRead, dependencies=[_WRITE])
async def update_loss_event(lid: uuid.UUID, body: LossEventUpdate, db: DbSession) -> LossEventRead:
    obj = await _get(db, LossEvent, lid, "Loss event")
    for k, v in body.model_dump(exclude_unset=True, exclude={"risk_ids"}).items():
        setattr(obj, k, v)
    if body.risk_ids is not None:
        obj.risks = await _resolve(db, Risk, body.risk_ids)
    await db.flush()
    return LossEventRead.model_validate(obj)


@router.delete("/loss-events/{lid}", status_code=204, dependencies=[_WRITE])
async def delete_loss_event(lid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, LossEvent, lid, "Loss event")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


class LossSummaryRow(BaseModel):
    basel_event_type: str
    count: int
    gross_loss: float
    net_loss: float


class LossSummary(BaseModel):
    rows: list[LossSummaryRow]
    total_gross: float
    total_net: float
    total_count: int


@router.get("/loss-events-summary", response_model=LossSummary, dependencies=[_READ],
            summary="Operational loss roll-up by Basel event type")
async def loss_summary(db: DbSession) -> LossSummary:
    events = (await db.scalars(select(LossEvent).where(LossEvent.deleted.is_(False)))).all()
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "gross": 0.0, "net": 0.0})
    for e in events:
        g = groups[e.basel_event_type.value]
        g["count"] += 1
        g["gross"] += float(e.gross_loss or 0)
        g["net"] += e.net_loss
    rows = [LossSummaryRow(basel_event_type=k, count=v["count"],
                           gross_loss=round(v["gross"], 2), net_loss=round(v["net"], 2))
            for k, v in sorted(groups.items())]
    return LossSummary(
        rows=rows,
        total_gross=round(sum(r.gross_loss for r in rows), 2),
        total_net=round(sum(r.net_loss for r in rows), 2),
        total_count=sum(r.count for r in rows),
    )
