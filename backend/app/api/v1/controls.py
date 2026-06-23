"""Internal controls — CRUD plus recurring audit & maintenance test cycles."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.control import Control, ControlAudit, ControlMaintenance
from app.schemas.common import Page
from app.schemas.control import (
    ControlAuditCreate,
    ControlAuditRead,
    ControlCreate,
    ControlMaintenanceCreate,
    ControlMaintenanceRead,
    ControlRead,
    ControlUpdate,
)
from app.services import audit as audit_log
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/controls", tags=["controls"])


async def _get_or_404(db, control_id: uuid.UUID) -> Control:
    control = await db.scalar(
        select(Control).where(Control.id == control_id, Control.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if control is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control not found")
    return control


async def _load_policies(db, ids):
    if not ids:
        return []
    from app.models.policy import Policy

    return list((await db.scalars(select(Policy).where(Policy.id.in_(ids)))).all())


async def _fresh(db, control_id: uuid.UUID) -> Control:
    return await db.scalar(
        select(Control).where(Control.id == control_id).execution_options(populate_existing=True)
    )


@router.get("", response_model=Page[ControlRead], dependencies=[Depends(require("control:read"))])
async def list_controls(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ControlRead]:
    stmt = select(Control).where(Control.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(Control.name).limit(limit).offset(offset))
    ).all()
    return Page(
        items=[ControlRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post(
    "",
    response_model=ControlRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("control:write"))],
)
async def create_control(body: ControlCreate, db: DbSession, user: CurrentUser) -> ControlRead:
    data = body.model_dump()
    policy_ids = data.pop("policy_ids", [])
    control = Control(tenant_id=user.tenant_id, **data)
    control.policies = await _load_policies(db, policy_ids)
    control.next_audit_date = next_review_date(control.audit_frequency)
    control.next_maintenance_date = next_review_date(control.maintenance_frequency)
    db.add(control)
    await db.flush()
    return ControlRead.model_validate(await _fresh(db, control.id))


@router.get(
    "/{control_id}", response_model=ControlRead, dependencies=[Depends(require("control:read"))]
)
async def get_control(control_id: uuid.UUID, db: DbSession) -> ControlRead:
    return ControlRead.model_validate(await _get_or_404(db, control_id))


@router.patch(
    "/{control_id}", response_model=ControlRead, dependencies=[Depends(require("control:write"))]
)
async def update_control(control_id: uuid.UUID, body: ControlUpdate, db: DbSession) -> ControlRead:
    control = await _get_or_404(db, control_id)
    data = body.model_dump(exclude_unset=True)
    policy_ids = data.pop("policy_ids", None)
    for field, value in data.items():
        setattr(control, field, value)
    if policy_ids is not None:
        control.policies = await _load_policies(db, policy_ids)
    if "audit_frequency" in data:
        control.next_audit_date = next_review_date(control.audit_frequency, control.last_audit_date)
    if "maintenance_frequency" in data:
        control.next_maintenance_date = next_review_date(
            control.maintenance_frequency, control.last_maintenance_date
        )
    await db.flush()
    return ControlRead.model_validate(await _fresh(db, control.id))


@router.delete(
    "/{control_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("control:write"))],
)
async def delete_control(control_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    control = await _get_or_404(db, control_id)
    control.deleted = True
    control.deleted_date = datetime.now(timezone.utc)


# ----------------------------------------------------------------- audit cycle
@router.get(
    "/{control_id}/audits",
    response_model=list[ControlAuditRead],
    dependencies=[Depends(require("control:read"))],
)
async def list_control_audits(control_id: uuid.UUID, db: DbSession) -> list[ControlAuditRead]:
    await _get_or_404(db, control_id)
    rows = (
        await db.scalars(
            select(ControlAudit)
            .where(ControlAudit.control_id == control_id)
            .order_by(ControlAudit.created_at.desc())
        )
    ).all()
    return [ControlAuditRead.model_validate(r) for r in rows]


@router.post(
    "/{control_id}/audits",
    response_model=ControlRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("control:write"))],
    summary="Record a control audit and reschedule the next one",
)
async def record_control_audit(
    control_id: uuid.UUID, body: ControlAuditCreate, db: DbSession, user: CurrentUser
) -> ControlRead:
    control = await _get_or_404(db, control_id)
    conducted = body.conducted_date or date.today()
    db.add(ControlAudit(tenant_id=user.tenant_id, control_id=control_id, **body.model_dump()))
    control.last_audit_date = conducted
    control.next_audit_date = next_review_date(control.audit_frequency, conducted)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="audit", entity_type="control", entity_id=control.id,
        summary=f"Recorded {body.result.value} audit for control {control.reference or control.name}",
    )
    return ControlRead.model_validate(await _fresh(db, control.id))


# ----------------------------------------------------------- maintenance cycle
@router.get(
    "/{control_id}/maintenances",
    response_model=list[ControlMaintenanceRead],
    dependencies=[Depends(require("control:read"))],
)
async def list_control_maintenances(
    control_id: uuid.UUID, db: DbSession
) -> list[ControlMaintenanceRead]:
    await _get_or_404(db, control_id)
    rows = (
        await db.scalars(
            select(ControlMaintenance)
            .where(ControlMaintenance.control_id == control_id)
            .order_by(ControlMaintenance.created_at.desc())
        )
    ).all()
    return [ControlMaintenanceRead.model_validate(r) for r in rows]


@router.post(
    "/{control_id}/maintenances",
    response_model=ControlRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("control:write"))],
    summary="Record a control maintenance and reschedule the next one",
)
async def record_control_maintenance(
    control_id: uuid.UUID, body: ControlMaintenanceCreate, db: DbSession, user: CurrentUser
) -> ControlRead:
    control = await _get_or_404(db, control_id)
    conducted = body.conducted_date or date.today()
    db.add(
        ControlMaintenance(tenant_id=user.tenant_id, control_id=control_id, **body.model_dump())
    )
    control.last_maintenance_date = conducted
    control.next_maintenance_date = next_review_date(control.maintenance_frequency, conducted)
    await db.flush()
    return ControlRead.model_validate(await _fresh(db, control.id))
