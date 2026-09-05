"""PDF report endpoints — board packs, audit-committee, Shariah-board and risk reports.

Each streams a generated PDF (``application/pdf``) scoped to the caller's tenant.
Guarded by the same read permission as the underlying module.
"""
from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.v1.risks import build_risk_query
from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import Asset
from app.models.enums import RiskStatus
from app.models.identity import User
from app.models.internal_audit import AuditEngagement
from app.models.organization import BusinessUnit, Process
from app.models.shariah import ShariahReview
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.services import pdf_report
from app.services.risk_scoring import max_score_for
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
    eng = await db.scalar(
        select(AuditEngagement).where(
            AuditEngagement.id == eid, AuditEngagement.deleted.is_(False)
        )
    )
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
async def risk_register_report(
    db: DbSession,
    user: CurrentUser,
    status_filter: Annotated[RiskStatus | None, Query(alias="status")] = None,
    category: str | None = None,
    business_unit_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    search: str | None = None,
    details: Annotated[bool, Query()] = True,
) -> Response:
    """The register report, narrowed to whatever the screen was showing.

    The filter parameters are the register's own, resolved through the same query
    builder the list endpoint uses, so "export what I am looking at" is literally true
    rather than approximately true. Without that shared builder a report drifts from the
    screen silently: nothing errors, the numbers are just wrong.
    """
    settings = await get_or_create_settings(db, user.tenant_id)
    stmt = build_risk_query(
        status=status_filter,
        category=category,
        business_unit_id=business_unit_id,
        process_id=process_id,
        asset_id=asset_id,
        search=search,
    )
    risks = list((await db.scalars(stmt.order_by(Risk.reference))).all())

    context = pdf_report.RiskReportContext(
        org_name=await _org_name(db, user),
        appetite=settings.appetite_score,
        tolerance=settings.tolerance_score,
        max_score=max_score_for(settings.matrix_size),
        matrix_size=settings.matrix_size,
        scope=await _scope_label(
            db, status_filter, category, business_unit_id, process_id, asset_id, search
        ),
        owner_names=await _owner_names(db, risks),
        include_details=details,
    )
    return _pdf(pdf_report.risk_register_pdf(risks, context), "risk-report.pdf")


async def _owner_names(db, risks) -> dict[uuid.UUID, str]:
    """Resolve owner ids to names in one query rather than per risk."""
    ids = {r.owner_id for r in risks if r.owner_id}
    if not ids:
        return {}
    rows = (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    return {u.id: (u.full_name or u.email) for u in rows}


async def _scope_label(
    db, status_filter, category, business_unit_id, process_id, asset_id, search
) -> str:
    """Describe the filter in the words the reader used to choose it.

    Printed on the cover: a filtered export circulating without this line is
    indistinguishable from the whole register, which is how a segment's report ends up
    being read as the bank's total exposure.
    """
    parts: list[str] = []
    if business_unit_id is not None:
        unit = await db.get(BusinessUnit, business_unit_id)
        parts.append(unit.name if unit else "Unknown business unit")
    if process_id is not None:
        process = await db.get(Process, process_id)
        parts.append(process.name if process else "Unknown process")
    if asset_id is not None:
        asset = await db.get(Asset, asset_id)
        parts.append(asset.name if asset else "Unknown asset")
    if status_filter is not None:
        parts.append(status_filter.value.replace("_", " ").title())
    if category:
        parts.append(category)
    if search:
        parts.append(f'matching "{search}"')
    return " · ".join(parts) if parts else "Whole register"


@router.get("/executive-summary", dependencies=[Depends(require("risk:read"))])
async def executive_summary_report(db: DbSession, user: CurrentUser) -> Response:
    from app.api.v1.dashboard import get_dashboard

    stats = await get_dashboard(db, user)
    data = pdf_report.executive_summary_pdf(stats.model_dump(), await _org_name(db, user))
    return _pdf(data, "executive-summary.pdf")
