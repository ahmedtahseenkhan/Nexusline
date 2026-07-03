"""Incident Management (Security Operations) API — with response-stage lifecycle."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, delete, func, insert, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import assets_incidents
from app.models.control import Control
from app.models.enums import IncidentStatus, Severity, StageStatus
from app.models.incident import DEFAULT_STAGES, Incident, IncidentStage
from app.models.risk import risk_incidents
from app.models.vendor import Vendor
from app.schemas.common import Page
from app.schemas.incident import (
    IncidentCreate,
    IncidentRead,
    IncidentUpdate,
    StageCreate,
    StageUpdate,
)
from app.services import audit

router = APIRouter(prefix="/incidents", tags=["incidents"])

_KEEP = object()  # sentinel: field absent from request -> leave the link table untouched


def _loads():
    return (
        selectinload(Incident.stages),
        selectinload(Incident.regulatory_reports),
        selectinload(Incident.controls),
        selectinload(Incident.vendors),
        selectinload(Incident.assets),
        selectinload(Incident.risks),
    )


async def _load(db, incident_id: uuid.UUID) -> Incident:
    obj = await db.scalar(
        select(Incident).where(Incident.id == incident_id, Incident.deleted.is_(False)).options(*_loads())
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return obj


async def _resolve(db, model, ids):
    if not ids:
        return []
    return list((await db.scalars(select(model).where(model.id.in_(ids)))).all())


async def _set_assoc(db, table, self_col: str, other_col: str, self_id, other_ids) -> None:
    """Replace the rows in a 2-column association table for ``self_id`` with ``other_ids``.

    Incident.assets/risks are ``viewonly=True`` reverse views (the writable side lives on
    Asset/Risk), so direct assignment is ignored — we manage the join tables here instead.
    """
    if other_ids is _KEEP or other_ids is None:
        return
    await db.execute(delete(table).where(table.c[self_col] == self_id))
    if other_ids:
        await db.execute(insert(table), [{self_col: self_id, other_col: oid} for oid in other_ids])


async def _flush_assoc(db, incident_id, asset_ids, risk_ids) -> None:
    await _set_assoc(db, assets_incidents, "incident_id", "asset_id", incident_id, asset_ids)
    await _set_assoc(db, risk_incidents, "incident_id", "risk_id", incident_id, risk_ids)


async def _fresh(db, incident_id: uuid.UUID) -> Incident:
    return await db.scalar(
        select(Incident).where(Incident.id == incident_id).options(*_loads())
        .execution_options(populate_existing=True)
    )


async def _stage_or_404(db, incident_id, stage_id) -> IncidentStage:
    obj = await db.scalar(
        select(IncidentStage).where(
            IncidentStage.id == stage_id, IncidentStage.incident_id == incident_id
        )
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    return obj


async def _next_ref(db) -> str:
    count = await db.scalar(select(func.count()).select_from(Incident)) or 0
    return f"INC-{count + 1:03d}"


@router.get("", response_model=Page[IncidentRead], dependencies=[Depends(require("incident:read"))])
async def list_incidents(
    db: DbSession,
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    severity: Severity | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IncidentRead]:
    stmt: Select = select(Incident).where(Incident.deleted.is_(False))
    if status_filter is not None:
        stmt = stmt.where(Incident.status == status_filter)
    if severity is not None:
        stmt = stmt.where(Incident.severity == severity)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.options(*_loads()).order_by(Incident.created_at.desc()).limit(limit).offset(offset))
    ).all()
    return Page(
        items=[IncidentRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post(
    "",
    response_model=IncidentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("incident:write"))],
)
async def create_incident(body: IncidentCreate, db: DbSession, user: CurrentUser) -> IncidentRead:
    data = body.model_dump()
    control_ids = data.pop("control_ids", [])
    vendor_ids = data.pop("vendor_ids", [])
    asset_ids = data.pop("asset_ids", [])
    risk_ids = data.pop("risk_ids", [])
    obj = Incident(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db)
    obj.controls = await _resolve(db, Control, control_ids)
    obj.vendors = await _resolve(db, Vendor, vendor_ids)
    obj.stages = [
        IncidentStage(tenant_id=user.tenant_id, name=name, order_index=i)
        for i, name in enumerate(DEFAULT_STAGES)
    ]
    db.add(obj)
    await db.flush()
    await _flush_assoc(db, obj.id, asset_ids, risk_ids)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="incident", entity_id=obj.id,
        summary=f"Logged incident {obj.reference}: {obj.title}",
    )
    return IncidentRead.model_validate(await _fresh(db, obj.id))


@router.get("/{incident_id}", response_model=IncidentRead, dependencies=[Depends(require("incident:read"))])
async def get_incident(incident_id: uuid.UUID, db: DbSession) -> IncidentRead:
    return IncidentRead.model_validate(await _load(db, incident_id))


@router.patch(
    "/{incident_id}", response_model=IncidentRead, dependencies=[Depends(require("incident:write"))]
)
async def update_incident(
    incident_id: uuid.UUID, body: IncidentUpdate, db: DbSession, user: CurrentUser
) -> IncidentRead:
    obj = await _load(db, incident_id)
    data = body.model_dump(exclude_unset=True)
    control_ids = data.pop("control_ids", None)
    vendor_ids = data.pop("vendor_ids", None)
    asset_ids = data.pop("asset_ids", _KEEP)
    risk_ids = data.pop("risk_ids", _KEEP)
    for field, value in data.items():
        setattr(obj, field, value)
    if control_ids is not None:
        obj.controls = await _resolve(db, Control, control_ids)
    if vendor_ids is not None:
        obj.vendors = await _resolve(db, Vendor, vendor_ids)
    await db.flush()
    await _flush_assoc(db, obj.id, asset_ids, risk_ids)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="incident", entity_id=obj.id,
        summary=f"Updated incident {obj.reference}",
    )
    return IncidentRead.model_validate(await _fresh(db, obj.id))


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("incident:write"))],
)
async def delete_incident(incident_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, incident_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)


# ----------------------------------------------------------------- stages
@router.post(
    "/{incident_id}/stages",
    response_model=IncidentRead,
    status_code=201,
    dependencies=[Depends(require("incident:write"))],
)
async def add_stage(incident_id: uuid.UUID, body: StageCreate, db: DbSession, user: CurrentUser) -> IncidentRead:
    await _load(db, incident_id)
    db.add(IncidentStage(tenant_id=user.tenant_id, incident_id=incident_id, **body.model_dump()))
    await db.flush()
    return IncidentRead.model_validate(await _fresh(db, incident_id))


@router.patch(
    "/{incident_id}/stages/{stage_id}",
    response_model=IncidentRead,
    dependencies=[Depends(require("incident:write"))],
    summary="Advance a response stage (pending → in_progress → done)",
)
async def update_stage(
    incident_id: uuid.UUID, stage_id: uuid.UUID, body: StageUpdate, db: DbSession
) -> IncidentRead:
    stage = await _stage_or_404(db, incident_id, stage_id)
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(stage, field, value)
    if "status" in data:
        stage.completed_at = date.today() if stage.status == StageStatus.done else None
    await db.flush()
    return IncidentRead.model_validate(await _fresh(db, incident_id))
