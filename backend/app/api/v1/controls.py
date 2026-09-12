"""Internal controls — CRUD, attributes, derived effectiveness, and the recurring
test (workpaper + four-eyes review) and maintenance cycles."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.audit import AuditLog
from app.models.compliance import Requirement, requirement_controls
from app.models.control import (
    Control,
    ControlAudit,
    ControlMaintenance,
    control_business_units,
    control_processes,
)
from app.models.enums import ControlEffectiveness, EvidenceStatus, TestResult
from app.models.evidence import Evidence
from app.models.identity import User
from app.models.issue import Issue, IssueSource, IssueStatus2, issue_controls
from app.models.organization import BusinessUnit, Process
from app.models.risk import Risk, risk_controls
from app.schemas.bulk import BulkMapRequirementsBody, BulkResult, BulkResultItem
from app.schemas.common import GraphRef, Page
from app.schemas.control import (
    CONCLUSIVE_RESULTS,
    OVERRIDE_REASON_NEEDED,
    REVIEW_PENDING,
    REVIEW_RETURNED,
    REVIEW_REVIEWED,
    ControlAuditCreate,
    ControlAuditRead,
    ControlCreate,
    ControlMaintenanceCreate,
    ControlMaintenanceRead,
    ControlRead,
    ControlTestReview,
    ControlUpdate,
    EffectivenessOverride,
    workpaper_problems,
)
from app.services import bulk_edit
from app.services import clause_suggestions
from app.services import control_assurance
from app.services import drill_through
from app.services import audit as audit_log
from app.services import delete_guard
from app.services import dual_control
from app.services import ref_fields
from app.services.refs import next_reference


TESTER_INDEPENDENCE_DETAIL = (
    "Segregation of duties: you entered this control, so someone independent must test "
    "it. Ask a colleague to record the test, or name them as the tester."
)

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
#: What a test shows: the tester and the reviewer.
AUDIT_READ_REFS: tuple[ref_fields.RefField, ...] = AUDIT_REFS + (ref_fields.user("reviewed_by_id", None),)
#: The permission to record and review control tests (``control:write`` edits the control).
TEST_PERMISSION = "control:test"
_OPEN_ISSUE_EXCLUDED = tuple(IssueStatus2(s) for s in control_assurance.CLOSED_ISSUE_STATES)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


async def _open_issues_by_control(db, control_ids) -> dict:
    """Open issues linked to each control, as graph refs — one query for a page."""
    ids = list(control_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(issue_controls.c.control_id, Issue.id, Issue.reference, Issue.title)
            .join(Issue, Issue.id == issue_controls.c.issue_id)
            .where(
                issue_controls.c.control_id.in_(ids),
                Issue.deleted.is_(False),
                Issue.status.notin_(_OPEN_ISSUE_EXCLUDED),
            )
            .order_by(Issue.reference)
        )
    ).all()
    out: dict = {}
    for control_id, iid, ref, title in rows:
        out.setdefault(control_id, []).append(GraphRef(id=iid, reference=ref or "", title=title or ""))
    return out


async def _reads(db, controls) -> list[ControlRead]:
    items = [ControlRead.model_validate(c) for c in controls]
    await ref_fields.fill_refs(db, list(zip(controls, items)), CONTROL_REFS)
    open_issues = await _open_issues_by_control(db, [c.id for c in controls])
    for control, item in zip(controls, items):
        tests = list(control.audits or [])
        # Design / operating are shown as derived from the tests even where the stored
        # columns have not been re-derived yet (controls tested before Phase 2 until
        # their next recompute); the combined rating shown is always the stored one —
        # the value the rest of the platform reads.
        derived = control_assurance.derive_effectiveness(
            tests, has_open_issue=bool(open_issues.get(control.id)),
            override_reason=control.effectiveness_override_reason or "", current=control.effectiveness,
        )
        item.design_effectiveness = derived.design
        item.operating_effectiveness = derived.operating
        item.effectiveness_basis = derived.basis
        item.pending_review_count = sum(1 for t in tests if t.review_status == REVIEW_PENDING)
        item.open_issues = open_issues.get(control.id, [])
        item.business_units = [u for u in item.business_units if not _is_archived(control.business_units, u.id)]
        item.processes = [p for p in item.processes if not _is_archived(control.processes, p.id)]
    return items


def _is_archived(rows, rid) -> bool:
    return any(r.id == rid and getattr(r, "deleted", False) for r in rows or [])


async def _read(db, control: Control) -> ControlRead:
    return (await _reads(db, [control]))[0]


def _loads():
    # policies/requirements are lazy="selectin" already, but eager-load explicitly so a
    # populate_existing refresh re-reads them after we rewrite the join tables.
    return (
        selectinload(Control.policies),
        selectinload(Control.requirements),
        selectinload(Control.business_units),
        selectinload(Control.processes),
        selectinload(Control.audits),
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


async def _resolve_scope(db, model, ids, field: str) -> list:
    """Business units / processes for the control's scope; unknown or archived ids are a
    422 naming the field."""
    if not ids:
        return []
    ids = list(dict.fromkeys(ids))
    rows = (
        await db.scalars(select(model).where(model.id.in_(ids), model.deleted.is_(False)))
    ).all()
    missing = sorted(str(i) for i in set(ids) - {r.id for r in rows})
    if missing:
        noun = "business unit" if model is BusinessUnit else "process"
        raise _unprocessable(f"{field}: no such {noun} (or it is archived): {', '.join(missing)}")
    return list(rows)


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
    "design_effectiveness": Control.design_effectiveness,
    "operating_effectiveness": Control.operating_effectiveness,
    "nature": Control.nature,
    "automation": Control.automation,
    "is_key": Control.is_key,
    "operating_frequency": Control.operating_frequency,
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
    nature: str | None = None,
    automation: str | None = None,
    is_key: bool | None = None,
    business_unit_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    assurance: Annotated[
        drill_through.AssuranceFilter | None,
        Query(description=(
            "assured | effective | partially_effective | failing | not_assessed (operating "
            "controls with that rating) · not_operating (planned or retired) · unmapped "
            "(implements no live clause) — the dashboard's control-assurance numbers"
        )),
    ] = None,
    test: Annotated[
        drill_through.TestFilter | None,
        Query(description=(
            "overdue | due_30d | failed (the latest reviewed or pre-review test failed) — "
            "operating controls only, as the dashboard counts them"
        )),
    ] = None,
    key: Annotated[bool | None, Query(description="Key controls only (true) or the rest (false); same as is_key")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ControlRead]:
    stmt = select(Control).where(Control.deleted.is_(False))
    if is_key is None:
        is_key = key
    # Drill-through filters: the same predicates the dashboard counts with.
    if assurance:
        stmt = stmt.where(drill_through.control_assurance_clause(assurance))
    if test:
        stmt = stmt.where(drill_through.control_test_clause(test, date.today()))
    if nature:
        stmt = stmt.where(Control.nature == nature)
    if automation:
        stmt = stmt.where(Control.automation == automation)
    if is_key is not None:
        stmt = stmt.where(Control.is_key.is_(is_key))
    if business_unit_id is not None:
        stmt = stmt.where(Control.id.in_(
            select(control_business_units.c.control_id)
            .where(control_business_units.c.business_unit_id == business_unit_id)
        ))
    if process_id is not None:
        stmt = stmt.where(Control.id.in_(
            select(control_processes.c.control_id).where(control_processes.c.process_id == process_id)
        ))
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
    return Page(items=await _reads(db, rows), total=total, limit=limit, offset=offset)


def _clause_label(requirement) -> str:
    fw = requirement.framework.name if getattr(requirement, "framework", None) else ""
    return f"{requirement.reference or requirement.title}" + (f" ({fw})" if fw else "")


@router.post(
    "/bulk/map-requirements",
    response_model=BulkResult,
    dependencies=[Depends(require("control:write"))],
    summary="Map many controls to the same requirements",
)
async def bulk_map_requirements(
    body: BulkMapRequirementsBody, db: DbSession, user: CurrentUser
) -> BulkResult:
    """Link every listed control to every listed requirement ("Map to requirements" on
    the register). Links are added, never removed. The requirements are checked once —
    an unknown or archived one is a 422 naming it; a control that is archived or not
    found is skipped, and one already linked to all of them is skipped as "already
    mapped". Links go through the clause-suggestion writer (``clause_suggestions.link``)
    and need ``control:write``, as accepting a suggestion does. One audit entry per
    control that gained a link, each carrying the batch id."""
    batch = bulk_edit.new_batch_id()
    requirement_ids = list(dict.fromkeys(body.requirement_ids))
    requirements = (
        await db.scalars(
            select(Requirement)
            .options(selectinload(Requirement.framework))
            .where(Requirement.id.in_(requirement_ids), Requirement.deleted.is_(False))
        )
    ).all()
    missing = sorted(str(i) for i in set(requirement_ids) - {r.id for r in requirements})
    if missing:
        raise _unprocessable(f"requirement_ids: unknown or archived requirement(s): {', '.join(missing)}")
    control_ids = list(dict.fromkeys(body.control_ids))
    found = {
        c.id: c for c in (await db.scalars(select(Control).where(Control.id.in_(control_ids)))).all()
        if c.tenant_id == user.tenant_id
    }
    live = [found[cid] for cid in control_ids if cid in found and not found[cid].deleted]
    written = await clause_suggestions.link(db, [(c.id, r.id) for c in live for r in requirements])
    gained: dict = {}
    for control, requirement in written:
        gained.setdefault(control.id, []).append(requirement)

    results: list[BulkResultItem] = []
    for cid in control_ids:
        control = found.get(cid)
        if control is None:
            results.append(BulkResultItem(id=cid, outcome="skipped", reason=bulk_edit.NOT_FOUND))
            continue
        ref, label = control.reference or "", " ".join(p for p in (control.reference, control.name) if p)
        if control.deleted:
            results.append(BulkResultItem(id=cid, reference=ref, label=label, outcome="skipped", reason=bulk_edit.ARCHIVED))
            continue
        new = gained.get(cid, [])
        if not new:
            results.append(BulkResultItem(id=cid, reference=ref, label=label, outcome="skipped", reason="already mapped"))
            continue
        shown = ", ".join(_clause_label(r) for r in new[:8]) + (f" and {len(new) - 8} more" if len(new) > 8 else "")
        await audit_log.record(
            db, actor=user, action="map_requirements", entity_type="control", entity_id=cid,
            summary=f"Bulk-mapped {label} to {len(new)} requirement(s): {shown}"[:500],
            changes={"batch_id": batch, "bulk": True, "requirement_ids": [str(r.id) for r in new]},
        )
        results.append(BulkResultItem(
            id=cid, reference=ref, label=label, outcome="updated",
            changed=[f"{len(new)} requirement{'s' if len(new) != 1 else ''}"],
        ))
    updated = sum(1 for r in results if r.outcome == "updated")
    return BulkResult(
        entity_type="control", batch_id=batch, updated=updated, skipped=len(results) - updated,
        summary=bulk_edit.summarize(results), results=results,
    )


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
    unit_ids = data.pop("business_unit_ids", [])
    process_ids = data.pop("process_ids", [])
    stash = {"requirements": data.pop("requirement_ids", []), "risks": data.pop("risk_ids", [])}
    explicit_audit = data.pop("next_audit_date", None)
    explicit_maint = data.pop("next_maintenance_date", None)
    # A new control has no tests: any rating other than not assessed is set by hand and
    # carries its reason (the schema has already refused one without).
    reason = (data.pop("effectiveness_override_reason", "") or "").strip()
    control = Control(tenant_id=user.tenant_id, **data)
    control.effectiveness_override_reason = (
        reason if control.effectiveness != ControlEffectiveness.not_assessed else ""
    )
    control.policies = await _load_policies(db, policy_ids)
    control.assets = await _resolve_assets(db, asset_ids)
    control.business_units = await _resolve_scope(db, BusinessUnit, unit_ids, "business_unit_ids")
    control.processes = await _resolve_scope(db, Process, process_ids, "process_ids")
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
        summary=f"Created control {control.reference or control.name}"
        + (f" rated {control.effectiveness.value} by hand: {reason}"[:300] if control.effectiveness_override_reason else ""),
        changes=(
            {"effectiveness": control.effectiveness.value, "effectiveness_override_reason": reason}
            if control.effectiveness_override_reason else None
        ),
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
    unit_ids = data.pop("business_unit_ids", None)
    process_ids = data.pop("process_ids", None)
    override = _override_edit(control, data)
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
    if unit_ids is not None:
        control.business_units = await _resolve_scope(db, BusinessUnit, unit_ids, "business_unit_ids")
    if process_ids is not None:
        control.processes = await _resolve_scope(db, Process, process_ids, "process_ids")
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
    if override is not None:
        await _apply_override(db, control, user, *override)
    return await _read(db, await _fresh(db, control.id))


# ------------------------------------------------------------ effectiveness override
def _override_edit(control: Control, data: dict) -> tuple[ControlEffectiveness | None, str] | None:
    """Take the effectiveness fields out of an update, and say what they ask for:
    ``None`` (nothing — an unchanged value is what a form resaving every field sends),
    ``(value, reason)`` to set an override, or ``(None, "")`` to drop it. A changed
    value without a reason (sent now, or already on the control) is a 422."""
    sent = data.pop("effectiveness", None)
    reason_sent = "effectiveness_override_reason" in data
    reason = (data.pop("effectiveness_override_reason", None) or "").strip()
    current_reason = control.effectiveness_override_reason or ""
    if sent is not None and sent != control.effectiveness:
        if not (reason or current_reason):
            raise _unprocessable(OVERRIDE_REASON_NEEDED)
        return sent, reason or current_reason
    if reason_sent and not reason:
        return (None, "") if current_reason else None
    if reason and reason != current_reason:
        return control.effectiveness, reason
    return None


async def _apply_override(db, control: Control, user, value: ControlEffectiveness | None, reason: str) -> None:
    """Set (``value`` + ``reason``) or drop (``None``) a manual effectiveness rating,
    re-derive the design/operating ratings beside it, and audit the change."""
    before = control.effectiveness
    if value is not None:
        control.effectiveness = value
        control.effectiveness_override_reason = reason
        await control_assurance.recompute(db, control)
        summary = (f"Overrode effectiveness of {control.reference or control.name}: "
                   f"{before.value} → {value.value} — {reason}")
        action = "override_effectiveness"
    else:
        control.effectiveness_override_reason = ""
        await control_assurance.recompute(db, control, forget_manual=True)
        summary = (f"Dropped the effectiveness override on {control.reference or control.name}: "
                   f"{before.value} → {control.effectiveness.value} (derived from tests)")
        action = "clear_override"
    await db.flush()
    await audit_log.record(
        db, actor=user, action=action, entity_type="control", entity_id=control.id,
        summary=summary[:500],
        changes={"effectiveness": {"from": before.value, "to": control.effectiveness.value},
                 "effectiveness_override_reason": reason},
    )


@router.post(
    "/{control_id}/effectiveness-override",
    response_model=ControlRead,
    dependencies=[Depends(require("control:write"))],
    summary="Set the control's effectiveness by hand, with a reason",
)
async def override_effectiveness(
    control_id: uuid.UUID, body: EffectivenessOverride, db: DbSession, user: CurrentUser
) -> ControlRead:
    """The combined rating normally derives from reviewed tests. An override replaces it
    until it is dropped or the next test is approved; the design and operating ratings
    stay derived and visible beside it. Audited with the reason."""
    control = await _get_or_404(db, control_id)
    await _apply_override(db, control, user, body.effectiveness, body.reason)
    return await _read(db, await _fresh(db, control.id))


@router.delete(
    "/{control_id}/effectiveness-override",
    response_model=ControlRead,
    dependencies=[Depends(require("control:write"))],
    summary="Drop a manual effectiveness override",
)
async def clear_effectiveness_override(control_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ControlRead:
    control = await _get_or_404(db, control_id)
    if not control.effectiveness_override_reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The effectiveness is not overridden.")
    await _apply_override(db, control, user, None, "")
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
# A control test is a workpaper: what was tested (design or operating), over which
# period, on what sample, what was found, and the evidence. It is recorded by (or on
# behalf of) the tester and starts *pending review*; it changes nothing about the
# control until an independent reviewer approves it (``review_test`` below). A failed
# test, or one with exceptions, opens an issue on approval.
async def _test_or_404(db, control_id: uuid.UUID, audit_id: uuid.UUID) -> ControlAudit:
    audit = await db.scalar(
        select(ControlAudit).where(ControlAudit.id == audit_id, ControlAudit.control_id == control_id)
        .execution_options(populate_existing=True)
    )
    if audit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control test not found")
    return audit


async def _makers_by_test(db, tests) -> dict:
    """Everyone who put their name to each test: its tester, whoever recorded it and
    whoever edited it since (the trail's create/update entries). None of them may
    review it."""
    ids = [t.id for t in tests]
    out: dict = {t.id: ({t.tested_by_id} if t.tested_by_id else set()) for t in tests}
    if not ids:
        return out
    rows = (
        await db.execute(
            select(AuditLog.entity_id, AuditLog.actor_id).where(
                AuditLog.entity_type == "control_audit",
                AuditLog.entity_id.in_(ids),
                AuditLog.action.in_(("create", "update")),
            )
        )
    ).all()
    for test_id, actor_id in rows:
        if actor_id is not None:
            out.setdefault(test_id, set()).add(actor_id)
    return out


async def _evidence_to_attach(db, control_id, ids, audit_id=None) -> list[Evidence]:
    """The existing evidence a test cites: this control's, and not already supporting
    another test (an item supports one test; re-pointing it would strip the other)."""
    ids = list(dict.fromkeys(ids or []))
    if not ids:
        return []
    rows = list((await db.scalars(select(Evidence).where(Evidence.id.in_(ids)))).all())
    missing = sorted(str(i) for i in set(ids) - {r.id for r in rows})
    if missing:
        raise _unprocessable(f"evidence_ids: no such evidence: {', '.join(missing)}")
    for r in rows:
        if r.control_id != control_id:
            raise _unprocessable(f"evidence_ids: '{r.title}' is evidence of another control.")
        if r.control_audit_id not in (None, audit_id):
            raise _unprocessable(
                f"evidence_ids: '{r.title}' already supports another test of this control; "
                "add a new evidence item for this one."
            )
    return rows


def _check_workpaper(body: ControlAuditCreate) -> None:
    problems = workpaper_problems(
        body.result, test_type=body.test_type, period_start=body.period_start,
        period_end=body.period_end,
        evidence_count=len(set(body.evidence_ids)) + len(body.new_evidence),
    )
    if problems:
        raise _unprocessable(" ".join(problems))


def _add_new_evidence(db, user, control_id, audit: ControlAudit, items) -> None:
    for item in items:
        db.add(Evidence(
            tenant_id=user.tenant_id, control_id=control_id, control_audit_id=audit.id,
            title=item.title, evidence_type=item.evidence_type, reference=item.reference,
            description=item.description,
            collected_at=item.collected_at or audit.conducted_date,
            status=EvidenceStatus.valid,
        ))


def _move_clock(control: Control, audit: ControlAudit) -> None:
    """A performed test (a conclusive result) moves the test clock; a placeholder does not."""
    if audit.result not in CONCLUSIVE_RESULTS or audit.conducted_date is None:
        return
    if control.last_audit_date is None or audit.conducted_date >= control.last_audit_date:
        control.last_audit_date = audit.conducted_date
        control.next_audit_date = control_assurance.after_test_date(
            control.status, control.audit_frequency, audit.conducted_date
        )


def _test_label(audit: ControlAudit) -> str:
    kind = f"{audit.test_type} " if audit.test_type else ""
    return f"{audit.result.value.replace('_', ' ')} {kind}test"


@router.get(
    "/{control_id}/audits",
    response_model=list[ControlAuditRead],
    dependencies=[Depends(require("control:read"))],
)
async def list_control_audits(control_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[ControlAuditRead]:
    """The control's tests, newest first, with their review state, evidence and raised
    issue — and, for the signed-in user, whether they may review or edit each one."""
    await _get_or_404(db, control_id)
    rows = (
        await db.scalars(
            select(ControlAudit)
            .where(ControlAudit.control_id == control_id)
            .order_by(ControlAudit.created_at.desc())
        )
    ).all()
    items = [ControlAuditRead.model_validate(r) for r in rows]
    await ref_fields.fill_refs(db, list(zip(rows, items)), AUDIT_READ_REFS)
    ids = [r.id for r in rows]
    evidence: dict = {}
    if ids:
        for ev in (
            await db.scalars(select(Evidence).where(Evidence.control_audit_id.in_(ids)).order_by(Evidence.title))
        ).all():
            evidence.setdefault(ev.control_audit_id, []).append(GraphRef(id=ev.id, title=ev.title))
    issue_ids = [r.raised_issue_id for r in rows if r.raised_issue_id]
    issues = {}
    if issue_ids:
        issues = {
            i.id: GraphRef(id=i.id, reference=i.reference or "", title=i.title or "")
            for i in (await db.scalars(select(Issue).where(Issue.id.in_(issue_ids)))).all()
        }
    holds = TEST_PERMISSION in set(getattr(user, "permission_codes", []) or [])
    required, _rule = await dual_control.dual_control_required(db, "control", "review_test")
    makers = await _makers_by_test(db, [r for r in rows if r.review_status == REVIEW_PENDING])
    for row, item in zip(rows, items):
        item.evidence = evidence.get(row.id, [])
        item.raised_issue = issues.get(row.raised_issue_id)
        item.can_edit = holds and row.review_status in (REVIEW_PENDING, REVIEW_RETURNED)
        item.can_review, item.review_blocked_reason = review_eligibility(
            row, holds=holds, sod_required=required, makers=makers.get(row.id, set()), user_id=user.id
        )
    return items


def review_eligibility(test, *, holds: bool, sod_required: bool, makers: set, user_id) -> tuple[bool, str]:
    """May this user approve or return this test? ``(yes, why not)``. Pure."""
    if test.review_status != REVIEW_PENDING:
        return False, ""
    if test.result not in CONCLUSIVE_RESULTS:
        return False, "Nothing to review yet: the test has no result."
    if not holds:
        return False, f"Reviewing a test needs the {TEST_PERMISSION} permission."
    if sod_required and user_id in makers:
        return False, "You performed, recorded or edited this test; an independent reviewer must decide."
    return True, ""


@router.post(
    "/{control_id}/audits",
    response_model=ControlRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(TEST_PERMISSION))],
    summary="Record a control test (workpaper); it awaits independent review",
)
async def record_control_audit(
    control_id: uuid.UUID, body: ControlAuditCreate, db: DbSession, user: CurrentUser
) -> ControlRead:
    """Record a test. A conclusive result needs a date, a conclusion, the test type, a
    period (operating tests) and at least one evidence item — existing evidence of the
    control (``evidence_ids``) or new items created with it (``new_evidence``). The
    test starts *pending review* and changes no rating until it is approved.

    **Dual control** ``control / audit``: neither whoever records the test nor the named
    tester may be the person who entered the control.
    """
    control = await _get_or_404(db, control_id)
    # An audit result is assurance evidence: the person who created the control cannot
    # also sign off its audit. Independence is the whole point of the test.
    await dual_control.enforce_record_maker_checker(
        db, module="control", action="audit", entity_type="control", entity_id=control.id,
        checker_id=user.id, subject="control audit", message=TESTER_INDEPENDENCE_DETAIL,
    )
    _check_workpaper(body)
    fields = body.model_dump(exclude={"evidence_ids", "new_evidence"})
    if fields.get("tested_by_id") is None and not (fields.get("auditor") or "").strip():
        fields["tested_by_id"] = user.id  # recorded by the tester themself
    await ref_fields.apply_refs(db, ControlAudit, fields, AUDIT_REFS)
    # The named tester is a checker too: recording on someone's behalf must not let the
    # control's own maker be written down as its independent tester.
    if fields.get("tested_by_id") not in (None, user.id):
        await dual_control.enforce_record_maker_checker(
            db, module="control", action="audit", entity_type="control", entity_id=control.id,
            checker_id=fields["tested_by_id"], subject="control audit",
            message=(
                "Segregation of duties: the person you named as tester entered this "
                "control, so they can't be its independent tester."
            ),
        )
    cited = await _evidence_to_attach(db, control.id, body.evidence_ids)
    audit = ControlAudit(
        tenant_id=user.tenant_id, control_id=control_id,
        **{**fields, "conducted_date": body.conducted_date or date.today(), "review_status": REVIEW_PENDING},
    )
    db.add(audit)
    await db.flush()
    for ev in cited:
        ev.control_audit_id = audit.id
    _add_new_evidence(db, user, control.id, audit, body.new_evidence)
    _move_clock(control, audit)
    await db.flush()
    evidence_n = len(cited) + len(body.new_evidence)
    await audit_log.record(
        db, actor=user, action="create", entity_type="control_audit", entity_id=audit.id,
        summary=f"Recorded {_test_label(audit)} of {control.reference or control.name} "
        f"with {evidence_n} evidence item(s) — pending review",
    )
    await audit_log.record(
        db, actor=user, action="audit", entity_type="control", entity_id=control.id,
        summary=f"Recorded {_test_label(audit)} for control {control.reference or control.name} — pending review",
        changes={"test_id": str(audit.id), "result": audit.result.value, "test_type": audit.test_type},
    )
    return await _read(db, await _fresh(db, control.id))


@router.put(
    "/{control_id}/audits/{audit_id}",
    response_model=ControlRead,
    dependencies=[Depends(require(TEST_PERMISSION))],
    summary="Edit a pending or returned test and resubmit it for review",
)
async def update_control_audit(
    control_id: uuid.UUID, audit_id: uuid.UUID, body: ControlAuditCreate, db: DbSession, user: CurrentUser
) -> ControlRead:
    """Replace the workpaper of a test that is pending or was returned, and send it back
    for review. The same rules as recording apply; ``evidence_ids`` is the complete list
    of existing evidence the test cites (items no longer listed are detached). An
    approved test is signed off and cannot be edited — record a new test instead.
    Whoever edits a test may not review it."""
    control = await _get_or_404(db, control_id)
    audit = await _test_or_404(db, control_id, audit_id)
    if audit.review_status not in (REVIEW_PENDING, REVIEW_RETURNED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This test has been reviewed and is signed off; record a new test instead.",
        )
    await dual_control.enforce_record_maker_checker(
        db, module="control", action="audit", entity_type="control", entity_id=control.id,
        checker_id=user.id, subject="control audit",
    )
    _check_workpaper(body)
    fields = body.model_dump(exclude={"evidence_ids", "new_evidence"})
    if fields.get("tested_by_id") is None and not (fields.get("auditor") or "").strip():
        fields["tested_by_id"] = audit.tested_by_id or user.id
    await ref_fields.apply_refs(db, ControlAudit, fields, AUDIT_REFS, record=audit)
    tester = fields.get("tested_by_id", audit.tested_by_id)
    if tester not in (None, user.id):
        await dual_control.enforce_record_maker_checker(
            db, module="control", action="audit", entity_type="control", entity_id=control.id,
            checker_id=tester, subject="control audit",
        )
    cited = await _evidence_to_attach(db, control.id, body.evidence_ids, audit_id=audit.id)
    keep = {ev.id for ev in cited}
    for ev in (await db.scalars(select(Evidence).where(Evidence.control_audit_id == audit.id))).all():
        if ev.id not in keep:
            ev.control_audit_id = None
    was = audit.review_status
    conducted = body.conducted_date or audit.conducted_date or date.today()
    for field, value in fields.items():
        setattr(audit, field, value)
    audit.conducted_date = conducted
    audit.review_status = REVIEW_PENDING
    audit.reviewed_by_id = None
    audit.reviewed_at = None
    for ev in cited:
        ev.control_audit_id = audit.id
    _add_new_evidence(db, user, control.id, audit, body.new_evidence)
    _move_clock(control, audit)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="control_audit", entity_id=audit.id,
        summary=f"{'Resubmitted' if was == REVIEW_RETURNED else 'Edited'} {_test_label(audit)} "
        f"of {control.reference or control.name} — pending review",
    )
    return await _read(db, await _fresh(db, control.id))


@router.post(
    "/{control_id}/audits/{audit_id}/review",
    response_model=ControlRead,
    dependencies=[Depends(require(TEST_PERMISSION))],
    summary="Approve or return a pending control test (four-eyes)",
)
async def review_control_audit(
    control_id: uuid.UUID, audit_id: uuid.UUID, body: ControlTestReview, db: DbSession, user: CurrentUser
) -> ControlRead:
    """An independent reviewer's decision on a pending test.

    * **approve** — the test becomes *reviewed* and the control's design / operating /
      combined effectiveness are re-derived (a manual override is dropped: the reviewed
      test replaces it). A *failed* or *passed with exceptions* result opens an issue
      in the same transaction — owned by the control owner, linked to the control,
      high severity when a key control failed.
    * **return** — back to the tester with the note; they edit and resubmit it.

    **Dual control** ``control / review_test``: the reviewer may not be the tester, nor
    anyone who recorded or edited the test — 403.
    """
    control = await _get_or_404(db, control_id)
    audit = await _test_or_404(db, control_id, audit_id)
    if audit.review_status != REVIEW_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a test pending review can be decided; this one is {audit.review_status}.",
        )
    if body.decision == "approve" and audit.result not in CONCLUSIVE_RESULTS:
        raise _unprocessable("This test has no result yet; edit it and record the result before it is approved.")
    for maker in sorted((await _makers_by_test(db, [audit]))[audit.id], key=str):
        await dual_control.enforce_maker_checker(
            db, module="control", action="review_test", maker_id=maker, checker_id=user.id,
            subject="control test",
        )
    audit.reviewed_by_id = user.id
    audit.reviewed_at = datetime.now(timezone.utc)
    audit.review_note = body.note.strip()
    label = f"{_test_label(audit)} of {control.reference or control.name}"
    if body.decision == "return":
        audit.review_status = REVIEW_RETURNED
        await db.flush()
        await audit_log.record(
            db, actor=user, action="review", entity_type="control_audit", entity_id=audit.id,
            summary=f"Returned the {label} to the tester: {audit.review_note}"[:500],
            changes={"decision": "return", "note": audit.review_note},
        )
        return await _read(db, await _fresh(db, control.id))

    audit.review_status = REVIEW_REVIEWED
    issue = None
    if audit.result in control_assurance.ISSUE_RAISING_RESULTS and audit.raised_issue_id is None:
        issue = await _raise_issue(db, user, control, audit)
    dropped = control.effectiveness_override_reason or ""
    control.effectiveness_override_reason = ""  # the reviewed test replaces a manual rating
    changes = await control_assurance.recompute(db, control)
    await db.flush()
    moved = "; ".join(f"{k.replace('_', ' ')} {v['from']} → {v['to']}" for k, v in changes.items())
    await audit_log.record(
        db, actor=user, action="review", entity_type="control_audit", entity_id=audit.id,
        summary=f"Approved the {label}" + (f"; raised {issue.reference}" if issue else ""),
        changes={"decision": "approve", "note": audit.review_note,
                 **({"raised_issue": issue.reference} if issue else {})},
    )
    await audit_log.record(
        db, actor=user, action="review_test", entity_type="control", entity_id=control.id,
        summary=(f"Approved the {label}" + (f" — {moved}" if moved else "")
                 + (" (manual override dropped)" if dropped else ""))[:500],
        changes={"effectiveness": changes, **({"dropped_override": dropped} if dropped else {})},
    )
    return await _read(db, await _fresh(db, control.id))


async def _raise_issue(db, user, control: Control, audit: ControlAudit) -> Issue:
    """Open the issue a failed (or exception-finding) test calls for, linked to the
    control and to the test, owned by the control owner."""
    owner_name = ""
    if control.owner_id is not None:
        owner = await db.get(User, control.owner_id)
        owner_name = (owner.full_name or owner.email) if owner is not None else ""
    period = (
        f" Period tested: {audit.period_start} to {audit.period_end}."
        if audit.period_start and audit.period_end else ""
    )
    sample = (
        f" Sample: {audit.sample_size} of {audit.population_size}."
        if audit.sample_size is not None and audit.population_size is not None else ""
    )
    exceptions = (
        f" Exceptions: {audit.exceptions_count}." + (f" {audit.exceptions_detail}" if audit.exceptions_detail else "")
        if audit.exceptions_count else ""
    )
    issue = Issue(
        tenant_id=control.tenant_id,
        title=control_assurance.issue_title(audit.result, control.reference, control.name),
        description=(
            f"Raised by the approved {_test_label(audit)} of {audit.conducted_date}."
            f"{period}{sample}{exceptions}\n\nConclusion: {audit.conclusion or audit.result_description}"
        ),
        source_type=IssueSource.assessment,
        source_reference=f"{control.reference or control.name} — control test {audit.conducted_date}"[:255],
        source_id=control.id,
        severity=control_assurance.issue_severity(audit.result, bool(control.is_key)),
        status=IssueStatus2.open,
        owner_id=control.owner_id,
        owner=owner_name or control.owner or "",
        identified_date=date.today(),
    )
    issue.reference = await next_reference(db, Issue, "ISS")
    db.add(issue)
    await db.flush()
    await db.execute(insert(issue_controls).values(issue_id=issue.id, control_id=control.id))
    audit.raised_issue_id = issue.id
    await audit_log.record(
        db, actor=user, action="create", entity_type="issue", entity_id=issue.id,
        summary=f"Raised issue {issue.reference}: {issue.title} (from the approved control test)"[:500],
        changes={"source": "control_test", "control_id": str(control.id), "test_id": str(audit.id)},
    )
    return issue


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
    await audit_log.record(
        db, actor=user, action="maintenance", entity_type="control", entity_id=control.id,
        summary=f"Recorded {body.result.value} maintenance for control {control.reference or control.name}"
        + (f": {body.task}" if body.task else ""),
    )
    return await _read(db, await _fresh(db, control.id))
