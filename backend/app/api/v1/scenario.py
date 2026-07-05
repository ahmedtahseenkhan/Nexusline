"""Scenario Analysis + Basel SMA operational-risk capital API.

Completes the Basel operational-risk suite. Two record types:

* ``/scenario-analyses`` — forward-looking op-risk scenarios (frequency × typical
  loss = expected annual loss), filterable by free-text search, Basel event type
  and status.
* ``/capital-calculations`` — Basel III Standardised Approach (SMA) capital, with
  BIC / Loss Component / ILM / ORC computed server-side.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.enums import BaselEventType
from app.models.scenario import CapitalCalculation, ScenarioAnalysis, ScenarioStatus
from app.schemas.common import Page
from app.schemas.scenario import (
    CapitalCreate,
    CapitalRead,
    CapitalSnapshot,
    CapitalUpdate,
    ScenarioCreate,
    ScenarioRead,
    ScenarioSummary,
    ScenarioSummaryRow,
    ScenarioUpdate,
)
from app.services import audit as audit_log

router = APIRouter(tags=["scenario analysis"])

_READ = Depends(require("scenario:read"))
_WRITE = Depends(require("scenario:write"))


async def _next_ref(db, model, prefix: str) -> str:
    count = await db.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{count + 1:03d}"


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ===================================================== scenario analyses ===
@router.get("/scenario-analyses", response_model=Page[ScenarioRead], dependencies=[_READ])
async def list_scenarios(
    db: DbSession,
    search: Annotated[str | None, Query()] = None,
    basel_event_type: Annotated[BaselEventType | None, Query()] = None,
    status_filter: Annotated[ScenarioStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ScenarioRead]:
    stmt: Select = select(ScenarioAnalysis).where(ScenarioAnalysis.deleted.is_(False))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                ScenarioAnalysis.title.ilike(like),
                ScenarioAnalysis.reference.ilike(like),
                ScenarioAnalysis.business_line.ilike(like),
                ScenarioAnalysis.owner.ilike(like),
            )
        )
    if basel_event_type is not None:
        stmt = stmt.where(ScenarioAnalysis.basel_event_type == basel_event_type)
    if status_filter is not None:
        stmt = stmt.where(ScenarioAnalysis.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(ScenarioAnalysis.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[ScenarioRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/scenario-analyses", response_model=ScenarioRead, status_code=201, dependencies=[_WRITE])
async def create_scenario(body: ScenarioCreate, db: DbSession, user: CurrentUser) -> ScenarioRead:
    obj = ScenarioAnalysis(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, ScenarioAnalysis, "SCN")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="scenario_analysis",
                           entity_id=obj.id, summary=f"Created scenario {obj.reference}: {obj.title}")
    return ScenarioRead.model_validate(obj)


@router.get("/scenario-analyses/{sid}", response_model=ScenarioRead, dependencies=[_READ])
async def get_scenario(sid: uuid.UUID, db: DbSession) -> ScenarioRead:
    return ScenarioRead.model_validate(await _get(db, ScenarioAnalysis, sid, "Scenario"))


@router.patch("/scenario-analyses/{sid}", response_model=ScenarioRead, dependencies=[_WRITE])
async def update_scenario(sid: uuid.UUID, body: ScenarioUpdate, db: DbSession) -> ScenarioRead:
    obj = await _get(db, ScenarioAnalysis, sid, "Scenario")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return ScenarioRead.model_validate(obj)


@router.delete("/scenario-analyses/{sid}", status_code=204, dependencies=[_WRITE])
async def delete_scenario(sid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, ScenarioAnalysis, sid, "Scenario")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ===================================================== capital calculations ===
@router.get("/capital-calculations", response_model=Page[CapitalRead], dependencies=[_READ])
async def list_capital(db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 100,
                       offset: Annotated[int, Query(ge=0)] = 0) -> Page[CapitalRead]:
    stmt = select(CapitalCalculation).where(CapitalCalculation.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(CapitalCalculation.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[CapitalRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/capital-calculations", response_model=CapitalRead, status_code=201, dependencies=[_WRITE])
async def create_capital(body: CapitalCreate, db: DbSession, user: CurrentUser) -> CapitalRead:
    obj = CapitalCalculation(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, CapitalCalculation, "CAP")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="capital_calculation",
                           entity_id=obj.id, summary=f"Computed SMA capital {obj.reference} ({obj.period})")
    return CapitalRead.model_validate(obj)


@router.get("/capital-calculations/{cid}", response_model=CapitalRead, dependencies=[_READ])
async def get_capital(cid: uuid.UUID, db: DbSession) -> CapitalRead:
    return CapitalRead.model_validate(await _get(db, CapitalCalculation, cid, "Capital calculation"))


@router.patch("/capital-calculations/{cid}", response_model=CapitalRead, dependencies=[_WRITE])
async def update_capital(cid: uuid.UUID, body: CapitalUpdate, db: DbSession) -> CapitalRead:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return CapitalRead.model_validate(obj)


@router.delete("/capital-calculations/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_capital(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================================= summary ===
@router.get("/scenario-summary", response_model=ScenarioSummary, dependencies=[_READ],
            summary="Scenario roll-up by Basel event type + latest SMA capital")
async def scenario_summary(db: DbSession) -> ScenarioSummary:
    scenarios = (await db.scalars(
        select(ScenarioAnalysis).where(ScenarioAnalysis.deleted.is_(False)))).all()
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "eal": 0.0})
    approved = 0
    for s in scenarios:
        g = groups[s.basel_event_type.value]
        g["count"] += 1
        g["eal"] += s.expected_annual_loss
        if s.status == ScenarioStatus.approved:
            approved += 1
    rows = [ScenarioSummaryRow(basel_event_type=k, count=v["count"],
                               expected_annual_loss=round(v["eal"], 2))
            for k, v in sorted(groups.items())]

    latest = await db.scalar(
        select(CapitalCalculation)
        .where(CapitalCalculation.deleted.is_(False))
        .order_by(CapitalCalculation.created_at.desc())
    )
    latest_capital = (
        CapitalSnapshot(
            reference=latest.reference,
            period=latest.period,
            bic=latest.bic,
            loss_component=latest.loss_component,
            ilm=latest.ilm,
            orc=latest.orc,
            currency=latest.currency,
        )
        if latest is not None
        else None
    )

    return ScenarioSummary(
        rows=rows,
        total_expected_annual_loss=round(sum(r.expected_annual_loss for r in rows), 2),
        total_count=sum(r.count for r in rows),
        approved_count=approved,
        latest_capital=latest_capital,
    )
