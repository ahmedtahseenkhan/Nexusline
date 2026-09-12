"""Operational Risk API — RCSA campaigns, Key Risk Indicators and the Basel loss database."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.services import ref_fields as rf

router = APIRouter(tags=["operational risk"])

_READ = Depends(require("oprisk:read"))
_WRITE = Depends(require("oprisk:write"))

# Phase 1 picker fields and the legacy text each one keeps in step (services/ref_fields).
RCSA_REFS = (
    rf.user("assessor_id", "assessor"),
    rf.unit("business_unit_id", "business_unit"),
    rf.process("process_id", "process"),
    rf.WORKFLOW_OWNER,
)
RCSA_LINE_REFS = (
    rf.lookup(RcsaRisk, "category_id", "category"),
    rf.user("action_owner_id", "action_owner"),
)
KRI_REFS = (
    rf.user("owner_id", "owner"),
    rf.unit("business_unit_id", "business_area"),
    rf.lookup(KeyRiskIndicator, "category_id", "category"),
    rf.WORKFLOW_OWNER,
)
LOSS_REFS = (
    rf.user("action_owner_id", "action_owner"),
    rf.unit("business_unit_id", "business_line"),
    rf.WORKFLOW_OWNER,
)


async def _rcsa_reads(db, rows) -> list[RcsaRead]:
    """RCSA read models with people, units, processes and categories resolved in one
    query per kind across the campaigns and their risk lines."""
    items = [RcsaRead.model_validate(r) for r in rows]
    pairs: list = []
    for row, item in zip(rows, items):
        pairs.append((row, item))
        pairs.extend(zip(row.risks, item.risks))
    await rf.fill_refs(db, pairs, RCSA_REFS + RCSA_LINE_REFS)
    return items


async def _reads(db, schema, rows, fields) -> list:
    items = [schema.model_validate(r) for r in rows]
    await rf.fill_refs(db, list(zip(rows, items)), fields)
    return items


async def _audit_delete(db, user, entity_type: str, obj, label: str) -> None:
    await audit_log.record(
        db, actor=user, action="delete", entity_type=entity_type, entity_id=obj.id,
        summary=f"Archived {label} {obj.reference}",
    )


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
    return list(
        (
            await db.scalars(
                select(model).where(model.id.in_(ids), model.deleted.is_(False))
            )
        ).all()
    )


# ==================================================================== RCSA ===
async def _load_rcsa(db, rid) -> RcsaAssessment:
    obj = await db.scalar(
        select(RcsaAssessment)
        .where(RcsaAssessment.id == rid, RcsaAssessment.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
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
                    business_unit_id: uuid.UUID | None = None,
                    assessor_id: uuid.UUID | None = None,
                    sort_by: Annotated[str | None, Query()] = None,
                    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                    limit: Annotated[int, Query(ge=1, le=200)] = 100,
                    offset: Annotated[int, Query(ge=0)] = 0) -> Page[RcsaRead]:
    stmt = select(RcsaAssessment).where(RcsaAssessment.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(RcsaAssessment.title.ilike(like), RcsaAssessment.reference.ilike(like),
                             RcsaAssessment.business_unit.ilike(like)))
    if business_unit_id is not None:
        stmt = stmt.where(RcsaAssessment.business_unit_id == business_unit_id)
    if assessor_id is not None:
        stmt = stmt.where(RcsaAssessment.assessor_id == assessor_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _RCSA_SORTABLE, default=RcsaAssessment.created_at)
    else:
        stmt = stmt.order_by(RcsaAssessment.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=await _rcsa_reads(db, rows), total=total, limit=limit, offset=offset)


@router.post("/rcsa", response_model=RcsaRead, status_code=201, dependencies=[_WRITE])
async def create_rcsa(body: RcsaCreate, db: DbSession, user: CurrentUser) -> RcsaRead:
    data = body.model_dump()
    await rf.apply_refs(db, RcsaAssessment, data, RCSA_REFS)
    obj = RcsaAssessment(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, RcsaAssessment, "RCSA")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="rcsa_assessment",
                           entity_id=obj.id, summary=f"Opened RCSA {obj.reference}: {obj.title}")
    return (await _rcsa_reads(db, [await _load_rcsa(db, obj.id)]))[0]


@router.get("/rcsa/{rid}", response_model=RcsaRead, dependencies=[_READ])
async def get_rcsa(rid: uuid.UUID, db: DbSession) -> RcsaRead:
    return (await _rcsa_reads(db, [await _load_rcsa(db, rid)]))[0]


@router.patch("/rcsa/{rid}", response_model=RcsaRead, dependencies=[_WRITE])
async def update_rcsa(rid: uuid.UUID, body: RcsaUpdate, db: DbSession) -> RcsaRead:
    obj = await _load_rcsa(db, rid)
    data = body.model_dump(exclude_unset=True)
    await rf.apply_refs(db, RcsaAssessment, data, RCSA_REFS, record=obj)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return (await _rcsa_reads(db, [await _load_rcsa(db, rid)]))[0]


@router.delete("/rcsa/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_rcsa(rid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_rcsa(db, rid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _audit_delete(db, user, "rcsa_assessment", obj, "RCSA")


@router.post("/rcsa/{rid}/risks", response_model=RcsaRead, status_code=201, dependencies=[_WRITE])
async def add_rcsa_risk(rid: uuid.UUID, body: RcsaRiskCreate, db: DbSession, user: CurrentUser) -> RcsaRead:
    await _load_rcsa(db, rid)
    data = body.model_dump()
    await rf.apply_refs(db, RcsaRisk, data, RCSA_LINE_REFS)
    db.add(RcsaRisk(tenant_id=user.tenant_id, assessment_id=rid, **data))
    await db.flush()
    return (await _rcsa_reads(db, [await _load_rcsa(db, rid)]))[0]


@router.patch("/rcsa-risks/{line_id}", response_model=RcsaRiskRead, dependencies=[_WRITE])
async def update_rcsa_risk(line_id: uuid.UUID, body: RcsaRiskUpdate, db: DbSession) -> RcsaRiskRead:
    obj = await _get(db, RcsaRisk, line_id, "RCSA risk")
    data = body.model_dump(exclude_unset=True)
    await rf.apply_refs(db, RcsaRisk, data, RCSA_LINE_REFS, record=obj)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return (await _reads(db, RcsaRiskRead, [obj], RCSA_LINE_REFS))[0]


@router.delete("/rcsa-risks/{line_id}", status_code=204, dependencies=[_WRITE])
async def delete_rcsa_risk(line_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(RcsaRisk).where(RcsaRisk.id == line_id))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


# ===================================================================== KRIs ===
async def _load_kri(db, kid) -> KeyRiskIndicator:
    obj = await db.scalar(
        select(KeyRiskIndicator)
        .where(KeyRiskIndicator.id == kid, KeyRiskIndicator.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="KRI not found")
    return obj


async def _kri_read(db, kid) -> KriRead:
    return (await _reads(db, KriRead, [await _load_kri(db, kid)], KRI_REFS))[0]


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
                    owner_id: uuid.UUID | None = None,
                    category_id: uuid.UUID | None = None,
                    business_unit_id: uuid.UUID | None = None,
                    sort_by: Annotated[str | None, Query()] = None,
                    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                    limit: Annotated[int, Query(ge=1, le=200)] = 100,
                    offset: Annotated[int, Query(ge=0)] = 0) -> Page[KriRead]:
    stmt = select(KeyRiskIndicator).where(KeyRiskIndicator.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(KeyRiskIndicator.name.ilike(like), KeyRiskIndicator.reference.ilike(like),
                             KeyRiskIndicator.category.ilike(like), KeyRiskIndicator.owner.ilike(like)))
    if owner_id is not None:
        stmt = stmt.where(KeyRiskIndicator.owner_id == owner_id)
    if category_id is not None:
        stmt = stmt.where(KeyRiskIndicator.category_id == category_id)
    if business_unit_id is not None:
        stmt = stmt.where(KeyRiskIndicator.business_unit_id == business_unit_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _KRI_SORTABLE, default=KeyRiskIndicator.name)
    else:
        stmt = stmt.order_by(KeyRiskIndicator.name)
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=await _reads(db, KriRead, rows, KRI_REFS), total=total, limit=limit, offset=offset)


@router.post("/kris", response_model=KriRead, status_code=201, dependencies=[_WRITE])
async def create_kri(body: KriCreate, db: DbSession, user: CurrentUser) -> KriRead:
    data = body.model_dump(exclude={"risk_ids"})
    await rf.apply_refs(db, KeyRiskIndicator, data, KRI_REFS)
    obj = KeyRiskIndicator(tenant_id=user.tenant_id, **data)
    obj.risks = await _resolve(db, Risk, body.risk_ids)
    obj.reference = await _next_ref(db, KeyRiskIndicator, "KRI")
    db.add(obj)
    await db.flush()
    return await _kri_read(db, obj.id)


@router.get("/kris/{kid}", response_model=KriRead, dependencies=[_READ])
async def get_kri(kid: uuid.UUID, db: DbSession) -> KriRead:
    return await _kri_read(db, kid)


@router.patch("/kris/{kid}", response_model=KriRead, dependencies=[_WRITE])
async def update_kri(kid: uuid.UUID, body: KriUpdate, db: DbSession) -> KriRead:
    obj = await _load_kri(db, kid)
    data = body.model_dump(exclude_unset=True, exclude={"risk_ids"})
    await rf.apply_refs(db, KeyRiskIndicator, data, KRI_REFS, record=obj)
    for k, v in data.items():
        setattr(obj, k, v)
    if body.risk_ids is not None:
        obj.risks = await _resolve(db, Risk, body.risk_ids)
    await db.flush()
    return await _kri_read(db, kid)


@router.delete("/kris/{kid}", status_code=204, dependencies=[_WRITE])
async def delete_kri(kid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_kri(db, kid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _audit_delete(db, user, "key_risk_indicator", obj, "KRI")


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
    return await _kri_read(db, kid)


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
                           business_unit_id: uuid.UUID | None = None,
                           action_owner_id: uuid.UUID | None = None,
                           sort_by: Annotated[str | None, Query()] = None,
                           sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                           limit: Annotated[int, Query(ge=1, le=200)] = 100,
                           offset: Annotated[int, Query(ge=0)] = 0) -> Page[LossEventRead]:
    stmt = select(LossEvent).where(LossEvent.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(LossEvent.title.ilike(like), LossEvent.reference.ilike(like),
                             LossEvent.business_line.ilike(like)))
    if business_unit_id is not None:
        stmt = stmt.where(LossEvent.business_unit_id == business_unit_id)
    if action_owner_id is not None:
        stmt = stmt.where(LossEvent.action_owner_id == action_owner_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _LOSS_SORTABLE, default=LossEvent.occurrence_date)
    else:
        stmt = stmt.order_by(LossEvent.occurrence_date.is_(None), LossEvent.occurrence_date.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=await _reads(db, LossEventRead, rows, LOSS_REFS), total=total, limit=limit, offset=offset)


@router.post("/loss-events", response_model=LossEventRead, status_code=201, dependencies=[_WRITE])
async def create_loss_event(body: LossEventCreate, db: DbSession, user: CurrentUser) -> LossEventRead:
    data = body.model_dump(exclude={"risk_ids"})
    await rf.apply_refs(db, LossEvent, data, LOSS_REFS)
    obj = LossEvent(tenant_id=user.tenant_id, **data)
    obj.risks = await _resolve(db, Risk, body.risk_ids)
    obj.reference = await _next_ref(db, LossEvent, "LOSS")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="loss_event",
                           entity_id=obj.id, summary=f"Logged loss event {obj.reference}: {obj.title}")
    return (await _reads(db, LossEventRead, [await _get(db, LossEvent, obj.id, "Loss event")], LOSS_REFS))[0]


@router.patch("/loss-events/{lid}", response_model=LossEventRead, dependencies=[_WRITE])
async def update_loss_event(lid: uuid.UUID, body: LossEventUpdate, db: DbSession) -> LossEventRead:
    obj = await _get(db, LossEvent, lid, "Loss event")
    data = body.model_dump(exclude_unset=True, exclude={"risk_ids"})
    await rf.apply_refs(db, LossEvent, data, LOSS_REFS, record=obj)
    for k, v in data.items():
        setattr(obj, k, v)
    if body.risk_ids is not None:
        obj.risks = await _resolve(db, Risk, body.risk_ids)
    await db.flush()
    return (await _reads(db, LossEventRead, [obj], LOSS_REFS))[0]


@router.delete("/loss-events/{lid}", status_code=204, dependencies=[_WRITE])
async def delete_loss_event(lid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _get(db, LossEvent, lid, "Loss event")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _audit_delete(db, user, "loss_event", obj, "loss event")


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
