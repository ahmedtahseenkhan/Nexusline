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
from app.services import control_assurance
from app.services import audit as audit_log
from app.services import delete_guard
from app.services import dual_control
from app.services import ref_fields

router = APIRouter(prefix="/controls", tags=["controls"])

#: The control's picked fields (phase 1). ``operator_id`` has no text column of its own:
#: the start-up backfill seeds it from the same ``owner`` text. See services.ref_fields.
CONTROL_REFS: tuple[ref_fields.RefField, ...] = (
    ref_fields.user("owner_id", "owner"),
    ref_fields.user("operator_id", None),
    ref_fields.lookup(Control, "classification_id", "classification"),
    ref_fields.WORKFLOW_OWNER,
)
#: A control test's tester; ``auditor`` stays as the tester's name.
AUDIT_REFS: tuple[ref_fields.RefField, ...] = (ref_fields.user("tested_by_id", "auditor"),)


async def _read(db, control: Control) -> ControlRead:
    read = ControlRead.model_validate(control)
    await ref_fields.fill_refs(db, [(control, read)], CONTROL_REFS)
    return read


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

    return list(
        (
            await db.scalars(
                select(Policy).where(Policy.id.in_(ids), Policy.deleted.is_(False))
            )
        ).all()
    )


async def _resolve_assets(db, ids):
    if not ids:
        return []
    from app.models.asset import Asset

    return list((await db.scalars(select(Asset).where(Asset.id.in_(ids)))).all())


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
        select(Control).where(Control.id == control_id, Control.deleted.is_(False))
        .options(*_loads()).execution_options(populate_existing=True)
    )
    if control is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control not found")
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
    owner_id: uuid.UUID | None = None,
    operator_id: uuid.UUID | None = None,
    classification_id: uuid.UUID | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ControlRead]:
    stmt = select(Control).where(Control.deleted.is_(False))
    if search:
        stmt = stmt.where(Control.name.ilike(f"%{search}%") | Control.reference.ilike(f"%{search}%"))
    if owner_id is not None:
        stmt = stmt.where(Control.owner_id == owner_id)
    if operator_id is not None:
        stmt = stmt.where(Control.operator_id == operator_id)
    if classification_id is not None:
        stmt = stmt.where(Control.classification_id == classification_id)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _CONTROL_SORTABLE, default=Control.name)
    else:
        stmt = stmt.order_by(Control.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.options(*_loads()).limit(limit).offset(offset))).all()
    await _attach_risks_bulk(db, rows)
    items = [ControlRead.model_validate(r) for r in rows]
    await ref_fields.fill_refs(db, list(zip(rows, items)), CONTROL_REFS)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=ControlRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("control:write"))],
)
async def create_control(body: ControlCreate, db: DbSession, user: CurrentUser) -> ControlRead:
    data = body.model_dump()
    await ref_fields.apply_refs(db, Control, data, CONTROL_REFS)
    policy_ids = data.pop("policy_ids", [])
    asset_ids = data.pop("asset_ids", [])
    stash = {"requirements": data.pop("requirement_ids", []), "risks": data.pop("risk_ids", [])}
    explicit_audit = data.pop("next_audit_date", None)
    explicit_maint = data.pop("next_maintenance_date", None)
    control = Control(tenant_id=user.tenant_id, **data)
    control.policies = await _load_policies(db, policy_ids)
    control.assets = await _resolve_assets(db, asset_ids)
    # Honour an explicit schedule date, otherwise derive it from the frequency — but only
    # for a live control: a planned (or retired) one carries no test clock at all.
    control.next_audit_date = control_assurance.next_cycle_date(
        control.status, control.audit_frequency, explicit=explicit_audit,
        explicit_given=explicit_audit is not None, became_testable=True,
    )
    control.next_maintenance_date = control_assurance.next_cycle_date(
        control.status, control.maintenance_frequency, explicit=explicit_maint,
        explicit_given=explicit_maint is not None, became_testable=True,
    )
    db.add(control)
    await db.flush()
    await _flush_assoc(db, control.id, stash)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="control", entity_id=control.id,
        summary=f"Created control {control.reference or control.name}",
    )
    return await _read(db, await _fresh(db, control.id))


@router.get(
    "/{control_id}", response_model=ControlRead, dependencies=[Depends(require("control:read"))]
)
async def get_control(control_id: uuid.UUID, db: DbSession) -> ControlRead:
    return await _read(db, await _attach_risks(db, await _get_or_404(db, control_id)))


@router.patch(
    "/{control_id}", response_model=ControlRead, dependencies=[Depends(require("control:write"))]
)
async def update_control(
    control_id: uuid.UUID, body: ControlUpdate, db: DbSession, user: CurrentUser
) -> ControlRead:
    control = await _get_or_404(db, control_id)
    data = body.model_dump(exclude_unset=True)
    await ref_fields.apply_refs(db, Control, data, CONTROL_REFS, record=control)
    policy_ids = data.pop("policy_ids", None)
    asset_ids = data.pop("asset_ids", None)
    stash = {
        "requirements": data.pop("requirement_ids", _KEEP),
        "risks": data.pop("risk_ids", _KEEP),
    }
    explicit_audit = data.pop("next_audit_date", _KEEP)
    explicit_maint = data.pop("next_maintenance_date", _KEEP)
    was_testable = control_assurance.carries_test_clock(control.status)
    for field, value in data.items():
        setattr(control, field, value)
    if policy_ids is not None:
        control.policies = await _load_policies(db, policy_ids)
    if asset_ids is not None:
        control.assets = await _resolve_assets(db, asset_ids)
    # The test clock: none while planned or retired (an explicit date is ignored); it
    # starts when the control goes live; an explicit date wins after that, and a changed
    # frequency (or a date cleared to blank) re-derives it from the last run.
    became_testable = not was_testable and control_assurance.carries_test_clock(control.status)
    control.next_audit_date = control_assurance.next_cycle_date(
        control.status, control.audit_frequency, current=control.next_audit_date,
        explicit=None if explicit_audit is _KEEP else explicit_audit,
        explicit_given=explicit_audit is not _KEEP,
        frequency_changed="audit_frequency" in data,
        became_testable=became_testable, last_done=control.last_audit_date,
    )
    control.next_maintenance_date = control_assurance.next_cycle_date(
        control.status, control.maintenance_frequency, current=control.next_maintenance_date,
        explicit=None if explicit_maint is _KEEP else explicit_maint,
        explicit_given=explicit_maint is not _KEEP,
        frequency_changed="maintenance_frequency" in data,
        became_testable=became_testable, last_done=control.last_maintenance_date,
    )
    await db.flush()
    await _flush_assoc(db, control.id, stash)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="control", entity_id=control.id,
        summary=f"Updated control {control.reference or control.name}",
        changes={k: str(v) for k, v in data.items()},
    )
    return await _read(db, await _fresh(db, control.id))


@router.delete(
    "/{control_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("control:write"))],
)
async def delete_control(control_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Archive a control (soft delete, audit-logged).

    **Dual control** ``control / delete``: while segregation of duties applies, whoever
    entered the control (``dual_control.maker_of``) cannot also archive it — 403.
    """
    from datetime import datetime, timezone

    control = await _get_or_404(db, control_id)
    await delete_guard.enforce(db, entity_type="control", record=control, user=user, label="control")
    control.deleted = True
    control.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="delete", entity_type="control", entity_id=control.id,
        summary=f"Archived control {control.reference or control.name}",
    )


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
    items = [ControlAuditRead.model_validate(r) for r in rows]
    await ref_fields.fill_refs(db, list(zip(rows, items)), AUDIT_REFS)
    return items


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
    # An audit result is assurance evidence: the person who created the control cannot
    # also sign off its audit. Independence is the whole point of the test.
    await dual_control.enforce_record_maker_checker(
        db, module="control", action="audit", entity_type="control", entity_id=control.id,
        checker_id=user.id, subject="control audit",
    )
    fields = body.model_dump()
    await ref_fields.apply_refs(db, ControlAudit, fields, AUDIT_REFS)
    # The named tester is a checker too: recording on someone's behalf must not let the
    # control's own maker be written down as its independent tester.
    if fields.get("tested_by_id") not in (None, user.id):
        await dual_control.enforce_record_maker_checker(
            db, module="control", action="audit", entity_type="control", entity_id=control.id,
            checker_id=fields["tested_by_id"], subject="control audit",
        )
    conducted = body.conducted_date or date.today()
    override = fields.pop("effectiveness", None)
    db.add(ControlAudit(tenant_id=user.tenant_id, control_id=control_id,
                        **{**fields, "conducted_date": conducted}))
    control.last_audit_date = conducted
    control.next_audit_date = control_assurance.after_test_date(
        control.status, control.audit_frequency, conducted
    )

    # The test *is* the assessment. Recording "passed" and then separately editing the
    # control to say "effective" was two steps where one is the record; the second was
    # skipped in practice and every control stayed not-assessed, which starved the
    # residual suggestion on every risk it mitigates.
    before = control.effectiveness
    after = control_assurance.effectiveness_after_test(body.result, override, before)
    changes = {}
    if after != before:
        control.effectiveness = after
        changes = {"effectiveness": {"from": before.value, "to": after.value}}
    await db.flush()
    await audit_log.record(
        db, actor=user, action="audit", entity_type="control", entity_id=control.id,
        summary=f"Recorded {body.result.value} audit for control {control.reference or control.name}"
        + (f" — effectiveness {before.value} → {after.value}" if changes else ""),
        changes=changes,
    )
    return await _read(db, await _fresh(db, control.id))


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
    control.next_maintenance_date = control_assurance.after_test_date(
        control.status, control.maintenance_frequency, conducted
    )
    await db.flush()
    return await _read(db, await _fresh(db, control.id))
