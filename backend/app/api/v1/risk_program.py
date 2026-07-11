"""Enterprise risk program: appetite/tolerance settings, breach alerts, and roll-up."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.risk import Risk
from app.schemas.risk import (
    RiskAggregate,
    RiskAggregateRow,
    RiskRead,
    RiskSettingRead,
    RiskSettingUpdate,
)
from app.services.risk_scoring import effective_score
from app.services.risk_settings import get_or_create_settings

router = APIRouter(tags=["risk program"])


class MatrixCell(BaseModel):
    likelihood: int
    impact: int
    score: int
    inherent_count: int
    residual_count: int
    inherent_refs: list[str]
    residual_refs: list[str]


class RiskMatrix(BaseModel):
    cells: list[MatrixCell]
    appetite_score: int
    tolerance_score: int
    total: int


@router.get(
    "/risk-settings", response_model=RiskSettingRead, dependencies=[Depends(require("risk:read"))]
)
async def get_risk_settings(db: DbSession, user: CurrentUser) -> RiskSettingRead:
    return RiskSettingRead.model_validate(await get_or_create_settings(db, user.tenant_id))


@router.put(
    "/risk-settings", response_model=RiskSettingRead, dependencies=[Depends(require("risk:write"))]
)
async def update_risk_settings(
    body: RiskSettingUpdate, db: DbSession, user: CurrentUser
) -> RiskSettingRead:
    settings = await get_or_create_settings(db, user.tenant_id)
    settings.appetite_score = body.appetite_score
    settings.tolerance_score = body.tolerance_score
    await db.flush()
    return RiskSettingRead.model_validate(settings)


@router.get(
    "/risk-alerts",
    response_model=list[RiskRead],
    dependencies=[Depends(require("risk:read"))],
    summary="Risks whose effective score breaches the tolerance threshold",
)
async def risk_alerts(db: DbSession, user: CurrentUser) -> list[RiskRead]:
    settings = await get_or_create_settings(db, user.tenant_id)
    risks = (await db.scalars(select(Risk).where(Risk.deleted.is_(False)))).all()
    breached = [
        r
        for r in risks
        if (eff := effective_score(r.inherent_score, r.residual_score)) is not None
        and eff > settings.tolerance_score
    ]
    breached.sort(
        key=lambda r: effective_score(r.inherent_score, r.residual_score) or 0, reverse=True
    )
    return [RiskRead.model_validate(r) for r in breached]


@router.get(
    "/risk-matrix",
    response_model=RiskMatrix,
    dependencies=[Depends(require("risk:read"))],
    summary="5x5 likelihood-by-impact heatmap counts (inherent & residual)",
)
async def risk_matrix(db: DbSession, user: CurrentUser) -> RiskMatrix:
    settings = await get_or_create_settings(db, user.tenant_id)
    risks = (await db.scalars(select(Risk).where(Risk.deleted.is_(False)))).all()

    inherent: dict[tuple[int, int], list[str]] = defaultdict(list)
    residual: dict[tuple[int, int], list[str]] = defaultdict(list)
    for r in risks:
        il, ii = getattr(r, "inherent_likelihood", None), getattr(r, "inherent_impact", None)
        if il and ii:
            inherent[(il, ii)].append(r.reference)
        # Residual falls back to inherent when a risk hasn't been separately re-scored.
        rl = getattr(r, "residual_likelihood", None) or il
        ri = getattr(r, "residual_impact", None) or ii
        if rl and ri:
            residual[(rl, ri)].append(r.reference)

    cells: list[MatrixCell] = []
    for likelihood in range(1, 6):
        for impact in range(1, 6):
            ic = inherent.get((likelihood, impact), [])
            rc = residual.get((likelihood, impact), [])
            cells.append(
                MatrixCell(
                    likelihood=likelihood,
                    impact=impact,
                    score=likelihood * impact,
                    inherent_count=len(ic),
                    residual_count=len(rc),
                    inherent_refs=ic[:25],
                    residual_refs=rc[:25],
                )
            )
    return RiskMatrix(
        cells=cells,
        appetite_score=settings.appetite_score,
        tolerance_score=settings.tolerance_score,
        total=len(risks),
    )


@router.get(
    "/risk-aggregate",
    response_model=RiskAggregate,
    dependencies=[Depends(require("risk:read"))],
    summary="Enterprise roll-up of risks by category",
)
async def risk_aggregate(db: DbSession, user: CurrentUser) -> RiskAggregate:
    settings = await get_or_create_settings(db, user.tenant_id)
    risks = (await db.scalars(select(Risk).where(Risk.deleted.is_(False)))).all()

    groups: dict[str, dict] = {}
    for r in risks:
        cat = r.category or "Uncategorized"
        g = groups.setdefault(
            cat, {"count": 0, "max_inh": None, "max_res": None, "breaches": 0, "exposure": 0.0}
        )
        g["count"] += 1
        if r.inherent_score is not None:
            g["max_inh"] = max(g["max_inh"] or 0, r.inherent_score)
        if r.residual_score is not None:
            g["max_res"] = max(g["max_res"] or 0, r.residual_score)
        eff = effective_score(r.inherent_score, r.residual_score)
        if eff is not None and eff > settings.tolerance_score:
            g["breaches"] += 1
        if r.annual_loss_expectancy:
            g["exposure"] += r.annual_loss_expectancy

    rows = [
        RiskAggregateRow(
            category=cat,
            count=g["count"],
            max_inherent_score=g["max_inh"],
            max_residual_score=g["max_res"],
            breaches=g["breaches"],
            exposure=round(g["exposure"], 2),
        )
        for cat, g in sorted(groups.items())
    ]
    total = round(sum(g["exposure"] for g in groups.values()), 2)
    return RiskAggregate(
        rows=rows,
        total_exposure=total,
        appetite_score=settings.appetite_score,
        tolerance_score=settings.tolerance_score,
    )
