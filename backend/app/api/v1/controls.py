"""Internal controls — CRUD plus recurring audit & maintenance test cycles."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.compliance import Requirement, requirement_controls
from app.models.control import Control, ControlAudit, ControlMaintenance
from app.models.risk import Risk, risk_controls
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


def _loads():
    # policies/requirements are lazy="selectin" already, but eager-load explicitly so a
    # populate_existing refresh re-reads them after we rewrite the join tables.
    return (
        selectinload(Control.policies),
        selectinload(Control.requirements),
    )


async def _get_or_404(db, control_id: uuid.UUID) -> Control:
    control = await db.scalar(
        select(Control).where(Control.id == control_id, Control.deleted.is_(False))
        .options(*_loads()).execution_options(populate_existing=True)
    )
    if control is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control not found")
    return control


async def _load_policies(db, ids):
    if not ids:
        return []
    from app.models.policy import Policy

    return list((await db.scalars(select(Policy).where(Policy.id.in_(ids)))).all())


async def _attach_risks(db, control: Control) -> Control:
    """`Control` has no ORM `risks` relationship (the writable side lives on `Risk.controls`,
    via the `risk_controls` join). Query the linked risks and stash them on a transient
    attribute so `ControlRead.risks` can serialise them."""
    rows = (
        await db.scalars(
            select(Risk)
            .join(risk_controls, risk_controls.c.risk_id == Risk.id)
            .where(risk_controls.c.control_id == control.id, Risk.deleted.is_(False))
            .order_by(Risk.reference)
        )
    ).all()
    control.risks = list(rows)
    return control


_KEEP = object()  # sentinel: field absent from request -> leave the join table untouched


async def _set_assoc(db, table, self_col: str, other_col: str, self_id, other_ids) -> None:
    """Replace the rows in a 2-column association table for `self_id` with `other_ids`.

    Used for relationships that are viewonly from the control side: `requirements`
    (writable side on Requirement) and `risks` (writable side on Risk). We manage the
    join tables directly, exactly like policies.py does for its reverse views.
    """
    if other_ids is _KEEP or other_ids is None:
        return
    await db.execute(delete(table).where(table.c[self_col] == self_id))
    if other_ids:
        await db.execute(insert(table), [{self_col: self_id, other_col: oid} for oid in other_ids])


async def _validate_ids(db, model, ids, label: str) -> None:
    if not ids or ids is _KEEP:
        return
    stmt = select(model.id).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    found = set((await db.scalars(stmt)).all())
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or archived {label} id(s): {sorted(missing)}",
        )


async def _flush_assoc(db, control_id, stash: dict) -> None:
    await _validate_ids(db, Requirement, stash["requirements"], "requirement")
    await _validate_ids(db, Risk, stash["risks"], "risk")
    await _set_assoc(
        db, requirement_controls, "control_id", "requirement_id", control_id, stash["requirements"]
    )
    await _set_assoc(db, risk_controls, "control_id", "risk_id", control_id, stash["risks"])


async def _fresh(db, control_id: uuid.UUID) -> Control:
    control = await db.scalar(
        select(Control).where(Control.id == control_id)
        .options(*_loads()).execution_options(populate_existing=True)
    )
    return await _attach_risks(db, control)


_CONTROL_SORTABLE = {
    "name": Control.name,
    "reference": Control.reference,
    "status": Control.status,
    "effectiveness": Control.effectiveness,
    "next_audit_date": Control.next_audit_date,
    "created_at": Control.created_at,
}


async def _attach_risks_bulk(db, controls) -> None:
    """Attach linked (non-deleted) risks to a list of controls in ONE query instead of
    one per control (the previous per-row loop was a 200-row → 200-query N+1)."""
    ids = [c.id for c in controls]
    if not ids:
        return
    rows = (
        await db.execute(
            select(risk_controls.c.control_id, Risk)
            .join(Risk, risk_controls.c.risk_id == Risk.id)
            .where(risk_controls.c.control_id.in_(ids), Risk.deleted.is_(False))
            .order_by(Risk.reference)
        )
    ).all()
    by_control: dict = {}
    for control_id, risk in rows:
        by_control.setdefault(control_id, []).append(risk)
    for control in controls:
        control.risks = by_control.get(control.id, [])


@router.get("", response_model=Page[ControlRead], dependencies=[Depends(require("control:read"))])
async def list_controls(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ControlRead]:
    stmt = select(Control).where(Control.deleted.is_(False))
    if search:
        stmt = stmt.where(Control.name.ilike(f"%{search}%") | Control.reference.ilike(f"%{search}%"))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _CONTROL_SORTABLE, default=Control.name)
    else:
        stmt = stmt.order_by(Control.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.options(*_loads()).limit(limit).offset(offset))).all()
    await _attach_risks_bulk(db, rows)
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
    stash = {"requirements": data.pop("requirement_ids", []), "risks": data.pop("risk_ids", [])}
    explicit_audit = data.pop("next_audit_date", None)
    explicit_maint = data.pop("next_maintenance_date", None)
    control = Control(tenant_id=user.tenant_id, **data)
    control.policies = await _load_policies(db, policy_ids)
    # Honour an explicit schedule date, otherwise derive it from the frequency.
    control.next_audit_date = explicit_audit or next_review_date(control.audit_frequency)
    control.next_maintenance_date = explicit_maint or next_review_date(control.maintenance_frequency)
    db.add(control)
    await db.flush()
    await _flush_assoc(db, control.id, stash)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="control", entity_id=control.id,
        summary=f"Created control {control.reference or control.name}",
    )
    return ControlRead.model_validate(await _fresh(db, control.id))


@router.get(
    "/{control_id}", response_model=ControlRead, dependencies=[Depends(require("control:read"))]
)
async def get_control(control_id: uuid.UUID, db: DbSession) -> ControlRead:
    return ControlRead.model_validate(await _attach_risks(db, await _get_or_404(db, control_id)))


@router.patch(
    "/{control_id}", response_model=ControlRead, dependencies=[Depends(require("control:write"))]
)
async def update_control(
    control_id: uuid.UUID, body: ControlUpdate, db: DbSession, user: CurrentUser
) -> ControlRead:
    control = await _get_or_404(db, control_id)
    data = body.model_dump(exclude_unset=True)
    policy_ids = data.pop("policy_ids", None)
    stash = {
        "requirements": data.pop("requirement_ids", _KEEP),
        "risks": data.pop("risk_ids", _KEEP),
    }
    explicit_audit = data.pop("next_audit_date", _KEEP)
    explicit_maint = data.pop("next_maintenance_date", _KEEP)
    for field, value in data.items():
        setattr(control, field, value)
    if policy_ids is not None:
        control.policies = await _load_policies(db, policy_ids)
    # Explicit schedule date wins; else recompute when the frequency changed.
    if explicit_audit is not _KEEP:
        control.next_audit_date = explicit_audit
    elif "audit_frequency" in data:
        control.next_audit_date = next_review_date(control.audit_frequency, control.last_audit_date)
    if explicit_maint is not _KEEP:
        control.next_maintenance_date = explicit_maint
    elif "maintenance_frequency" in data:
        control.next_maintenance_date = next_review_date(
            control.maintenance_frequency, control.last_maintenance_date
        )
    await db.flush()
    await _flush_assoc(db, control.id, stash)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="control", entity_id=control.id,
        summary=f"Updated control {control.reference or control.name}",
    )
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
    db.add(ControlAudit(tenant_id=user.tenant_id, control_id=control_id,
                        **{**body.model_dump(), "conducted_date": conducted}))
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
        ControlMaintenance(tenant_id=user.tenant_id, control_id=control_id,
                           **{**body.model_dump(), "conducted_date": conducted})
    )
    control.last_maintenance_date = conducted
    control.next_maintenance_date = next_review_date(control.maintenance_frequency, conducted)
    await db.flush()
    return ControlRead.model_validate(await _fresh(db, control.id))
