"""Model Risk Management & AI Governance API — the model inventory and its
validation lifecycle (SR 11-7 / ISO 42001 flavoured).

Supervisors expect banks to maintain a materiality-tiered inventory of quantitative
and AI/ML models (IFRS 9 ECL, AML scoring, credit scoring, capital, stress) and to
subject each to independent validation on a periodic cycle.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.model_risk import (
    ModelInventory,
    ModelStatus,
    ModelType,
    ModelValidation,
)
from app.schemas.common import Page
from app.schemas.model_risk import (
    ModelCreate,
    ModelRead,
    ModelUpdate,
    ValidationCreate,
    ValidationRead,
    ValidationUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["model risk"])

_READ = Depends(require("modelrisk:read"))
_WRITE = Depends(require("modelrisk:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _load_model(db, mid) -> ModelInventory:
    obj = await db.scalar(
        select(ModelInventory).where(ModelInventory.id == mid, ModelInventory.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return obj


# ========================================================== model inventory ===
# `is_validation_overdue` is computed; sort by the underlying next_validation_date column.
_MODEL_SORTABLE = {
    "reference": ModelInventory.reference,
    "name": ModelInventory.name,
    "model_type": ModelInventory.model_type,
    "owner": ModelInventory.owner,
    "materiality": ModelInventory.materiality,
    "status": ModelInventory.status,
    "next_validation_date": ModelInventory.next_validation_date,
    "created_at": ModelInventory.created_at,
}


@router.get("/model-risk", response_model=Page[ModelRead], dependencies=[_READ])
async def list_models(
    db: DbSession,
    search: str | None = None,
    model_type: ModelType | None = None,
    status: ModelStatus | None = None,
    validation_overdue: bool | None = None,
    ai_ml: bool | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ModelRead]:
    stmt = select(ModelInventory).where(ModelInventory.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                ModelInventory.name.ilike(like),
                ModelInventory.reference.ilike(like),
                ModelInventory.owner.ilike(like),
                ModelInventory.vendor.ilike(like),
            )
        )
    if model_type is not None:
        stmt = stmt.where(ModelInventory.model_type == model_type)
    if status is not None:
        stmt = stmt.where(ModelInventory.status == status)
    if ai_ml is not None:
        stmt = stmt.where(ModelInventory.ai_ml.is_(ai_ml))
    if validation_overdue:
        stmt = stmt.where(
            ModelInventory.status != ModelStatus.retired,
            ModelInventory.next_validation_date.is_not(None),
            ModelInventory.next_validation_date < date.today(),
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _MODEL_SORTABLE, default=ModelInventory.created_at)
    else:
        stmt = stmt.order_by(ModelInventory.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[ModelRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/model-risk", response_model=ModelRead, status_code=201, dependencies=[_WRITE])
async def create_model(body: ModelCreate, db: DbSession, user: CurrentUser) -> ModelRead:
    obj = ModelInventory(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, ModelInventory, "MDL")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="model_inventory",
                           entity_id=obj.id, summary=f"Registered model {obj.reference}: {obj.name}")
    return ModelRead.model_validate(await _load_model(db, obj.id))


@router.get("/model-risk/{mid}", response_model=ModelRead, dependencies=[_READ])
async def get_model(mid: uuid.UUID, db: DbSession) -> ModelRead:
    return ModelRead.model_validate(await _load_model(db, mid))


@router.patch("/model-risk/{mid}", response_model=ModelRead, dependencies=[_WRITE])
async def update_model(mid: uuid.UUID, body: ModelUpdate, db: DbSession) -> ModelRead:
    obj = await _load_model(db, mid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return ModelRead.model_validate(await _load_model(db, mid))


@router.delete("/model-risk/{mid}", status_code=204, dependencies=[_WRITE])
async def delete_model(mid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_model(db, mid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ========================================================= model validations ===
@router.post("/model-risk/{mid}/validations", response_model=ModelRead, status_code=201, dependencies=[_WRITE])
async def add_validation(mid: uuid.UUID, body: ValidationCreate, db: DbSession, user: CurrentUser) -> ModelRead:
    model = await _load_model(db, mid)
    v = ModelValidation(tenant_id=user.tenant_id, model_id=mid, **body.model_dump())
    v.reference = await _next_ref(db, ModelValidation, "VAL")
    db.add(v)
    # Advance the inventory's last-validation date only for the most recent exercise, so a
    # back-dated validation entry can't regress the schedule.
    if body.validation_date is not None and (
        model.last_validation_date is None or body.validation_date >= model.last_validation_date
    ):
        model.last_validation_date = body.validation_date
    await db.flush()
    return ModelRead.model_validate(await _load_model(db, mid))


@router.patch("/model-validations/{vid}", response_model=ValidationRead, dependencies=[_WRITE])
async def update_validation(vid: uuid.UUID, body: ValidationUpdate, db: DbSession) -> ValidationRead:
    obj = await _get(db, ModelValidation, vid, "Validation")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return ValidationRead.model_validate(obj)


@router.delete("/model-validations/{vid}", status_code=204, dependencies=[_WRITE])
async def delete_validation(vid: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(ModelValidation).where(ModelValidation.id == vid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


# ================================================================ summary ===
class ModelRiskSummary(BaseModel):
    total_models: int
    models_by_status: dict[str, int]
    models_by_type: dict[str, int]
    validation_overdue: int
    ai_ml_count: int
    regulatory_relevant_count: int


@router.get("/model-risk-summary", response_model=ModelRiskSummary, dependencies=[_READ],
            summary="Model-risk dashboard roll-up: inventory by status / type, overdue validations, AI-ML and regulatory counts")
async def model_risk_summary(db: DbSession) -> ModelRiskSummary:
    models = (await db.scalars(select(ModelInventory).where(ModelInventory.deleted.is_(False)))).all()
    by_status: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    validation_overdue = 0
    ai_ml_count = 0
    regulatory_relevant_count = 0
    for m in models:
        by_status[m.status.value] += 1
        by_type[m.model_type.value] += 1
        if m.is_validation_overdue:
            validation_overdue += 1
        if m.ai_ml:
            ai_ml_count += 1
        if m.regulatory_relevant:
            regulatory_relevant_count += 1
    return ModelRiskSummary(
        total_models=len(models),
        models_by_status=dict(by_status),
        models_by_type=dict(by_type),
        validation_overdue=validation_overdue,
        ai_ml_count=ai_ml_count,
        regulatory_relevant_count=regulatory_relevant_count,
    )
