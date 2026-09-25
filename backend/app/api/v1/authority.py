"""Delegation of Authority (DoA) + Maker-Checker configuration API.

Two governance registers:

* ``/authority-matrix`` — the delegation-of-authority matrix (who may approve what,
  by amount band / approval level).
* ``/dual-control-rules`` — the maker-checker (four-eyes) configuration registry per
  module action.

Enforcement lives in ``services/dual_control.py``: the rules decide four-eyes at every
decision listed by :func:`dual_control.enforced_keys` (``GET /dual-control-rules/keys``),
and only those keys may be configured. Relaxing a rule needs an administrator
(:func:`dual_control.relaxations`). Authority-matrix limits are checked by
:func:`dual_control.enforce_authority_limit` where a decision carries an amount;
``GET /authority-matrix/mandate`` answers "may I approve this amount?" for the UI.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.config import settings
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
from app.services import dual_control

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


class MandateCheck(BaseModel):
    category: AuthorityCategory
    amount: float
    currency: str
    allowed: bool
    reason: str = ""
    lines: list[AuthorityMatrixRead] = []


@router.get("/authority-matrix/mandate", response_model=MandateCheck, dependencies=[_READ],
            summary="May the current user approve this amount in this category?")
async def check_mandate(
    db: DbSession, user: CurrentUser, category: AuthorityCategory,
    amount: Annotated[float, Query(ge=0)], currency: str = "",
) -> MandateCheck:
    """The same answer :func:`dual_control.enforce_authority_limit` gives a decision
    that carries an amount, with the matrix lines that cover the amount."""
    reason = dual_control.mandate_refusal(
        await dual_control.authority_lines(db, category.value), amount=amount,
        role_names=user.role_names, currency=currency,
    )
    rows = (await db.scalars(
        select(AuthorityMatrix).where(
            AuthorityMatrix.deleted.is_(False), AuthorityMatrix.category == category,
            AuthorityMatrix.status == AuthorityStatus.active, AuthorityMatrix.amount_from <= amount,
            or_(AuthorityMatrix.amount_to.is_(None), AuthorityMatrix.amount_to >= amount),
        ).order_by(AuthorityMatrix.approval_level)
    )).all()
    return MandateCheck(category=category, amount=amount, currency=currency, allowed=reason is None,
                        reason=reason or "", lines=[AuthorityMatrixRead.model_validate(r) for r in rows])


def _band_or_422(amount_from, amount_to) -> None:
    if amount_to is not None and float(amount_to) < float(amount_from or 0):
        raise HTTPException(
            status_code=422,
            detail="amount_to: the upper limit is below the lower limit. Leave it blank for "
                   "no upper limit.",
        )


@router.post("/authority-matrix", response_model=AuthorityMatrixRead, status_code=201, dependencies=[_WRITE])
async def create_authority_matrix(body: AuthorityMatrixCreate, db: DbSession, user: CurrentUser) -> AuthorityMatrixRead:
    _band_or_422(body.amount_from, body.amount_to)
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
async def update_authority_matrix(
    aid: uuid.UUID, body: AuthorityMatrixUpdate, db: DbSession, user: CurrentUser
) -> AuthorityMatrixRead:
    obj = await _get(db, AuthorityMatrix, aid, "Authority line")
    # The authority matrix defines who may approve what and up to which limit. Letting
    # one person both write and revise a line would let them raise their own limit.
    await dual_control.enforce_record_maker_checker(
        db, module="authority", action="update", entity_type="authority_matrix",
        entity_id=obj.id, checker_id=user.id, subject="authority-matrix change",
    )
    data = body.model_dump(exclude_unset=True)
    # A PATCH of one bound is checked against the other as stored.
    _band_or_422(data.get("amount_from", obj.amount_from),
                 data["amount_to"] if "amount_to" in data else obj.amount_to)
    changes = {k: {"from": _plain(getattr(obj, k)), "to": _plain(v)}
               for k, v in data.items() if getattr(obj, k) != v}
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if changes:
        await audit_log.record(
            db, actor=user, action="update", entity_type="authority_matrix", entity_id=obj.id,
            summary=f"Updated authority line {obj.reference}: {obj.activity} ({', '.join(changes)})"[:500],
            changes=changes,
        )
    return AuthorityMatrixRead.model_validate(obj)


@router.delete("/authority-matrix/{aid}", status_code=204, dependencies=[_WRITE])
async def delete_authority_matrix(aid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _get(db, AuthorityMatrix, aid, "Authority line")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    # Removing a mandate changes who may approve what: on the trail like any amendment.
    await audit_log.record(
        db, actor=user, action="delete", entity_type="authority_matrix", entity_id=obj.id,
        summary=f"Deleted authority line {obj.reference}: {obj.activity} "
                f"({obj.role_title or 'no role'}, level {obj.approval_level}, {obj.amount_range_label})"[:500],
    )


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
    return Page(items=[_rule_read(r) for r in rows], total=total, limit=limit, offset=offset)


class EnforcedKeyRead(BaseModel):
    module: str
    action: str
    label: str
    group: str


@router.get("/dual-control-rules/keys", response_model=list[EnforcedKeyRead], dependencies=[_READ],
            summary="The (module, action) decisions a maker-checker rule can govern")
async def list_dual_control_keys() -> list[EnforcedKeyRead]:
    return [EnforcedKeyRead(module=k.module, action=k.action, label=k.label, group=k.group)
            for k in dual_control.enforced_keys()]


def _rule_read(obj: DualControlRule) -> DualControlRuleRead:
    out = DualControlRuleRead.model_validate(obj)
    out.enforced = dual_control.is_enforced_key(obj.module, obj.action)
    return out


def _key_or_422(module: str, action: str) -> None:
    if not dual_control.is_enforced_key(module, action):
        raise HTTPException(status_code=422, detail=dual_control.unknown_key_message(module, action))


def _relax_or_403(reasons: list[str], user) -> None:
    refusal = dual_control.relax_refusal(reasons, user.permission_codes)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)


@router.post("/dual-control-rules", response_model=DualControlRuleRead, status_code=201, dependencies=[_WRITE])
async def create_dual_control_rule(body: DualControlRuleCreate, db: DbSession, user: CurrentUser) -> DualControlRuleRead:
    data = body.model_dump()
    data["module"], data["action"] = data["module"].strip(), data["action"].strip()
    _key_or_422(data["module"], data["action"])
    # The newest rule for a key governs it, so a new rule that exempts an action (or
    # adds a threshold) relaxes whatever decides it today.
    reasons = dual_control.relaxations(
        before=None, after=data, global_switch=settings.enforce_segregation_of_duties,
        superseded=await dual_control.find_rule(db, data["module"], data["action"]),
    )
    _relax_or_403(reasons, user)
    obj = DualControlRule(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, DualControlRule, "MC")
    db.add(obj)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="dual_control_rule", entity_id=obj.id,
        summary=(f"Added maker-checker rule {obj.reference}: {obj.module}/{obj.action}"
                 + (f" — relaxes four-eyes ({'; '.join(reasons)})" if reasons else ""))[:500],
        changes={"relaxed": reasons} if reasons else None,
    )
    return _rule_read(obj)


@router.get("/dual-control-rules/{rid}", response_model=DualControlRuleRead, dependencies=[_READ])
async def get_dual_control_rule(rid: uuid.UUID, db: DbSession) -> DualControlRuleRead:
    return _rule_read(await _get(db, DualControlRule, rid, "Dual-control rule"))


@router.patch("/dual-control-rules/{rid}", response_model=DualControlRuleRead, dependencies=[_WRITE])
async def update_dual_control_rule(
    rid: uuid.UUID, body: DualControlRuleUpdate, db: DbSession, user: CurrentUser
) -> DualControlRuleRead:
    obj = await _get(db, DualControlRule, rid, "Dual-control rule")
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items()
            if v is not None or k == "threshold_amount"}
    for k in ("module", "action"):
        if k in data:
            data[k] = data[k].strip()
    before = {k: getattr(obj, k) for k in (
        "module", "action", "requires_dual_control", "threshold_amount", "enabled", "status")}
    after = {**before, **{k: v for k, v in data.items() if k in before}}
    moved = (after["module"], after["action"]) != (before["module"], before["action"])
    if moved:
        _key_or_422(after["module"], after["action"])
    reasons = dual_control.relaxations(
        before=before, after=after, global_switch=settings.enforce_segregation_of_duties,
        new_key_current=await dual_control.find_rule(db, after["module"], after["action"]) if moved else None,
    )
    _relax_or_403(reasons, user)
    changes = {k: {"from": _plain(getattr(obj, k)), "to": _plain(v)}
               for k, v in data.items() if getattr(obj, k) != v}
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if changes:
        # Loosening four-eyes is exactly what an examiner looks for: every change to a
        # rule is on the trail with its before and after values, and a relaxation says so.
        await audit_log.record(
            db, actor=user, action="update", entity_type="dual_control_rule", entity_id=obj.id,
            summary=(f"{'Relaxed' if reasons else 'Changed'} maker-checker rule {obj.reference}: "
                     f"{obj.module}/{obj.action} "
                     + ", ".join(f"{k.replace('_', ' ')} {c['from']} → {c['to']}" for k, c in changes.items()))[:500],
            changes={**changes, **({"relaxed": reasons} if reasons else {})},
        )
    return _rule_read(obj)


def _plain(value):
    """A JSON-safe value for the audit trail (enums by value, numbers as floats)."""
    value = getattr(value, "value", value)
    return float(value) if hasattr(value, "is_finite") else value


@router.delete("/dual-control-rules/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_dual_control_rule(rid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _get(db, DualControlRule, rid, "Dual-control rule")
    reasons = dual_control.relaxations(before=obj, after=None, global_switch=settings.enforce_segregation_of_duties)
    _relax_or_403(reasons, user)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="delete", entity_type="dual_control_rule", entity_id=obj.id,
        summary=f"Deleted maker-checker rule {obj.reference}: {obj.module}/{obj.action} "
        "(the global segregation-of-duties switch now decides this action)",
        changes={"relaxed": reasons} if reasons else None,
    )


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
