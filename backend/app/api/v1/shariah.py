"""Islamic / Shariah Governance API — fatwa register, Islamic product register,
Shariah compliance reviews with SNC findings, and the purification (charity) ledger."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.enums import ShariahFindingStatus
from app.models.shariah import (
    CharityDisbursement,
    IslamicProduct,
    ShariahFinding,
    ShariahReview,
    ShariahRuling,
)
from app.schemas.common import Page
from app.schemas.shariah import (
    CharityCreate,
    CharityRead,
    CharityUpdate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    ReviewCreate,
    ReviewRead,
    ReviewUpdate,
    RulingCreate,
    RulingRead,
    RulingUpdate,
    ShariahFindingCreate,
    ShariahFindingRead,
    ShariahFindingUpdate,
)
from app.services import audit as audit_log

router = APIRouter(tags=["shariah governance"])

_READ = Depends(require("shariah:read"))
_WRITE = Depends(require("shariah:write"))


async def _next_ref(db, model, prefix: str) -> str:
    count = await db.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{count + 1:03d}"


async def _get(db, model, obj_id, name: str):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# =============================================================== rulings / fatwas ===
@router.get("/shariah-rulings", response_model=Page[RulingRead], dependencies=[_READ])
async def list_rulings(db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 100,
                       offset: Annotated[int, Query(ge=0)] = 0) -> Page[RulingRead]:
    stmt = select(ShariahRuling).where(ShariahRuling.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(ShariahRuling.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[RulingRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/shariah-rulings", response_model=RulingRead, status_code=201, dependencies=[_WRITE])
async def create_ruling(body: RulingCreate, db: DbSession, user: CurrentUser) -> RulingRead:
    obj = ShariahRuling(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, ShariahRuling, "SR")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="shariah_ruling",
                           entity_id=obj.id, summary=f"Issued Shariah ruling {obj.reference}: {obj.title}")
    return RulingRead.model_validate(obj)


@router.patch("/shariah-rulings/{rid}", response_model=RulingRead, dependencies=[_WRITE])
async def update_ruling(rid: uuid.UUID, body: RulingUpdate, db: DbSession) -> RulingRead:
    obj = await _get(db, ShariahRuling, rid, "Ruling")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return RulingRead.model_validate(obj)


@router.delete("/shariah-rulings/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_ruling(rid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, ShariahRuling, rid, "Ruling")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# =============================================================== islamic products ===
@router.get("/islamic-products", response_model=Page[ProductRead], dependencies=[_READ])
async def list_products(db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 100,
                        offset: Annotated[int, Query(ge=0)] = 0) -> Page[ProductRead]:
    stmt = select(IslamicProduct).where(IslamicProduct.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(IslamicProduct.name).limit(limit).offset(offset))).all()
    return Page(items=[ProductRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/islamic-products", response_model=ProductRead, status_code=201, dependencies=[_WRITE])
async def create_product(body: ProductCreate, db: DbSession, user: CurrentUser) -> ProductRead:
    if body.approving_ruling_id is not None:
        await _get(db, ShariahRuling, body.approving_ruling_id, "Ruling")
    obj = IslamicProduct(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, IslamicProduct, "IP")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="islamic_product",
                           entity_id=obj.id, summary=f"Registered Islamic product {obj.reference}: {obj.name}")
    return ProductRead.model_validate(obj)


@router.patch("/islamic-products/{pid}", response_model=ProductRead, dependencies=[_WRITE])
async def update_product(pid: uuid.UUID, body: ProductUpdate, db: DbSession) -> ProductRead:
    obj = await _get(db, IslamicProduct, pid, "Product")
    data = body.model_dump(exclude_unset=True)
    if data.get("approving_ruling_id") is not None:
        await _get(db, ShariahRuling, data["approving_ruling_id"], "Ruling")
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return ProductRead.model_validate(obj)


@router.delete("/islamic-products/{pid}", status_code=204, dependencies=[_WRITE])
async def delete_product(pid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, IslamicProduct, pid, "Product")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================================ shariah reviews ===
async def _load_review(db, rid: uuid.UUID) -> ShariahReview:
    obj = await db.scalar(
        select(ShariahReview).where(ShariahReview.id == rid).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Shariah review not found")
    return obj


@router.get("/shariah-reviews", response_model=Page[ReviewRead], dependencies=[_READ])
async def list_reviews(db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 100,
                       offset: Annotated[int, Query(ge=0)] = 0) -> Page[ReviewRead]:
    stmt = select(ShariahReview).where(ShariahReview.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(ShariahReview.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[ReviewRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/shariah-reviews", response_model=ReviewRead, status_code=201, dependencies=[_WRITE])
async def create_review(body: ReviewCreate, db: DbSession, user: CurrentUser) -> ReviewRead:
    if body.product_id is not None:
        await _get(db, IslamicProduct, body.product_id, "Product")
    obj = ShariahReview(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, ShariahReview, "SHR")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="shariah_review",
                           entity_id=obj.id, summary=f"Opened Shariah review {obj.reference}: {obj.title}")
    return ReviewRead.model_validate(await _load_review(db, obj.id))


@router.get("/shariah-reviews/{rid}", response_model=ReviewRead, dependencies=[_READ])
async def get_review(rid: uuid.UUID, db: DbSession) -> ReviewRead:
    return ReviewRead.model_validate(await _load_review(db, rid))


@router.patch("/shariah-reviews/{rid}", response_model=ReviewRead, dependencies=[_WRITE])
async def update_review(rid: uuid.UUID, body: ReviewUpdate, db: DbSession) -> ReviewRead:
    obj = await _load_review(db, rid)
    data = body.model_dump(exclude_unset=True)
    if data.get("product_id") is not None:
        await _get(db, IslamicProduct, data["product_id"], "Product")
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return ReviewRead.model_validate(await _load_review(db, rid))


@router.delete("/shariah-reviews/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_review(rid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_review(db, rid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ---------------------------------------------------- SNC findings (children) ---
@router.post("/shariah-reviews/{rid}/findings", response_model=ReviewRead, status_code=201, dependencies=[_WRITE])
async def add_finding(rid: uuid.UUID, body: ShariahFindingCreate, db: DbSession, user: CurrentUser) -> ReviewRead:
    await _load_review(db, rid)
    finding = ShariahFinding(tenant_id=user.tenant_id, review_id=rid, **body.model_dump())
    finding.reference = await _next_ref(db, ShariahFinding, "SNC")
    db.add(finding)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="shariah_finding",
                           entity_id=finding.id, summary=f"Raised SNC finding {finding.reference}: {finding.title}")
    return ReviewRead.model_validate(await _load_review(db, rid))


@router.patch("/shariah-findings/{fid}", response_model=ShariahFindingRead, dependencies=[_WRITE])
async def update_finding(fid: uuid.UUID, body: ShariahFindingUpdate, db: DbSession) -> ShariahFindingRead:
    obj = await _get(db, ShariahFinding, fid, "Finding")
    data = body.model_dump(exclude_unset=True)
    if data.get("status") in (ShariahFindingStatus.closed, ShariahFindingStatus.remediated) and not obj.closed_date and "closed_date" not in data:
        obj.closed_date = date.today()
    if data.get("status") == ShariahFindingStatus.open:
        obj.closed_date = None
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return ShariahFindingRead.model_validate(obj)


@router.delete("/shariah-findings/{fid}", status_code=204, dependencies=[_WRITE])
async def delete_finding(fid: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(ShariahFinding).where(ShariahFinding.id == fid))
    if obj is not None:
        await db.delete(obj)


# ================================================= purification / charity ledger ===
@router.get("/charity-ledger", response_model=Page[CharityRead], dependencies=[_READ])
async def list_charity(db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 100,
                       offset: Annotated[int, Query(ge=0)] = 0) -> Page[CharityRead]:
    stmt = select(CharityDisbursement).where(CharityDisbursement.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(CharityDisbursement.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[CharityRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/charity-ledger", response_model=CharityRead, status_code=201, dependencies=[_WRITE])
async def create_charity(body: CharityCreate, db: DbSession, user: CurrentUser) -> CharityRead:
    if body.source_finding_id is not None:
        await _get(db, ShariahFinding, body.source_finding_id, "Finding")
    obj = CharityDisbursement(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, CharityDisbursement, "CHR")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="charity_disbursement",
                           entity_id=obj.id, summary=f"Recorded purification {obj.reference}: {obj.amount} {obj.currency}")
    return CharityRead.model_validate(obj)


@router.patch("/charity-ledger/{cid}", response_model=CharityRead, dependencies=[_WRITE])
async def update_charity(cid: uuid.UUID, body: CharityUpdate, db: DbSession) -> CharityRead:
    obj = await _get(db, CharityDisbursement, cid, "Disbursement")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return CharityRead.model_validate(obj)


@router.delete("/charity-ledger/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_charity(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, CharityDisbursement, cid, "Disbursement")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()
