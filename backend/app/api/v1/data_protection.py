"""Data Protection API — DPIAs, DSARs, the breach register and the consent ledger.

The operational data-protection layer for Pakistan PDPA readiness. Where ``privacy``
holds the RoPA register, this router runs the DPO's day-to-day workflows: impact
assessments, subject requests on a 30-day SLA, breach notification (72-hour rule)
and a consent ledger.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.data_protection import (
    BreachStatus,
    ConsentRecord,
    ConsentStatus,
    DataBreach,
    Dpia,
    Dsar,
    DsarStatus,
)
from app.schemas.common import Page
from app.schemas.data_protection import (
    ConsentRecordCreate,
    ConsentRecordRead,
    ConsentRecordUpdate,
    DataBreachCreate,
    DataBreachRead,
    DataBreachUpdate,
    DpiaCreate,
    DpiaRead,
    DpiaUpdate,
    DsarCreate,
    DsarRead,
    DsarUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["data protection"])

_READ = Depends(require("dpo:read"))
_WRITE = Depends(require("dpo:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# =================================================================== DPIA ===
@router.get("/dpias", response_model=Page[DpiaRead], dependencies=[_READ])
async def list_dpias(db: DbSession, status: str | None = None,
                     limit: Annotated[int, Query(ge=1, le=200)] = 100,
                     offset: Annotated[int, Query(ge=0)] = 0) -> Page[DpiaRead]:
    stmt = select(Dpia).where(Dpia.deleted.is_(False))
    if status:
        stmt = stmt.where(Dpia.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(Dpia.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[DpiaRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/dpias", response_model=DpiaRead, status_code=201, dependencies=[_WRITE])
async def create_dpia(body: DpiaCreate, db: DbSession, user: CurrentUser) -> DpiaRead:
    obj = Dpia(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, Dpia, "DPIA")
    db.add(obj)
    await db.flush()
    return DpiaRead.model_validate(obj)


@router.patch("/dpias/{did}", response_model=DpiaRead, dependencies=[_WRITE])
async def update_dpia(did: uuid.UUID, body: DpiaUpdate, db: DbSession) -> DpiaRead:
    obj = await _get(db, Dpia, did, "DPIA")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return DpiaRead.model_validate(obj)


@router.delete("/dpias/{did}", status_code=204, dependencies=[_WRITE])
async def delete_dpia(did: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, Dpia, did, "DPIA")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# =================================================================== DSAR ===
@router.get("/dsars", response_model=Page[DsarRead], dependencies=[_READ])
async def list_dsars(db: DbSession, status: str | None = None, request_type: str | None = None,
                     overdue: bool | None = None,
                     limit: Annotated[int, Query(ge=1, le=200)] = 100,
                     offset: Annotated[int, Query(ge=0)] = 0) -> Page[DsarRead]:
    stmt = select(Dsar).where(Dsar.deleted.is_(False))
    if status:
        stmt = stmt.where(Dsar.status == status)
    if request_type:
        stmt = stmt.where(Dsar.request_type == request_type)
    if overdue:
        # is_overdue is a computed property — evaluate in Python, then paginate.
        rows = (await db.scalars(stmt.order_by(Dsar.created_at.desc()))).all()
        rows = [r for r in rows if r.is_overdue]
        total = len(rows)
        rows = rows[offset:offset + limit]
    else:
        total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await db.scalars(stmt.order_by(Dsar.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[DsarRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/dsars", response_model=DsarRead, status_code=201, dependencies=[_WRITE])
async def create_dsar(body: DsarCreate, db: DbSession, user: CurrentUser) -> DsarRead:
    obj = Dsar(tenant_id=user.tenant_id, **body.model_dump())
    # Default the statutory response deadline to received_date + 30 days when the caller
    # doesn't supply one — otherwise a DSAR with no due_date could never become overdue,
    # silently defeating the SLA clock.
    if obj.due_date is None:
        base = obj.received_date or date.today()
        obj.due_date = base + timedelta(days=obj.sla_days)
    obj.reference = await _next_ref(db, Dsar, "DSAR")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="dsar",
                           entity_id=obj.id,
                           summary=f"Logged DSAR {obj.reference} ({obj.request_type.value}) for {obj.subject_name}")
    return DsarRead.model_validate(obj)


@router.patch("/dsars/{did}", response_model=DsarRead, dependencies=[_WRITE])
async def update_dsar(did: uuid.UUID, body: DsarUpdate, db: DbSession) -> DsarRead:
    obj = await _get(db, Dsar, did, "DSAR")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return DsarRead.model_validate(obj)


@router.delete("/dsars/{did}", status_code=204, dependencies=[_WRITE])
async def delete_dsar(did: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, Dsar, did, "DSAR")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================================ data breach ===
@router.get("/data-breaches", response_model=Page[DataBreachRead], dependencies=[_READ])
async def list_data_breaches(db: DbSession, status: str | None = None, breach_type: str | None = None,
                             notification_overdue: bool | None = None,
                             limit: Annotated[int, Query(ge=1, le=200)] = 100,
                             offset: Annotated[int, Query(ge=0)] = 0) -> Page[DataBreachRead]:
    stmt = select(DataBreach).where(DataBreach.deleted.is_(False))
    if status:
        stmt = stmt.where(DataBreach.status == status)
    if breach_type:
        stmt = stmt.where(DataBreach.breach_type == breach_type)
    if notification_overdue:
        # notification_overdue is computed — evaluate in Python, then paginate.
        rows = (await db.scalars(stmt.order_by(DataBreach.created_at.desc()))).all()
        rows = [r for r in rows if r.notification_overdue]
        total = len(rows)
        rows = rows[offset:offset + limit]
    else:
        total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await db.scalars(stmt.order_by(DataBreach.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[DataBreachRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/data-breaches", response_model=DataBreachRead, status_code=201, dependencies=[_WRITE])
async def create_data_breach(body: DataBreachCreate, db: DbSession, user: CurrentUser) -> DataBreachRead:
    obj = DataBreach(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, DataBreach, "BR")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="data_breach",
                           entity_id=obj.id,
                           summary=f"Registered data breach {obj.reference}: {obj.title}")
    return DataBreachRead.model_validate(obj)


@router.patch("/data-breaches/{bid}", response_model=DataBreachRead, dependencies=[_WRITE])
async def update_data_breach(bid: uuid.UUID, body: DataBreachUpdate, db: DbSession) -> DataBreachRead:
    obj = await _get(db, DataBreach, bid, "Data breach")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return DataBreachRead.model_validate(obj)


@router.delete("/data-breaches/{bid}", status_code=204, dependencies=[_WRITE])
async def delete_data_breach(bid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, DataBreach, bid, "Data breach")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ========================================================= consent records ===
@router.get("/consent-records", response_model=Page[ConsentRecordRead], dependencies=[_READ])
async def list_consent_records(db: DbSession, status: str | None = None,
                               limit: Annotated[int, Query(ge=1, le=200)] = 100,
                               offset: Annotated[int, Query(ge=0)] = 0) -> Page[ConsentRecordRead]:
    stmt = select(ConsentRecord).where(ConsentRecord.deleted.is_(False))
    if status:
        stmt = stmt.where(ConsentRecord.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(ConsentRecord.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[ConsentRecordRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/consent-records", response_model=ConsentRecordRead, status_code=201, dependencies=[_WRITE])
async def create_consent_record(body: ConsentRecordCreate, db: DbSession, user: CurrentUser) -> ConsentRecordRead:
    obj = ConsentRecord(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, ConsentRecord, "CON")
    db.add(obj)
    await db.flush()
    return ConsentRecordRead.model_validate(obj)


@router.patch("/consent-records/{cid}", response_model=ConsentRecordRead, dependencies=[_WRITE])
async def update_consent_record(cid: uuid.UUID, body: ConsentRecordUpdate, db: DbSession) -> ConsentRecordRead:
    obj = await _get(db, ConsentRecord, cid, "Consent record")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return ConsentRecordRead.model_validate(obj)


@router.delete("/consent-records/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_consent_record(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, ConsentRecord, cid, "Consent record")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================================= summary ===
class DataProtectionSummary(BaseModel):
    dpias_by_status: dict[str, int]
    dpias_total: int
    dsars_open: int
    dsars_overdue: int
    breaches_open: int
    breaches_notification_overdue: int
    consents_active: int
    consents_withdrawn: int


@router.get("/data-protection-summary", response_model=DataProtectionSummary, dependencies=[_READ],
            summary="Data-protection posture roll-up (DPIA / DSAR / breach / consent)")
async def data_protection_summary(db: DbSession) -> DataProtectionSummary:
    dpias = (await db.scalars(select(Dpia).where(Dpia.deleted.is_(False)))).all()
    dsars = (await db.scalars(select(Dsar).where(Dsar.deleted.is_(False)))).all()
    breaches = (await db.scalars(select(DataBreach).where(DataBreach.deleted.is_(False)))).all()
    consents = (await db.scalars(select(ConsentRecord).where(ConsentRecord.deleted.is_(False)))).all()

    dpias_by_status: dict[str, int] = defaultdict(int)
    for d in dpias:
        dpias_by_status[d.status.value] += 1

    open_dsar_states = (DsarStatus.received, DsarStatus.verifying, DsarStatus.in_progress)
    dsars_open = sum(1 for d in dsars if d.status in open_dsar_states)
    dsars_overdue = sum(1 for d in dsars if d.is_overdue)

    breaches_open = sum(1 for b in breaches if b.status != BreachStatus.closed)
    breaches_notification_overdue = sum(1 for b in breaches if b.notification_overdue)

    consents_active = sum(1 for c in consents if c.status == ConsentStatus.active)
    consents_withdrawn = sum(1 for c in consents if c.status == ConsentStatus.withdrawn)

    return DataProtectionSummary(
        dpias_by_status=dict(dpias_by_status),
        dpias_total=len(dpias),
        dsars_open=dsars_open,
        dsars_overdue=dsars_overdue,
        breaches_open=breaches_open,
        breaches_notification_overdue=breaches_notification_overdue,
        consents_active=consents_active,
        consents_withdrawn=consents_withdrawn,
    )
