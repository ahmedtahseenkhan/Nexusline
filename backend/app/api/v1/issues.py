"""Unified Issues & Actions (CAPA) API.

One issue universe that aggregates findings/actions from every other module
(internal audit, compliance, RCSA, Shariah, assessments, incidents, external /
SBP inspections) with a full remediation lifecycle: issues, their CAPA action
lines and a chronological progress log.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.enums import Severity
from app.models.issue import (
    ActionStatus,
    Issue,
    IssueAction,
    IssueSource,
    IssueStatus2,
    IssueUpdate,
)
from app.schemas.common import Page
from app.schemas.issue import (
    IssueActionCreate,
    IssueActionRead,
    IssueActionUpdate,
    IssueCreate,
    IssueRead,
    IssuesSummary,
    IssueUpdateCreate,
    IssueUpdatePatch,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["issues"])

_READ = Depends(require("issue:read"))
_WRITE = Depends(require("issue:write"))

_CLOSED_STATES = (IssueStatus2.closed, IssueStatus2.remediated, IssueStatus2.risk_accepted)


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _load_issue(db, iid) -> Issue:
    obj = await db.scalar(
        select(Issue).where(Issue.id == iid, Issue.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return obj


_ISSUE_SORTABLE = {
    "reference": Issue.reference,
    "title": Issue.title,
    "severity": Issue.severity,
    "status": Issue.status,
    "source_type": Issue.source_type,
    "owner": Issue.owner,
    "due_date": Issue.due_date,
    "identified_date": Issue.identified_date,
    "created_at": Issue.created_at,
}


# ================================================================== issues ===
@router.get("/issues", response_model=Page[IssueRead], dependencies=[_READ])
async def list_issues(
    db: DbSession,
    search: Annotated[str | None, Query()] = None,
    status_filter: Annotated[IssueStatus2 | None, Query(alias="status")] = None,
    source_type: Annotated[IssueSource | None, Query()] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
    overdue: Annotated[bool | None, Query()] = None,
    regulator_related: Annotated[bool | None, Query()] = None,
    repeat_finding: Annotated[bool | None, Query()] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IssueRead]:
    stmt: Select = select(Issue).where(Issue.deleted.is_(False))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Issue.title.ilike(like),
                Issue.description.ilike(like),
                Issue.reference.ilike(like),
                Issue.source_reference.ilike(like),
                Issue.owner.ilike(like),
            )
        )
    if status_filter is not None:
        stmt = stmt.where(Issue.status == status_filter)
    if source_type is not None:
        stmt = stmt.where(Issue.source_type == source_type)
    if source_id is not None:
        stmt = stmt.where(Issue.source_id == source_id)
    if severity is not None:
        stmt = stmt.where(Issue.severity == severity)
    if regulator_related is not None:
        stmt = stmt.where(Issue.regulator_related.is_(regulator_related))
    if repeat_finding is not None:
        stmt = stmt.where(Issue.repeat_finding.is_(repeat_finding))
    if overdue:
        stmt = stmt.where(
            Issue.due_date.is_not(None),
            Issue.due_date < date.today(),
            Issue.status.notin_(_CLOSED_STATES),
        )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _ISSUE_SORTABLE, default=Issue.created_at)
    else:
        stmt = stmt.order_by(Issue.created_at.desc())
    rows = (
        await db.scalars(stmt.limit(limit).offset(offset))
    ).all()
    return Page(items=[IssueRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/issues", response_model=IssueRead, status_code=201, dependencies=[_WRITE])
async def create_issue(body: IssueCreate, db: DbSession, user: CurrentUser) -> IssueRead:
    data = body.model_dump()
    if data.get("identified_date") is None:
        data["identified_date"] = date.today()
    obj = Issue(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, Issue, "ISS")
    db.add(obj)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="issue", entity_id=obj.id,
        summary=f"Raised issue {obj.reference}: {obj.title}",
    )
    return IssueRead.model_validate(await _load_issue(db, obj.id))


@router.get("/issues/{iid}", response_model=IssueRead, dependencies=[_READ])
async def get_issue(iid: uuid.UUID, db: DbSession) -> IssueRead:
    return IssueRead.model_validate(await _load_issue(db, iid))


@router.patch("/issues/{iid}", response_model=IssueRead, dependencies=[_WRITE])
async def update_issue(iid: uuid.UUID, body: IssueUpdatePatch, db: DbSession, user: CurrentUser) -> IssueRead:
    obj = await _load_issue(db, iid)
    prev_status = obj.status
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    # Stamp the closed date and log the closure when an issue is retired.
    just_closed = obj.status in _CLOSED_STATES and prev_status not in _CLOSED_STATES
    if just_closed and obj.closed_date is None:
        obj.closed_date = date.today()
    await db.flush()
    if just_closed:
        await audit_log.record(
            db, actor=user, action="close", entity_type="issue", entity_id=obj.id,
            summary=f"Closed issue {obj.reference} as {obj.status.value}",
        )
    return IssueRead.model_validate(await _load_issue(db, iid))


@router.delete("/issues/{iid}", status_code=204, dependencies=[_WRITE])
async def delete_issue(iid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_issue(db, iid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================================= CAPA actions ===
@router.post("/issues/{iid}/actions", response_model=IssueRead, status_code=201, dependencies=[_WRITE])
async def add_action(iid: uuid.UUID, body: IssueActionCreate, db: DbSession, user: CurrentUser) -> IssueRead:
    await _load_issue(db, iid)
    db.add(IssueAction(tenant_id=user.tenant_id, issue_id=iid, **body.model_dump()))
    await db.flush()
    return IssueRead.model_validate(await _load_issue(db, iid))


@router.patch("/issue-actions/{line_id}", response_model=IssueActionRead, dependencies=[_WRITE])
async def update_action(line_id: uuid.UUID, body: IssueActionUpdate, db: DbSession) -> IssueActionRead:
    obj = await _get(db, IssueAction, line_id, "Action")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)
    # Auto-stamp completion when an action is marked done.
    if obj.status == ActionStatus.done and obj.completed_date is None:
        obj.completed_date = date.today()
    await db.flush()
    return IssueActionRead.model_validate(obj)


@router.delete("/issue-actions/{line_id}", status_code=204, dependencies=[_WRITE])
async def delete_action(line_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(IssueAction).where(IssueAction.id == line_id))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


# =========================================================== progress updates ===
@router.post("/issues/{iid}/updates", response_model=IssueRead, status_code=201, dependencies=[_WRITE])
async def add_update(iid: uuid.UUID, body: IssueUpdateCreate, db: DbSession, user: CurrentUser) -> IssueRead:
    await _load_issue(db, iid)
    data = body.model_dump()
    if data.get("update_date") is None:
        data["update_date"] = date.today()
    db.add(IssueUpdate(tenant_id=user.tenant_id, issue_id=iid, **data))
    await db.flush()
    return IssueRead.model_validate(await _load_issue(db, iid))


# ================================================================== summary ===
@router.get("/issues-summary", response_model=IssuesSummary, dependencies=[_READ],
            summary="Issue register roll-up (status / source / overdue / regulator)")
async def issues_summary(db: DbSession) -> IssuesSummary:
    issues = (await db.scalars(select(Issue).where(Issue.deleted.is_(False)))).all()
    by_status: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    total_open = overdue_count = repeat_count = regulator_open = 0
    for i in issues:
        by_status[i.status.value] += 1
        by_source[i.source_type.value] += 1
        is_open = i.status not in _CLOSED_STATES
        if is_open:
            total_open += 1
        if i.is_overdue:
            overdue_count += 1
        if i.repeat_finding:
            repeat_count += 1
        if i.regulator_related and is_open:
            regulator_open += 1
    return IssuesSummary(
        by_status=dict(by_status),
        by_source_type=dict(by_source),
        total=len(issues),
        total_open=total_open,
        overdue_count=overdue_count,
        repeat_finding_count=repeat_count,
        regulator_related_open=regulator_open,
    )
