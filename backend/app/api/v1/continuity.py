"""Business Continuity Management API — plans, 5W playbook tasks, recurring tests."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.continuity import ContinuityPlan, ContinuityTask, ContinuityTest
from app.schemas.common import Page
from app.schemas.continuity import (
    PlanCreate,
    PlanRead,
    PlanUpdate,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    TestCreate,
    TestRead,
    TestUpdate,
)
from app.services.refs import next_reference
from app.services import audit
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/continuity-plans", tags=["continuity"])


async def _load(db, plan_id: uuid.UUID) -> ContinuityPlan:
    obj = await db.scalar(
        select(ContinuityPlan).where(ContinuityPlan.id == plan_id, ContinuityPlan.deleted.is_(False))
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return obj


async def _fresh(db, plan_id: uuid.UUID) -> ContinuityPlan:
    return await db.scalar(
        select(ContinuityPlan)
        .where(ContinuityPlan.id == plan_id)
        .execution_options(populate_existing=True)
    )


async def _next_ref(db) -> str:
    return await next_reference(db, ContinuityPlan, "BCP")


async def _task_or_404(db, plan_id, task_id) -> ContinuityTask:
    obj = await db.scalar(
        select(ContinuityTask).where(
            ContinuityTask.id == task_id, ContinuityTask.plan_id == plan_id
        )
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return obj


async def _test_or_404(db, plan_id, test_id) -> ContinuityTest:
    obj = await db.scalar(
        select(ContinuityTest).where(
            ContinuityTest.id == test_id, ContinuityTest.plan_id == plan_id
        )
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    return obj


@router.get("", response_model=Page[PlanRead], dependencies=[Depends(require("bcp:read"))])
async def list_plans(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PlanRead]:
    stmt = select(ContinuityPlan).where(ContinuityPlan.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(ContinuityPlan.name).limit(limit).offset(offset))
    ).all()
    return Page(items=[PlanRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=PlanRead, status_code=201, dependencies=[Depends(require("bcp:write"))])
async def create_plan(body: PlanCreate, db: DbSession, user: CurrentUser) -> PlanRead:
    obj = ContinuityPlan(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db)
    obj.next_test_date = next_review_date(obj.test_frequency)
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="continuity_plan", entity_id=obj.id,
        summary=f"Created continuity plan {obj.reference}: {obj.name}",
    )
    return PlanRead.model_validate(await _fresh(db, obj.id))


@router.get("/{plan_id}", response_model=PlanRead, dependencies=[Depends(require("bcp:read"))])
async def get_plan(plan_id: uuid.UUID, db: DbSession) -> PlanRead:
    return PlanRead.model_validate(await _load(db, plan_id))


@router.patch("/{plan_id}", response_model=PlanRead, dependencies=[Depends(require("bcp:write"))])
async def update_plan(plan_id: uuid.UUID, body: PlanUpdate, db: DbSession) -> PlanRead:
    obj = await _load(db, plan_id)
    data = body.model_dump(exclude_unset=True)
    for f, v in data.items():
        setattr(obj, f, v)
    if "test_frequency" in data:
        obj.next_test_date = next_review_date(obj.test_frequency, obj.last_test_date)
    await db.flush()
    return PlanRead.model_validate(await _fresh(db, obj.id))


@router.delete("/{plan_id}", status_code=204, dependencies=[Depends(require("bcp:write"))])
async def delete_plan(plan_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, plan_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit.record(db, actor=user, action="delete", entity_type="continuity_plan",
                         entity_id=obj.id, summary=f"Archived continuity plan {obj.reference}")


# ----------------------------------------------------------------- 5W tasks
@router.get(
    "/{plan_id}/tasks", response_model=list[TaskRead], dependencies=[Depends(require("bcp:read"))]
)
async def list_tasks(plan_id: uuid.UUID, db: DbSession) -> list[TaskRead]:
    plan = await _load(db, plan_id)
    return [TaskRead.model_validate(t) for t in plan.tasks]


@router.post("/{plan_id}/tasks", response_model=PlanRead, status_code=201, dependencies=[Depends(require("bcp:write"))])
async def add_task(plan_id: uuid.UUID, body: TaskCreate, db: DbSession, user: CurrentUser) -> PlanRead:
    await _load(db, plan_id)
    db.add(ContinuityTask(tenant_id=user.tenant_id, plan_id=plan_id, **body.model_dump()))
    await db.flush()
    return PlanRead.model_validate(await _fresh(db, plan_id))


@router.patch("/{plan_id}/tasks/{task_id}", response_model=PlanRead, dependencies=[Depends(require("bcp:write"))])
async def update_task(plan_id: uuid.UUID, task_id: uuid.UUID, body: TaskUpdate, db: DbSession) -> PlanRead:
    task = await _task_or_404(db, plan_id, task_id)
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(task, f, v)
    await db.flush()
    return PlanRead.model_validate(await _fresh(db, plan_id))


@router.delete("/{plan_id}/tasks/{task_id}", status_code=204, dependencies=[Depends(require("bcp:write"))])
async def delete_task(plan_id: uuid.UUID, task_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _task_or_404(db, plan_id, task_id))


# -------------------------------------------------------------- test cycle
@router.post(
    "/{plan_id}/tests",
    response_model=PlanRead,
    status_code=201,
    dependencies=[Depends(require("bcp:write"))],
    summary="Record a continuity test/exercise and reschedule the next one",
)
async def record_test(plan_id: uuid.UUID, body: TestCreate, db: DbSession, user: CurrentUser) -> PlanRead:
    plan = await _load(db, plan_id)
    conducted = body.conducted_date or date.today()
    db.add(ContinuityTest(tenant_id=user.tenant_id, plan_id=plan_id,
                          **{**body.model_dump(), "conducted_date": conducted}))
    plan.last_test_date = conducted
    plan.next_test_date = next_review_date(plan.test_frequency, conducted)
    await db.flush()
    await audit.record(
        db, actor=user, action="test", entity_type="continuity_plan", entity_id=plan.id,
        summary=f"Recorded {body.result.value} continuity test for {plan.reference}",
    )
    return PlanRead.model_validate(await _fresh(db, plan_id))


@router.get(
    "/{plan_id}/tests", response_model=list[TestRead], dependencies=[Depends(require("bcp:read"))]
)
async def list_tests(plan_id: uuid.UUID, db: DbSession) -> list[TestRead]:
    plan = await _load(db, plan_id)
    return [TestRead.model_validate(t) for t in plan.tests]


@router.patch(
    "/{plan_id}/tests/{test_id}", response_model=PlanRead, dependencies=[Depends(require("bcp:write"))]
)
async def update_test(plan_id: uuid.UUID, test_id: uuid.UUID, body: TestUpdate, db: DbSession) -> PlanRead:
    test = await _test_or_404(db, plan_id, test_id)
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(test, f, v)
    await db.flush()
    return PlanRead.model_validate(await _fresh(db, plan_id))


@router.delete(
    "/{plan_id}/tests/{test_id}", status_code=204, dependencies=[Depends(require("bcp:write"))]
)
async def delete_test(plan_id: uuid.UUID, test_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _test_or_404(db, plan_id, test_id))
