"""Dynamic Status Rules API — manage rules, introspect fields, evaluate records.

A rule is validated against the model's evaluable fields and the operator list when it
is saved, so a rule that could never match is refused rather than stored. Evaluating
labels reads the record, so it needs that record type's read permission; models whose
module the organisation can't use are left out of the listings (and refused outright by
``modules.gate_shared_request``).
"""
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
from app.services import audit as audit_log
from app.services import entity_types
from app.services import modules as module_service
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


async def _usable_models(tenant_id) -> list[str]:
    return [m for m in engine.MODEL_MAP if await module_service.entity_type_usable(m, tenant_id)]


def _check(model: str, field: str | None, operator: str | None) -> None:
    problem = engine.condition_problem(model, field, operator)
    if problem:
        raise HTTPException(status_code=422, detail=problem)


@router.get("/models", response_model=list[str])
async def list_models(user: CurrentUser) -> list[str]:
    return await _usable_models(user.tenant_id)


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
    user: CurrentUser,
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
    else:
        stmt = stmt.where(StatusRule.model.in_(await _usable_models(user.tenant_id)))
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
    _check(body.model, body.field, body.operator)
    obj = StatusRule(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    # Status rules drive how records are labelled across a register — an audited change.
    await audit_log.record(
        db, actor=user, action="create", entity_type="status_rule", entity_id=obj.id,
        summary=f"Added status rule '{obj.label}' on {obj.model}",
    )
    return StatusRuleRead.model_validate(obj)


@router.patch("/{rule_id}", response_model=StatusRuleRead, dependencies=[Depends(require("automation:manage"))])
async def update_rule(
    rule_id: uuid.UUID, body: StatusRuleUpdate, db: DbSession, user: CurrentUser
) -> StatusRuleRead:
    obj = await _load(db, rule_id)
    data = body.model_dump(exclude_unset=True)
    # Re-validate the rule as it will stand — otherwise a PATCH can persist a field or
    # operator that the engine silently treats as "never matches".
    if {"field", "operator"} & data.keys():
        _check(obj.model, data.get("field", obj.field), data.get("operator", obj.operator))
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    await audit_log.record(
        db, actor=user, action="update", entity_type="status_rule", entity_id=obj.id,
        summary=f"Updated status rule '{obj.label}' on {obj.model}", changes=data,
    )
    return StatusRuleRead.model_validate(obj)


@router.delete("/{rule_id}", status_code=204, dependencies=[Depends(require("automation:manage"))])
async def delete_rule(rule_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, rule_id)
    await audit_log.record(
        db, actor=user, action="delete", entity_type="status_rule", entity_id=obj.id,
        summary=f"Deleted status rule '{obj.label}' from {obj.model}",
    )
    await db.delete(obj)


@router.get("/evaluate/{model}/{entity_id}", response_model=list[StatusLabel])
async def evaluate_one(model: str, entity_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[StatusLabel]:
    # A label is derived from the record's fields, so it reads the record.
    entity_types.require_read(user, model)
    if model not in engine.MODEL_MAP:
        # A real record type that status rules don't cover yet has no labels. Every
        # record page asks, so answer "none" rather than 404 on each view.
        return []
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
    model: str, body: BulkEvaluateRequest, db: DbSession, user: CurrentUser
) -> dict[uuid.UUID, list[StatusLabel]]:
    entity_types.require_read(user, model)
    if model not in engine.MODEL_MAP:
        return {}
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
