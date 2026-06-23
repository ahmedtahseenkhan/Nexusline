"""Project Management API — remediation projects, tasks/milestones and expenses."""
from __future__ import annotations

import uuid
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.control import Control
from app.models.enums import ProjectStatus
from app.models.policy import Policy
from app.models.project import Project, ProjectExpense, ProjectTask
from app.models.risk import Risk
from app.schemas.common import Page
from app.schemas.project import (
    ExpenseCreate,
    ExpenseRead,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from app.services import audit

router = APIRouter(prefix="/projects", tags=["projects"])


async def _load(db, project_id: uuid.UUID) -> Project:
    obj = await db.scalar(select(Project).where(Project.id == project_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return obj


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


async def _apply_links(db, obj: Project, data: dict) -> None:
    if data.get("risk_ids") is not None:
        obj.risks = await _resolve(db, Risk, data["risk_ids"])
    if data.get("control_ids") is not None:
        obj.controls = await _resolve(db, Control, data["control_ids"])
    if data.get("policy_ids") is not None:
        obj.policies = await _resolve(db, Policy, data["policy_ids"])


async def _next_ref(db) -> str:
    count = await db.scalar(select(func.count()).select_from(Project)) or 0
    return f"PRJ-{count + 1:03d}"


async def _task_or_404(db, project_id, task_id) -> ProjectTask:
    obj = await db.scalar(
        select(ProjectTask).where(ProjectTask.id == task_id, ProjectTask.project_id == project_id)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return obj


# ------------------------------------------------------------------- projects
@router.get("", response_model=Page[ProjectRead], dependencies=[Depends(require("project:read"))])
async def list_projects(
    db: DbSession,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProjectRead]:
    stmt: Select = select(Project).where(Project.deleted.is_(False))
    if status_filter is not None:
        stmt = stmt.where(Project.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(Project.created_at.desc()).limit(limit).offset(offset))
    ).all()
    return Page(items=[ProjectRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ProjectRead, status_code=201, dependencies=[Depends(require("project:write"))])
async def create_project(body: ProjectCreate, db: DbSession, user: CurrentUser) -> ProjectRead:
    data = body.model_dump(exclude={"risk_ids", "control_ids", "policy_ids"})
    obj = Project(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db)
    await _apply_links(db, obj, body.model_dump())
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="project", entity_id=obj.id,
        summary=f"Created project {obj.reference}: {obj.title}",
    )
    return ProjectRead.model_validate(await _load(db, obj.id))


@router.get("/{project_id}", response_model=ProjectRead, dependencies=[Depends(require("project:read"))])
async def get_project(project_id: uuid.UUID, db: DbSession) -> ProjectRead:
    return ProjectRead.model_validate(await _load(db, project_id))


@router.patch("/{project_id}", response_model=ProjectRead, dependencies=[Depends(require("project:write"))])
async def update_project(project_id: uuid.UUID, body: ProjectUpdate, db: DbSession) -> ProjectRead:
    obj = await _load(db, project_id)
    full = body.model_dump(exclude_unset=True)
    await _apply_links(db, obj, full)
    for f, v in body.model_dump(exclude_unset=True, exclude={"risk_ids", "control_ids", "policy_ids"}).items():
        setattr(obj, f, v)
    await db.flush()
    return ProjectRead.model_validate(await _load(db, obj.id))


@router.delete("/{project_id}", status_code=204, dependencies=[Depends(require("project:write"))])
async def delete_project(project_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, project_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)


# ---------------------------------------------------------------------- tasks
@router.post(
    "/{project_id}/tasks", response_model=ProjectRead, status_code=201,
    dependencies=[Depends(require("project:write"))],
)
async def add_task(project_id: uuid.UUID, body: TaskCreate, db: DbSession, user: CurrentUser) -> ProjectRead:
    await _load(db, project_id)
    db.add(ProjectTask(tenant_id=user.tenant_id, project_id=project_id, **body.model_dump()))
    await db.flush()
    return ProjectRead.model_validate(await _load(db, project_id))


@router.patch(
    "/{project_id}/tasks/{task_id}", response_model=ProjectRead,
    dependencies=[Depends(require("project:write"))],
)
async def update_task(
    project_id: uuid.UUID, task_id: uuid.UUID, body: TaskUpdate, db: DbSession
) -> ProjectRead:
    task = await _task_or_404(db, project_id, task_id)
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(task, f, v)
    await db.flush()
    return ProjectRead.model_validate(await _load(db, project_id))


@router.delete(
    "/{project_id}/tasks/{task_id}", status_code=204,
    dependencies=[Depends(require("project:write"))],
)
async def delete_task(project_id: uuid.UUID, task_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _task_or_404(db, project_id, task_id))


# ------------------------------------------------------------------- expenses
@router.post(
    "/{project_id}/expenses", response_model=ProjectRead, status_code=201,
    dependencies=[Depends(require("project:write"))],
)
async def add_expense(project_id: uuid.UUID, body: ExpenseCreate, db: DbSession, user: CurrentUser) -> ProjectRead:
    await _load(db, project_id)
    db.add(ProjectExpense(tenant_id=user.tenant_id, project_id=project_id, **body.model_dump()))
    await db.flush()
    return ProjectRead.model_validate(await _load(db, project_id))


@router.delete(
    "/{project_id}/expenses/{expense_id}", status_code=204,
    dependencies=[Depends(require("project:write"))],
)
async def delete_expense(project_id: uuid.UUID, expense_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(
        select(ProjectExpense).where(
            ProjectExpense.id == expense_id, ProjectExpense.project_id == project_id
        )
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    await db.delete(obj)
