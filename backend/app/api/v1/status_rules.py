"""Dynamic Status Rules API — manage rules, introspect fields, evaluate records."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.status_rule import StatusRule
from app.schemas.common import Page
from app.schemas.status_rule import (
    BulkEvaluateRequest,
    StatusLabel,
    StatusRuleCreate,
    StatusRuleRead,
    StatusRuleUpdate,
)
from app.services import status_rules as engine

router = APIRouter(prefix="/status-rules", tags=["status-rules"])

_STATUS_RULE_SORTABLE = {
    "label": StatusRule.label,
    "model": StatusRule.model,
    "field": StatusRule.field,
    "priority": StatusRule.priority,
    "created_at": StatusRule.created_at,
}


async def _load(db, rule_id: uuid.UUID) -> StatusRule:
    obj = await db.scalar(select(StatusRule).where(StatusRule.id == rule_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return obj


async def _rules_for(db, model: str) -> list[StatusRule]:
    return list((await db.scalars(select(StatusRule).where(StatusRule.model == model))).all())


@router.get("/models", response_model=list[str])
async def list_models(_: CurrentUser) -> list[str]:
    return list(engine.MODEL_MAP.keys())


@router.get("/operators", response_model=list[str])
async def list_operators(_: CurrentUser) -> list[str]:
    return engine.OPERATORS


@router.get("/fields/{model}", response_model=list[dict])
async def fields(model: str, _: CurrentUser) -> list[dict]:
    if model not in engine.MODEL_MAP:
        raise HTTPException(status_code=404, detail="Unsupported model")
    return engine.evaluable_fields(model)


@router.get("", response_model=Page[StatusRuleRead])
async def list_rules(
    db: DbSession,
    _: CurrentUser,
    model: str | None = Query(default=None),
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[StatusRuleRead]:
    stmt = select(StatusRule)
    if model:
        stmt = stmt.where(StatusRule.model == model)
    if search:
        stmt = stmt.where(StatusRule.label.ilike(f"%{search}%") | StatusRule.field.ilike(f"%{search}%"))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _STATUS_RULE_SORTABLE, default=StatusRule.model)
    else:
        stmt = stmt.order_by(StatusRule.model, StatusRule.priority)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[StatusRuleRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=StatusRuleRead, status_code=201, dependencies=[Depends(require("automation:manage"))])
async def create_rule(body: StatusRuleCreate, db: DbSession, user: CurrentUser) -> StatusRuleRead:
    if body.model not in engine.MODEL_MAP:
        raise HTTPException(status_code=422, detail=f"Unsupported model '{body.model}'")
    if body.operator not in engine.OPERATORS:
        raise HTTPException(status_code=422, detail=f"Unsupported operator '{body.operator}'")
    obj = StatusRule(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return StatusRuleRead.model_validate(obj)


@router.patch("/{rule_id}", response_model=StatusRuleRead, dependencies=[Depends(require("automation:manage"))])
async def update_rule(rule_id: uuid.UUID, body: StatusRuleUpdate, db: DbSession) -> StatusRuleRead:
    obj = await _load(db, rule_id)
    data = body.model_dump(exclude_unset=True)
    # Re-validate the same way create does — otherwise a PATCH can persist an invalid
    # model/operator that the engine silently treats as "never matches".
    if "model" in data and data["model"] not in engine.MODEL_MAP:
        raise HTTPException(status_code=422, detail=f"Unsupported model '{data['model']}'")
    if "operator" in data and data["operator"] not in engine.OPERATORS:
        raise HTTPException(status_code=422, detail=f"Unsupported operator '{data['operator']}'")
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return StatusRuleRead.model_validate(obj)


@router.delete("/{rule_id}", status_code=204, dependencies=[Depends(require("automation:manage"))])
async def delete_rule(rule_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _load(db, rule_id))


@router.get("/evaluate/{model}/{entity_id}", response_model=list[StatusLabel])
async def evaluate_one(model: str, entity_id: uuid.UUID, db: DbSession, _: CurrentUser) -> list[StatusLabel]:
    if model not in engine.MODEL_MAP:
        raise HTTPException(status_code=404, detail="Unsupported model")
    cls = engine.MODEL_MAP[model]
    stmt = select(cls).where(cls.id == entity_id)
    if hasattr(cls, "deleted"):
        stmt = stmt.where(cls.deleted.is_(False))
    record = await db.scalar(stmt)
    if record is None:
        return []
    rules = await _rules_for(db, model)
    return [StatusLabel(**lbl) for lbl in engine.evaluate(record, rules)]


@router.post("/evaluate/{model}", response_model=dict[uuid.UUID, list[StatusLabel]])
async def evaluate_bulk(
    model: str, body: BulkEvaluateRequest, db: DbSession, _: CurrentUser
) -> dict[uuid.UUID, list[StatusLabel]]:
    if model not in engine.MODEL_MAP:
        raise HTTPException(status_code=404, detail="Unsupported model")
    cls = engine.MODEL_MAP[model]
    rules = await _rules_for(db, model)
    if not rules or not body.ids:
        return {}
    stmt = select(cls).where(cls.id.in_(body.ids))
    if hasattr(cls, "deleted"):
        stmt = stmt.where(cls.deleted.is_(False))
    records = (await db.scalars(stmt)).all()
    return {
        rec.id: [StatusLabel(**lbl) for lbl in engine.evaluate(rec, rules)]
        for rec in records
    }
