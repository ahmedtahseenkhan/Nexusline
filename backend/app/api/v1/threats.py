"""Threat & Vulnerability catalog API (part of Risk Management)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.risk import Risk
from app.models.threat import (
    Threat,
    Vulnerability,
    risk_threats,
    risk_vulnerabilities,
)
from app.schemas.common import GraphRef, Page
from app.schemas.threat import (
    ThreatCreate,
    ThreatRead,
    ThreatUpdate,
    VulnerabilityCreate,
    VulnerabilityRead,
    VulnerabilityUpdate,
)

router = APIRouter(tags=["threats"])


async def _get(db, model, obj_id, name):
    obj = await db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{name} not found")
    return obj


async def _linked_risks(db, assoc, fk_col, obj_id):
    """The actual (non-deleted) risks referencing this catalog item, as GraphRefs."""
    rows = (
        await db.scalars(
            select(Risk)
            .join(assoc, assoc.c.risk_id == Risk.id)
            .where(fk_col == obj_id, Risk.deleted.is_(False))
            .order_by(Risk.reference)
        )
    ).all()
    return [GraphRef.model_validate(r) for r in rows]


async def _usage_counts(db, assoc, fk_col):
    """Return {entity_id: number-of-risks-referencing-it} from an association table,
    excluding archived (soft-deleted) risks."""
    rows = await db.execute(
        select(fk_col, func.count())
        .select_from(assoc.join(Risk, Risk.id == assoc.c.risk_id))
        .where(Risk.deleted.is_(False))
        .group_by(fk_col)
    )
    return {row[0]: row[1] for row in rows.all()}


def _read(schema, obj, counts):
    data = schema.model_validate(obj)
    data.used_by_risks_count = counts.get(obj.id, 0)
    return data


# ------------------------------------------------------------------- threats
_THREAT_SORTABLE = {
    "name": Threat.name,
    "category": Threat.category,
    "created_at": Threat.created_at,
}


@router.get("/threats", response_model=Page[ThreatRead], dependencies=[Depends(require("risk:read"))])
async def list_threats(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ThreatRead]:
    tstmt = select(Threat)
    if search:
        tstmt = tstmt.where(Threat.name.ilike(f"%{search}%"))
    total = await db.scalar(select(func.count()).select_from(tstmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        tstmt = apply_sort(tstmt, params, _THREAT_SORTABLE, default=Threat.name)
    else:
        tstmt = tstmt.order_by(Threat.name)
    rows = (await db.scalars(tstmt.limit(limit).offset(offset))).all()
    counts = await _usage_counts(db, risk_threats, risk_threats.c.threat_id)
    return Page(
        items=[_read(ThreatRead, r, counts) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/threats/{obj_id}", response_model=ThreatRead, dependencies=[Depends(require("risk:read"))])
async def get_threat(obj_id: uuid.UUID, db: DbSession) -> ThreatRead:
    obj = await _get(db, Threat, obj_id, "Threat")
    counts = await _usage_counts(db, risk_threats, risk_threats.c.threat_id)
    data = _read(ThreatRead, obj, counts)
    data.risks = await _linked_risks(db, risk_threats, risk_threats.c.threat_id, obj_id)
    return data


@router.post("/threats", response_model=ThreatRead, status_code=201, dependencies=[Depends(require("risk:write"))])
async def create_threat(body: ThreatCreate, db: DbSession, user: CurrentUser) -> ThreatRead:
    obj = Threat(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return ThreatRead.model_validate(obj)  # brand-new → used_by_risks_count defaults to 0


@router.patch("/threats/{obj_id}", response_model=ThreatRead, dependencies=[Depends(require("risk:write"))])
async def update_threat(obj_id: uuid.UUID, body: ThreatUpdate, db: DbSession) -> ThreatRead:
    obj = await _get(db, Threat, obj_id, "Threat")
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, f, v)
    await db.flush()
    await db.refresh(obj)
    counts = await _usage_counts(db, risk_threats, risk_threats.c.threat_id)
    return _read(ThreatRead, obj, counts)


@router.delete("/threats/{obj_id}", status_code=204, dependencies=[Depends(require("risk:write"))])
async def delete_threat(obj_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _get(db, Threat, obj_id, "Threat"))


# ------------------------------------------------------------- vulnerabilities
_VULN_SORTABLE = {
    "name": Vulnerability.name,
    "category": Vulnerability.category,
    "created_at": Vulnerability.created_at,
}


@router.get(
    "/vulnerabilities", response_model=Page[VulnerabilityRead], dependencies=[Depends(require("risk:read"))]
)
async def list_vulnerabilities(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[VulnerabilityRead]:
    vstmt = select(Vulnerability)
    if search:
        vstmt = vstmt.where(Vulnerability.name.ilike(f"%{search}%"))
    total = await db.scalar(select(func.count()).select_from(vstmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        vstmt = apply_sort(vstmt, params, _VULN_SORTABLE, default=Vulnerability.name)
    else:
        vstmt = vstmt.order_by(Vulnerability.name)
    rows = (await db.scalars(vstmt.limit(limit).offset(offset))).all()
    counts = await _usage_counts(db, risk_vulnerabilities, risk_vulnerabilities.c.vulnerability_id)
    return Page(
        items=[_read(VulnerabilityRead, r, counts) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/vulnerabilities/{obj_id}",
    response_model=VulnerabilityRead,
    dependencies=[Depends(require("risk:read"))],
)
async def get_vulnerability(obj_id: uuid.UUID, db: DbSession) -> VulnerabilityRead:
    obj = await _get(db, Vulnerability, obj_id, "Vulnerability")
    counts = await _usage_counts(db, risk_vulnerabilities, risk_vulnerabilities.c.vulnerability_id)
    data = _read(VulnerabilityRead, obj, counts)
    data.risks = await _linked_risks(db, risk_vulnerabilities, risk_vulnerabilities.c.vulnerability_id, obj_id)
    return data


@router.post(
    "/vulnerabilities", response_model=VulnerabilityRead, status_code=201, dependencies=[Depends(require("risk:write"))]
)
async def create_vulnerability(body: VulnerabilityCreate, db: DbSession, user: CurrentUser) -> VulnerabilityRead:
    obj = Vulnerability(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return VulnerabilityRead.model_validate(obj)  # brand-new → used_by_risks_count defaults to 0


@router.patch(
    "/vulnerabilities/{obj_id}", response_model=VulnerabilityRead, dependencies=[Depends(require("risk:write"))]
)
async def update_vulnerability(obj_id: uuid.UUID, body: VulnerabilityUpdate, db: DbSession) -> VulnerabilityRead:
    obj = await _get(db, Vulnerability, obj_id, "Vulnerability")
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, f, v)
    await db.flush()
    await db.refresh(obj)
    counts = await _usage_counts(db, risk_vulnerabilities, risk_vulnerabilities.c.vulnerability_id)
    return _read(VulnerabilityRead, obj, counts)


@router.delete("/vulnerabilities/{obj_id}", status_code=204, dependencies=[Depends(require("risk:write"))])
async def delete_vulnerability(obj_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _get(db, Vulnerability, obj_id, "Vulnerability"))
