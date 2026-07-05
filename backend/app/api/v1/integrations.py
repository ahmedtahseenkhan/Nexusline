"""Integrations & Continuous Controls Monitoring (CCM) API.

A connector registry plus automated control tests that record pass/fail over time.
Runtime execution is stubbed/manual for now — recording a run updates the parent
test's last_run / last_result / pass_rate so the UI can trend control health.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.integrations import (
    AutomatedControlTest,
    CcmResult,
    CcmStatus,
    Connector,
    ConnectorStatus,
    ConnectorType,
    ControlTestRun,
)
from app.schemas.common import Page
from app.schemas.integrations import (
    CctCreate,
    CctRead,
    CctUpdate,
    ConnectorCreate,
    ConnectorRead,
    ConnectorUpdate,
    RunCreate,
)
from app.services import audit as audit_log

router = APIRouter(tags=["integrations"])

_READ = Depends(require("ccm:read"))
_WRITE = Depends(require("ccm:write"))


async def _next_ref(db, model, prefix: str) -> str:
    count = await db.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{count + 1:03d}"


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ================================================================ connectors ===
async def _load_connector(db, cid) -> Connector:
    obj = await db.scalar(select(Connector).where(Connector.id == cid).execution_options(populate_existing=True))
    if obj is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return obj


@router.get("/connectors", response_model=Page[ConnectorRead], dependencies=[_READ])
async def list_connectors(
    db: DbSession,
    status: ConnectorStatus | None = None,
    connector_type: ConnectorType | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ConnectorRead]:
    stmt = select(Connector).where(Connector.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(Connector.status == status)
    if connector_type is not None:
        stmt = stmt.where(Connector.connector_type == connector_type)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(Connector.name).limit(limit).offset(offset))).all()
    return Page(items=[ConnectorRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/connectors", response_model=ConnectorRead, status_code=201, dependencies=[_WRITE])
async def create_connector(body: ConnectorCreate, db: DbSession, user: CurrentUser) -> ConnectorRead:
    obj = Connector(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, Connector, "CON")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="connector",
                           entity_id=obj.id, summary=f"Registered connector {obj.reference}: {obj.name}")
    return ConnectorRead.model_validate(await _load_connector(db, obj.id))


@router.get("/connectors/{cid}", response_model=ConnectorRead, dependencies=[_READ])
async def get_connector(cid: uuid.UUID, db: DbSession) -> ConnectorRead:
    return ConnectorRead.model_validate(await _load_connector(db, cid))


@router.patch("/connectors/{cid}", response_model=ConnectorRead, dependencies=[_WRITE])
async def update_connector(cid: uuid.UUID, body: ConnectorUpdate, db: DbSession) -> ConnectorRead:
    obj = await _load_connector(db, cid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return ConnectorRead.model_validate(await _load_connector(db, cid))


@router.delete("/connectors/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_connector(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_connector(db, cid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================= automated control tests (CCM) ===
async def _load_test(db, tid) -> AutomatedControlTest:
    obj = await db.scalar(
        select(AutomatedControlTest).where(AutomatedControlTest.id == tid).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Automated control test not found")
    return obj


@router.get("/automated-control-tests", response_model=Page[CctRead], dependencies=[_READ])
async def list_tests(
    db: DbSession,
    status: CcmStatus | None = None,
    last_result: CcmResult | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CctRead]:
    stmt = select(AutomatedControlTest).where(AutomatedControlTest.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(AutomatedControlTest.status == status)
    if last_result is not None:
        stmt = stmt.where(AutomatedControlTest.last_result == last_result)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(AutomatedControlTest.name).limit(limit).offset(offset))).all()
    return Page(items=[CctRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/automated-control-tests", response_model=CctRead, status_code=201, dependencies=[_WRITE])
async def create_test(body: CctCreate, db: DbSession, user: CurrentUser) -> CctRead:
    obj = AutomatedControlTest(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, AutomatedControlTest, "CCM")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="automated_control_test",
                           entity_id=obj.id, summary=f"Created continuous control test {obj.reference}: {obj.name}")
    return CctRead.model_validate(await _load_test(db, obj.id))


@router.get("/automated-control-tests/{tid}", response_model=CctRead, dependencies=[_READ])
async def get_test(tid: uuid.UUID, db: DbSession) -> CctRead:
    return CctRead.model_validate(await _load_test(db, tid))


@router.patch("/automated-control-tests/{tid}", response_model=CctRead, dependencies=[_WRITE])
async def update_test(tid: uuid.UUID, body: CctUpdate, db: DbSession) -> CctRead:
    obj = await _load_test(db, tid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return CctRead.model_validate(await _load_test(db, tid))


@router.delete("/automated-control-tests/{tid}", status_code=204, dependencies=[_WRITE])
async def delete_test(tid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_test(db, tid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


@router.post("/automated-control-tests/{tid}/runs", response_model=CctRead, status_code=201, dependencies=[_WRITE])
async def add_run(tid: uuid.UUID, body: RunCreate, db: DbSession, user: CurrentUser) -> CctRead:
    test = await _load_test(db, tid)
    run = ControlTestRun(tenant_id=user.tenant_id, test_id=tid, **body.model_dump())
    db.add(run)
    # Recording a run rolls its outcome up onto the test (last_run / last_result / pass_rate).
    test.last_run = body.run_date or date.today()
    test.last_result = body.result
    test.pass_rate = body.pass_rate
    await db.flush()
    return CctRead.model_validate(await _load_test(db, tid))


@router.delete("/control-test-runs/{run_id}", status_code=204, dependencies=[_WRITE])
async def delete_run(run_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(ControlTestRun).where(ControlTestRun.id == run_id))
    if obj is not None:
        await db.delete(obj)


# ================================================================== summary ===
class IntegrationsSummary(BaseModel):
    total_connectors: int
    active_connectors: int
    error_connectors: int
    stale_connectors: int
    total_tests: int
    tests_by_result: dict[str, int]
    avg_pass_rate: float
    failing_tests: int


@router.get("/integrations-summary", response_model=IntegrationsSummary, dependencies=[_READ],
            summary="CCM dashboard roll-up: connector health and automated-control-test results")
async def integrations_summary(db: DbSession) -> IntegrationsSummary:
    connectors = (await db.scalars(select(Connector).where(Connector.deleted.is_(False)))).all()
    active = sum(1 for c in connectors if c.status == ConnectorStatus.active)
    errored = sum(1 for c in connectors if c.status == ConnectorStatus.error)
    stale = sum(1 for c in connectors if c.is_stale)

    tests = (await db.scalars(select(AutomatedControlTest).where(AutomatedControlTest.deleted.is_(False)))).all()
    by_result: dict[str, int] = defaultdict(int)
    for t in tests:
        by_result[t.last_result.value] += 1
    failing = by_result.get(CcmResult.failed.value, 0)
    rated = [float(t.pass_rate or 0) for t in tests]
    avg_pass = round(sum(rated) / len(rated), 2) if rated else 0.0

    return IntegrationsSummary(
        total_connectors=len(connectors),
        active_connectors=active,
        error_connectors=errored,
        stale_connectors=stale,
        total_tests=len(tests),
        tests_by_result=dict(by_result),
        avg_pass_rate=avg_pass,
        failing_tests=failing,
    )
