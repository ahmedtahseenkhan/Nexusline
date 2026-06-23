"""Asset Management — full eramba-parity API.

Assets with media type, RACI ownership (owner/guardian/user), CIA classifications,
labels, a review cycle, workflow status, soft-delete, and links to risks, processes,
legal obligations, compliance requirements, incidents, exceptions and related assets.
Plus the per-module lookup registries (media types, classification types, labels).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import (
    Asset,
    AssetClassification,
    AssetClassificationType,
    AssetLabel,
    AssetMediaType,
    AssetReview,
)
from app.models.enums import AssetReviewStatus
from app.models.exception import ExceptionRecord
from app.models.incident import Incident
from app.models.compliance import Requirement
from app.models.organization import Legal, Process
from app.schemas.asset import (
    AssetClassificationCreate,
    AssetClassificationRead,
    AssetClassificationTypeCreate,
    AssetClassificationTypeRead,
    AssetCreate,
    AssetLabelCreate,
    AssetLabelRead,
    AssetMediaTypeCreate,
    AssetMediaTypeRead,
    AssetRead,
    AssetReviewComplete,
    AssetReviewCreate,
    AssetReviewRead,
    AssetUpdate,
    ClassificationRef,
    LinkRef,
)
from app.schemas.common import Page
from app.services import audit
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/assets", tags=["assets"])

# Relationship name -> (model, write-field on the schema)
_REL = {
    "classifications": (AssetClassification, "classification_ids"),
    "processes": (Process, "process_ids"),
    "legals": (Legal, "legal_ids"),
    "requirements": (Requirement, "requirement_ids"),
    "incidents": (Incident, "incident_ids"),
    "exceptions": (ExceptionRecord, "exception_ids"),
}


def _loads():
    """Eager-load everything the serializer touches (incl. nested classification.type)."""
    return (
        selectinload(Asset.media_type),
        selectinload(Asset.label),
        selectinload(Asset.owner),
        selectinload(Asset.guardian),
        selectinload(Asset.user),
        selectinload(Asset.classifications).selectinload(AssetClassification.type),
        selectinload(Asset.processes),
        selectinload(Asset.legals),
        selectinload(Asset.requirements),
        selectinload(Asset.incidents),
        selectinload(Asset.exceptions),
        selectinload(Asset.related_assets),
        selectinload(Asset.risks),
        selectinload(Asset.reviews),
    )


def _ref(obj) -> LinkRef | None:
    if obj is None:
        return None
    label = getattr(obj, "reference", None) or getattr(obj, "name", None) or getattr(obj, "title", None) or str(obj.id)[:8]
    return LinkRef(id=obj.id, label=str(label))


def _serialize(a: Asset) -> AssetRead:
    return AssetRead(
        id=a.id,
        name=a.name,
        description=a.description,
        media_type=_ref(a.media_type),
        label=_ref(a.label),
        owner=_ref(a.owner),
        guardian=_ref(a.guardian),
        user=_ref(a.user),
        confidentiality=a.confidentiality,
        integrity=a.integrity,
        availability=a.availability,
        criticality=a.criticality,
        classification=a.classification,
        potential_liabilities=a.potential_liabilities,
        review_frequency=a.review_frequency,
        next_review_date=a.next_review_date,
        last_review_date=a.last_review_date,
        expired_reviews=a.expired_reviews,
        review_status=a.review_status,
        workflow_status=a.workflow_status,
        classifications=[
            ClassificationRef(id=c.id, name=c.name, value=c.value, type_name=c.type.name if c.type else "")
            for c in a.classifications
        ],
        processes=[_ref(x) for x in a.processes],
        legals=[_ref(x) for x in a.legals],
        requirements=[_ref(x) for x in a.requirements],
        incidents=[_ref(x) for x in a.incidents],
        exceptions=[_ref(x) for x in a.exceptions],
        related_assets=[_ref(x) for x in a.related_assets],
        risks=[_ref(x) for x in a.risks],
        reviews=[AssetReviewRead.model_validate(r) for r in a.reviews],
        risk_count=len(a.risks),
        review_count=len(a.reviews),
        created_at=a.created_at,
    )


async def _get_or_404(db, asset_id: uuid.UUID) -> Asset:
    asset = await db.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.deleted.is_(False)).options(*_loads())
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


async def _fresh(db, asset_id: uuid.UUID) -> Asset:
    return await db.scalar(
        select(Asset).where(Asset.id == asset_id).options(*_loads()).execution_options(populate_existing=True)
    )


async def _load_many(db, model, ids):
    if not ids:
        return []
    return list((await db.scalars(select(model).where(model.id.in_(ids)))).all())


async def _apply_relations(db, asset: Asset, data: dict) -> None:
    for rel, (model, field) in _REL.items():
        if field in data and data[field] is not None:
            setattr(asset, rel, await _load_many(db, model, data[field]))
    if data.get("related_ids") is not None:
        related = await _load_many(db, Asset, [i for i in data["related_ids"] if i != asset.id])
        asset.related_assets = related


@router.get("", response_model=Page[AssetRead], dependencies=[Depends(require("asset:read"))])
async def list_assets(
    db: DbSession,
    search: Annotated[str | None, Query()] = None,
    media_type_id: Annotated[uuid.UUID | None, Query()] = None,
    review_overdue: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AssetRead]:
    stmt = select(Asset).where(Asset.deleted.is_(False))
    if search:
        stmt = stmt.where(Asset.name.ilike(f"%{search}%"))
    if media_type_id:
        stmt = stmt.where(Asset.media_type_id == media_type_id)
    if review_overdue:
        stmt = stmt.where(Asset.next_review_date < date.today())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.options(*_loads()).order_by(Asset.name).limit(limit).offset(offset))).all()
    return Page(items=[_serialize(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=AssetRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_asset(body: AssetCreate, db: DbSession, user: CurrentUser) -> AssetRead:
    data = body.model_dump()
    rel_data = {k: data.pop(k) for k in list(data) if k.endswith("_ids")}
    if data.get("next_review_date") is None:
        data["next_review_date"] = next_review_date(body.review_frequency, date.today())
    asset = Asset(tenant_id=user.tenant_id, **data)
    db.add(asset)
    await db.flush()
    await _apply_relations(db, asset, rel_data)
    await db.flush()
    await audit.record(db, actor=user, action="create", entity_type="asset", entity_id=asset.id,
                       summary=f"Created asset {asset.name}")
    return _serialize(await _fresh(db, asset.id))


@router.get("/{asset_id}", response_model=AssetRead, dependencies=[Depends(require("asset:read"))])
async def get_asset(asset_id: uuid.UUID, db: DbSession) -> AssetRead:
    return _serialize(await _get_or_404(db, asset_id))


@router.patch("/{asset_id}", response_model=AssetRead, dependencies=[Depends(require("asset:write"))])
async def update_asset(asset_id: uuid.UUID, body: AssetUpdate, db: DbSession, user: CurrentUser) -> AssetRead:
    asset = await _get_or_404(db, asset_id)
    data = body.model_dump(exclude_unset=True)
    rel_data = {k: data.pop(k) for k in list(data) if k.endswith("_ids")}
    for field, value in data.items():
        setattr(asset, field, value)
    await _apply_relations(db, asset, rel_data)
    await db.flush()
    await audit.record(db, actor=user, action="update", entity_type="asset", entity_id=asset.id,
                       summary=f"Updated asset {asset.name}")
    return _serialize(await _fresh(db, asset.id))


@router.delete("/{asset_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_asset(asset_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    from datetime import datetime, timezone

    asset = await _get_or_404(db, asset_id)
    asset.deleted = True
    asset.deleted_date = datetime.now(timezone.utc)
    await audit.record(db, actor=user, action="delete", entity_type="asset", entity_id=asset.id,
                       summary=f"Archived asset {asset.name}")


# ----------------------------------------------------------------- review cycle
@router.get("/{asset_id}/reviews", response_model=list[AssetReviewRead], dependencies=[Depends(require("asset:read"))])
async def list_reviews(asset_id: uuid.UUID, db: DbSession) -> list[AssetReviewRead]:
    asset = await _get_or_404(db, asset_id)
    return [AssetReviewRead.model_validate(r) for r in asset.reviews]


@router.post("/{asset_id}/reviews", response_model=AssetRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def schedule_review(asset_id: uuid.UUID, body: AssetReviewCreate, db: DbSession) -> AssetRead:
    asset = await _get_or_404(db, asset_id)
    db.add(AssetReview(tenant_id=asset.tenant_id, asset_id=asset.id, reviewer=body.reviewer,
                       scheduled_date=body.scheduled_date, comments=body.comments,
                       status=AssetReviewStatus.scheduled))
    asset.next_review_date = body.scheduled_date
    await db.flush()
    return _serialize(await _fresh(db, asset.id))


@router.post("/{asset_id}/reviews/{review_id}/complete", response_model=AssetRead, dependencies=[Depends(require("asset:write"))])
async def complete_review(asset_id: uuid.UUID, review_id: uuid.UUID, body: AssetReviewComplete, db: DbSession, user: CurrentUser) -> AssetRead:
    asset = await _get_or_404(db, asset_id)
    review = await db.scalar(select(AssetReview).where(AssetReview.id == review_id, AssetReview.asset_id == asset_id))
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    today = date.today()
    review.status = AssetReviewStatus.completed
    review.actual_date = today
    review.outcome = body.outcome
    if body.comments:
        review.comments = body.comments
    asset.last_review_date = today
    asset.next_review_date = next_review_date(asset.review_frequency, today)
    await audit.record(db, actor=user, action="review", entity_type="asset", entity_id=asset.id,
                       summary=f"Reviewed asset {asset.name} ({body.outcome})")
    await db.flush()
    return _serialize(await _fresh(db, asset.id))


# ----------------------------------------------------------------- labels lookup
labels_router = APIRouter(prefix="/asset-labels", tags=["assets"])


@labels_router.get("", response_model=list[AssetLabelRead], dependencies=[Depends(require("asset:read"))])
async def list_asset_labels(db: DbSession) -> list[AssetLabelRead]:
    rows = (await db.scalars(select(AssetLabel).order_by(AssetLabel.name))).all()
    return [AssetLabelRead.model_validate(r) for r in rows]


@labels_router.post("", response_model=AssetLabelRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_asset_label(body: AssetLabelCreate, db: DbSession, user: CurrentUser) -> AssetLabelRead:
    obj = AssetLabel(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return AssetLabelRead.model_validate(obj)


@labels_router.delete("/{label_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_asset_label(label_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.get(AssetLabel, label_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Label not found")
    await db.delete(obj)


# ------------------------------------------------------------- media types lookup
media_types_router = APIRouter(prefix="/asset-media-types", tags=["assets"])


@media_types_router.get("", response_model=list[AssetMediaTypeRead], dependencies=[Depends(require("asset:read"))])
async def list_media_types(db: DbSession) -> list[AssetMediaTypeRead]:
    rows = (await db.scalars(select(AssetMediaType).order_by(AssetMediaType.name))).all()
    return [AssetMediaTypeRead.model_validate(r) for r in rows]


@media_types_router.post("", response_model=AssetMediaTypeRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_media_type(body: AssetMediaTypeCreate, db: DbSession, user: CurrentUser) -> AssetMediaTypeRead:
    obj = AssetMediaType(tenant_id=user.tenant_id, editable=True, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return AssetMediaTypeRead.model_validate(obj)


@media_types_router.delete("/{type_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_media_type(type_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.get(AssetMediaType, type_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Media type not found")
    if not obj.editable:
        raise HTTPException(status_code=409, detail="Built-in media type cannot be deleted")
    await db.delete(obj)


# ------------------------------------------------- classification types + values
class_router = APIRouter(prefix="/asset-classification-types", tags=["assets"])


@class_router.get("", response_model=list[AssetClassificationTypeRead], dependencies=[Depends(require("asset:read"))])
async def list_classification_types(db: DbSession) -> list[AssetClassificationTypeRead]:
    rows = (await db.scalars(select(AssetClassificationType).order_by(AssetClassificationType.name))).all()
    return [AssetClassificationTypeRead.model_validate(r) for r in rows]


@class_router.post("", response_model=AssetClassificationTypeRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_classification_type(body: AssetClassificationTypeCreate, db: DbSession, user: CurrentUser) -> AssetClassificationTypeRead:
    obj = AssetClassificationType(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    return AssetClassificationTypeRead.model_validate(await db.scalar(
        select(AssetClassificationType).where(AssetClassificationType.id == obj.id).execution_options(populate_existing=True)
    ))


@class_router.post("/{type_id}/classifications", response_model=AssetClassificationRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def add_classification(type_id: uuid.UUID, body: AssetClassificationCreate, db: DbSession, user: CurrentUser) -> AssetClassificationRead:
    if await db.get(AssetClassificationType, type_id) is None:
        raise HTTPException(status_code=404, detail="Classification type not found")
    obj = AssetClassification(tenant_id=user.tenant_id, type_id=type_id, name=body.name, criteria=body.criteria, value=body.value)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return AssetClassificationRead.model_validate(obj)


@class_router.delete("/classifications/{classification_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_classification(classification_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.get(AssetClassification, classification_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Classification not found")
    await db.delete(obj)
