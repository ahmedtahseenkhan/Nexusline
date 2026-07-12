"""Custom Fields API — manage per-model field definitions and per-record values."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.custom_field import CUSTOM_FIELD_MODELS, CustomField, CustomFieldValue
from app.schemas.common import Page
from app.schemas.custom_field import (
    CustomFieldCreate,
    CustomFieldRead,
    CustomFieldUpdate,
    CustomFieldValueItem,
    CustomFieldValuesUpdate,
)

router = APIRouter(prefix="/custom-fields", tags=["custom-fields"])

_CUSTOM_FIELD_SORTABLE = {
    "label": CustomField.label,
    "model": CustomField.model,
    "field_type": CustomField.field_type,
    "order_index": CustomField.order_index,
    "created_at": CustomField.created_at,
}


async def _load(db, field_id: uuid.UUID) -> CustomField:
    obj = await db.scalar(select(CustomField).where(CustomField.id == field_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom field not found")
    return obj


@router.get("/models", response_model=list[str])
async def list_models(_: CurrentUser) -> list[str]:
    """Models that can carry custom fields (UI dropdown)."""
    return CUSTOM_FIELD_MODELS


@router.get("", response_model=Page[CustomFieldRead])
async def list_fields(
    db: DbSession,
    _: CurrentUser,
    model: str | None = Query(default=None),
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CustomFieldRead]:
    stmt = select(CustomField)
    if model:
        stmt = stmt.where(CustomField.model == model)
    if search:
        stmt = stmt.where(CustomField.label.ilike(f"%{search}%"))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _CUSTOM_FIELD_SORTABLE, default=CustomField.model)
    else:
        stmt = stmt.order_by(CustomField.model, CustomField.order_index)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[CustomFieldRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=CustomFieldRead, status_code=201, dependencies=[Depends(require("customfield:manage"))])
async def create_field(body: CustomFieldCreate, db: DbSession, user: CurrentUser) -> CustomFieldRead:
    if body.model not in CUSTOM_FIELD_MODELS:
        raise HTTPException(status_code=422, detail=f"Unsupported model '{body.model}'")
    obj = CustomField(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return CustomFieldRead.model_validate(obj)


@router.patch("/{field_id}", response_model=CustomFieldRead, dependencies=[Depends(require("customfield:manage"))])
async def update_field(field_id: uuid.UUID, body: CustomFieldUpdate, db: DbSession) -> CustomFieldRead:
    obj = await _load(db, field_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return CustomFieldRead.model_validate(obj)


@router.delete("/{field_id}", status_code=204, dependencies=[Depends(require("customfield:manage"))])
async def delete_field(field_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _load(db, field_id))


@router.get("/{model}/values/{entity_id}", response_model=list[CustomFieldValueItem])
async def get_values(model: str, entity_id: uuid.UUID, db: DbSession, _: CurrentUser) -> list[CustomFieldValueItem]:
    fields = (
        await db.scalars(
            select(CustomField)
            .where(CustomField.model == model, CustomField.enabled.is_(True))
            .order_by(CustomField.order_index)
        )
    ).all()
    if not fields:
        return []
    field_ids = [f.id for f in fields]
    values = (
        await db.scalars(
            select(CustomFieldValue).where(
                CustomFieldValue.custom_field_id.in_(field_ids),
                CustomFieldValue.entity_id == entity_id,
            )
        )
    ).all()
    by_field = {v.custom_field_id: v.value for v in values}
    return [
        CustomFieldValueItem(field=CustomFieldRead.model_validate(f), value=by_field.get(f.id, ""))
        for f in fields
    ]


@router.put("/{model}/values/{entity_id}", response_model=list[CustomFieldValueItem])
async def set_values(
    model: str, entity_id: uuid.UUID, body: CustomFieldValuesUpdate, db: DbSession, user: CurrentUser
) -> list[CustomFieldValueItem]:
    # Only accept values for fields that belong to this model (RLS already scopes by tenant).
    valid_ids = set(
        (await db.scalars(select(CustomField.id).where(CustomField.model == model))).all()
    )
    existing = {
        v.custom_field_id: v
        for v in (
            await db.scalars(
                select(CustomFieldValue).where(CustomFieldValue.entity_id == entity_id)
            )
        ).all()
    }
    for field_id, value in body.values.items():
        if field_id not in valid_ids:
            continue
        if field_id in existing:
            existing[field_id].value = value
        else:
            db.add(
                CustomFieldValue(
                    tenant_id=user.tenant_id,
                    custom_field_id=field_id,
                    entity_id=entity_id,
                    value=value,
                )
            )
    await db.flush()
    return await get_values(model, entity_id, db, user)
