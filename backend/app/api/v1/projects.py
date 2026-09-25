"""Project Management API — remediation projects, tasks/milestones and expenses.

Remediation projects are how a bank evidences that audit findings and control gaps are
being closed, so their changes are on the activity trail against the project: edits
(including which risks, controls and policies it addresses), tasks and expenses.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.control import Control
from app.models.enums import ProjectStatus
from app.models.policy import Policy
from app.models.project import Project, ProjectExpense, ProjectTask
from app.models.risk import Risk
from app.schemas.common import Page
from app.schemas.project import (
    ExpenseCreate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    TaskCreate,
    TaskUpdate,
)
from app.services.refs import next_reference
from app.services import audit

router = APIRouter(prefix="/projects", tags=["projects"])

_LINKS = {"risk_ids": "risks", "control_ids": "controls", "policy_ids": "policies"}


def _plain(value):
    return getattr(value, "value", value)


def _changes(obj, data: dict) -> dict:
    return {k: {"from": _plain(getattr(obj, k)), "to": _plain(v)}
            for k, v in data.items() if getattr(obj, k) != v}


def _link_labels(items) -> list[str]:
    return sorted(getattr(x, "reference", "") or getattr(x, "title", "") or getattr(x, "name", "") or str(x.id)
                  for x in items)


async def _trail(db, user, project, summary: str, changes: dict | None = None, action: str = "update") -> None:
    await audit.record(db, actor=user, action=action, entity_type="project", entity_id=project.id,
                       summary=summary[:500], changes=changes or None)


async def _load(db, project_id: uuid.UUID) -> Project:
    # populate_existing: a task or expense added in this request is on the project the
    # response reads (it used to come back without it until the next request).
    obj = await db.scalar(
        select(Project).where(Project.id == project_id, Project.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return obj


async def _resolve(db, model, ids: Sequence[uuid.UUID]) -> list:
    if not ids:
        return []
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    rows = (await db.scalars(stmt)).all()
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
    return await next_reference(db, Project, "PRJ")


async def _task_or_404(db, project_id, task_id) -> ProjectTask:
    obj = await db.scalar(
        select(ProjectTask).where(ProjectTask.id == task_id, ProjectTask.project_id == project_id)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return obj


# ------------------------------------------------------------------- projects
_PROJECT_SORTABLE = {
    "reference": Project.reference,
    "title": Project.title,
    "status": Project.status,
    "owner": Project.owner,
    "start_date": Project.start_date,
    "deadline": Project.deadline,
    "created_at": Project.created_at,
}


@router.get("", response_model=Page[ProjectRead], dependencies=[Depends(require("project:read"))])
async def list_projects(
    db: DbSession,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProjectRead]:
    stmt: Select = select(Project).where(Project.deleted.is_(False))
    if status_filter is not None:
        stmt = stmt.where(Project.status == status_filter)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Project.title.ilike(like) | Project.reference.ilike(like))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _PROJECT_SORTABLE, default=Project.created_at)
    else:
        stmt = stmt.order_by(Project.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
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
async def update_project(project_id: uuid.UUID, body: ProjectUpdate, db: DbSession, user: CurrentUser) -> ProjectRead:
    obj = await _load(db, project_id)
    full = body.model_dump(exclude_unset=True)
    before_links = {attr: _link_labels(getattr(obj, attr)) for key, attr in _LINKS.items() if full.get(key) is not None}
    await _apply_links(db, obj, full)
    fields = {k: v for k, v in body.model_dump(exclude_unset=True, exclude=set(_LINKS)).items()
              if v is not None or k in ("start_date", "deadline", "budget")}
    changes = _changes(obj, fields)
    for f, v in fields.items():
        setattr(obj, f, v)
    for attr, before in before_links.items():
        after = _link_labels(getattr(obj, attr))
        if after != before:
            changes[attr] = {"from": before, "to": after}
    await db.flush()
    if changes:
        await _trail(db, user, obj, f"Updated project {obj.reference}: {', '.join(changes)}", changes)
    return ProjectRead.model_validate(await _load(db, obj.id))


@router.delete("/{project_id}", status_code=204, dependencies=[Depends(require("project:write"))])
async def delete_project(project_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, project_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit.record(db, actor=user, action="delete", entity_type="project",
                       entity_id=obj.id, summary=f"Archived project {obj.reference}: {obj.title}")


# ---------------------------------------------------------------------- tasks
@router.post(
    "/{project_id}/tasks", response_model=ProjectRead, status_code=201,
    dependencies=[Depends(require("project:write"))],
)
async def add_task(project_id: uuid.UUID, body: TaskCreate, db: DbSession, user: CurrentUser) -> ProjectRead:
    project = await _load(db, project_id)
    task = ProjectTask(tenant_id=user.tenant_id, project_id=project_id, **body.model_dump())
    db.add(task)
    await db.flush()
    await _trail(db, user, project, f"Added task '{task.title}' to project {project.reference}",
                 {"task": task.title, "due_date": task.due_date, "assignee": task.assignee})
    return ProjectRead.model_validate(await _load(db, project_id))


@router.patch(
    "/{project_id}/tasks/{task_id}", response_model=ProjectRead,
    dependencies=[Depends(require("project:write"))],
)
async def update_task(
    project_id: uuid.UUID, task_id: uuid.UUID, body: TaskUpdate, db: DbSession, user: CurrentUser
) -> ProjectRead:
    project = await _load(db, project_id)
    task = await _task_or_404(db, project_id, task_id)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "due_date"}
    changes = _changes(task, data)
    for f, v in data.items():
        setattr(task, f, v)
    await db.flush()
    if changes:
        await _trail(db, user, project, f"Updated task '{task.title}' on project {project.reference}: "
                                        f"{', '.join(changes)}", {f"task.{k}": v for k, v in changes.items()})
    return ProjectRead.model_validate(await _load(db, project_id))


@router.delete(
    "/{project_id}/tasks/{task_id}", status_code=204,
    dependencies=[Depends(require("project:write"))],
)
async def delete_task(project_id: uuid.UUID, task_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    project = await _load(db, project_id)
    task = await _task_or_404(db, project_id, task_id)
    title, done = task.title, task.completion
    await db.delete(task)
    await db.flush()
    await _trail(db, user, project, f"Removed task '{title}' ({done}% complete) from project {project.reference}",
                 {"task": title})


# ------------------------------------------------------------------- expenses
@router.post(
    "/{project_id}/expenses", response_model=ProjectRead, status_code=201,
    dependencies=[Depends(require("project:write"))],
)
async def add_expense(project_id: uuid.UUID, body: ExpenseCreate, db: DbSession, user: CurrentUser) -> ProjectRead:
    project = await _load(db, project_id)
    expense = ProjectExpense(tenant_id=user.tenant_id, project_id=project_id, **body.model_dump())
    db.add(expense)
    await db.flush()
    await _trail(db, user, project, f"Recorded an expense of {expense.amount:,.2f} on project {project.reference}"
                                    + (f": {expense.description}" if expense.description else ""),
                 {"expense": expense.amount, "description": expense.description, "expense_date": expense.expense_date})
    return ProjectRead.model_validate(await _load(db, project_id))


@router.delete(
    "/{project_id}/expenses/{expense_id}", status_code=204,
    dependencies=[Depends(require("project:write"))],
)
async def delete_expense(project_id: uuid.UUID, expense_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    project = await _load(db, project_id)
    obj = await db.scalar(
        select(ProjectExpense).where(
            ProjectExpense.id == expense_id, ProjectExpense.project_id == project_id
        )
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    amount, description = obj.amount, obj.description
    await db.delete(obj)
    await db.flush()
    await _trail(db, user, project, f"Removed an expense of {amount:,.2f} from project {project.reference}"
                                    + (f" ({description})" if description else ""),
                 {"expense": amount, "description": description})
