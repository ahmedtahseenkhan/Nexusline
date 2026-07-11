"""Delegation of Authority (DoA) + Maker-Checker configuration API.

Two governance registers:

* ``/authority-matrix`` — the delegation-of-authority matrix (who may approve what,
  by amount band / approval level).
* ``/dual-control-rules`` — the maker-checker (four-eyes) configuration registry per
  module action.

Both are configuration/registry surfaces. Runtime enforcement is a later
cross-cutting task.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.authority import (
    AuthorityCategory,
    AuthorityMatrix,
    AuthorityStatus,
    DualControlRule,
)
from app.schemas.authority import (
    AuthorityMatrixCreate,
    AuthorityMatrixRead,
    AuthorityMatrixUpdate,
    AuthoritySummary,
    DualControlRuleCreate,
    DualControlRuleRead,
    DualControlRuleUpdate,
)
from app.schemas.common import Page
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["delegation of authority"])

_READ = Depends(require("authority:read"))
_WRITE = Depends(require("authority:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ==================================================== delegation-of-authority matrix ===
_MATRIX_SORTABLE = {
    "reference": AuthorityMatrix.reference,
    "activity": AuthorityMatrix.activity,
    "category": AuthorityMatrix.category,
    "role_title": AuthorityMatrix.role_title,
    "approval_level": AuthorityMatrix.approval_level,
    "amount_from": AuthorityMatrix.amount_from,
    "status": AuthorityMatrix.status,
    "effective_date": AuthorityMatrix.effective_date,
    "created_at": AuthorityMatrix.created_at,
}


@router.get("/authority-matrix", response_model=Page[AuthorityMatrixRead], dependencies=[_READ])
async def list_authority_matrix(
    db: DbSession,
    search: str | None = None,
    category: AuthorityCategory | None = None,
    matrix_status: Annotated[AuthorityStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuthorityMatrixRead]:
    stmt = select(AuthorityMatrix).where(AuthorityMatrix.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            AuthorityMatrix.activity.ilike(like),
            AuthorityMatrix.reference.ilike(like),
            AuthorityMatrix.role_title.ilike(like),
            AuthorityMatrix.description.ilike(like),
        ))
    if category is not None:
        stmt = stmt.where(AuthorityMatrix.category == category)
    if matrix_status is not None:
        stmt = stmt.where(AuthorityMatrix.status == matrix_status)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _MATRIX_SORTABLE, default=AuthorityMatrix.approval_level)
    else:
        stmt = stmt.order_by(AuthorityMatrix.approval_level, AuthorityMatrix.activity)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[AuthorityMatrixRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/authority-matrix", response_model=AuthorityMatrixRead, status_code=201, dependencies=[_WRITE])
async def create_authority_matrix(body: AuthorityMatrixCreate, db: DbSession, user: CurrentUser) -> AuthorityMatrixRead:
    obj = AuthorityMatrix(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, AuthorityMatrix, "DOA")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="authority_matrix",
                           entity_id=obj.id, summary=f"Added authority line {obj.reference}: {obj.activity}")
    return AuthorityMatrixRead.model_validate(obj)


@router.get("/authority-matrix/{aid}", response_model=AuthorityMatrixRead, dependencies=[_READ])
async def get_authority_matrix(aid: uuid.UUID, db: DbSession) -> AuthorityMatrixRead:
    return AuthorityMatrixRead.model_validate(await _get(db, AuthorityMatrix, aid, "Authority line"))


@router.patch("/authority-matrix/{aid}", response_model=AuthorityMatrixRead, dependencies=[_WRITE])
async def update_authority_matrix(aid: uuid.UUID, body: AuthorityMatrixUpdate, db: DbSession) -> AuthorityMatrixRead:
    obj = await _get(db, AuthorityMatrix, aid, "Authority line")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return AuthorityMatrixRead.model_validate(obj)


@router.delete("/authority-matrix/{aid}", status_code=204, dependencies=[_WRITE])
async def delete_authority_matrix(aid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, AuthorityMatrix, aid, "Authority line")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================== maker-checker / dual-control rules ===
_RULE_SORTABLE = {
    "reference": DualControlRule.reference,
    "module": DualControlRule.module,
    "action": DualControlRule.action,
    "maker_role": DualControlRule.maker_role,
    "checker_role": DualControlRule.checker_role,
    "threshold_amount": DualControlRule.threshold_amount,
    "status": DualControlRule.status,
    "created_at": DualControlRule.created_at,
}


@router.get("/dual-control-rules", response_model=Page[DualControlRuleRead], dependencies=[_READ])
async def list_dual_control_rules(
    db: DbSession,
    search: str | None = None,
    module: str | None = None,
    enabled: bool | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DualControlRuleRead]:
    stmt = select(DualControlRule).where(DualControlRule.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            DualControlRule.module.ilike(like),
            DualControlRule.action.ilike(like),
            DualControlRule.reference.ilike(like),
            DualControlRule.maker_role.ilike(like),
            DualControlRule.checker_role.ilike(like),
            DualControlRule.description.ilike(like),
        ))
    if module:
        stmt = stmt.where(DualControlRule.module == module)
    if enabled is not None:
        stmt = stmt.where(DualControlRule.enabled.is_(enabled))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _RULE_SORTABLE, default=DualControlRule.module)
    else:
        stmt = stmt.order_by(DualControlRule.module, DualControlRule.action)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[DualControlRuleRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/dual-control-rules", response_model=DualControlRuleRead, status_code=201, dependencies=[_WRITE])
async def create_dual_control_rule(body: DualControlRuleCreate, db: DbSession, user: CurrentUser) -> DualControlRuleRead:
    obj = DualControlRule(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, DualControlRule, "MC")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="dual_control_rule",
                           entity_id=obj.id, summary=f"Added maker-checker rule {obj.reference}: {obj.module}/{obj.action}")
    return DualControlRuleRead.model_validate(obj)


@router.get("/dual-control-rules/{rid}", response_model=DualControlRuleRead, dependencies=[_READ])
async def get_dual_control_rule(rid: uuid.UUID, db: DbSession) -> DualControlRuleRead:
    return DualControlRuleRead.model_validate(await _get(db, DualControlRule, rid, "Dual-control rule"))


@router.patch("/dual-control-rules/{rid}", response_model=DualControlRuleRead, dependencies=[_WRITE])
async def update_dual_control_rule(rid: uuid.UUID, body: DualControlRuleUpdate, db: DbSession) -> DualControlRuleRead:
    obj = await _get(db, DualControlRule, rid, "Dual-control rule")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return DualControlRuleRead.model_validate(obj)


@router.delete("/dual-control-rules/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_dual_control_rule(rid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, DualControlRule, rid, "Dual-control rule")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================================== summary ===
@router.get("/authority-summary", response_model=AuthoritySummary, dependencies=[_READ],
            summary="Delegation-of-authority + maker-checker roll-up for the module dashboard")
async def authority_summary(db: DbSession) -> AuthoritySummary:
    matrix = (await db.scalars(select(AuthorityMatrix).where(AuthorityMatrix.deleted.is_(False)))).all()
    by_category: dict[str, int] = defaultdict(int)
    by_level: dict[str, int] = defaultdict(int)
    for m in matrix:
        by_category[m.category.value] += 1
        by_level[str(m.approval_level)] += 1

    rules = (await db.scalars(select(DualControlRule).where(DualControlRule.deleted.is_(False)))).all()
    enabled_count = sum(1 for r in rules if r.enabled)
    modules_covered = len({r.module for r in rules if r.module})

    return AuthoritySummary(
        matrix_total=len(matrix),
        matrix_by_category=dict(sorted(by_category.items())),
        matrix_by_level=dict(sorted(by_level.items(), key=lambda kv: int(kv[0]))),
        categories_covered=len(by_category),
        dual_control_total=len(rules),
        dual_control_enabled=enabled_count,
        modules_covered=modules_covered,
    )
