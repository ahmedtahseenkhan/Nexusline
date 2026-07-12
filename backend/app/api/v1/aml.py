"""AML/CFT API — sanctions/PEP screening, STR/SAR filings, and AML risk assessments."""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.aml import AmlRiskAssessment, ScreeningCase, SuspiciousActivityReport
from app.models.enums import SarStatus, ScreeningCaseStatus
from app.schemas.aml import (
    AmlRiskCreate,
    AmlRiskRead,
    AmlRiskUpdate,
    SarCreate,
    SarRead,
    SarUpdate,
    ScreeningCreate,
    ScreeningRead,
    ScreeningUpdate,
)
from app.schemas.common import Page
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["aml/cft"])

_READ = Depends(require("aml:read"))
_WRITE = Depends(require("aml:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _soft_delete(db, model, obj_id, name):
    obj = await _get(db, model, obj_id, name)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================================ screening cases ===
_SCREENING_SORTABLE = {
    "reference": ScreeningCase.reference,
    "subject_name": ScreeningCase.subject_name,
    "subject_type": ScreeningCase.subject_type,
    "screening_type": ScreeningCase.screening_type,
    "match_status": ScreeningCase.match_status,
    "risk_rating": ScreeningCase.risk_rating,
    "status": ScreeningCase.status,
    "screened_date": ScreeningCase.screened_date,
    "created_at": ScreeningCase.created_at,
}


@router.get("/aml/screening", response_model=Page[ScreeningRead], dependencies=[_READ])
async def list_screening(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ScreeningRead]:
    stmt = select(ScreeningCase).where(ScreeningCase.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(ScreeningCase.subject_name.ilike(like) | ScreeningCase.reference.ilike(like))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _SCREENING_SORTABLE, default=ScreeningCase.created_at)
    else:
        stmt = stmt.order_by(ScreeningCase.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[ScreeningRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/aml/screening", response_model=ScreeningRead, status_code=201, dependencies=[_WRITE])
async def create_screening(body: ScreeningCreate, db: DbSession, user: CurrentUser) -> ScreeningRead:
    obj = ScreeningCase(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, ScreeningCase, "SCR")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="screening_case",
                           entity_id=obj.id, summary=f"Screening case {obj.reference}: {obj.subject_name}")
    return ScreeningRead.model_validate(obj)


@router.get("/aml/screening/{cid}", response_model=ScreeningRead, dependencies=[_READ])
async def get_screening(cid: uuid.UUID, db: DbSession) -> ScreeningRead:
    return ScreeningRead.model_validate(await _get(db, ScreeningCase, cid, "Screening case"))


@router.patch("/aml/screening/{cid}", response_model=ScreeningRead, dependencies=[_WRITE])
async def update_screening(cid: uuid.UUID, body: ScreeningUpdate, db: DbSession) -> ScreeningRead:
    obj = await _get(db, ScreeningCase, cid, "Screening case")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return ScreeningRead.model_validate(obj)


@router.delete("/aml/screening/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_screening(cid: uuid.UUID, db: DbSession) -> None:
    await _soft_delete(db, ScreeningCase, cid, "Screening case")


class ScreeningSummary(BaseModel):
    total: int
    by_match_status: dict[str, int]
    open_cases: int
    escalated: int


@router.get("/aml/screening-summary", response_model=ScreeningSummary, dependencies=[_READ])
async def screening_summary(db: DbSession) -> ScreeningSummary:
    rows = (await db.scalars(select(ScreeningCase).where(ScreeningCase.deleted.is_(False)))).all()
    match = Counter(r.match_status.value for r in rows)
    return ScreeningSummary(
        total=len(rows),
        by_match_status=dict(match),
        open_cases=sum(1 for r in rows if r.status == ScreeningCaseStatus.open),
        escalated=sum(1 for r in rows if r.status == ScreeningCaseStatus.escalated),
    )


# ==================================================================== STR/SAR ===
_SAR_SORTABLE = {
    "reference": SuspiciousActivityReport.reference,
    "subject": SuspiciousActivityReport.subject,
    "priority": SuspiciousActivityReport.priority,
    "amount": SuspiciousActivityReport.amount,
    "detected_date": SuspiciousActivityReport.detected_date,
    "deadline": SuspiciousActivityReport.deadline,
    "filed_date": SuspiciousActivityReport.filed_date,
    "status": SuspiciousActivityReport.status,
    "created_at": SuspiciousActivityReport.created_at,
}


@router.get("/aml/sars", response_model=Page[SarRead], dependencies=[_READ])
async def list_sars(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SarRead]:
    stmt = select(SuspiciousActivityReport).where(SuspiciousActivityReport.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            SuspiciousActivityReport.subject.ilike(like) | SuspiciousActivityReport.reference.ilike(like)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _SAR_SORTABLE, default=SuspiciousActivityReport.created_at)
    else:
        stmt = stmt.order_by(SuspiciousActivityReport.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[SarRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/aml/sars", response_model=SarRead, status_code=201, dependencies=[_WRITE])
async def create_sar(body: SarCreate, db: DbSession, user: CurrentUser) -> SarRead:
    data = body.model_dump()
    # Default the FMU filing deadline from the detection date when not supplied.
    if data.get("deadline") is None and data.get("detected_date") is not None:
        data["deadline"] = data["detected_date"] + timedelta(days=settings.aml_str_filing_days)
    obj = SuspiciousActivityReport(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, SuspiciousActivityReport, "STR")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="sar",
                           entity_id=obj.id, summary=f"STR/SAR {obj.reference}: {obj.subject}")
    return SarRead.model_validate(obj)


@router.get("/aml/sars/{sid}", response_model=SarRead, dependencies=[_READ])
async def get_sar(sid: uuid.UUID, db: DbSession) -> SarRead:
    return SarRead.model_validate(await _get(db, SuspiciousActivityReport, sid, "SAR"))


@router.patch("/aml/sars/{sid}", response_model=SarRead, dependencies=[_WRITE])
async def update_sar(sid: uuid.UUID, body: SarUpdate, db: DbSession) -> SarRead:
    obj = await _get(db, SuspiciousActivityReport, sid, "SAR")
    data = body.model_dump(exclude_unset=True)
    # Stamp the filing date when marked filed and none supplied.
    if data.get("status") == SarStatus.filed and not obj.filed_date and "filed_date" not in data:
        obj.filed_date = date.today()
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return SarRead.model_validate(obj)


@router.delete("/aml/sars/{sid}", status_code=204, dependencies=[_WRITE])
async def delete_sar(sid: uuid.UUID, db: DbSession) -> None:
    await _soft_delete(db, SuspiciousActivityReport, sid, "SAR")


# ========================================================= AML risk assessments ===
_AML_RISK_SORTABLE = {
    "reference": AmlRiskAssessment.reference,
    "title": AmlRiskAssessment.title,
    "scope": AmlRiskAssessment.scope,
    "subject": AmlRiskAssessment.subject,
    "inherent_risk": AmlRiskAssessment.inherent_risk,
    "residual_risk": AmlRiskAssessment.residual_risk,
    "next_review_date": AmlRiskAssessment.next_review_date,
    "created_at": AmlRiskAssessment.created_at,
}


@router.get("/aml/risk-assessments", response_model=Page[AmlRiskRead], dependencies=[_READ])
async def list_aml_risks(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AmlRiskRead]:
    stmt = select(AmlRiskAssessment).where(AmlRiskAssessment.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            AmlRiskAssessment.title.ilike(like)
            | AmlRiskAssessment.reference.ilike(like)
            | AmlRiskAssessment.subject.ilike(like)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _AML_RISK_SORTABLE, default=AmlRiskAssessment.created_at)
    else:
        stmt = stmt.order_by(AmlRiskAssessment.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[AmlRiskRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/aml/risk-assessments", response_model=AmlRiskRead, status_code=201, dependencies=[_WRITE])
async def create_aml_risk(body: AmlRiskCreate, db: DbSession, user: CurrentUser) -> AmlRiskRead:
    obj = AmlRiskAssessment(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, AmlRiskAssessment, "AML")
    db.add(obj)
    await db.flush()
    return AmlRiskRead.model_validate(obj)


@router.patch("/aml/risk-assessments/{aid}", response_model=AmlRiskRead, dependencies=[_WRITE])
async def update_aml_risk(aid: uuid.UUID, body: AmlRiskUpdate, db: DbSession) -> AmlRiskRead:
    obj = await _get(db, AmlRiskAssessment, aid, "Risk assessment")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return AmlRiskRead.model_validate(obj)


@router.delete("/aml/risk-assessments/{aid}", status_code=204, dependencies=[_WRITE])
async def delete_aml_risk(aid: uuid.UUID, db: DbSession) -> None:
    await _soft_delete(db, AmlRiskAssessment, aid, "Risk assessment")
