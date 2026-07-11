"""Internal Audit API — audit universe, engagements, working papers and findings.

A full assurance workflow: maintain the risk-based audit universe, run engagements
through their lifecycle, record test procedures (working papers), raise findings and
track them through remediation follow-up to closure.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.enums import AuditFindingStatus
from app.models.internal_audit import (
    AuditableUnit,
    AuditEngagement,
    AuditFinding,
    AuditProcedure,
)
from app.schemas.common import Page
from app.schemas.internal_audit import (
    AuditableUnitCreate,
    AuditableUnitRead,
    AuditableUnitUpdate,
    EngagementCreate,
    EngagementRead,
    EngagementUpdate,
    FindingCreate,
    FindingRead,
    FindingUpdate,
    ProcedureCreate,
    ProcedureRead,
    ProcedureUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["internal audit"])

_READ = Depends(require("internal_audit:read"))
_WRITE = Depends(require("internal_audit:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


# ============================================================ audit universe ===
@router.get("/audit-universe", response_model=Page[AuditableUnitRead], dependencies=[_READ])
async def list_units(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditableUnitRead]:
    stmt = select(AuditableUnit).where(AuditableUnit.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(AuditableUnit.name).limit(limit).offset(offset))).all()
    return Page(items=[AuditableUnitRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/audit-universe", response_model=AuditableUnitRead, status_code=201, dependencies=[_WRITE])
async def create_unit(body: AuditableUnitCreate, db: DbSession, user: CurrentUser) -> AuditableUnitRead:
    obj = AuditableUnit(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, AuditableUnit, "AU")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="auditable_unit",
                           entity_id=obj.id, summary=f"Created auditable unit {obj.reference}: {obj.name}")
    return AuditableUnitRead.model_validate(obj)


async def _load_unit(db, unit_id: uuid.UUID) -> AuditableUnit:
    obj = await db.scalar(select(AuditableUnit).where(AuditableUnit.id == unit_id, AuditableUnit.deleted.is_(False)))
    if obj is None:
        raise HTTPException(status_code=404, detail="Auditable unit not found")
    return obj


@router.patch("/audit-universe/{unit_id}", response_model=AuditableUnitRead, dependencies=[_WRITE])
async def update_unit(unit_id: uuid.UUID, body: AuditableUnitUpdate, db: DbSession) -> AuditableUnitRead:
    obj = await _load_unit(db, unit_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return AuditableUnitRead.model_validate(obj)


@router.delete("/audit-universe/{unit_id}", status_code=204, dependencies=[_WRITE])
async def delete_unit(unit_id: uuid.UUID, db: DbSession) -> None:
    obj = await _load_unit(db, unit_id)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================================== engagements ===
async def _load_engagement(db, eid: uuid.UUID) -> AuditEngagement:
    obj = await db.scalar(
        select(AuditEngagement).where(AuditEngagement.id == eid, AuditEngagement.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Audit engagement not found")
    return obj


@router.get("/audit-engagements", response_model=Page[EngagementRead], dependencies=[_READ])
async def list_engagements(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EngagementRead]:
    stmt = select(AuditEngagement).where(AuditEngagement.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(AuditEngagement.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[EngagementRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/audit-engagements", response_model=EngagementRead, status_code=201, dependencies=[_WRITE])
async def create_engagement(body: EngagementCreate, db: DbSession, user: CurrentUser) -> EngagementRead:
    if body.auditable_unit_id is not None:
        await _load_unit(db, body.auditable_unit_id)  # validate FK within tenant
    obj = AuditEngagement(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, AuditEngagement, "IA")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="audit_engagement",
                           entity_id=obj.id, summary=f"Opened audit {obj.reference}: {obj.title}")
    return EngagementRead.model_validate(await _load_engagement(db, obj.id))


@router.get("/audit-engagements/{eid}", response_model=EngagementRead, dependencies=[_READ])
async def get_engagement(eid: uuid.UUID, db: DbSession) -> EngagementRead:
    return EngagementRead.model_validate(await _load_engagement(db, eid))


@router.patch("/audit-engagements/{eid}", response_model=EngagementRead, dependencies=[_WRITE])
async def update_engagement(eid: uuid.UUID, body: EngagementUpdate, db: DbSession) -> EngagementRead:
    obj = await _load_engagement(db, eid)
    data = body.model_dump(exclude_unset=True)
    if data.get("auditable_unit_id") is not None:
        await _load_unit(db, data["auditable_unit_id"])
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return EngagementRead.model_validate(await _load_engagement(db, eid))


@router.delete("/audit-engagements/{eid}", status_code=204, dependencies=[_WRITE])
async def delete_engagement(eid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_engagement(db, eid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ------------------------------------------------------------- procedures ---
@router.post("/audit-engagements/{eid}/procedures", response_model=EngagementRead, status_code=201, dependencies=[_WRITE])
async def add_procedure(eid: uuid.UUID, body: ProcedureCreate, db: DbSession, user: CurrentUser) -> EngagementRead:
    await _load_engagement(db, eid)
    db.add(AuditProcedure(tenant_id=user.tenant_id, engagement_id=eid, **body.model_dump()))
    await db.flush()
    return EngagementRead.model_validate(await _load_engagement(db, eid))


@router.patch("/audit-procedures/{pid}", response_model=ProcedureRead, dependencies=[_WRITE])
async def update_procedure(pid: uuid.UUID, body: ProcedureUpdate, db: DbSession) -> ProcedureRead:
    obj = await db.scalar(select(AuditProcedure).where(AuditProcedure.id == pid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Procedure not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return ProcedureRead.model_validate(obj)


@router.delete("/audit-procedures/{pid}", status_code=204, dependencies=[_WRITE])
async def delete_procedure(pid: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(AuditProcedure).where(AuditProcedure.id == pid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


# ---------------------------------------------------------------- findings ---
@router.post("/audit-engagements/{eid}/findings", response_model=EngagementRead, status_code=201, dependencies=[_WRITE])
async def add_finding(eid: uuid.UUID, body: FindingCreate, db: DbSession, user: CurrentUser) -> EngagementRead:
    await _load_engagement(db, eid)
    finding = AuditFinding(tenant_id=user.tenant_id, engagement_id=eid, **body.model_dump())
    finding.reference = await _next_ref(db, AuditFinding, "IAF")
    db.add(finding)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="audit_finding",
                           entity_id=finding.id, summary=f"Raised finding {finding.reference}: {finding.title}")
    return EngagementRead.model_validate(await _load_engagement(db, eid))


async def _load_finding(db, fid: uuid.UUID) -> AuditFinding:
    obj = await db.scalar(select(AuditFinding).where(AuditFinding.id == fid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return obj


@router.patch("/audit-findings/{fid}", response_model=FindingRead, dependencies=[_WRITE])
async def update_finding(fid: uuid.UUID, body: FindingUpdate, db: DbSession) -> FindingRead:
    obj = await _load_finding(db, fid)
    data = body.model_dump(exclude_unset=True)
    # Auto-stamp closure date when a finding is closed and none was supplied.
    if data.get("status") in (AuditFindingStatus.closed, AuditFindingStatus.risk_accepted) and not obj.closed_date and "closed_date" not in data:
        obj.closed_date = date.today()
    if data.get("status") == AuditFindingStatus.open:
        obj.closed_date = None
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return FindingRead.model_validate(obj)


@router.delete("/audit-findings/{fid}", status_code=204, dependencies=[_WRITE])
async def delete_finding(fid: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(AuditFinding).where(AuditFinding.id == fid))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


@router.get("/audit-findings", response_model=list[FindingRead], dependencies=[_READ],
            summary="All findings (remediation follow-up view)")
async def list_findings(
    db: DbSession,
    status_filter: Annotated[AuditFindingStatus | None, Query(alias="status")] = None,
    overdue: bool = False,
) -> list[FindingRead]:
    # Exclude findings of archived engagements from the remediation follow-up view.
    stmt = (
        select(AuditFinding)
        .join(AuditEngagement, AuditEngagement.id == AuditFinding.engagement_id)
        .where(AuditEngagement.deleted.is_(False))
    )
    if status_filter is not None:
        stmt = stmt.where(AuditFinding.status == status_filter)
    rows = (await db.scalars(stmt.order_by(AuditFinding.due_date.is_(None), AuditFinding.due_date))).all()
    result = [FindingRead.model_validate(f) for f in rows]
    if overdue:
        result = [f for f in result if f.is_overdue]
    return result
