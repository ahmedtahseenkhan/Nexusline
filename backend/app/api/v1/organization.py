"""Business Organization API — business units (with legal obligations), processes
(RTO/RPO/RPD), and the legal/regulatory register. eramba record envelope: soft-delete."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, insert, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import Asset, assets_legals, assets_processes
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
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    rows = list((await db.scalars(stmt)).all())
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or archived {model.__name__.lower()} id(s): {sorted(map(str, missing))}",
        )
    return rows


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


@router.get("/business-units/{obj_id}", response_model=BusinessUnitRead, dependencies=[Depends(require("org:read"))])
async def get_business_unit(obj_id: uuid.UUID, db: DbSession) -> BusinessUnitRead:
    obj = await _get(db, BusinessUnit, obj_id, "Business unit")
    return _bu_read(obj, await _bu_name_map(db))


@router.patch("/business-units/{obj_id}", response_model=BusinessUnitRead, dependencies=[Depends(require("org:write"))])
async def update_business_unit(obj_id: uuid.UUID, body: BusinessUnitUpdate, db: DbSession) -> BusinessUnitRead:
    obj = await _get(db, BusinessUnit, obj_id, "Business unit")
    data = body.model_dump(exclude_unset=True)
    legal_ids = data.pop("legal_ids", None)
    if "parent_id" in data and data["parent_id"] is not None:
        # Walk the proposed parent's ancestry; reject if this unit appears, which would
        # create a cycle (A→B→A) that any tree rollup would loop on.
        cursor = data["parent_id"]
        seen: set = set()
        while cursor is not None and cursor not in seen:
            if cursor == obj.id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="That parent would create a business-unit cycle.",
                )
            seen.add(cursor)
            parent = await db.scalar(
                select(BusinessUnit.parent_id).where(BusinessUnit.id == cursor)
            )
            cursor = parent
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
async def _process_assets_map(db, process_ids) -> dict:
    """Map process_id -> [Ref(asset)] via the assets_processes join (viewonly side).

    ``Asset`` owns the writable ``assets_processes`` relationship; ``Process`` has no
    reverse attribute, so the link is read/written through the join table directly.
    """
    if not process_ids:
        return {}
    rows = (
        await db.execute(
            select(assets_processes.c.process_id, Asset.id, Asset.name)
            .join(Asset, Asset.id == assets_processes.c.asset_id)
            .where(assets_processes.c.process_id.in_(process_ids))
            .order_by(Asset.name)
        )
    ).all()
    out: dict = {}
    for proc_id, asset_id, asset_name in rows:
        out.setdefault(proc_id, []).append({"id": asset_id, "name": asset_name})
    return out


def _process_read(obj: Process, assets_map: dict) -> ProcessRead:
    rd = ProcessRead.model_validate(obj)
    rd.assets = assets_map.get(obj.id, [])
    return rd


async def _validate_assets(db, asset_ids) -> None:
    if not asset_ids:
        return
    found = set((await db.scalars(
        select(Asset.id).where(Asset.id.in_(asset_ids), Asset.deleted.is_(False))
    )).all())
    missing = [str(i) for i in asset_ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or archived asset id(s): {sorted(missing)}",
        )


async def _set_process_assets(db, process_id, asset_ids) -> None:
    """Replace the assets_processes rows for a process (call after the row has an id)."""
    if asset_ids is None:
        return
    await _validate_assets(db, asset_ids)
    await db.execute(delete(assets_processes).where(assets_processes.c.process_id == process_id))
    if asset_ids:
        await db.execute(
            insert(assets_processes),
            [{"process_id": process_id, "asset_id": aid} for aid in asset_ids],
        )


@router.get("/processes", response_model=Page[ProcessRead], dependencies=[Depends(require("org:read"))])
async def list_processes(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProcessRead]:
    stmt = select(Process).where(Process.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(Process.name).limit(limit).offset(offset))).all()
    assets_map = await _process_assets_map(db, [r.id for r in rows])
    return Page(items=[_process_read(r, assets_map) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/processes", response_model=ProcessRead, status_code=201, dependencies=[Depends(require("org:write"))])
async def create_process(body: ProcessCreate, db: DbSession, user: CurrentUser) -> ProcessRead:
    data = body.model_dump()
    asset_ids = data.pop("asset_ids", [])
    obj = Process(tenant_id=user.tenant_id, **data)
    db.add(obj)
    await db.flush()
    await _set_process_assets(db, obj.id, asset_ids)
    await db.flush()
    obj = await _get(db, Process, obj.id, "Process")
    return _process_read(obj, await _process_assets_map(db, [obj.id]))


@router.get("/processes/{obj_id}", response_model=ProcessRead, dependencies=[Depends(require("org:read"))])
async def get_process(obj_id: uuid.UUID, db: DbSession) -> ProcessRead:
    obj = await _get(db, Process, obj_id, "Process")
    return _process_read(obj, await _process_assets_map(db, [obj.id]))


@router.patch("/processes/{obj_id}", response_model=ProcessRead, dependencies=[Depends(require("org:write"))])
async def update_process(obj_id: uuid.UUID, body: ProcessUpdate, db: DbSession) -> ProcessRead:
    obj = await _get(db, Process, obj_id, "Process")
    data = body.model_dump(exclude_unset=True)
    asset_ids = data.pop("asset_ids", None)
    for f, v in data.items():
        setattr(obj, f, v)
    await db.flush()
    await _set_process_assets(db, obj.id, asset_ids)
    await db.flush()
    obj = await _get(db, Process, obj.id, "Process")
    return _process_read(obj, await _process_assets_map(db, [obj.id]))


@router.delete("/processes/{obj_id}", status_code=204, dependencies=[Depends(require("org:write"))])
async def delete_process(obj_id: uuid.UUID, db: DbSession) -> None:
    await _soft_delete(db, await _get(db, Process, obj_id, "Process"))


# ---------------------------------------------------------------- legal register
async def _legal_assets_map(db, legal_ids) -> dict:
    """Map legal_id -> [Ref(asset)] via the assets_legals join (viewonly side).

    ``Asset`` owns the writable ``assets_legals`` relationship; ``Legal`` has no
    reverse attribute, so the link is read/written through the join table directly.
    """
    if not legal_ids:
        return {}
    rows = (
        await db.execute(
            select(assets_legals.c.legal_id, Asset.id, Asset.name)
            .join(Asset, Asset.id == assets_legals.c.asset_id)
            .where(assets_legals.c.legal_id.in_(legal_ids))
            .order_by(Asset.name)
        )
    ).all()
    out: dict = {}
    for legal_id, asset_id, asset_name in rows:
        out.setdefault(legal_id, []).append({"id": asset_id, "name": asset_name})
    return out


def _legal_read(obj: Legal, assets_map: dict) -> LegalRead:
    rd = LegalRead.model_validate(obj)  # business_units is a real relationship -> auto
    rd.assets = assets_map.get(obj.id, [])
    return rd


async def _set_legal_assets(db, legal_id, asset_ids) -> None:
    """Replace the assets_legals rows for a legal obligation (after it has an id)."""
    if asset_ids is None:
        return
    await _validate_assets(db, asset_ids)
    await db.execute(delete(assets_legals).where(assets_legals.c.legal_id == legal_id))
    if asset_ids:
        await db.execute(
            insert(assets_legals),
            [{"legal_id": legal_id, "asset_id": aid} for aid in asset_ids],
        )


@router.get("/legals", response_model=Page[LegalRead], dependencies=[Depends(require("org:read"))])
async def list_legals(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[LegalRead]:
    stmt = select(Legal).where(Legal.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(Legal.name).limit(limit).offset(offset))).all()
    assets_map = await _legal_assets_map(db, [r.id for r in rows])
    return Page(items=[_legal_read(r, assets_map) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/legals", response_model=LegalRead, status_code=201, dependencies=[Depends(require("org:write"))])
async def create_legal(body: LegalCreate, db: DbSession, user: CurrentUser) -> LegalRead:
    data = body.model_dump()
    business_unit_ids = data.pop("business_unit_ids", [])
    asset_ids = data.pop("asset_ids", [])
    obj = Legal(tenant_id=user.tenant_id, **data)
    obj.business_units = await _load_many(db, BusinessUnit, business_unit_ids)  # assign while pending
    db.add(obj)
    await db.flush()
    await _set_legal_assets(db, obj.id, asset_ids)
    await db.flush()
    obj = await _get(db, Legal, obj.id, "Legal")
    return _legal_read(obj, await _legal_assets_map(db, [obj.id]))


@router.get("/legals/{obj_id}", response_model=LegalRead, dependencies=[Depends(require("org:read"))])
async def get_legal(obj_id: uuid.UUID, db: DbSession) -> LegalRead:
    obj = await _get(db, Legal, obj_id, "Legal")
    return _legal_read(obj, await _legal_assets_map(db, [obj.id]))


@router.patch("/legals/{obj_id}", response_model=LegalRead, dependencies=[Depends(require("org:write"))])
async def update_legal(obj_id: uuid.UUID, body: LegalUpdate, db: DbSession) -> LegalRead:
    obj = await _get(db, Legal, obj_id, "Legal")
    data = body.model_dump(exclude_unset=True)
    business_unit_ids = data.pop("business_unit_ids", None)
    asset_ids = data.pop("asset_ids", None)
    for f, v in data.items():
        setattr(obj, f, v)
    if business_unit_ids is not None:
        obj.business_units = await _load_many(db, BusinessUnit, business_unit_ids)
    await db.flush()
    await _set_legal_assets(db, obj.id, asset_ids)
    await db.flush()
    obj = await _get(db, Legal, obj.id, "Legal")
    return _legal_read(obj, await _legal_assets_map(db, [obj.id]))


@router.delete("/legals/{obj_id}", status_code=204, dependencies=[Depends(require("org:write"))])
async def delete_legal(obj_id: uuid.UUID, db: DbSession) -> None:
    await _soft_delete(db, await _get(db, Legal, obj_id, "Legal"))
