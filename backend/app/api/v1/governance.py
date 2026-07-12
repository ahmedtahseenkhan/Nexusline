"""Board & Committee Governance API — committees, meetings (agenda/minutes/attendance)
and a decision / action tracker.

Maintain the committee register with charters and cadence, minute each sitting through
its lifecycle, and log decisions / actions / resolutions that roll up into an
enterprise-wide action tracker with an overdue view.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.governance import (
    Committee,
    CommitteeStatus,
    CommitteeType,
    DecisionStatus,
    Meeting,
    MeetingDecision,
    MeetingStatus,
)
from app.schemas.common import Page
from app.schemas.governance import (
    CommitteeCreate,
    CommitteeRead,
    CommitteeUpdate,
    DecisionCreate,
    DecisionRead,
    DecisionTrackerRow,
    DecisionUpdate,
    GovernanceSummary,
    MeetingCreate,
    MeetingRead,
    MeetingUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["governance"])

_READ = Depends(require("governance:read"))
_WRITE = Depends(require("governance:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


_COMMITTEE_SORTABLE = {
    "name": Committee.name,
    "reference": Committee.reference,
    "committee_type": Committee.committee_type,
    "chairperson": Committee.chairperson,
    "status": Committee.status,
    "created_at": Committee.created_at,
}
_DECISION_SORTABLE = {
    "reference": MeetingDecision.reference,
    "description": MeetingDecision.description,
    "decision_type": MeetingDecision.decision_type,
    "owner": MeetingDecision.owner,
    "status": MeetingDecision.status,
    "due_date": MeetingDecision.due_date,
    "committee": Committee.name,
    "meeting": Meeting.title,
    "created_at": MeetingDecision.created_at,
}


# ============================================================== committees ===
async def _load_committee(db, cid: uuid.UUID) -> Committee:
    obj = await db.scalar(
        select(Committee).where(Committee.id == cid, Committee.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Committee not found")
    return obj


@router.get("/governance", response_model=Page[CommitteeRead], dependencies=[_READ])
async def list_committees(
    db: DbSession,
    search: str | None = None,
    committee_type: CommitteeType | None = None,
    status_filter: Annotated[CommitteeStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CommitteeRead]:
    stmt: Select = select(Committee).where(Committee.deleted.is_(False))
    if committee_type is not None:
        stmt = stmt.where(Committee.committee_type == committee_type)
    if status_filter is not None:
        stmt = stmt.where(Committee.status == status_filter)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            Committee.name.ilike(like)
            | Committee.chairperson.ilike(like)
            | Committee.reference.ilike(like)
        )
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _COMMITTEE_SORTABLE, default=Committee.name)
    else:
        stmt = stmt.order_by(Committee.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[CommitteeRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/governance", response_model=CommitteeRead, status_code=201, dependencies=[_WRITE])
async def create_committee(body: CommitteeCreate, db: DbSession, user: CurrentUser) -> CommitteeRead:
    obj = Committee(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, Committee, "CMT")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="committee",
                           entity_id=obj.id, summary=f"Constituted committee {obj.reference}: {obj.name}")
    return CommitteeRead.model_validate(await _load_committee(db, obj.id))


@router.get("/governance/{cid}", response_model=CommitteeRead, dependencies=[_READ])
async def get_committee(cid: uuid.UUID, db: DbSession) -> CommitteeRead:
    return CommitteeRead.model_validate(await _load_committee(db, cid))


@router.patch("/governance/{cid}", response_model=CommitteeRead, dependencies=[_WRITE])
async def update_committee(cid: uuid.UUID, body: CommitteeUpdate, db: DbSession) -> CommitteeRead:
    obj = await _load_committee(db, cid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return CommitteeRead.model_validate(await _load_committee(db, cid))


@router.delete("/governance/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_committee(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_committee(db, cid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================================= meetings ===
async def _load_meeting(db, mid: uuid.UUID) -> Meeting:
    obj = await db.scalar(
        select(Meeting).where(Meeting.id == mid, Meeting.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return obj


@router.post("/governance/{cid}/meetings", response_model=CommitteeRead, status_code=201, dependencies=[_WRITE])
async def add_meeting(cid: uuid.UUID, body: MeetingCreate, db: DbSession, user: CurrentUser) -> CommitteeRead:
    await _load_committee(db, cid)
    meeting = Meeting(tenant_id=user.tenant_id, committee_id=cid, **body.model_dump())
    meeting.reference = await _next_ref(db, Meeting, "MTG")
    db.add(meeting)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="committee_meeting",
                           entity_id=meeting.id, summary=f"Scheduled meeting {meeting.reference}: {meeting.title}")
    return CommitteeRead.model_validate(await _load_committee(db, cid))


@router.get("/governance-meetings/{mid}", response_model=MeetingRead, dependencies=[_READ])
async def get_meeting(mid: uuid.UUID, db: DbSession) -> MeetingRead:
    return MeetingRead.model_validate(await _load_meeting(db, mid))


@router.patch("/governance-meetings/{mid}", response_model=MeetingRead, dependencies=[_WRITE])
async def update_meeting(mid: uuid.UUID, body: MeetingUpdate, db: DbSession) -> MeetingRead:
    obj = await _load_meeting(db, mid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return MeetingRead.model_validate(await _load_meeting(db, mid))


@router.delete("/governance-meetings/{mid}", status_code=204, dependencies=[_WRITE])
async def delete_meeting(mid: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(Meeting).where(Meeting.id == mid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)
    await db.flush()


# ---------------------------------------------------- decisions (per meeting) ---
def _stamp_decision(obj: MeetingDecision, data: dict) -> None:
    """Auto-manage completed_date as a decision moves in and out of 'done'."""
    if data.get("status") == DecisionStatus.done and not obj.completed_date and "completed_date" not in data:
        obj.completed_date = date.today()
    if data.get("status") in (DecisionStatus.open, DecisionStatus.in_progress, DecisionStatus.deferred):
        obj.completed_date = data.get("completed_date")


@router.post("/governance-meetings/{mid}/decisions", response_model=MeetingRead, status_code=201, dependencies=[_WRITE])
async def add_decision(mid: uuid.UUID, body: DecisionCreate, db: DbSession, user: CurrentUser) -> MeetingRead:
    await _load_meeting(db, mid)
    decision = MeetingDecision(tenant_id=user.tenant_id, meeting_id=mid, **body.model_dump())
    decision.reference = await _next_ref(db, MeetingDecision, "DEC")
    if decision.status == DecisionStatus.done and decision.completed_date is None:
        decision.completed_date = date.today()
    db.add(decision)
    await db.flush()
    return MeetingRead.model_validate(await _load_meeting(db, mid))


async def _load_decision(db, did: uuid.UUID) -> MeetingDecision:
    obj = await db.scalar(select(MeetingDecision).where(MeetingDecision.id == did))
    if obj is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return obj


@router.patch("/meeting-decisions/{did}", response_model=DecisionRead, dependencies=[_WRITE])
async def update_decision(did: uuid.UUID, body: DecisionUpdate, db: DbSession) -> DecisionRead:
    obj = await _load_decision(db, did)
    data = body.model_dump(exclude_unset=True)
    _stamp_decision(obj, data)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return DecisionRead.model_validate(obj)


@router.delete("/meeting-decisions/{did}", status_code=204, dependencies=[_WRITE])
async def delete_decision(did: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(MeetingDecision).where(MeetingDecision.id == did))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)
    await db.flush()


@router.get("/meeting-decisions", response_model=Page[DecisionTrackerRow], dependencies=[_READ],
            summary="Enterprise decision / action tracker across all committees")
async def list_decisions(
    db: DbSession,
    search: str | None = None,
    status_filter: Annotated[DecisionStatus | None, Query(alias="status")] = None,
    overdue: bool = False,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DecisionTrackerRow]:
    stmt = (
        select(MeetingDecision, Meeting, Committee)
        .join(Meeting, MeetingDecision.meeting_id == Meeting.id)
        .join(Committee, Meeting.committee_id == Committee.id)
        .where(Committee.deleted.is_(False))
    )
    if status_filter is not None:
        stmt = stmt.where(MeetingDecision.status == status_filter)
    if overdue:
        # `is_overdue` mirrored as SQL so the filter works with server-side pagination.
        stmt = stmt.where(
            MeetingDecision.status.in_([DecisionStatus.open, DecisionStatus.in_progress]),
            MeetingDecision.due_date.is_not(None),
            MeetingDecision.due_date < date.today(),
        )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            MeetingDecision.description.ilike(like)
            | MeetingDecision.owner.ilike(like)
            | MeetingDecision.reference.ilike(like)
            | Committee.name.ilike(like)
            | Meeting.title.ilike(like)
        )
    total = await db.scalar(
        select(func.count()).select_from(
            stmt.with_only_columns(MeetingDecision.id).order_by(None).subquery()
        )
    ) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _DECISION_SORTABLE, default=MeetingDecision.due_date)
    else:
        stmt = stmt.order_by(
            MeetingDecision.due_date.is_(None), MeetingDecision.due_date, MeetingDecision.created_at
        )
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()
    result: list[DecisionTrackerRow] = []
    for decision, meeting, committee in rows:
        row = DecisionTrackerRow.model_validate(decision)
        row.committee_id = committee.id
        row.committee_reference = committee.reference
        row.committee_name = committee.name
        row.meeting_reference = meeting.reference
        row.meeting_title = meeting.title
        row.meeting_date = meeting.meeting_date
        result.append(row)
    return Page(items=result, total=total, limit=limit, offset=offset)


# ================================================================== summary ===
@router.get("/governance-summary", response_model=GovernanceSummary, dependencies=[_READ],
            summary="Board & committee governance roll-up for the dashboard")
async def governance_summary(db: DbSession) -> GovernanceSummary:
    committees = (await db.scalars(select(Committee).where(Committee.deleted.is_(False)))).all()
    committees_active = sum(1 for c in committees if c.status == CommitteeStatus.active)

    meetings = (await db.scalars(
        select(Meeting).join(Committee, Meeting.committee_id == Committee.id)
        .where(Committee.deleted.is_(False))
    )).all()
    meetings_held = sum(1 for m in meetings if m.status in (MeetingStatus.held, MeetingStatus.minuted))
    meetings_scheduled = sum(1 for m in meetings if m.status == MeetingStatus.scheduled)

    decisions = (await db.scalars(
        select(MeetingDecision)
        .join(Meeting, MeetingDecision.meeting_id == Meeting.id)
        .join(Committee, Meeting.committee_id == Committee.id)
        .where(Committee.deleted.is_(False))
    )).all()
    open_actions = sum(1 for d in decisions if d.status in (DecisionStatus.open, DecisionStatus.in_progress))
    overdue_actions = sum(1 for d in decisions if d.is_overdue)

    return GovernanceSummary(
        committees_total=len(committees),
        committees_active=committees_active,
        meetings_total=len(meetings),
        meetings_held=meetings_held,
        meetings_scheduled=meetings_scheduled,
        open_actions=open_actions,
        overdue_actions=overdue_actions,
    )
