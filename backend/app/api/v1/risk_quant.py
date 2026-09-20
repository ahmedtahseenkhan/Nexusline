"""Risk Quantification API — FAIR-style Monte Carlo loss-exposure over the risk register.

CRUD over quantification records plus a `/simulate` action that runs a triangular-input
Monte Carlo (Threat Event Frequency × Loss Magnitude) to estimate the annualised loss
distribution, and a summary roll-up for the module dashboard.
"""
from __future__ import annotations

import random
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.risk import Risk
from app.models.risk_quant import QuantStatus, RiskQuantification
from app.schemas.common import Page
from app.schemas.risk_quant import (
    RiskQuantCreate,
    RiskQuantRead,
    RiskQuantUpdate,
    SimulationResult,
)
from app.services.refs import next_reference
from app.schemas.fx import UnconvertedAmount
from app.services import audit as audit_log
from app.services import fx

router = APIRouter(tags=["risk quantification"])

_READ = Depends(require("riskquant:read"))
_WRITE = Depends(require("riskquant:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _validate_risk(db, risk_id) -> None:
    """A quantification may optionally link a parent risk; reject unknown/archived ids
    with a 400 instead of a flush-time 500 (FK violation)."""
    if risk_id is None:
        return
    exists = await db.scalar(
        select(Risk.id).where(Risk.id == risk_id, Risk.deleted.is_(False))
    )
    if exists is None:
        raise HTTPException(status_code=400, detail=f"Unknown or archived risk id: {risk_id}")


async def _load(db, qid) -> RiskQuantification:
    obj = await db.scalar(
        select(RiskQuantification).where(RiskQuantification.id == qid, RiskQuantification.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Risk quantification not found")
    return obj


# ====================================================================== CRUD ===
# `ale_point` is computed (tef_likely × lm_likely); the cached run columns are sortable.
_QUANT_SORTABLE = {
    "reference": RiskQuantification.reference,
    "title": RiskQuantification.title,
    "asset_at_risk": RiskQuantification.asset_at_risk,
    "last_mean_ale": RiskQuantification.last_mean_ale,
    "last_p90": RiskQuantification.last_p90,
    "status": RiskQuantification.status,
    "created_at": RiskQuantification.created_at,
}


@router.get("/risk-quantification", response_model=Page[RiskQuantRead], dependencies=[_READ])
async def list_quantifications(
    db: DbSession,
    search: str | None = None,
    status_filter: Annotated[QuantStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RiskQuantRead]:
    stmt: Select = select(RiskQuantification).where(RiskQuantification.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(RiskQuantification.title.ilike(like), RiskQuantification.reference.ilike(like),
                             RiskQuantification.asset_at_risk.ilike(like)))
    if status_filter is not None:
        stmt = stmt.where(RiskQuantification.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _QUANT_SORTABLE, default=RiskQuantification.last_mean_ale)
    else:
        stmt = stmt.order_by(RiskQuantification.last_mean_ale.desc(), RiskQuantification.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[RiskQuantRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/risk-quantification", response_model=RiskQuantRead, status_code=201, dependencies=[_WRITE])
async def create_quantification(body: RiskQuantCreate, db: DbSession, user: CurrentUser) -> RiskQuantRead:
    await _validate_risk(db, body.risk_id)
    obj = RiskQuantification(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, RiskQuantification, "FAIR")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="risk_quantification",
                           entity_id=obj.id, summary=f"Created risk quantification {obj.reference}: {obj.title}")
    return RiskQuantRead.model_validate(await _load(db, obj.id))


@router.get("/risk-quantification/{qid}", response_model=RiskQuantRead, dependencies=[_READ])
async def get_quantification(qid: uuid.UUID, db: DbSession) -> RiskQuantRead:
    return RiskQuantRead.model_validate(await _load(db, qid))


@router.patch("/risk-quantification/{qid}", response_model=RiskQuantRead, dependencies=[_WRITE])
async def update_quantification(qid: uuid.UUID, body: RiskQuantUpdate, db: DbSession) -> RiskQuantRead:
    obj = await _load(db, qid)
    data = body.model_dump(exclude_unset=True)
    if "risk_id" in data:
        await _validate_risk(db, data["risk_id"])
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return RiskQuantRead.model_validate(await _load(db, qid))


@router.delete("/risk-quantification/{qid}", status_code=204, dependencies=[_WRITE])
async def delete_quantification(qid: uuid.UUID, db: DbSession) -> None:
    obj = await _load(db, qid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================================== monte carlo ===
def _triangular_sample(low: float, mode: float, high: float) -> float:
    """One draw from a triangular distribution, guarding degenerate inputs.

    Clamps a reversed range (min > max) and pins the mode inside [low, high]; when the
    range collapses (min == max) it returns the single point without touching ``random``.
    """
    if high < low:
        low, high = high, low
    if high <= low:
        return low
    if mode < low:
        mode = low
    elif mode > high:
        mode = high
    return random.triangular(low, mode, high)


@router.post("/risk-quantification/{qid}/simulate", response_model=SimulationResult, dependencies=[_WRITE])
async def simulate(qid: uuid.UUID, db: DbSession, user: CurrentUser) -> SimulationResult:
    obj = await _load(db, qid)
    iterations = max(1, int(obj.iterations or 0))

    tef = (float(obj.tef_min or 0), float(obj.tef_likely or 0), float(obj.tef_max or 0))
    lm = (float(obj.lm_min or 0), float(obj.lm_likely or 0), float(obj.lm_max or 0))

    samples = sorted(
        _triangular_sample(*tef) * _triangular_sample(*lm) for _ in range(iterations)
    )

    def pct(p: float) -> float:
        idx = min(len(samples) - 1, max(0, int(round(p * (len(samples) - 1)))))
        return samples[idx]

    p10, p50, p90 = pct(0.10), pct(0.50), pct(0.90)
    mean = sum(samples) / len(samples)
    mx = samples[-1]

    obj.last_mean_ale = round(mean, 2)
    obj.last_p90 = round(p90, 2)
    obj.last_simulated = date.today()
    obj.status = QuantStatus.simulated
    await db.flush()
    await audit_log.record(db, actor=user, action="update", entity_type="risk_quantification",
                           entity_id=obj.id,
                           summary=f"Simulated {obj.reference}: mean ALE {round(mean, 2):,.2f} {obj.currency} "
                                   f"({iterations:,} iterations)")

    return SimulationResult(
        p10=round(p10, 2), p50=round(p50, 2), p90=round(p90, 2),
        mean=round(mean, 2), max=round(mx, 2), iterations=iterations,
    )


# ================================================================== summary ===
class QuantSummaryTop(BaseModel):
    id: uuid.UUID
    title: str
    last_mean_ale: float
    last_p90: float


class QuantSummary(BaseModel):
    total_mean_ale: float
    count_quantified: int
    count_simulated: int
    highest_p90: float
    top: list[QuantSummaryTop]
    #: Decision 4: the currency the figures above are in (converted at today's rate —
    #: an annual loss expectancy is a forward-looking figure, not a dated one).
    reporting_currency: str = "PKR"
    #: Quantifications whose currency has no exchange rate; left out of the total.
    unconverted: list[UnconvertedAmount] = []


@router.get("/risk-quantification-summary", response_model=QuantSummary, dependencies=[_READ],
            summary="Aggregate loss-exposure roll-up across quantified risks")
async def quant_summary(db: DbSession) -> QuantSummary:
    rows = (await db.scalars(select(RiskQuantification).where(RiskQuantification.deleted.is_(False)))).all()
    book = await fx.load_rate_book(db)
    total = fx.MoneyTotal(book)
    converted: list[tuple] = []
    for r in rows:
        mean = book.convert(r.last_mean_ale or 0, r.currency)
        p90 = book.convert(r.last_p90 or 0, r.currency)
        total.add(r.last_mean_ale or 0, r.currency)
        converted.append((r, mean, p90))
    highest_p90 = max((float(p90.amount) for _r, _m, p90 in converted if p90.amount is not None), default=0.0)
    simulated = [r for r in rows if r.last_simulated is not None]
    top = sorted(converted, key=lambda c: float(c[1].amount or 0), reverse=True)[:5]
    return QuantSummary(
        total_mean_ale=fx.money(total.total),
        count_quantified=len(rows),
        count_simulated=len(simulated),
        highest_p90=round(highest_p90, 2),
        top=[
            QuantSummaryTop(
                id=r.id, title=r.title,
                last_mean_ale=round(float(mean.amount or 0), 2),
                last_p90=round(float(p90.amount or 0), 2),
            )
            for r, mean, p90 in top
        ],
        reporting_currency=book.reporting_currency,
        unconverted=[UnconvertedAmount(**u) for u in total.as_dict()["unconverted"]],
    )
