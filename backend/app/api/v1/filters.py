"""Saved Filters API — CRUD named condition-sets and run them against a model."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import or_, select

from app.core.deps import CurrentUser, DbSession
from app.models.saved_filter import SavedFilter
from app.schemas.saved_filter import (
    FilterMatch,
    FilterResults,
    SavedFilterCreate,
    SavedFilterRead,
    SavedFilterUpdate,
)
from app.services import status_rules as engine

router = APIRouter(prefix="/filters", tags=["filters"])


def _is_admin(user) -> bool:
    return "role:write" in user.permission_codes


def _label(record) -> str:
    for attr in ("reference", "name", "title"):
        v = getattr(record, attr, None)
        if v:
            return str(v)
    return str(record.id)[:8]


def _record_matches(record, mode: str, conditions: list) -> bool:
    if not conditions:
        return True
    results = [
        engine.match_values(record, c.get("field"), c.get("operator"), c.get("value", ""))
        for c in conditions
    ]
    return all(results) if mode == "all" else any(results)


async def _load(db, filter_id: uuid.UUID) -> SavedFilter:
    obj = await db.scalar(select(SavedFilter).where(SavedFilter.id == filter_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Filter not found")
    return obj


@router.get("/fields/{model}", response_model=list[dict])
async def fields(model: str, _: CurrentUser) -> list[dict]:
    if model not in engine.MODEL_MAP:
        raise HTTPException(status_code=404, detail="Unsupported model")
    return engine.evaluable_fields(model)


@router.get("", response_model=list[SavedFilterRead])
async def list_filters(
    db: DbSession, user: CurrentUser, model: str | None = Query(default=None)
) -> list[SavedFilterRead]:
    stmt = select(SavedFilter).where(
        or_(SavedFilter.shared.is_(True), SavedFilter.owner_id == user.id)
    )
    if model:
        stmt = stmt.where(SavedFilter.model == model)
    rows = (await db.scalars(stmt.order_by(SavedFilter.name))).all()
    return [SavedFilterRead.model_validate(r) for r in rows]


@router.post("", response_model=SavedFilterRead, status_code=201)
async def create_filter(body: SavedFilterCreate, db: DbSession, user: CurrentUser) -> SavedFilterRead:
    if body.model not in engine.MODEL_MAP:
        raise HTTPException(status_code=422, detail=f"Unsupported model '{body.model}'")
    obj = SavedFilter(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        owner_email=user.email,
        name=body.name,
        model=body.model,
        description=body.description,
        match_mode=body.match_mode,
        conditions=[c.model_dump() for c in body.conditions],
        shared=body.shared,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return SavedFilterRead.model_validate(obj)


@router.patch("/{filter_id}", response_model=SavedFilterRead)
async def update_filter(filter_id: uuid.UUID, body: SavedFilterUpdate, db: DbSession, user: CurrentUser) -> SavedFilterRead:
    obj = await _load(db, filter_id)
    if not (_is_admin(user) or obj.owner_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your filter")
    data = body.model_dump(exclude_unset=True)
    if "conditions" in data and data["conditions"] is not None:
        data["conditions"] = [c if isinstance(c, dict) else c.model_dump() for c in data["conditions"]]
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return SavedFilterRead.model_validate(obj)


@router.delete("/{filter_id}", status_code=204)
async def delete_filter(filter_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, filter_id)
    if not (_is_admin(user) or obj.owner_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your filter")
    await db.delete(obj)


@router.get("/{filter_id}/results", response_model=FilterResults)
async def run_filter(filter_id: uuid.UUID, db: DbSession, _: CurrentUser) -> FilterResults:
    flt = await _load(db, filter_id)
    cls = engine.MODEL_MAP.get(flt.model)
    if cls is None:
        raise HTTPException(status_code=422, detail="Unsupported model")
    records = (await db.scalars(select(cls))).all()
    matched = [r for r in records if _record_matches(r, flt.match_mode, flt.conditions or [])]
    return FilterResults(
        count=len(matched),
        total=len(records),
        matches=[FilterMatch(id=r.id, label=_label(r)) for r in matched[:200]],
    )
