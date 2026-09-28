"""Scenario Analysis + Basel SMA operational-risk capital API.

Completes the Basel operational-risk suite. Two record types:

* ``/scenario-analyses`` — forward-looking op-risk scenarios (frequency × typical
  loss = expected annual loss), filterable by free-text search, Basel event type
  and status.
* ``/capital-calculations`` — Basel III Standardised Approach (SMA) capital, with
  BIC / Loss Component / ILM / ORC computed server-side. The Basel BI bucket edges
  (EUR 1bn / EUR 30bn) are converted into each record's currency at the organisation's
  latest exchange rates; without a rate the capital is not computed and the read says
  which rate is missing (see :func:`sma_thresholds`). Marking a calculation final
  freezes that basis onto it (:func:`_freeze`); ``POST .../reopen`` is the only way
  back to draft, and it needs a reason that goes into the audit trail.
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
    CapitalStatus,
    ScenarioAnalysis,
    ScenarioStatus,
    sma_capital,
)
from app.schemas.common import Page
from app.schemas.scenario import (
    CapitalCreate,
    CapitalRead,
    CapitalReopen,
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
    #: Units of the record's currency per 1 EUR (1 for a EUR record).
    factor: float = 1.0


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
    basis = f"Basel CRE25 bucket edges {edges} at 1 {base} = {factor:,.4f} {code}"
    if dates:
        basis += f" (rate of {', '.join(dates)})"
    return SmaThresholds(BASEL_BI_BUCKET_1 * factor, BASEL_BI_BUCKET_2 * factor, basis, factor)


def _capital_read(obj: CapitalCalculation, book: fx.RateBook) -> CapitalRead:
    """The record with its SMA figures (``models.scenario.sma_capital``): the frozen
    snapshot once final, else computed at today's rates."""
    read = CapitalRead.model_validate(obj)
    if obj.status == CapitalStatus.final and obj.final_at is not None:
        read.basis_frozen = True
        read.bucket = obj.final_bucket
        read.bic = _num(obj.final_bic)
        read.loss_component = _num(obj.final_loss_component) or 0
        read.ilm = _num(obj.final_ilm)
        read.orc = _num(obj.final_orc)
        read.bucket_1_threshold = _num(obj.final_bucket_1)
        read.bucket_2_threshold = _num(obj.final_bucket_2)
        read.fx_factor = _num(obj.final_fx_factor)
        read.threshold_basis = obj.final_basis
        return read
    if obj.status == CapitalStatus.final:
        read.frozen_note = (
            "Marked final before calculations froze their basis, so these figures use "
            "today's exchange rate. Reopen it and mark it final again to freeze them."
        )
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
    read.fx_factor = edges.factor
    read.threshold_basis = edges.basis
    return read


def _num(value) -> float | None:
    return None if value is None else float(value)


def _differs(current, new) -> bool:
    """Whether an update really changes a field; money compares by value (Decimal vs float)."""
    if isinstance(new, float) and current is not None:
        return float(current) != new
    return current != new


def _freeze(obj: CapitalCalculation, book: fx.RateBook, user) -> None:
    """Stamp the basis a calculation is final on: the EUR factor, the bucket edges in its
    currency, and BIC / LC / ILM / ORC as computed now. A final figure is what was filed
    (the ICAAP, the SBP return), so a later rate change must not restate it. Refused
    when the edges cannot be computed — a final figure with no capital is not a figure."""
    edges = sma_thresholds(book, obj.currency)
    if isinstance(edges, str):
        raise HTTPException(status_code=409, detail=f"Cannot mark the calculation final. {edges}")
    result = sma_capital(obj.business_indicator, obj.avg_annual_loss, edges.bucket_1, edges.bucket_2)
    obj.final_at = datetime.now(timezone.utc)
    obj.final_by = user.email
    obj.final_fx_factor = edges.factor
    obj.final_bucket_1 = round(edges.bucket_1, 2)
    obj.final_bucket_2 = round(edges.bucket_2, 2)
    obj.final_basis = edges.basis
    obj.final_bucket = result.bucket
    obj.final_bic = round(result.bic, 2)
    obj.final_loss_component = round(result.loss_component, 2)
    obj.final_ilm = round(result.ilm, 6)
    obj.final_orc = round(result.orc, 2)


def _snapshot(obj: CapitalCalculation) -> dict:
    """The frozen basis as plain values, for the audit entry of a reopen."""
    return {
        "final_at": obj.final_at.isoformat() if obj.final_at else None,
        "final_by": obj.final_by,
        "currency": obj.currency,
        "business_indicator": _num(obj.business_indicator),
        "avg_annual_loss": _num(obj.avg_annual_loss),
        "fx_factor": _num(obj.final_fx_factor),
        "bucket_1": _num(obj.final_bucket_1),
        "bucket_2": _num(obj.final_bucket_2),
        "basis": obj.final_basis,
        "bucket": obj.final_bucket,
        "bic": _num(obj.final_bic),
        "loss_component": _num(obj.final_loss_component),
        "ilm": _num(obj.final_ilm),
        "orc": _num(obj.final_orc),
    }


def _unfreeze(obj: CapitalCalculation) -> None:
    obj.final_at = None
    obj.final_by = ""
    obj.final_basis = ""
    for col in ("final_fx_factor", "final_bucket_1", "final_bucket_2", "final_bucket",
                "final_bic", "final_loss_component", "final_ilm", "final_orc"):
        setattr(obj, col, None)


#: Fields that decide the figure. Locked while final; only a reopen unlocks them.
_CAPITAL_INPUTS = ("period", "business_indicator", "avg_annual_loss", "currency")


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
    book = await fx.load_rate_book(db)
    if obj.status == CapitalStatus.final:
        _freeze(obj, book, user)
    obj.reference = await _next_ref(db, CapitalCalculation, "CAP")
    db.add(obj)
    await db.flush()
    final = " and marked it final" if obj.final_at else ""
    await audit_log.record(db, actor=user, action="create", entity_type="capital_calculation",
                           entity_id=obj.id,
                           summary=f"Computed SMA capital {obj.reference} ({obj.period}){final}")
    return _capital_read(obj, book)


@router.get("/capital-calculations/{cid}", response_model=CapitalRead, dependencies=[_READ])
async def get_capital(cid: uuid.UUID, db: DbSession) -> CapitalRead:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    return _capital_read(obj, await fx.load_rate_book(db))


@router.patch("/capital-calculations/{cid}", response_model=CapitalRead, dependencies=[_WRITE])
async def update_capital(cid: uuid.UUID, body: CapitalUpdate, db: DbSession,
                         user: CurrentUser) -> CapitalRead:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    changed = {k: v for k, v in data.items() if _differs(getattr(obj, k), v)}
    was_final = obj.status == CapitalStatus.final
    if was_final:
        locked = sorted(k for k in changed if k in _CAPITAL_INPUTS or k == "status")
        if locked:
            raise HTTPException(
                status_code=409,
                detail=f"{obj.reference} is final, so {', '.join(locked)} cannot change. "
                       "Reopen it (with a reason) to make it a draft again.",
            )
    for k, v in changed.items():
        setattr(obj, k, v)
    book = await fx.load_rate_book(db)
    finalised = not was_final and obj.status == CapitalStatus.final
    if finalised:
        _freeze(obj, book, user)
    await db.flush()
    if changed:
        if finalised:
            summary = f"Marked SMA capital {obj.reference} final (ORC {obj.final_orc:,.2f} {obj.currency})"
        else:
            summary = f"Updated SMA capital {obj.reference} ({', '.join(sorted(changed))})"
        await audit_log.record(
            db, actor=user, action="finalise" if finalised else "update",
            entity_type="capital_calculation", entity_id=obj.id, summary=summary,
            changes={"basis": _snapshot(obj)} if finalised else None,
        )
    return _capital_read(obj, book)


REOPEN_OWN_FINAL = (
    "Segregation of duties: you marked this capital figure final, so someone else must reopen it. "
    "A final figure is what was filed (the ICAAP, the SBP return); unlocking it takes a second person."
)


async def _check_reopen_four_eyes(db, obj: CapitalCalculation, user) -> None:
    """Dual control ``(capital_calculation, reopen)``: reopening unlocks a figure that may
    already be filed, so it is an amendment of an authorised record — as a core-banking
    system would, it needs a second person: whoever marked the figure final may not
    reopen it (a rule's checker role, where one is named, also applies)."""
    from app.models.identity import User
    from app.services import dual_control

    required, rule = await dual_control.dual_control_required(
        db, "capital_calculation", "reopen", amount=float(obj.final_orc or 0) or None,
    )
    if not required:
        return
    finaliser = (obj.final_by or "").strip().lower()
    if finaliser and finaliser == (user.email or "").strip().lower():
        raise HTTPException(status_code=403, detail=REOPEN_OWN_FINAL)
    maker_id = await db.scalar(select(User.id).where(func.lower(User.email) == finaliser)) if finaliser else None
    await dual_control.enforce_checker_role(db, rule, module="capital_calculation", action="reopen",
                                            checker_id=user.id, maker_id=maker_id)


@router.post("/capital-calculations/{cid}/reopen", response_model=CapitalRead, dependencies=[_WRITE],
             summary="Put a final capital calculation back to draft (reasoned, audited)")
async def reopen_capital(cid: uuid.UUID, body: CapitalReopen, db: DbSession,
                         user: CurrentUser) -> CapitalRead:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    if obj.status != CapitalStatus.final:
        raise HTTPException(status_code=409, detail=f"{obj.reference} is not final, so there is nothing to reopen.")
    await _check_reopen_four_eyes(db, obj, user)
    frozen = _snapshot(obj)
    obj.status = CapitalStatus.draft
    _unfreeze(obj)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="reopen", entity_type="capital_calculation", entity_id=obj.id,
        summary=f"Reopened final SMA capital {obj.reference} ({obj.period}): {body.reason.strip()}"[:500],
        changes={"reason": body.reason.strip(), "frozen_basis": frozen},
    )
    return _capital_read(obj, await fx.load_rate_book(db))


@router.delete("/capital-calculations/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_capital(cid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _get(db, CapitalCalculation, cid, "Capital calculation")
    if obj.status == CapitalStatus.final:
        # A filed figure does not disappear quietly: reopening records who and why first.
        raise HTTPException(
            status_code=409,
            detail=f"{obj.reference} is final. Reopen it (with a reason) before archiving it.",
        )
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit_log.record(db, actor=user, action="delete", entity_type="capital_calculation",
                           entity_id=obj.id, summary=f"Archived SMA capital {obj.reference} ({obj.period})")


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
            basis_frozen=figures.basis_frozen,
            final_at=figures.final_at,
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
