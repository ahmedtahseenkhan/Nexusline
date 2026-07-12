"""Aggregate stats for the risk dashboard."""
from __future__ import annotations

from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.core.deps import DbSession, require
from app.models.asset import Asset
from app.models.control import Control
from app.models.enums import AcceptanceStatus
from app.models.risk import Risk, RiskAcceptance
from app.core.deps import CurrentUser
from app.schemas.dashboard import DashboardStats
from app.services.risk_scoring import appetite_status, effective_score, severity_for_score
from app.services.risk_settings import get_or_create_settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats, dependencies=[Depends(require("risk:read"))])
async def get_dashboard(db: DbSession, user: CurrentUser) -> DashboardStats:
    settings = await get_or_create_settings(db, user.tenant_id)
    today = date.today()
    live = Risk.deleted.is_(False)

    # Pure-column tallies aggregate in SQL — no ORM hydration of the whole register.
    total_risks = await db.scalar(select(func.count()).select_from(Risk).where(live)) or 0
    total_exposure = float(
        await db.scalar(
            select(func.coalesce(func.sum(Risk.annual_loss_expectancy), 0)).where(live)
        )
        or 0
    )
    overdue = (
        await db.scalar(
            select(func.count()).select_from(Risk).where(live, Risk.next_review_date < today)
        )
        or 0
    )
    by_status: Counter[str] = Counter()
    for status_val, cnt in (
        await db.execute(select(Risk.status, func.count()).where(live).group_by(Risk.status))
    ).all():
        by_status[status_val.value] = cnt

    # Severity/appetite bands keep the scoring functions as the single source of truth,
    # so fetch just the two score columns (lightweight tuples, not full ORM objects).
    by_inherent: Counter[str] = Counter()
    by_residual: Counter[str] = Counter()
    appetite_counts: Counter[str] = Counter()
    for inherent, residual in (
        await db.execute(select(Risk.inherent_score, Risk.residual_score).where(live))
    ).all():
        inh = severity_for_score(inherent)
        if inh:
            by_inherent[inh.value] += 1
        res = severity_for_score(residual)
        if res:
            by_residual[res.value] += 1
        status = appetite_status(
            effective_score(inherent, residual),
            settings.appetite_score,
            settings.tolerance_score,
        )
        if status:
            appetite_counts[status] += 1

    total_controls = await db.scalar(
        select(func.count()).select_from(Control).where(Control.deleted.is_(False))
    ) or 0
    total_assets = await db.scalar(
        select(func.count()).select_from(Asset).where(Asset.deleted.is_(False))
    ) or 0
    pending = (
        await db.scalar(
            select(func.count())
            .select_from(RiskAcceptance)
            .join(Risk, Risk.id == RiskAcceptance.risk_id)
            .where(RiskAcceptance.status == AcceptanceStatus.pending, Risk.deleted.is_(False))
        )
        or 0
    )

    return DashboardStats(
        total_risks=total_risks,
        total_controls=total_controls,
        total_assets=total_assets,
        risks_by_status=dict(by_status),
        risks_by_inherent_severity=dict(by_inherent),
        risks_by_residual_severity=dict(by_residual),
        overdue_reviews=overdue,
        pending_acceptances=pending,
        appetite_score=settings.appetite_score,
        tolerance_score=settings.tolerance_score,
        risks_within_appetite=appetite_counts["within_appetite"],
        risks_elevated=appetite_counts["elevated"],
        risks_in_breach=appetite_counts["breach"],
        total_exposure=round(total_exposure, 2),
    )
