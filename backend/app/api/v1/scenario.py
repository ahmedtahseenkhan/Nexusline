"""Scenario Analysis + Basel SMA operational-risk capital API.

Completes the Basel operational-risk suite. Two record types:

* ``/scenario-analyses`` — forward-looking op-risk scenarios (frequency × typical
  loss = expected annual loss), filterable by free-text search, Basel event type
  and status.
* ``/capital-calculations`` — Basel III Standardised Approach (SMA) capital, with
  BIC / Loss Component / ILM / ORC computed server-side. The Basel BI bucket edges
  (EUR 1bn / EUR 30bn) are converted into each record's currency at the organisation's
  latest exchange rates; without a rate the capital is not computed and the read says
  which rate is missing (see :func:`sma_thresholds`).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.enums import BaselEventType
from app.models.scenario import (
    BASEL_BI_BUCKET_1,
    BASEL_BI_BUCKET_2,
    BASEL_THRESHOLD_CURRENCY,
    CapitalCalculation,
    ScenarioAnalysis,
    ScenarioStatus,
    sma_capital,
)
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
from app.services.refs import next_reference
from app.schemas.fx import UnconvertedAmount
from app.services import audit as audit_log
from app.services import fx

router = APIRouter(tags=["scenario analysis"])

_READ = Depends(require("scenario:read"))
_WRITE = Depends(require("scenario:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ===================================================== scenario analyses ===
# `expected_annual_loss` is computed (frequency × typical loss); its component columns
# are sortable instead.
_SCENARIO_SORTABLE = {
    "reference": ScenarioAnalysis.reference,
    "title": ScenarioAnalysis.title,
    "basel_event_type": ScenarioAnalysis.basel_event_type,
    "business_line": ScenarioAnalysis.business_line,
    "frequency_per_year": ScenarioAnalysis.frequency_per_year,
    "typical_loss": ScenarioAnalysis.typical_loss,
    "worst_case_loss": ScenarioAnalysis.worst_case_loss,
    "status": ScenarioAnalysis.status,
    "created_at": ScenarioAnalysis.created_at,
}


@router.get("/scenario-analyses", response_model=Page[ScenarioRead], dependencies=[_READ])
async def list_scenarios(
    db: DbSession,
    search: Annotated[str | None, Query()] = None,
    basel_event_type: Annotated[BaselEventType | None, Query()] = None,
    status_filter: Annotated[ScenarioStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
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
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _SCENARIO_SORTABLE, default=ScenarioAnalysis.created_at)
    else:
        stmt = stmt.order_by(ScenarioAnalysis.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
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
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()


# ===================================================== capital calculations ===
@dataclass(frozen=True)
class SmaThresholds:
    """The Basel BI bucket edges in one currency, and how they were obtained."""

    bucket_1: float
    bucket_2: float
    basis: str


def sma_thresholds(book: fx.RateBook, currency: str | None, on_date: date | None = None) -> SmaThresholds | str:
    """The EUR 1bn / EUR 30bn bucket edges (CRE25.4) expressed in ``currency``.

    Converted through the reporting currency at the latest rates on or before
    ``on_date`` (today): 1 EUR = rate(EUR) / rate(currency) units of ``currency``. The
    edges are restated at the rate current when the figure is read, as a supervisor
    restates them for its own currency. Returns the refusal text instead when a rate is
    missing — bucketing a PKR 100bn BI without knowing what EUR 1bn is worth in PKR
    would be a guess about which of three coefficients applies.
    """
    base = BASEL_THRESHOLD_CURRENCY
    code = fx.normalise(currency, book.reporting_currency)
    edges = f"{base} {BASEL_BI_BUCKET_1 / 1e9:g}bn / {base} {BASEL_BI_BUCKET_2 / 1e9:g}bn"
    if code == base:
        return SmaThresholds(BASEL_BI_BUCKET_1, BASEL_BI_BUCKET_2, f"Basel CRE25 bucket edges {edges}")
    eur = book.rate_for(base, on_date)
    own = book.rate_for(code, on_date)
    missing = [c for c, r in ((base, eur), (code, own)) if r is None]
    if missing:
        return (
            f"No {' or '.join(missing)} → {book.reporting_currency} exchange rate, so the Basel "
            f"bucket edges ({edges}) cannot be expressed in {code} and the capital is not "
            "computed. Add the rate under Organisation settings → Exchange rates."
        )
    factor = float(eur[0]) / float(own[0])
    dates = sorted({d.isoformat() for _r, d in (eur, own) if d is not None})
    return SmaThresholds(
        BASEL_BI_BUCKET_1 * factor,
        BASEL_BI_BUCKET_2 * factor,
        f"Basel CRE25 bucket edges {edges} at 1 {base} = {factor:,.4f} {code}"
        + (f" (rate of {', '.join(dates)})" if dates else ""),
    )


def _capital_read(obj: CapitalCalculation, book: fx.RateBook) -> CapitalRead:
    """The record with its SMA figures (``models.scenario.sma_capital``)."""
    read = CapitalRead.model_validate(obj)
    read.loss_component = round(15.0 * float(obj.avg_annual_loss or 0), 2)
    edges = sma_thresholds(book, obj.currency)
    if isinstance(edges, str):
        read.threshold_note = edges
        return read
    result = sma_capital(obj.business_indicator, obj.avg_annual_loss, edges.bucket_1, edges.bucket_2)
    read.bucket = result.bucket
    read.bic = round(result.bic, 2)
    read.loss_component = round(result.loss_component, 2)
    read.ilm = round(result.ilm, 4)
    read.orc = round(result.orc, 2)
    read.bucket_1_threshold = round(edges.bucket_1, 2)
    read.bucket_2_threshold = round(edges.bucket_2, 2)
    read.threshold_basis = edges.basis
    return read


# BIC / Loss Component / ILM / ORC are all computed server-side, so only the input
# columns are sortable.
_CAPITAL_SORTABLE = {
    "reference": CapitalCalculation.reference,
    "period": CapitalCalculation.period,
    "business_indicator": CapitalCalculation.business_indicator,
    "avg_annual_loss": CapitalCalculation.avg_annual_loss,
    "status": CapitalCalculation.status,
    "created_at": CapitalCalculation.created_at,
}


@router.get("/capital-calculations", response_model=Page[CapitalRead], dependencies=[_READ])
async def list_capital(db: DbSession, search: str | None = None,
                       sort_by: Annotated[str | None, Query()] = None,
                       sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                       limit: Annotated[int, Query(ge=1, le=200)] = 100,
                       offset: Annotated[int, Query(ge=0)] = 0) -> Page[CapitalRead]:
    stmt = select(CapitalCalculation).where(CapitalCalculation.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(CapitalCalculation.period.ilike(like), CapitalCalculation.reference.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _CAPITAL_SORTABLE, default=CapitalCalculation.created_at)
    else:
        stmt = stmt.order_by(CapitalCalculation.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    book = await fx.load_rate_book(db)
    return Page(items=[_capital_read(r, book) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/capital-calculations", response_model=CapitalRead, status_code=201, dependencies=[_WRITE])
async def create_capital(body: CapitalCreate, db: DbSession, user: CurrentUser) -> CapitalRead:
    obj = CapitalCalculation(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, CapitalCalculation, "CAP")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="capital_calculation",
                           entity_id=obj.id, summary=f"Computed SMA capital {obj.reference} ({obj.period})")
    return _capital_read(obj, await fx.load_rate_book(db))


@router.get("/capital-calculations/{cid}", response_model=CapitalRead, dependencies=[_READ])
async def get_capital(cid: uuid.UUID, db: DbSession) -> CapitalRead:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    return _capital_read(obj, await fx.load_rate_book(db))


@router.patch("/capital-calculations/{cid}", response_model=CapitalRead, dependencies=[_WRITE])
async def update_capital(cid: uuid.UUID, body: CapitalUpdate, db: DbSession) -> CapitalRead:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return _capital_read(obj, await fx.load_rate_book(db))


@router.delete("/capital-calculations/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_capital(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()


# ================================================================= summary ===
@router.get("/scenario-summary", response_model=ScenarioSummary, dependencies=[_READ],
            summary="Scenario roll-up by Basel event type + latest SMA capital")
async def scenario_summary(db: DbSession) -> ScenarioSummary:
    scenarios = (await db.scalars(
        select(ScenarioAnalysis).where(ScenarioAnalysis.deleted.is_(False)))).all()
    # Decision 4: a scenario's expected annual loss is forward-looking, so it converts at
    # today's rate; a currency with no rate is reported, never added in.
    book = await fx.load_rate_book(db)
    groups: dict[str, fx.MoneyTotal] = defaultdict(lambda: fx.MoneyTotal(book))
    all_eal = fx.MoneyTotal(book)
    approved = 0
    for s in scenarios:
        groups[s.basel_event_type.value].add(s.expected_annual_loss, s.currency)
        all_eal.add(s.expected_annual_loss, s.currency)
        if s.status == ScenarioStatus.approved:
            approved += 1
    rows = [ScenarioSummaryRow(basel_event_type=k, count=v.count,
                               expected_annual_loss=fx.money(v.total))
            for k, v in sorted(groups.items())]

    latest = await db.scalar(
        select(CapitalCalculation)
        .where(CapitalCalculation.deleted.is_(False))
        .order_by(CapitalCalculation.created_at.desc())
    )
    latest_capital = None
    if latest is not None:
        figures = _capital_read(latest, book)
        latest_capital = CapitalSnapshot(
            reference=latest.reference,
            period=latest.period,
            bucket=figures.bucket,
            bic=figures.bic,
            loss_component=figures.loss_component,
            ilm=figures.ilm,
            orc=figures.orc,
            currency=latest.currency,
            threshold_note=figures.threshold_note,
        )

    return ScenarioSummary(
        rows=rows,
        total_expected_annual_loss=fx.money(all_eal.total),
        total_count=sum(r.count for r in rows),
        approved_count=approved,
        latest_capital=latest_capital,
        reporting_currency=book.reporting_currency,
        unconverted=[UnconvertedAmount(**u) for u in all_eal.as_dict()["unconverted"]],
    )
