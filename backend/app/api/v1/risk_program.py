"""Enterprise risk program: appetite/tolerance, the configurable matrix, breach alerts,
the residual-suggestion policy, and the category roll-up."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.risk import Risk, RiskMatrixLevel
from app.schemas.risk import (
    MatrixBand,
    MatrixLevel,
    ResidualPolicyRead,
    ResidualPolicyUpdate,
    RiskAggregate,
    RiskAggregateRow,
    RiskMatrixConfig,
    RiskMatrixConfigUpdate,
    RiskRead,
    RiskSettingRead,
    RiskSettingUpdate,
)
from app.services import audit as audit_log
from app.services.risk_scoring import band_ranges, effective_score, max_score_for
from app.services.risk_settings import (
    default_label,
    get_levels,
    get_or_create_residual_policy,
    get_or_create_settings,
)

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
    # The matrix the counts were plotted on, so the client renders the right grid and
    # colours it with the same bands the server used — no duplicated thresholds.
    size: int = 5
    max_score: int = 25
    likelihood_levels: list[MatrixLevel] = []
    impact_levels: list[MatrixLevel] = []
    bands: list[MatrixBand] = []


def _levels_for(
    axis: str, size: int, configured: dict[str, dict[int, RiskMatrixLevel]]
) -> list[MatrixLevel]:
    """The axis' rungs 1..size, falling back to generic wording where unconfigured."""
    rows = configured.get(axis, {})
    out: list[MatrixLevel] = []
    for level in range(1, size + 1):
        row = rows.get(level)
        out.append(
            MatrixLevel(
                level=level,
                label=(row.label if row and row.label else default_label(axis, level)),
                definition=(row.definition if row else ""),
            )
        )
    return out


def _bands_for(max_score: int) -> list[MatrixBand]:
    return [
        MatrixBand(severity=sev, min_score=low, max_score=high)
        for low, high, sev in band_ranges(max_score)
    ]


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
    ceiling = max_score_for(settings.matrix_size)
    for name, value in (("Appetite", body.appetite_score), ("Tolerance", body.tolerance_score)):
        if value > ceiling:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{name} score {value} exceeds the maximum score of {ceiling} on a "
                    f"{settings.matrix_size}x{settings.matrix_size} matrix"
                ),
            )
    if body.appetite_score > body.tolerance_score:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Appetite cannot be higher than tolerance — nothing would ever be 'elevated'",
        )
    settings.appetite_score = body.appetite_score
    settings.tolerance_score = body.tolerance_score
    await db.flush()
    return RiskSettingRead.model_validate(settings)


# ---------------------------------------------------------------------------
# Configurable matrix — size and the bank's own scale definitions
# ---------------------------------------------------------------------------
@router.get(
    "/risk-matrix-config",
    response_model=RiskMatrixConfig,
    dependencies=[Depends(require("risk:read"))],
    summary="Matrix size, per-level scale definitions and the derived severity bands",
)
async def get_matrix_config(db: DbSession, user: CurrentUser) -> RiskMatrixConfig:
    settings = await get_or_create_settings(db, user.tenant_id)
    size = settings.matrix_size
    configured = await get_levels(db, user.tenant_id)
    return RiskMatrixConfig(
        size=size,
        max_score=max_score_for(size),
        appetite_score=settings.appetite_score,
        tolerance_score=settings.tolerance_score,
        likelihood_levels=_levels_for("likelihood", size, configured),
        impact_levels=_levels_for("impact", size, configured),
        bands=_bands_for(max_score_for(size)),
    )


@router.put(
    "/risk-matrix-config",
    response_model=RiskMatrixConfig,
    dependencies=[Depends(require("risk:write"))],
    summary="Resize the matrix and record the scale definitions",
)
async def update_matrix_config(
    body: RiskMatrixConfigUpdate, db: DbSession, user: CurrentUser
) -> RiskMatrixConfig:
    """Resize the matrix and store each rung's wording.

    **Shrinking is refused while any risk still scores above the new maximum.** Silently
    clamping would rewrite assessed scores — the assessor's judgement — so the API names
    the offending risks and leaves the data alone for someone to re-score deliberately.
    """
    settings = await get_or_create_settings(db, user.tenant_id)
    size = body.size

    if size < settings.matrix_size:
        too_big = (
            await db.scalars(
                select(Risk).where(
                    Risk.deleted.is_(False),
                    (Risk.inherent_likelihood > size)
                    | (Risk.inherent_impact > size)
                    | (Risk.residual_likelihood > size)
                    | (Risk.residual_impact > size),
                )
            )
        ).all()
        if too_big:
            names = ", ".join(r.reference or r.title for r in too_big[:10])
            more = f" and {len(too_big) - 10} more" if len(too_big) > 10 else ""
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{len(too_big)} risk(s) score above {size} and would have to be "
                    f"re-scored first: {names}{more}"
                ),
            )

    settings.matrix_size = size
    # Keep appetite/tolerance inside the new scale rather than leaving thresholds no
    # score can ever reach (or, when growing, a tolerance that is now trivially low).
    ceiling = max_score_for(size)
    settings.appetite_score = min(settings.appetite_score, ceiling)
    settings.tolerance_score = min(settings.tolerance_score, ceiling)

    existing = await get_levels(db, user.tenant_id)
    for axis, levels in (("likelihood", body.likelihood_levels), ("impact", body.impact_levels)):
        for item in levels:
            if item.level > size:
                continue  # a rung outside the new scale is dropped, not stored
            row = existing.get(axis, {}).get(item.level)
            if row is None:
                row = RiskMatrixLevel(tenant_id=user.tenant_id, axis=axis, level=item.level)
                db.add(row)
            row.label = item.label
            row.definition = item.definition

    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="risk_settings", entity_id=settings.id,
        summary=f"Risk matrix set to {size}x{size}",
        changes={"matrix_size": size},
    )
    return await get_matrix_config(db, user)


# ---------------------------------------------------------------------------
# Residual-suggestion policy
# ---------------------------------------------------------------------------
@router.get(
    "/residual-policy",
    response_model=ResidualPolicyRead,
    dependencies=[Depends(require("risk:read"))],
    summary="How much residual credit a control earns, per effectiveness rating",
)
async def get_residual_policy(db: DbSession, user: CurrentUser) -> ResidualPolicyRead:
    return ResidualPolicyRead.model_validate(
        await get_or_create_residual_policy(db, user.tenant_id)
    )


@router.put(
    "/residual-policy",
    response_model=ResidualPolicyRead,
    dependencies=[Depends(require("risk:write"))],
)
async def update_residual_policy(
    body: ResidualPolicyUpdate, db: DbSession, user: CurrentUser
) -> ResidualPolicyRead:
    policy = await get_or_create_residual_policy(db, user.tenant_id)
    for name, value in body.model_dump().items():
        setattr(policy, name, value)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="risk_settings", entity_id=policy.id,
        summary="Updated the residual-risk suggestion policy",
        changes=body.model_dump(),
    )
    return ResidualPolicyRead.model_validate(policy)


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
    context = {"max_score": max_score_for(settings.matrix_size)}
    return [RiskRead.model_validate(r, context=context) for r in breached]


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

    size = settings.matrix_size
    configured = await get_levels(db, user.tenant_id)
    cells: list[MatrixCell] = []
    for likelihood in range(1, size + 1):
        for impact in range(1, size + 1):
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
        size=size,
        max_score=max_score_for(size),
        likelihood_levels=_levels_for("likelihood", size, configured),
        impact_levels=_levels_for("impact", size, configured),
        bands=_bands_for(max_score_for(size)),
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
