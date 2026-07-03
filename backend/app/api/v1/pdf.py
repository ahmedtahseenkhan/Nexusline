"""PDF report endpoints — board packs, audit-committee, Shariah-board and risk reports.

Each streams a generated PDF (``application/pdf``) scoped to the caller's tenant.
Guarded by the same read permission as the underlying module.
"""
from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.internal_audit import AuditEngagement
from app.models.shariah import ShariahReview
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.services import pdf_report
from app.services.risk_settings import get_or_create_settings

router = APIRouter(prefix="/reports/pdf", tags=["reports"])


async def _org_name(db, user) -> str:
    t = await db.scalar(select(Tenant).where(Tenant.id == user.tenant_id))
    return t.name if t else "Organization"


def _pdf(data: bytes, filename: str) -> Response:
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/audit-engagement/{eid}", dependencies=[Depends(require("internal_audit:read"))])
async def audit_engagement_report(eid: uuid.UUID, db: DbSession, user: CurrentUser) -> Response:
    eng = await db.scalar(select(AuditEngagement).where(AuditEngagement.id == eid))
    if eng is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    data = pdf_report.audit_engagement_pdf(eng, await _org_name(db, user))
    return _pdf(data, f"audit-{eng.reference}.pdf")


@router.get("/shariah-review/{rid}", dependencies=[Depends(require("shariah:read"))])
async def shariah_review_report(rid: uuid.UUID, db: DbSession, user: CurrentUser) -> Response:
    rev = await db.scalar(select(ShariahReview).where(ShariahReview.id == rid))
    if rev is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shariah review not found")
    data = pdf_report.shariah_review_pdf(rev, await _org_name(db, user))
    return _pdf(data, f"shariah-{rev.reference}.pdf")


@router.get("/risk-register", dependencies=[Depends(require("risk:read"))])
async def risk_register_report(db: DbSession, user: CurrentUser) -> Response:
    settings = await get_or_create_settings(db, user.tenant_id)
    risks = (await db.scalars(
        select(Risk).where(Risk.deleted.is_(False)).order_by(Risk.reference)
    )).all()
    data = pdf_report.risk_register_pdf(
        list(risks), settings.appetite_score, settings.tolerance_score, await _org_name(db, user)
    )
    return _pdf(data, "risk-register.pdf")


@router.get("/executive-summary", dependencies=[Depends(require("risk:read"))])
async def executive_summary_report(db: DbSession, user: CurrentUser) -> Response:
    from app.api.v1.dashboard import get_dashboard

    stats = await get_dashboard(db, user)
    data = pdf_report.executive_summary_pdf(stats.model_dump(), await _org_name(db, user))
    return _pdf(data, "executive-summary.pdf")
