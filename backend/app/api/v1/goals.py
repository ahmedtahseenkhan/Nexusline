"""Strategy & Goals API — goals with a recurring pass/fail audit cycle."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.goal import Goal, GoalAudit
from app.models.policy import Policy
from app.models.project import Project
from app.models.risk import Risk
from app.schemas.common import Page
from app.schemas.goal import GoalAuditCreate, GoalCreate, GoalRead, GoalUpdate
from app.services import audit as audit_log
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/goals", tags=["goals"])


async def _load(db, goal_id: uuid.UUID) -> Goal:
    obj = await db.scalar(select(Goal).where(Goal.id == goal_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return obj


async def _load_fresh(db, goal_id: uuid.UUID) -> Goal:
    # populate_existing forces selectin relationships (audits/links) to reload even when
    # the instance is already cached in the identity map (e.g. just modified this txn).
    return await db.scalar(
        select(Goal).where(Goal.id == goal_id).execution_options(populate_existing=True)
    )


async def _resolve(db, model, ids: Sequence[uuid.UUID]) -> list:
    if not ids:
        return []
    rows = (await db.scalars(select(model).where(model.id.in_(ids)))).all()
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown {model.__name__.lower()} id(s): {sorted(map(str, missing))}",
        )
    return list(rows)


async def _apply_links(db, obj: Goal, data: dict) -> None:
    if data.get("risk_ids") is not None:
        obj.risks = await _resolve(db, Risk, data["risk_ids"])
    if data.get("project_ids") is not None:
        obj.projects = await _resolve(db, Project, data["project_ids"])
    if data.get("policy_ids") is not None:
        obj.policies = await _resolve(db, Policy, data["policy_ids"])


async def _next_ref(db) -> str:
    count = await db.scalar(select(func.count()).select_from(Goal)) or 0
    return f"GOAL-{count + 1:03d}"


@router.get("", response_model=Page[GoalRead], dependencies=[Depends(require("goal:read"))])
async def list_goals(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[GoalRead]:
    stmt = select(Goal).where(Goal.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(Goal.name).limit(limit).offset(offset))
    ).all()
    return Page(items=[GoalRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=GoalRead, status_code=201, dependencies=[Depends(require("goal:write"))])
async def create_goal(body: GoalCreate, db: DbSession, user: CurrentUser) -> GoalRead:
    data = body.model_dump(exclude={"risk_ids", "project_ids", "policy_ids"})
    obj = Goal(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db)
    obj.next_audit_date = next_review_date(obj.audit_frequency)
    await _apply_links(db, obj, body.model_dump())
    db.add(obj)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="goal", entity_id=obj.id,
        summary=f"Created goal {obj.reference}: {obj.name}",
    )
    return GoalRead.model_validate(await _load(db, obj.id))


@router.get("/{goal_id}", response_model=GoalRead, dependencies=[Depends(require("goal:read"))])
async def get_goal(goal_id: uuid.UUID, db: DbSession) -> GoalRead:
    return GoalRead.model_validate(await _load(db, goal_id))


@router.patch("/{goal_id}", response_model=GoalRead, dependencies=[Depends(require("goal:write"))])
async def update_goal(goal_id: uuid.UUID, body: GoalUpdate, db: DbSession) -> GoalRead:
    obj = await _load(db, goal_id)
    full = body.model_dump(exclude_unset=True)
    await _apply_links(db, obj, full)
    data = body.model_dump(exclude_unset=True, exclude={"risk_ids", "project_ids", "policy_ids"})
    for f, v in data.items():
        setattr(obj, f, v)
    if "audit_frequency" in data:
        obj.next_audit_date = next_review_date(obj.audit_frequency, obj.last_audit_date)
    await db.flush()
    return GoalRead.model_validate(await _load(db, obj.id))


@router.post(
    "/{goal_id}/audits",
    response_model=GoalRead,
    status_code=201,
    dependencies=[Depends(require("goal:write"))],
    summary="Record a goal audit (pass/fail) and reschedule the next one",
)
async def record_audit(
    goal_id: uuid.UUID, body: GoalAuditCreate, db: DbSession, user: CurrentUser
) -> GoalRead:
    goal = await _load(db, goal_id)
    conducted = body.conducted_date or date.today()
    db.add(GoalAudit(tenant_id=user.tenant_id, goal_id=goal_id, **body.model_dump()))
    goal.last_audit_date = conducted
    goal.next_audit_date = next_review_date(goal.audit_frequency, conducted)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="audit", entity_type="goal", entity_id=goal.id,
        summary=f"Recorded {body.result.value} audit for goal {goal.reference}",
    )
    return GoalRead.model_validate(await _load_fresh(db, goal.id))


@router.delete("/{goal_id}", status_code=204, dependencies=[Depends(require("goal:write"))])
async def delete_goal(goal_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, goal_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
