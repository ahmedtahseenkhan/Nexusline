"""Threat & Vulnerability catalog API (part of Risk Management)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.threat import Threat, Vulnerability
from app.schemas.common import Page
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


# ------------------------------------------------------------------- threats
@router.get("/threats", response_model=Page[ThreatRead], dependencies=[Depends(require("risk:read"))])
async def list_threats(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ThreatRead]:
    total = await db.scalar(select(func.count()).select_from(Threat)) or 0
    rows = (await db.scalars(select(Threat).order_by(Threat.name).limit(limit).offset(offset))).all()
    return Page(items=[ThreatRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/threats", response_model=ThreatRead, status_code=201, dependencies=[Depends(require("risk:write"))])
async def create_threat(body: ThreatCreate, db: DbSession, user: CurrentUser) -> ThreatRead:
    obj = Threat(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return ThreatRead.model_validate(obj)


@router.patch("/threats/{obj_id}", response_model=ThreatRead, dependencies=[Depends(require("risk:write"))])
async def update_threat(obj_id: uuid.UUID, body: ThreatUpdate, db: DbSession) -> ThreatRead:
    obj = await _get(db, Threat, obj_id, "Threat")
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, f, v)
    await db.flush()
    await db.refresh(obj)
    return ThreatRead.model_validate(obj)


@router.delete("/threats/{obj_id}", status_code=204, dependencies=[Depends(require("risk:write"))])
async def delete_threat(obj_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _get(db, Threat, obj_id, "Threat"))


# ------------------------------------------------------------- vulnerabilities
@router.get(
    "/vulnerabilities", response_model=Page[VulnerabilityRead], dependencies=[Depends(require("risk:read"))]
)
async def list_vulnerabilities(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[VulnerabilityRead]:
    total = await db.scalar(select(func.count()).select_from(Vulnerability)) or 0
    rows = (
        await db.scalars(select(Vulnerability).order_by(Vulnerability.name).limit(limit).offset(offset))
    ).all()
    return Page(items=[VulnerabilityRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post(
    "/vulnerabilities", response_model=VulnerabilityRead, status_code=201, dependencies=[Depends(require("risk:write"))]
)
async def create_vulnerability(body: VulnerabilityCreate, db: DbSession, user: CurrentUser) -> VulnerabilityRead:
    obj = Vulnerability(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return VulnerabilityRead.model_validate(obj)


@router.patch(
    "/vulnerabilities/{obj_id}", response_model=VulnerabilityRead, dependencies=[Depends(require("risk:write"))]
)
async def update_vulnerability(obj_id: uuid.UUID, body: VulnerabilityUpdate, db: DbSession) -> VulnerabilityRead:
    obj = await _get(db, Vulnerability, obj_id, "Vulnerability")
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, f, v)
    await db.flush()
    await db.refresh(obj)
    return VulnerabilityRead.model_validate(obj)


@router.delete("/vulnerabilities/{obj_id}", status_code=204, dependencies=[Depends(require("risk:write"))])
async def delete_vulnerability(obj_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _get(db, Vulnerability, obj_id, "Vulnerability"))
