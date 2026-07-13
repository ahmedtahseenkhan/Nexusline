"""Third-Party / Vendor Risk API — vendor registry, types, service contracts, and
links to the risks/assets a third party touches. eramba record envelope (soft-delete)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.asset import Asset
from app.models.compliance import Requirement
from app.models.control import Control
from app.models.risk import Risk
from app.models.vendor import ServiceContract, Vendor, VendorType
from app.schemas.common import Page
from app.schemas.vendor import (
    ServiceContractCreate,
    ServiceContractRead,
    VendorCreate,
    VendorRead,
    VendorTypeCreate,
    VendorTypeRead,
    VendorUpdate,
)
from app.services import audit

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _loads():
    return (
        selectinload(Vendor.type),
        selectinload(Vendor.contracts),
        selectinload(Vendor.risks),
        selectinload(Vendor.assets),
    )


async def _load(db, vendor_id: uuid.UUID) -> Vendor:
    obj = await db.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.deleted.is_(False))
        .options(*_loads()).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return obj


async def _resolve(db, model, ids):
    if not ids:
        return []
    return list((await db.scalars(select(model).where(model.id.in_(ids)))).all())


_VENDOR_SORTABLE = {
    "name": Vendor.name,
    "category": Vendor.category,
    "criticality": Vendor.criticality,
    "status": Vendor.status,
    "risk_rating": Vendor.risk_rating,
    "assessment_status": Vendor.assessment_status,
    "last_assessed_at": Vendor.last_assessed_at,
    "created_at": Vendor.created_at,
}


@router.get("", response_model=Page[VendorRead], dependencies=[Depends(require("vendor:read"))])
async def list_vendors(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[VendorRead]:
    stmt = select(Vendor).where(Vendor.deleted.is_(False))
    if search:
        stmt = stmt.where(Vendor.name.ilike(f"%{search}%") | Vendor.category.ilike(f"%{search}%"))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _VENDOR_SORTABLE, default=Vendor.name)
    else:
        stmt = stmt.order_by(Vendor.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.options(*_loads()).limit(limit).offset(offset))).all()
    return Page(
        items=[VendorRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post("", response_model=VendorRead, status_code=201, dependencies=[Depends(require("vendor:write"))])
async def create_vendor(body: VendorCreate, db: DbSession, user: CurrentUser) -> VendorRead:
    data = body.model_dump()
    risk_ids = data.pop("risk_ids", [])
    asset_ids = data.pop("asset_ids", [])
    requirement_ids = data.pop("requirement_ids", [])
    control_ids = data.pop("control_ids", [])
    obj = Vendor(tenant_id=user.tenant_id, **data)
    obj.risks = await _resolve(db, Risk, risk_ids)
    obj.assets = await _resolve(db, Asset, asset_ids)
    obj.requirements = await _resolve(db, Requirement, requirement_ids)
    obj.controls = await _resolve(db, Control, control_ids)
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="vendor", entity_id=obj.id,
        summary=f"Registered vendor {obj.name}",
    )
    return VendorRead.model_validate(await _load(db, obj.id))


@router.get("/{vendor_id}", response_model=VendorRead, dependencies=[Depends(require("vendor:read"))])
async def get_vendor(vendor_id: uuid.UUID, db: DbSession) -> VendorRead:
    return VendorRead.model_validate(await _load(db, vendor_id))


@router.patch("/{vendor_id}", response_model=VendorRead, dependencies=[Depends(require("vendor:write"))])
async def update_vendor(
    vendor_id: uuid.UUID, body: VendorUpdate, db: DbSession, user: CurrentUser
) -> VendorRead:
    obj = await _load(db, vendor_id)
    data = body.model_dump(exclude_unset=True)
    risk_ids = data.pop("risk_ids", None)
    asset_ids = data.pop("asset_ids", None)
    requirement_ids = data.pop("requirement_ids", None)
    control_ids = data.pop("control_ids", None)
    for field, value in data.items():
        setattr(obj, field, value)
    if risk_ids is not None:
        obj.risks = await _resolve(db, Risk, risk_ids)
    if asset_ids is not None:
        obj.assets = await _resolve(db, Asset, asset_ids)
    if requirement_ids is not None:
        obj.requirements = await _resolve(db, Requirement, requirement_ids)
    if control_ids is not None:
        obj.controls = await _resolve(db, Control, control_ids)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="vendor", entity_id=obj.id,
        summary=f"Updated vendor {obj.name}",
    )
    return VendorRead.model_validate(await _load(db, obj.id))


@router.delete("/{vendor_id}", status_code=204, dependencies=[Depends(require("vendor:write"))])
async def delete_vendor(vendor_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, vendor_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit.record(db, actor=user, action="delete", entity_type="vendor",
                         entity_id=obj.id, summary=f"Archived vendor {obj.name}")


# ----------------------------------------------------------------- contracts
@router.post(
    "/{vendor_id}/contracts", response_model=VendorRead, status_code=201,
    dependencies=[Depends(require("vendor:write"))],
)
async def add_contract(vendor_id: uuid.UUID, body: ServiceContractCreate, db: DbSession) -> VendorRead:
    obj = await _load(db, vendor_id)
    db.add(ServiceContract(tenant_id=obj.tenant_id, vendor_id=obj.id, **body.model_dump()))
    await db.flush()
    return VendorRead.model_validate(await _load(db, obj.id))


@router.delete(
    "/contracts/{contract_id}", status_code=204, dependencies=[Depends(require("vendor:write"))],
)
async def delete_contract(contract_id: uuid.UUID, db: DbSession) -> None:
    c = await db.get(ServiceContract, contract_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    await db.delete(c)


# ----------------------------------------------------------------- vendor types
types_router = APIRouter(prefix="/vendor-types", tags=["vendors"])


@types_router.get("", response_model=list[VendorTypeRead], dependencies=[Depends(require("vendor:read"))])
async def list_vendor_types(db: DbSession) -> list[VendorTypeRead]:
    rows = (await db.scalars(select(VendorType).order_by(VendorType.name))).all()
    return [VendorTypeRead.model_validate(r) for r in rows]


@types_router.post("", response_model=VendorTypeRead, status_code=201, dependencies=[Depends(require("vendor:write"))])
async def create_vendor_type(body: VendorTypeCreate, db: DbSession, user: CurrentUser) -> VendorTypeRead:
    obj = VendorType(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return VendorTypeRead.model_validate(obj)
