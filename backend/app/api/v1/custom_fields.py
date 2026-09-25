"""Custom Fields API — manage per-model field definitions and per-record values."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.custom_field import (
    CUSTOM_FIELD_MODELS,
    CustomField,
    CustomFieldValue,
    custom_field_entity_type,
)
from app.schemas.common import Page
from app.schemas.custom_field import (
    CustomFieldCreate,
    CustomFieldRead,
    CustomFieldUpdate,
    CustomFieldValueItem,
    CustomFieldValuesUpdate,
)
from app.services import audit as audit_log
from app.services import custom_field_values as cf_values
from app.services import entity_types, record_registry
from app.services import modules as module_service

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


async def _reject_duplicate_label(
    db, model: str, label: str, exclude: uuid.UUID | None = None
) -> None:
    """One label per module: a repeated name is ambiguous on the record, in the form and
    as a spreadsheet heading on export/import."""
    stmt = select(CustomField.id).where(
        CustomField.model == model, func.lower(func.trim(CustomField.label)) == label.strip().lower()
    )
    if exclude is not None:
        stmt = stmt.where(CustomField.id != exclude)
    if await db.scalar(stmt.limit(1)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This module already has a custom field named '{label.strip()}'",
        )


#: Custom-field keys that are one register of a shared table: the record must also be of
#: this class, or an IT asset could carry the information-asset register's fields.
_RECORD_CLASS: dict[str, tuple[str, str, str]] = {
    "it_asset": ("asset_class", "it_asset", "IT asset"),
    "information_asset": ("asset_class", "information_asset", "information asset"),
}


def record_filter(model: str, entity_id: uuid.UUID):
    """``(ORM class, where-clauses)`` that find ``entity_id`` in the register behind a
    custom-field key, or ``None`` when the key has no table of its own. Pure."""
    orm = record_registry.model_for(custom_field_entity_type(model))
    if orm is None:
        return None
    clauses = [orm.id == entity_id]
    if model in _RECORD_CLASS:
        column, value, _label = _RECORD_CLASS[model]
        clauses.append(getattr(orm, column) == value)
    return orm, clauses


async def _require_record(db, model: str, entity_id: uuid.UUID) -> None:
    """Values are only written onto a record that exists in this key's register (one
    indexed lookup): a stray id, or a record of another register, gets a 404 rather than
    an orphan value no page will ever show. Archived records still take values, as they
    still carry them."""
    found = record_filter(model, entity_id)
    if found is None:
        return
    orm, clauses = found
    if await db.scalar(select(orm.id).where(*clauses)) is None:
        noun = _RECORD_CLASS[model][2] if model in _RECORD_CLASS else entity_types.spec(model).label.lower()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No {noun} with this id")


@router.get("/models", response_model=list[str])
async def list_models(user: CurrentUser) -> list[str]:
    """Models that can carry custom fields (UI dropdown) — those of usable modules."""
    return await _usable_models(user.tenant_id)


async def _usable_models(tenant_id: uuid.UUID) -> list[str]:
    """A switched-off or unlicensed module's registers are not offered or listed."""
    return [
        m for m in CUSTOM_FIELD_MODELS
        if await module_service.entity_type_usable(custom_field_entity_type(m), tenant_id)
    ]


@router.get("", response_model=Page[CustomFieldRead])
async def list_fields(
    db: DbSession,
    user: CurrentUser,
    model: str | None = Query(default=None),
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CustomFieldRead]:
    stmt = select(CustomField).where(CustomField.model.in_(await _usable_models(user.tenant_id)))
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
    await _reject_duplicate_label(db, body.model, body.label)
    obj = CustomField(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await audit_log.record(
        db, actor=user, action="create", entity_type="custom_field", entity_id=obj.id,
        summary=f"Added custom field '{obj.label}' to {obj.model}",
    )
    return CustomFieldRead.model_validate(obj)


@router.patch("/{field_id}", response_model=CustomFieldRead, dependencies=[Depends(require("customfield:manage"))])
async def update_field(
    field_id: uuid.UUID, body: CustomFieldUpdate, db: DbSession, user: CurrentUser
) -> CustomFieldRead:
    obj = await _load(db, field_id)
    await module_service.require_entity_module(custom_field_entity_type(obj.model), user.tenant_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("label"):
        await _reject_duplicate_label(db, obj.model, changes["label"], exclude=obj.id)
    for k, v in changes.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    await audit_log.record(
        db, actor=user, action="update", entity_type="custom_field", entity_id=obj.id,
        summary=f"Updated custom field '{obj.label}' on {obj.model}", changes=changes,
    )
    return CustomFieldRead.model_validate(obj)


@router.delete("/{field_id}", status_code=204, dependencies=[Depends(require("customfield:manage"))])
async def delete_field(field_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, field_id)
    await module_service.require_entity_module(custom_field_entity_type(obj.model), user.tenant_id)
    await audit_log.record(
        db, actor=user, action="delete", entity_type="custom_field", entity_id=obj.id,
        summary=f"Deleted custom field '{obj.label}' from {obj.model}",
    )
    await db.delete(obj)


@router.get("/{model}/values/{entity_id}", response_model=list[CustomFieldValueItem])
async def get_values(
    model: str, entity_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[CustomFieldValueItem]:
    entity_types.require_read(user, custom_field_entity_type(model))
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


def plan_values(
    fields: dict[uuid.UUID, CustomField], stored: dict[uuid.UUID, str], sent: dict[uuid.UUID, str]
) -> tuple[dict[uuid.UUID, str], dict[str, dict[str, str]]]:
    """What a save writes: ``(field id -> value to store, audit changes by label)``.

    Each sent value is validated and normalised like an imported cell
    (``services.custom_field_values``); ids of other modules' fields are ignored, and
    unchanged values are left alone. Raises ``HTTPException`` 422 listing every bad
    value, so nothing is half-saved. Pure.
    """
    writes: dict[uuid.UUID, str] = {}
    changes: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for field_id, raw in sent.items():
        field = fields.get(field_id)
        if field is None:
            continue
        try:
            value = cf_values.clean(field, raw)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        before = stored.get(field_id, "")
        if value == before:
            continue
        writes[field_id] = value
        changes[field.label] = {"from": before, "to": value}
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    return writes, changes


@router.put("/{model}/values/{entity_id}", response_model=list[CustomFieldValueItem])
async def set_values(
    model: str, entity_id: uuid.UUID, body: CustomFieldValuesUpdate, db: DbSession, user: CurrentUser
) -> list[CustomFieldValueItem]:
    # Custom-field values are record data: writing them needs the owning module's write
    # permission, the model name must be a real entity type, and the record must exist in
    # that register (in this organisation — RLS scopes the lookup).
    entity_type = custom_field_entity_type(model)
    entity_types.require_write(user, entity_type)
    await _require_record(db, model, entity_id)
    # Only accept values for fields that belong to this model (RLS already scopes by tenant).
    fields = {f.id: f for f in (await db.scalars(select(CustomField).where(CustomField.model == model))).all()}
    existing = {
        v.custom_field_id: v
        for v in (
            await db.scalars(
                select(CustomFieldValue).where(
                    CustomFieldValue.entity_id == entity_id,
                    CustomFieldValue.custom_field_id.in_(list(fields)),
                )
            )
        ).all()
    } if fields else {}
    writes, changes = plan_values(fields, {k: v.value for k, v in existing.items()}, body.values)
    for field_id, value in writes.items():
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
    if writes:
        await db.flush()
        await audit_log.record(
            db, actor=user, action="update", entity_type=entity_type, entity_id=entity_id,
            summary="Updated custom fields", changes=changes,
        )
    return await get_values(model, entity_id, db, user)
