"""ICFR API — Internal Control over Financial Reporting.

The SBP-mandated annual cycle: the process universe and its Risk-Control Matrix
(RCM), control testing (design + operating effectiveness), and the deficiency
register (deficiency / significant deficiency / material weakness).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.icfr import (
    DeficiencySeverity,
    DeficiencyStatus,
    IcfrControl,
    IcfrDeficiency,
    IcfrProcess,
    IcfrProcessStatus,
    IcfrTest,
)
from app.schemas.common import Page
from app.schemas.icfr import (
    IcfrControlCreate,
    IcfrControlRead,
    IcfrControlUpdate,
    IcfrDeficiencyCreate,
    IcfrDeficiencyRead,
    IcfrDeficiencyUpdate,
    IcfrProcessCreate,
    IcfrProcessRead,
    IcfrProcessUpdate,
    IcfrTestCreate,
    IcfrTestRead,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["icfr"])

_READ = Depends(require("icfr:read"))
_WRITE = Depends(require("icfr:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ================================================================ processes ===
async def _load_process(db, pid) -> IcfrProcess:
    obj = await db.scalar(
        select(IcfrProcess).where(IcfrProcess.id == pid, IcfrProcess.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="ICFR process not found")
    return obj


_PROCESS_SORTABLE = {
    "reference": IcfrProcess.reference,
    "name": IcfrProcess.name,
    "cycle": IcfrProcess.cycle,
    "business_unit": IcfrProcess.business_unit,
    "owner": IcfrProcess.owner,
    "status": IcfrProcess.status,
    "created_at": IcfrProcess.created_at,
}


@router.get("/icfr", response_model=Page[IcfrProcessRead], dependencies=[_READ])
async def list_processes(
    db: DbSession,
    search: str | None = None,
    cycle: str | None = None,
    status_filter: Annotated[IcfrProcessStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IcfrProcessRead]:
    stmt: Select = select(IcfrProcess).where(IcfrProcess.deleted.is_(False))
    if search:
        stmt = stmt.where(IcfrProcess.name.ilike(f"%{search}%") | IcfrProcess.reference.ilike(f"%{search}%"))
    if cycle:
        stmt = stmt.where(IcfrProcess.cycle == cycle)
    if status_filter is not None:
        stmt = stmt.where(IcfrProcess.status == status_filter)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _PROCESS_SORTABLE, default=IcfrProcess.created_at)
    else:
        stmt = stmt.order_by(IcfrProcess.created_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[IcfrProcessRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/icfr", response_model=IcfrProcessRead, status_code=201, dependencies=[_WRITE])
async def create_process(body: IcfrProcessCreate, db: DbSession, user: CurrentUser) -> IcfrProcessRead:
    obj = IcfrProcess(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, IcfrProcess, "PRC")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="icfr_process",
                           entity_id=obj.id, summary=f"Opened ICFR process {obj.reference}: {obj.name}")
    return IcfrProcessRead.model_validate(await _load_process(db, obj.id))


@router.get("/icfr/{pid}", response_model=IcfrProcessRead, dependencies=[_READ])
async def get_process(pid: uuid.UUID, db: DbSession) -> IcfrProcessRead:
    return IcfrProcessRead.model_validate(await _load_process(db, pid))


@router.patch("/icfr/{pid}", response_model=IcfrProcessRead, dependencies=[_WRITE])
async def update_process(pid: uuid.UUID, body: IcfrProcessUpdate, db: DbSession) -> IcfrProcessRead:
    obj = await _load_process(db, pid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return IcfrProcessRead.model_validate(await _load_process(db, pid))


@router.delete("/icfr/{pid}", status_code=204, dependencies=[_WRITE])
async def delete_process(pid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_process(db, pid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================= RCM controls (nested) ===
_CONTROL_SORTABLE = {
    "reference": IcfrControl.reference,
    "title": IcfrControl.title,
    "created_at": IcfrControl.created_at,
}


@router.get("/icfr-controls", response_model=Page[IcfrControlRead], dependencies=[_READ])
async def list_controls(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IcfrControlRead]:
    # Only surface controls whose parent process is live, matching the summary roll-up.
    stmt: Select = (
        select(IcfrControl)
        .join(IcfrProcess, IcfrProcess.id == IcfrControl.process_id)
        .where(IcfrProcess.deleted.is_(False))
    )
    if search:
        stmt = stmt.where(IcfrControl.title.ilike(f"%{search}%") | IcfrControl.reference.ilike(f"%{search}%"))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _CONTROL_SORTABLE, default=IcfrControl.reference)
    else:
        stmt = stmt.order_by(IcfrControl.reference)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[IcfrControlRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/icfr/{pid}/controls", response_model=IcfrProcessRead, status_code=201, dependencies=[_WRITE])
async def add_control(pid: uuid.UUID, body: IcfrControlCreate, db: DbSession, user: CurrentUser) -> IcfrProcessRead:
    await _load_process(db, pid)
    obj = IcfrControl(tenant_id=user.tenant_id, process_id=pid, **body.model_dump())
    obj.reference = await _next_ref(db, IcfrControl, "CTL")
    db.add(obj)
    await db.flush()
    return IcfrProcessRead.model_validate(await _load_process(db, pid))


@router.patch("/icfr-controls/{cid}", response_model=IcfrControlRead, dependencies=[_WRITE])
async def update_control(cid: uuid.UUID, body: IcfrControlUpdate, db: DbSession) -> IcfrControlRead:
    obj = await _get(db, IcfrControl, cid, "ICFR control")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return IcfrControlRead.model_validate(obj)


@router.delete("/icfr-controls/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_control(cid: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(IcfrControl).where(IcfrControl.id == cid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


# ================================================= control tests (nested) ===
@router.post("/icfr-controls/{cid}/tests", response_model=IcfrControlRead, status_code=201, dependencies=[_WRITE])
async def add_test(cid: uuid.UUID, body: IcfrTestCreate, db: DbSession, user: CurrentUser) -> IcfrControlRead:
    control = await _get(db, IcfrControl, cid, "ICFR control")
    t = IcfrTest(tenant_id=user.tenant_id, control_id=cid, **body.model_dump())
    t.reference = await _next_ref(db, IcfrTest, "TST")
    db.add(t)
    await db.flush()
    await db.refresh(control)
    return IcfrControlRead.model_validate(control)


# ====================================================== deficiency register ===
_DEF_SORTABLE = {
    "reference": IcfrDeficiency.reference,
    "title": IcfrDeficiency.title,
    "severity": IcfrDeficiency.severity,
    "status": IcfrDeficiency.status,
    "owner": IcfrDeficiency.owner,
    "identified_date": IcfrDeficiency.identified_date,
    "target_date": IcfrDeficiency.target_date,
    "created_at": IcfrDeficiency.created_at,
}


async def _attach_def_labels(db, defs) -> None:
    """Populate transient control_label/process_label on each deficiency for the link
    pickers, using column-only queries so we don't drag in each parent's nested tests."""
    cids = {d.control_id for d in defs if d.control_id}
    pids = {d.process_id for d in defs if d.process_id}
    ctl: dict = {}
    prc: dict = {}
    if cids:
        for cid, ref, title in (
            await db.execute(
                select(IcfrControl.id, IcfrControl.reference, IcfrControl.title).where(IcfrControl.id.in_(cids))
            )
        ).all():
            ctl[cid] = f"{ref or 'CTL'} — {title}"
    if pids:
        for pid, ref, name in (
            await db.execute(
                select(IcfrProcess.id, IcfrProcess.reference, IcfrProcess.name).where(IcfrProcess.id.in_(pids))
            )
        ).all():
            prc[pid] = f"{ref or 'PRC'} — {name}"
    for d in defs:
        d.control_label = ctl.get(d.control_id) if d.control_id else None
        d.process_label = prc.get(d.process_id) if d.process_id else None


@router.get("/icfr-deficiencies", response_model=Page[IcfrDeficiencyRead], dependencies=[_READ])
async def list_deficiencies(
    db: DbSession,
    search: str | None = None,
    severity: Annotated[DeficiencySeverity | None, Query()] = None,
    status_filter: Annotated[DeficiencyStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IcfrDeficiencyRead]:
    stmt: Select = select(IcfrDeficiency).where(IcfrDeficiency.deleted.is_(False))
    if search:
        stmt = stmt.where(IcfrDeficiency.title.ilike(f"%{search}%") | IcfrDeficiency.reference.ilike(f"%{search}%"))
    if severity is not None:
        stmt = stmt.where(IcfrDeficiency.severity == severity)
    if status_filter is not None:
        stmt = stmt.where(IcfrDeficiency.status == status_filter)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _DEF_SORTABLE, default=IcfrDeficiency.created_at)
    else:
        stmt = stmt.order_by(IcfrDeficiency.created_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    await _attach_def_labels(db, rows)
    return Page(items=[IcfrDeficiencyRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/icfr-deficiencies", response_model=IcfrDeficiencyRead, status_code=201, dependencies=[_WRITE])
async def create_deficiency(body: IcfrDeficiencyCreate, db: DbSession, user: CurrentUser) -> IcfrDeficiencyRead:
    # Validate optional parent links up front — an unknown id would otherwise only fail
    # at flush with an unhandled 500 (FK violation).
    if body.control_id:
        await _get(db, IcfrControl, body.control_id, "ICFR control")
    if body.process_id:
        await _get(db, IcfrProcess, body.process_id, "ICFR process")
    obj = IcfrDeficiency(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, IcfrDeficiency, "DEF")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="icfr_deficiency",
                           entity_id=obj.id, summary=f"Logged deficiency {obj.reference}: {obj.title}")
    await _attach_def_labels(db, [obj])
    return IcfrDeficiencyRead.model_validate(obj)


@router.patch("/icfr-deficiencies/{did}", response_model=IcfrDeficiencyRead, dependencies=[_WRITE])
async def update_deficiency(did: uuid.UUID, body: IcfrDeficiencyUpdate, db: DbSession) -> IcfrDeficiencyRead:
    obj = await _get(db, IcfrDeficiency, did, "Deficiency")
    data = body.model_dump(exclude_unset=True)
    if data.get("control_id"):
        await _get(db, IcfrControl, data["control_id"], "ICFR control")
    if data.get("process_id"):
        await _get(db, IcfrProcess, data["process_id"], "ICFR process")
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    await _attach_def_labels(db, [obj])
    return IcfrDeficiencyRead.model_validate(obj)


@router.delete("/icfr-deficiencies/{did}", status_code=204, dependencies=[_WRITE])
async def delete_deficiency(did: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, IcfrDeficiency, did, "Deficiency")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================================== summary ===
class IcfrSummary(BaseModel):
    processes: int
    key_processes: int
    controls: int
    key_controls: int
    controls_by_operating_effectiveness: dict[str, int]
    tests_by_result: dict[str, int]
    deficiencies_by_severity: dict[str, int]
    open_deficiencies: int
    material_weaknesses: int


@router.get("/icfr-summary", response_model=IcfrSummary, dependencies=[_READ],
            summary="ICFR RCM, testing and deficiency roll-up for the dashboard")
async def icfr_summary(db: DbSession) -> IcfrSummary:
    processes = (await db.scalars(select(IcfrProcess).where(IcfrProcess.deleted.is_(False)))).all()
    # Controls/tests carry no soft-delete of their own; exclude those whose parent
    # process is archived so the roll-up doesn't count controls/tests nobody can see.
    controls = (await db.scalars(
        select(IcfrControl).join(IcfrProcess, IcfrProcess.id == IcfrControl.process_id)
        .where(IcfrProcess.deleted.is_(False))
    )).all()
    tests = (await db.scalars(
        select(IcfrTest)
        .join(IcfrControl, IcfrControl.id == IcfrTest.control_id)
        .join(IcfrProcess, IcfrProcess.id == IcfrControl.process_id)
        .where(IcfrProcess.deleted.is_(False))
    )).all()
    deficiencies = (await db.scalars(select(IcfrDeficiency).where(IcfrDeficiency.deleted.is_(False)))).all()

    by_op_eff: dict[str, int] = defaultdict(int)
    for c in controls:
        by_op_eff[c.operating_effectiveness.value] += 1
    by_result: dict[str, int] = defaultdict(int)
    for t in tests:
        by_result[t.result.value] += 1
    by_severity: dict[str, int] = defaultdict(int)
    for d in deficiencies:
        by_severity[d.severity.value] += 1

    return IcfrSummary(
        processes=len(processes),
        key_processes=sum(1 for p in processes if p.key_process),
        controls=len(controls),
        key_controls=sum(1 for c in controls if c.is_key),
        controls_by_operating_effectiveness=dict(by_op_eff),
        tests_by_result=dict(by_result),
        deficiencies_by_severity=dict(by_severity),
        open_deficiencies=sum(1 for d in deficiencies if d.status != DeficiencyStatus.closed),
        material_weaknesses=sum(1 for d in deficiencies if d.severity == DeficiencySeverity.material_weakness),
    )
