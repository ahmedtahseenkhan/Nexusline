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
    rows = (
        await db.scalars(select(Risk).execution_options(populate_existing=True))
    ).all()

    by_status: Counter[str] = Counter()
    by_inherent: Counter[str] = Counter()
    by_residual: Counter[str] = Counter()
    overdue = 0
    appetite_counts: Counter[str] = Counter()
    total_exposure = 0.0
    today = date.today()

    for r in rows:
        by_status[r.status.value] += 1
        inh = severity_for_score(r.inherent_score)
        if inh:
            by_inherent[inh.value] += 1
        res = severity_for_score(r.residual_score)
        if res:
            by_residual[res.value] += 1
        if r.next_review_date and r.next_review_date < today:
            overdue += 1
        status = appetite_status(
            effective_score(r.inherent_score, r.residual_score),
            settings.appetite_score,
            settings.tolerance_score,
        )
        if status:
            appetite_counts[status] += 1
        if r.annual_loss_expectancy:
            total_exposure += r.annual_loss_expectancy

    total_controls = await db.scalar(select(func.count()).select_from(Control)) or 0
    total_assets = await db.scalar(select(func.count()).select_from(Asset)) or 0
    pending = (
        await db.scalar(
            select(func.count())
            .select_from(RiskAcceptance)
            .where(RiskAcceptance.status == AcceptanceStatus.pending)
        )
        or 0
    )

    return DashboardStats(
        total_risks=len(rows),
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
