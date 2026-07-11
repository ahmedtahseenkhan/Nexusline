"""Regulatory Change Management API — tracked SBP circulars/laws, their distilled
obligations, and the recurring regulatory-returns (submissions) calendar."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.regulatory_change import (
    Applicability,
    Obligation,
    ObligationStatus,
    RegChangeStatus,
    RegulatoryChange,
    RegulatoryReturn,
    ReturnStatus,
)
from app.schemas.common import Page
from app.schemas.regulatory_change import (
    ObligationCreate,
    ObligationRead,
    ObligationUpdate,
    RegChangeSummary,
    RegulatoryChangeCreate,
    RegulatoryChangeRead,
    RegulatoryChangeUpdate,
    RegulatoryReturnCreate,
    RegulatoryReturnRead,
    RegulatoryReturnUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["regulatory change"])

_READ = Depends(require("regchange:read"))
_WRITE = Depends(require("regchange:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ================================================== regulatory changes ===
async def _load_change(db, cid) -> RegulatoryChange:
    obj = await db.scalar(
        select(RegulatoryChange).where(RegulatoryChange.id == cid, RegulatoryChange.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Regulatory change not found")
    return obj


@router.get("/regulatory-change", response_model=Page[RegulatoryChangeRead], dependencies=[_READ])
async def list_changes(
    db: DbSession,
    search: str | None = None,
    status_filter: Annotated[RegChangeStatus | None, Query(alias="status")] = None,
    applicability: Applicability | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RegulatoryChangeRead]:
    stmt: Select = select(RegulatoryChange).where(RegulatoryChange.deleted.is_(False))
    if status_filter is not None:
        stmt = stmt.where(RegulatoryChange.status == status_filter)
    if applicability is not None:
        stmt = stmt.where(RegulatoryChange.applicability == applicability)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            RegulatoryChange.title.ilike(like)
            | RegulatoryChange.circular_ref.ilike(like)
            | RegulatoryChange.reference.ilike(like)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(RegulatoryChange.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return Page(items=[RegulatoryChangeRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/regulatory-change", response_model=RegulatoryChangeRead, status_code=201, dependencies=[_WRITE])
async def create_change(body: RegulatoryChangeCreate, db: DbSession, user: CurrentUser) -> RegulatoryChangeRead:
    obj = RegulatoryChange(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, RegulatoryChange, "REG")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="regulatory_change",
                           entity_id=obj.id, summary=f"Logged regulatory change {obj.reference}: {obj.title}")
    return RegulatoryChangeRead.model_validate(await _load_change(db, obj.id))


@router.get("/regulatory-change/{cid}", response_model=RegulatoryChangeRead, dependencies=[_READ])
async def get_change(cid: uuid.UUID, db: DbSession) -> RegulatoryChangeRead:
    return RegulatoryChangeRead.model_validate(await _load_change(db, cid))


@router.patch("/regulatory-change/{cid}", response_model=RegulatoryChangeRead, dependencies=[_WRITE])
async def update_change(cid: uuid.UUID, body: RegulatoryChangeUpdate, db: DbSession) -> RegulatoryChangeRead:
    obj = await _load_change(db, cid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return RegulatoryChangeRead.model_validate(await _load_change(db, cid))


@router.delete("/regulatory-change/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_change(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_change(db, cid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ---- nested obligations under a regulatory change ----
@router.post("/regulatory-change/{cid}/obligations", response_model=RegulatoryChangeRead,
             status_code=201, dependencies=[_WRITE])
async def add_obligation(cid: uuid.UUID, body: ObligationCreate, db: DbSession, user: CurrentUser) -> RegulatoryChangeRead:
    await _load_change(db, cid)
    data = body.model_dump()
    data["regulatory_change_id"] = cid  # nested add always links to the parent change
    obj = Obligation(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, Obligation, "OBL")
    db.add(obj)
    await db.flush()
    return RegulatoryChangeRead.model_validate(await _load_change(db, cid))


# ================================================================ obligations ===
@router.get("/obligations", response_model=Page[ObligationRead], dependencies=[_READ])
async def list_obligations(
    db: DbSession,
    search: str | None = None,
    status_filter: Annotated[ObligationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ObligationRead]:
    # Exclude obligations whose parent change is archived; keep standalone ones (null parent).
    stmt: Select = (
        select(Obligation)
        .outerjoin(RegulatoryChange, RegulatoryChange.id == Obligation.regulatory_change_id)
        .where(
            (Obligation.regulatory_change_id.is_(None)) | (RegulatoryChange.deleted.is_(False))
        )
    )
    if status_filter is not None:
        stmt = stmt.where(Obligation.status == status_filter)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Obligation.title.ilike(like) | Obligation.reference.ilike(like))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(Obligation.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return Page(items=[ObligationRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/obligations", response_model=ObligationRead, status_code=201, dependencies=[_WRITE])
async def create_obligation(body: ObligationCreate, db: DbSession, user: CurrentUser) -> ObligationRead:
    if body.regulatory_change_id is not None:
        await _load_change(db, body.regulatory_change_id)
    obj = Obligation(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, Obligation, "OBL")
    db.add(obj)
    await db.flush()
    return ObligationRead.model_validate(obj)


@router.patch("/obligations/{oid}", response_model=ObligationRead, dependencies=[_WRITE])
async def update_obligation(oid: uuid.UUID, body: ObligationUpdate, db: DbSession) -> ObligationRead:
    obj = await _get(db, Obligation, oid, "Obligation")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return ObligationRead.model_validate(obj)


@router.delete("/obligations/{oid}", status_code=204, dependencies=[_WRITE])
async def delete_obligation(oid: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(Obligation).where(Obligation.id == oid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)
    await db.flush()


# ====================================================== regulatory returns ===
async def _load_return(db, rid) -> RegulatoryReturn:
    obj = await db.scalar(select(RegulatoryReturn).where(RegulatoryReturn.id == rid, RegulatoryReturn.deleted.is_(False)))
    if obj is None:
        raise HTTPException(status_code=404, detail="Regulatory return not found")
    return obj


@router.get("/regulatory-returns", response_model=Page[RegulatoryReturnRead], dependencies=[_READ])
async def list_returns(
    db: DbSession,
    status_filter: Annotated[ReturnStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RegulatoryReturnRead]:
    stmt: Select = select(RegulatoryReturn).where(RegulatoryReturn.deleted.is_(False))
    if status_filter is not None:
        stmt = stmt.where(RegulatoryReturn.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(RegulatoryReturn.next_due_date.is_(None), RegulatoryReturn.next_due_date)
        .limit(limit).offset(offset)
    )).all()
    return Page(items=[RegulatoryReturnRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/regulatory-returns", response_model=RegulatoryReturnRead, status_code=201, dependencies=[_WRITE])
async def create_return(body: RegulatoryReturnCreate, db: DbSession, user: CurrentUser) -> RegulatoryReturnRead:
    obj = RegulatoryReturn(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, RegulatoryReturn, "RET")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="regulatory_return",
                           entity_id=obj.id, summary=f"Registered regulatory return {obj.reference}: {obj.name}")
    return RegulatoryReturnRead.model_validate(obj)


@router.patch("/regulatory-returns/{rid}", response_model=RegulatoryReturnRead, dependencies=[_WRITE])
async def update_return(rid: uuid.UUID, body: RegulatoryReturnUpdate, db: DbSession) -> RegulatoryReturnRead:
    obj = await _load_return(db, rid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return RegulatoryReturnRead.model_validate(obj)


@router.delete("/regulatory-returns/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_return(rid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_return(db, rid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================================== summary ===
@router.get("/regulatory-change-summary", response_model=RegChangeSummary, dependencies=[_READ],
            summary="Regulatory change, obligation and returns-calendar roll-up")
async def reg_change_summary(db: DbSession) -> RegChangeSummary:
    today = date.today()

    changes = (await db.scalars(select(RegulatoryChange).where(RegulatoryChange.deleted.is_(False)))).all()
    by_status: dict[str, int] = defaultdict(int)
    for c in changes:
        by_status[c.status.value] += 1
    changes_open = sum(
        1 for c in changes
        if c.status not in (RegChangeStatus.implemented, RegChangeStatus.closed)
    )
    changes_in_impl = by_status.get(RegChangeStatus.in_implementation.value, 0)
    changes_overdue = sum(1 for c in changes if c.is_overdue)

    obligations = (await db.scalars(
        select(Obligation)
        .outerjoin(RegulatoryChange, RegulatoryChange.id == Obligation.regulatory_change_id)
        .where((Obligation.regulatory_change_id.is_(None)) | (RegulatoryChange.deleted.is_(False)))
    )).all()
    obligations_open = sum(1 for o in obligations if o.status == ObligationStatus.open)
    obligations_met = sum(1 for o in obligations if o.status == ObligationStatus.met)

    returns = (await db.scalars(select(RegulatoryReturn).where(RegulatoryReturn.deleted.is_(False)))).all()
    pending = [r for r in returns if r.status != ReturnStatus.submitted and r.next_due_date is not None]
    due_30 = sum(1 for r in pending if today <= r.next_due_date <= today + timedelta(days=30))
    due_60 = sum(1 for r in pending if today <= r.next_due_date <= today + timedelta(days=60))
    due_90 = sum(1 for r in pending if today <= r.next_due_date <= today + timedelta(days=90))
    returns_overdue = sum(1 for r in returns if r.is_overdue)

    return RegChangeSummary(
        changes_by_status=dict(by_status),
        total_changes=len(changes),
        changes_open=changes_open,
        changes_in_implementation=changes_in_impl,
        changes_overdue=changes_overdue,
        obligations_total=len(obligations),
        obligations_open=obligations_open,
        obligations_met=obligations_met,
        returns_total=len(returns),
        returns_due_30=due_30,
        returns_due_60=due_60,
        returns_due_90=due_90,
        returns_overdue=returns_overdue,
    )
