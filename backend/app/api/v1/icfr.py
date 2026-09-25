"""ICFR API — Internal Control over Financial Reporting.

The SBP-mandated annual cycle: the process universe and its Risk-Control Matrix
(RCM), control testing (design + operating effectiveness), and the deficiency
register (deficiency / significant deficiency / material weakness).

An RCM control's design and operating effectiveness are the conclusions of its latest
design and operating tests (``models.icfr.derive_effectiveness``); a rating is entered by
hand only while no conclusive test of that kind exists. Every change to the RCM, its
tests and the deficiency register is on the activity trail — the external auditor's
walkthrough of ICFR relies on it.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

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
    IcfrTestResult,
    IcfrTestStatus,
    IcfrTestType,
    derive_effectiveness,
    latest_conclusive,
    figures_problem,
)
from app.models.control import Control
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
    IcfrTestUpdate,
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


def _control_ref(path=None):
    """Load an RCM line's enterprise control as just id / reference / name: the
    relationship is not eager (a Control brings a dozen eager links of its own) and the
    read shows only a reference to it. ``path`` is the loader the RCM lines come through
    (a process's controls); None when the lines are the rows queried."""
    rel = path.selectinload(IcfrControl.control) if path is not None else selectinload(IcfrControl.control)
    return rel.load_only(Control.id, Control.reference, Control.name, raiseload=True).lazyload("*")


_WITH_CONTROL = _control_ref(selectinload(IcfrProcess.controls))


def _plain(value):
    return getattr(value, "value", value)


def _changes(obj, data: dict) -> dict:
    return {k: {"from": _plain(getattr(obj, k)), "to": _plain(v)}
            for k, v in data.items() if getattr(obj, k) != v}


async def _audit(db, user, action: str, entity_type: str, entity_id, summary: str, changes=None) -> None:
    await audit_log.record(db, actor=user, action=action, entity_type=entity_type, entity_id=entity_id,
                           summary=summary[:500], changes=changes or None)


# ================================================================ processes ===
async def _load_process(db, pid) -> IcfrProcess:
    obj = await db.scalar(
        select(IcfrProcess).where(IcfrProcess.id == pid, IcfrProcess.deleted.is_(False))
        .options(_WITH_CONTROL).execution_options(populate_existing=True)
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
    rows = (await db.scalars(stmt.options(_WITH_CONTROL).limit(limit).offset(offset))).all()
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
async def update_process(pid: uuid.UUID, body: IcfrProcessUpdate, db: DbSession, user: CurrentUser) -> IcfrProcessRead:
    obj = await _load_process(db, pid)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    changes = _changes(obj, data)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if changes:
        await _audit(db, user, "update", "icfr_process", obj.id,
                     f"Updated ICFR process {obj.reference}: {', '.join(changes)}", changes)
    return IcfrProcessRead.model_validate(await _load_process(db, pid))


@router.delete("/icfr/{pid}", status_code=204, dependencies=[_WRITE])
async def delete_process(pid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_process(db, pid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _audit(db, user, "delete", "icfr_process", obj.id,
                 f"Archived ICFR process {obj.reference}: {obj.name} ({len(obj.controls)} RCM control(s))")


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
    rows = (await db.scalars(stmt.options(_control_ref()).limit(limit).offset(offset))).all()
    return Page(items=[IcfrControlRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


async def _load_control(db, cid) -> IcfrControl:
    """An RCM control of a live process, fresh from the database, with its tests and
    enterprise-control reference."""
    obj = await db.scalar(
        select(IcfrControl).join(IcfrProcess, IcfrProcess.id == IcfrControl.process_id)
        .where(IcfrControl.id == cid, IcfrProcess.deleted.is_(False))
        .options(_control_ref()).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="ICFR control not found")
    return obj


async def _check_enterprise_control(db, control_id) -> None:
    """An unknown or archived enterprise control would only fail at flush (FK) or leave
    a link to a record nobody can open."""
    if control_id is None:
        return
    found = await db.scalar(select(Control.id).where(Control.id == control_id, Control.deleted.is_(False)))
    if found is None:
        raise HTTPException(status_code=422, detail="control_id: no such control in the control register (or it is archived).")


def _manual_rating_refusal(control: IcfrControl, data: dict) -> str | None:
    """A rating the tests decide cannot be typed over: the auditor's evidence is the
    test. Change or add a test instead."""
    for field, kind in (("design_effectiveness", IcfrTestType.design),
                        ("operating_effectiveness", IcfrTestType.operating)):
        if field not in data or data[field] is None:
            continue
        test = latest_conclusive(control.tests, kind)
        if test is not None and _plain(data[field]) != _plain(getattr(control, field)):
            return (f"{field}: this rating comes from test {test.reference} ({_plain(test.result).replace('_', ' ')}). "
                    f"Record a new {kind.value} test, or correct that test, to change it.")
    return None


def _sync_effectiveness(control: IcfrControl) -> dict:
    """Store the ratings the tests give (what reports and exports read), returning the
    changes."""
    design, operating, _db, _ob = derive_effectiveness(
        control.tests, control.design_effectiveness, control.operating_effectiveness)
    changes = {}
    for field, value in (("design_effectiveness", design), ("operating_effectiveness", operating)):
        if getattr(control, field) != value:
            changes[field] = {"from": _plain(getattr(control, field)), "to": value.value}
            setattr(control, field, value)
    return changes


@router.post("/icfr/{pid}/controls", response_model=IcfrProcessRead, status_code=201, dependencies=[_WRITE])
async def add_control(pid: uuid.UUID, body: IcfrControlCreate, db: DbSession, user: CurrentUser) -> IcfrProcessRead:
    process = await _load_process(db, pid)
    await _check_enterprise_control(db, body.control_id)
    obj = IcfrControl(tenant_id=user.tenant_id, process_id=pid, **body.model_dump())
    obj.reference = await _next_ref(db, IcfrControl, "CTL")
    db.add(obj)
    await db.flush()
    await _audit(db, user, "create", "icfr_control", obj.id,
                 f"Added RCM control {obj.reference} to ICFR process {process.reference}: {obj.title}")
    return IcfrProcessRead.model_validate(await _load_process(db, pid))


@router.get("/icfr-controls/{cid}", response_model=IcfrControlRead, dependencies=[_READ])
async def get_control(cid: uuid.UUID, db: DbSession) -> IcfrControlRead:
    return IcfrControlRead.model_validate(await _load_control(db, cid))


@router.patch("/icfr-controls/{cid}", response_model=IcfrControlRead, dependencies=[_WRITE])
async def update_control(cid: uuid.UUID, body: IcfrControlUpdate, db: DbSession, user: CurrentUser) -> IcfrControlRead:
    obj = await _load_control(db, cid)
    # ``control_id`` may be cleared (unlink); every other null is "leave as is".
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "control_id"}
    if data.get("control_id") is not None:
        await _check_enterprise_control(db, data["control_id"])
    refusal = _manual_rating_refusal(obj, data)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    changes = _changes(obj, data)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if changes:
        await _audit(db, user, "update", "icfr_control", obj.id,
                     f"Updated RCM control {obj.reference}: {', '.join(changes)}", changes)
    return IcfrControlRead.model_validate(await _load_control(db, cid))


@router.delete("/icfr-controls/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_control(cid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_control(db, cid)
    label = f"{obj.reference}: {obj.title} ({len(obj.tests)} test(s))"
    await db.delete(obj)
    await db.flush()
    await _audit(db, user, "delete", "icfr_control", cid, f"Removed RCM control {label}")


# ================================================= control tests (nested) ===
def _conclude(data: dict) -> None:
    """A test with a conclusive result has been performed: a result recorded on a test
    still marked planned or in progress completes it, so the rating it gives is not
    left hanging on a status nobody updated."""
    result = data.get("result")
    if result is not None and IcfrTestResult(_plain(result)) != IcfrTestResult.not_tested:
        data["status"] = IcfrTestStatus.completed


async def _after_test_change(db, user, control: IcfrControl, summary: str, changes: dict | None) -> IcfrControlRead:
    control = await _load_control(db, control.id)
    rating = _sync_effectiveness(control)
    await db.flush()
    if rating:
        moved = ", ".join(f"{k.replace('_effectiveness', '')} {v['to'].replace('_', ' ')}" for k, v in rating.items())
        summary += f"; ratings now {moved}"
    await _audit(db, user, "update", "icfr_control", control.id, summary, {**(changes or {}), **rating})
    return IcfrControlRead.model_validate(await _load_control(db, control.id))


@router.post("/icfr-controls/{cid}/tests", response_model=IcfrControlRead, status_code=201, dependencies=[_WRITE])
async def add_test(cid: uuid.UUID, body: IcfrTestCreate, db: DbSession, user: CurrentUser) -> IcfrControlRead:
    control = await _load_control(db, cid)
    data = body.model_dump()
    _conclude(data)
    t = IcfrTest(tenant_id=user.tenant_id, control_id=cid, **data)
    t.reference = await _next_ref(db, IcfrTest, "TST")
    db.add(t)
    await db.flush()
    return await _after_test_change(
        db, user, control,
        f"Recorded {t.test_type.value} test {t.reference} on RCM control {control.reference}: "
        f"{t.result.value.replace('_', ' ')} ({t.exceptions_found}/{t.sample_size} exceptions)",
        {"test": t.reference, "result": t.result.value},
    )


async def _load_test(db, tid) -> IcfrTest:
    obj = await db.scalar(
        select(IcfrTest).join(IcfrControl, IcfrControl.id == IcfrTest.control_id)
        .join(IcfrProcess, IcfrProcess.id == IcfrControl.process_id)
        .where(IcfrTest.id == tid, IcfrProcess.deleted.is_(False))
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="ICFR test not found")
    return obj


@router.patch("/icfr-tests/{tid}", response_model=IcfrControlRead, dependencies=[_WRITE],
              summary="Correct a test; the control's ratings follow")
async def update_test(tid: uuid.UUID, body: IcfrTestUpdate, db: DbSession, user: CurrentUser) -> IcfrControlRead:
    t = await _load_test(db, tid)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "test_date"}
    problem = figures_problem(data.get("sample_size", t.sample_size),
                           data.get("exceptions_found", t.exceptions_found), data.get("result", t.result))
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    _conclude(data)
    changes = _changes(t, data)
    for k, v in data.items():
        setattr(t, k, v)
    await db.flush()
    control = await _load_control(db, t.control_id)
    if not changes:
        return IcfrControlRead.model_validate(control)
    return await _after_test_change(
        db, user, control, f"Updated test {t.reference} on RCM control {control.reference}: {', '.join(changes)}",
        {f"test.{k}": v for k, v in changes.items()},
    )


@router.delete("/icfr-tests/{tid}", status_code=204, dependencies=[_WRITE])
async def delete_test(tid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    t = await _load_test(db, tid)
    control_id, label = t.control_id, f"{t.reference} ({t.test_type.value}, {t.result.value.replace('_', ' ')})"
    await db.delete(t)
    await db.flush()
    control = await _load_control(db, control_id)
    await _after_test_change(db, user, control, f"Deleted test {label} from RCM control {control.reference}", None)


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
async def update_deficiency(did: uuid.UUID, body: IcfrDeficiencyUpdate, db: DbSession, user: CurrentUser) -> IcfrDeficiencyRead:
    obj = await _get(db, IcfrDeficiency, did, "Deficiency")
    data = body.model_dump(exclude_unset=True)
    if data.get("control_id"):
        await _get(db, IcfrControl, data["control_id"], "ICFR control")
    if data.get("process_id"):
        await _get(db, IcfrProcess, data["process_id"], "ICFR process")
    changes = _changes(obj, data)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if changes:
        # Re-grading a deficiency (say, material weakness → significant deficiency) is
        # what the audit committee and the external auditor ask about first.
        await _audit(db, user, "update", "icfr_deficiency", obj.id,
                     f"Updated deficiency {obj.reference}: {', '.join(changes)}", changes)
    await _attach_def_labels(db, [obj])
    return IcfrDeficiencyRead.model_validate(obj)


@router.delete("/icfr-deficiencies/{did}", status_code=204, dependencies=[_WRITE])
async def delete_deficiency(did: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _get(db, IcfrDeficiency, did, "Deficiency")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _audit(db, user, "delete", "icfr_deficiency", obj.id,
                 f"Archived deficiency {obj.reference}: {obj.title} ({_plain(obj.severity).replace('_', ' ')}, "
                 f"{_plain(obj.status)})")


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
        # From the tests, as each control's read shows it (a row saved before ratings
        # were derived may still hold its day-one value).
        _design, operating, _b1, _b2 = derive_effectiveness(
            c.tests, c.design_effectiveness, c.operating_effectiveness)
        by_op_eff[operating.value] += 1
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
