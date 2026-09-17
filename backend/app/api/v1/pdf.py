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

from app.api.v1.risks import RiskListFilters
from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import Asset
from app.models.identity import User
from app.models.lookup import Lookup
from app.models.internal_audit import AuditEngagement
from app.models.organization import BusinessUnit, Process
from app.models.shariah import ShariahReview
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.services import pdf_report
from app.services.risk_scoring import max_score_for
from app.services.risk_settings import get_or_create_settings, load_appetite_book, scale_for

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
    filters: Annotated[RiskListFilters, Depends()],
    details: Annotated[bool, Query()] = True,
) -> Response:
    """The register report, narrowed to whatever the screen was showing.

    The filters are the register list's own dependency (``api.v1.risks.RiskListFilters``):
    the same parameters, resolved through the same query builder, so "export what I am
    looking at" is literally true — any filter the list gains, the PDF gains. Without that
    shared builder a report drifts from the screen silently: nothing errors, the numbers
    are just wrong.
    """
    settings = await get_or_create_settings(db, user.tenant_id)
    book = await load_appetite_book(db, user.tenant_id, settings)
    stmt = filters.statement(book)
    risks = list((await db.scalars(stmt.order_by(Risk.reference))).all())

    context = pdf_report.RiskReportContext(
        org_name=await _org_name(db, user),
        appetite=settings.appetite_score,
        tolerance=settings.tolerance_score,
        max_score=max_score_for(settings.matrix_size),
        matrix_size=settings.matrix_size,
        scope=await _scope_label(db, filters),
        owner_names=await _owner_names(db, risks),
        include_details=details,
        book=book,
        scale=scale_for(settings),
    )
    return _pdf(pdf_report.risk_register_pdf(risks, context), "risk-report.pdf")


async def _owner_names(db, risks) -> dict[uuid.UUID, str]:
    """Resolve owner ids to names in one query rather than per risk."""
    ids = {r.owner_id for r in risks if r.owner_id}
    if not ids:
        return {}
    rows = (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    return {u.id: (u.full_name or u.email) for u in rows}


_LEVEL_WORDS = {"1": "enterprise (L1)", "2": "category (L2)", "3": "scenario (L3)", "none": "not placed"}
_REVIEW_WORDS = {"overdue": "overdue", "due_30d": "due in 30 days"}
_APPETITE_WORDS = {
    "within": "within appetite", "within_appetite": "within appetite",
    "elevated": "above appetite, within tolerance", "breach": "above tolerance",
}


def _yes_no(value: bool, yes: str, no: str) -> str:
    return yes if value else no


async def _scope_label(db, filters: RiskListFilters) -> str:
    """Describe every active filter in the words the reader used to choose it.

    Printed on the cover: a filtered export circulating without this line is
    indistinguishable from the whole register, which is how a segment's report ends up
    being read as the bank's total exposure. Ids are shown as names.
    """
    parts: list[str] = []
    active = filters.active()

    async def name_of(model, value, attr: str, missing: str) -> str:
        row = await db.get(model, value)
        return getattr(row, attr, None) or missing if row is not None else missing

    for key, value in active.items():
        label = RiskListFilters.LABELS[key]
        if key == "business_unit_id":
            parts.append(await name_of(BusinessUnit, value, "name", "Unknown business unit"))
        elif key == "process_id":
            parts.append(await name_of(Process, value, "name", "Unknown process"))
        elif key == "asset_id":
            parts.append(await name_of(Asset, value, "name", "Unknown asset"))
        elif key in ("owner_id", "treatment_owner_id"):
            person = await db.get(User, value)
            parts.append(f"{label}: {(person.full_name or person.email) if person else 'unknown user'}")
        elif key == "category_id":
            parts.append(f"{label}: {await name_of(Lookup, value, 'label', 'unknown category')}")
        elif key == "parent_id":
            parent = await db.get(Risk, value)
            parts.append(f"Below {parent.reference if parent else 'an unknown risk'}")
        elif key == "status_filter":
            parts.append(value.value.replace("_", " ").title())
        elif key == "category":
            parts.append(str(value))
        elif key == "search":
            parts.append(f'matching "{value}"')
        elif key == "level":
            parts.append(f"Level: {_LEVEL_WORDS.get(str(value), value)}")
        elif key == "max_level":
            parts.append(f"Levels 1–{value}")
        elif key == "review":
            parts.append(f"Review {_REVIEW_WORDS.get(value, value)}")
        elif key == "appetite":
            parts.append(_APPETITE_WORDS.get(value, str(value)))
        elif key == "roots_only":
            parts.append(_yes_no(value, "Top of the tree only", "Below another risk only"))
        elif key == "needs_review":
            parts.append(_yes_no(value, "Flagged for review", "Not flagged for review"))
        elif key == "has_controls":
            parts.append(_yes_no(value, "With controls", "Without controls"))
        elif key == "treatment_overdue":
            parts.append(_yes_no(value, "Treatment overdue", "Treatment not overdue"))
        elif key == "pending_validation":
            parts.append(_yes_no(value, "Pending validation (drafts)", "Out of Draft"))
        elif key in ("risk_type", "source"):
            parts.append(f"{label}: {str(value).replace('_', ' ')}")
        else:  # a filter added to RiskListFilters without a wording here still prints
            parts.append(f"{label}: {value}")
    return " · ".join(parts) if parts else "Whole register"


@router.get("/executive-summary", dependencies=[Depends(require("risk:read"))])
async def executive_summary_report(db: DbSession, user: CurrentUser) -> Response:
    from app.api.v1.dashboard import get_dashboard

    stats = await get_dashboard(db, user)
    data = pdf_report.executive_summary_pdf(stats.model_dump(), await _org_name(db, user))
    return _pdf(data, "executive-summary.pdf")
