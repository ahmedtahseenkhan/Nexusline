"""Business Organization API — business units (with legal obligations), processes
(RTO/RPO/RPD), and the legal/regulatory register. eramba record envelope: soft-delete."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.organization import BusinessUnit, Legal, Process
from app.schemas.common import Page
from app.schemas.organization import (
    BusinessUnitCreate,
    BusinessUnitRead,
    BusinessUnitUpdate,
    LegalCreate,
    LegalRead,
    LegalUpdate,
    ProcessCreate,
    ProcessRead,
    ProcessUpdate,
)

router = APIRouter(tags=["organization"])


async def _get(db, model, obj_id: uuid.UUID, name: str):
    obj = await db.scalar(
        select(model).where(model.id == obj_id, model.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{name} not found")
    return obj


async def _soft_delete(db, obj) -> None:
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)


async def _load_many(db, model, ids):
    if not ids:
        return []
    return list((await db.scalars(select(model).where(model.id.in_(ids)))).all())


# ------------------------------------------------------------- business units
async def _bu_name_map(db) -> dict:
    return dict((await db.execute(select(BusinessUnit.id, BusinessUnit.name))).all())


def _bu_read(obj: BusinessUnit, names: dict) -> BusinessUnitRead:
    rd = BusinessUnitRead.model_validate(obj)
    rd.parent_name = names.get(obj.parent_id) if obj.parent_id else None
    return rd


@router.get("/business-units", response_model=Page[BusinessUnitRead], dependencies=[Depends(require("org:read"))])
async def list_business_units(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[BusinessUnitRead]:
    stmt = select(BusinessUnit).where(BusinessUnit.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(BusinessUnit.name).limit(limit).offset(offset))).all()
    names = await _bu_name_map(db)
    return Page(items=[_bu_read(r, names) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/business-units", response_model=BusinessUnitRead, status_code=201, dependencies=[Depends(require("org:write"))])
async def create_business_unit(body: BusinessUnitCreate, db: DbSession, user: CurrentUser) -> BusinessUnitRead:
    data = body.model_dump()
    legal_ids = data.pop("legal_ids", [])
    obj = BusinessUnit(tenant_id=user.tenant_id, **data)
    obj.legals = await _load_many(db, Legal, legal_ids)  # assign while pending
    db.add(obj)
    await db.flush()
    return _bu_read(await _get(db, BusinessUnit, obj.id, "Business unit"), await _bu_name_map(db))


@router.patch("/business-units/{obj_id}", response_model=BusinessUnitRead, dependencies=[Depends(require("org:write"))])
async def update_business_unit(obj_id: uuid.UUID, body: BusinessUnitUpdate, db: DbSession) -> BusinessUnitRead:
    obj = await _get(db, BusinessUnit, obj_id, "Business unit")
    data = body.model_dump(exclude_unset=True)
    legal_ids = data.pop("legal_ids", None)
    for f, v in data.items():
        setattr(obj, f, v)
    if legal_ids is not None:
        obj.legals = await _load_many(db, Legal, legal_ids)
    await db.flush()
    return _bu_read(await _get(db, BusinessUnit, obj.id, "Business unit"), await _bu_name_map(db))


@router.delete("/business-units/{obj_id}", status_code=204, dependencies=[Depends(require("org:write"))])
async def delete_business_unit(obj_id: uuid.UUID, db: DbSession) -> None:
    await _soft_delete(db, await _get(db, BusinessUnit, obj_id, "Business unit"))


# ------------------------------------------------------------------- processes
@router.get("/processes", response_model=Page[ProcessRead], dependencies=[Depends(require("org:read"))])
async def list_processes(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProcessRead]:
    stmt = select(Process).where(Process.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(Process.name).limit(limit).offset(offset))).all()
    return Page(items=[ProcessRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/processes", response_model=ProcessRead, status_code=201, dependencies=[Depends(require("org:write"))])
async def create_process(body: ProcessCreate, db: DbSession, user: CurrentUser) -> ProcessRead:
    obj = Process(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    return ProcessRead.model_validate(await _get(db, Process, obj.id, "Process"))


@router.patch("/processes/{obj_id}", response_model=ProcessRead, dependencies=[Depends(require("org:write"))])
async def update_process(obj_id: uuid.UUID, body: ProcessUpdate, db: DbSession) -> ProcessRead:
    obj = await _get(db, Process, obj_id, "Process")
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, f, v)
    await db.flush()
    return ProcessRead.model_validate(await _get(db, Process, obj.id, "Process"))


@router.delete("/processes/{obj_id}", status_code=204, dependencies=[Depends(require("org:write"))])
async def delete_process(obj_id: uuid.UUID, db: DbSession) -> None:
    await _soft_delete(db, await _get(db, Process, obj_id, "Process"))


# ---------------------------------------------------------------- legal register
@router.get("/legals", response_model=Page[LegalRead], dependencies=[Depends(require("org:read"))])
async def list_legals(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[LegalRead]:
    stmt = select(Legal).where(Legal.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(Legal.name).limit(limit).offset(offset))).all()
    return Page(items=[LegalRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/legals", response_model=LegalRead, status_code=201, dependencies=[Depends(require("org:write"))])
async def create_legal(body: LegalCreate, db: DbSession, user: CurrentUser) -> LegalRead:
    obj = Legal(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    return LegalRead.model_validate(await _get(db, Legal, obj.id, "Legal"))


@router.patch("/legals/{obj_id}", response_model=LegalRead, dependencies=[Depends(require("org:write"))])
async def update_legal(obj_id: uuid.UUID, body: LegalUpdate, db: DbSession) -> LegalRead:
    obj = await _get(db, Legal, obj_id, "Legal")
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, f, v)
    await db.flush()
    return LegalRead.model_validate(await _get(db, Legal, obj.id, "Legal"))


@router.delete("/legals/{obj_id}", status_code=204, dependencies=[Depends(require("org:write"))])
async def delete_legal(obj_id: uuid.UUID, db: DbSession) -> None:
    await _soft_delete(db, await _get(db, Legal, obj_id, "Legal"))
