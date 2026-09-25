"""Incident Management (Security Operations) API — with response-stage lifecycle."""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, delete, func, insert, select
from sqlalchemy.orm import noload, selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.core.schema_loading import options_for, serialize_all
from app.models.asset import Asset, assets_incidents
from app.models.control import Control
from app.models.data_protection import BreachStatus, DataBreach
from app.models.enums import (
    BaselEventType,
    IncidentStatus,
    LossEventStatus,
    NotificationCategory,
    Severity,
    StageStatus,
)
from app.models.identity import Role
from app.models.incident import DEFAULT_STAGES, Incident, IncidentStage
from app.models.notification import EVENT_PREFIX, Notification
from app.models.operational_risk import LossEvent
from app.models.risk import Risk, risk_incidents
from app.models.vendor import Vendor
from app.schemas.common import Page
from app.schemas.incident import (
    IncidentAverages,
    IncidentCreate,
    IncidentRead,
    IncidentSummary,
    IncidentUpdate,
    LossFromIncident,
    StageCreate,
    StageUpdate,
)
from app.services.refs import next_reference
from app.services import audit, delete_guard, drill_through
from app.services import incident_clock as clock
from app.services import ref_fields as rf
from app.services.modules import is_enabled as module_enabled
from app.services.modules import require_module

router = APIRouter(prefix="/incidents", tags=["incidents"])

_KEEP = object()  # sentinel: field absent from request -> leave the link table untouched

# Phase 1 picker fields and the legacy text each one keeps in step (services/ref_fields).
REGULATOR_REF = rf.lookup(Incident, "regulator_id", "regulator")
INCIDENT_REFS = (
    rf.user("assignee_id", "assignee"),
    rf.user("reported_by_id", "reported_by"),
    rf.lookup(Incident, "category_id", "category"),
    rf.lookup(Incident, "classification_id", "classification"),
    REGULATOR_REF,
    rf.WORKFLOW_OWNER,
)
REPORT_REFS = (rf.user("submitted_by_id", "submitted_by"),)
#: A report's regulator (phase 2 column). Not in ``fk_backfill.FK_LOOKUP_KEYS``: reports
#: take their regulator from the incident rather than being backfilled from text.
REPORT_REGULATOR_REF = rf.RefField("regulator_id", "regulator", "lookup", "regulator")

#: Timestamp fields a request may send without an offset (read in the tenant timezone).
TIMESTAMP_FIELDS = (*clock.TIMELINE_FIELDS, "notified_at")
#: Incident-form fields stored on the initial regulatory report, not the incident.
NOTIFICATION_FIELDS = ("notified_at", "regulator_reference")


def with_clock(item: IncidentRead, row: Incident, now=None) -> IncidentRead:
    """Fill the derived regulator-notification clock and response times on a read."""
    c = clock.notification_clock(row.regulatory_reports, now)
    item.notification_deadline = c.notification_deadline
    item.notified_at = c.notified_at
    item.regulator_reference = c.regulator_reference
    item.hours_to_deadline = c.hours_to_deadline
    item.notified_on_time = c.notified_on_time
    t = clock.response_times(row)
    item.mttd_hours, item.mttc_hours, item.mttr_hours = t.mttd_hours, t.mttc_hours, t.mttr_hours
    return item


async def incident_reads(db, rows) -> list[IncidentRead]:
    """Read models for a page of incidents, with people and lookup values resolved in one
    query per kind across the incidents and their regulatory reports."""
    now = clock.now_utc()
    items = await serialize_all(db, rows, lambda r: with_clock(IncidentRead.model_validate(r), r, now))
    pairs: list = []
    for row, item in zip(rows, items):
        pairs.append((row, item))
        pairs.extend(zip(row.regulatory_reports, item.regulatory_reports))
    # REGULATOR_REF also fills each report's regulator_ref (same field, same list).
    await rf.fill_refs(db, pairs, INCIDENT_REFS + REPORT_REFS)
    return items


async def incident_read(db, obj: Incident) -> IncidentRead:
    return (await incident_reads(db, [obj]))[0]


def _loads():
    return (
        selectinload(Incident.stages),
        selectinload(Incident.regulatory_reports),
        selectinload(Incident.controls),
        selectinload(Incident.vendors),
        selectinload(Incident.assets),
        selectinload(Incident.risks),
        selectinload(Incident.loss_events),
        selectinload(Incident.data_breaches),
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
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    return list((await db.scalars(stmt)).all())


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


async def _validate_ids(db, model, ids, label: str) -> None:
    """Reject unknown/soft-deleted link ids with a 400 before they reach the FK layer
    (an invalid id would otherwise abort the transaction with a 500)."""
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


async def _flush_assoc(db, incident_id, asset_ids, risk_ids) -> None:
    await _validate_ids(db, Asset, asset_ids, "asset")
    await _validate_ids(db, Risk, risk_ids, "risk")
    await _set_assoc(db, assets_incidents, "incident_id", "asset_id", incident_id, asset_ids)
    await _set_assoc(db, risk_incidents, "incident_id", "risk_id", incident_id, risk_ids)


async def _fresh(db, incident_id: uuid.UUID) -> Incident:
    obj = await db.scalar(
        select(Incident)
        .where(Incident.id == incident_id, Incident.deleted.is_(False))
        .options(*_loads())
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return obj


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
    return await next_reference(db, Incident, "INC")


_INCIDENT_SORTABLE = {
    "reference": Incident.reference,
    "title": Incident.title,
    "category": Incident.category,
    "severity": Incident.severity,
    "status": Incident.status,
    "detected_at": Incident.detected_at,
    "occurred_at": Incident.occurred_at,
    "resolved_at": Incident.resolved_at,
    "created_at": Incident.created_at,
}


# ------------------------------------------------------------------ rules
def _refuse(problems: list[str]) -> None:
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))


def incident_problems(state: dict) -> list[str]:
    """What is wrong with an incident's merged state: the timeline out of order, or a
    near miss carrying a cost."""
    problems = clock.timeline_problems({f: state.get(f) for f in clock.TIMELINE_FIELDS})
    nm = clock.near_miss_problem(state.get("near_miss"), state.get("cost"))
    return problems + ([nm] if nm else [])


def _record_notification(obj: Incident, sent: dict) -> list[str]:
    try:
        return clock.apply_notification(obj.regulatory_reports, sent)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


def _sync_reports(obj: Incident, user, *, recompute: bool, create_missing: bool) -> list[str]:
    """Keep the incident's regulatory reports in step with its clock (one rule, shared
    with ``POST /incidents/{id}/regulatory-reports/generate``)."""
    changes = clock.sync_regulatory_reports(
        obj, tenant_id=user.tenant_id,
        initial_hours=settings.regulatory_initial_report_hours,
        final_days=settings.regulatory_final_report_days,
        default_regulator=settings.default_regulator,
        recompute=recompute, create_missing=create_missing,
    )
    return [f"{c.report_type.value.replace('_', ' ')} {c.action}" for c in changes]


async def _default_regulator(db, obj: Incident, data: dict) -> None:
    """A reportable incident with no regulator is owed to the default one (SBP): name it
    through the picker rule so the lookup value is matched."""
    if data.get("regulator_id") or data.get("regulator") or obj.regulator_id or obj.regulator:
        return
    patch = {"regulator": settings.default_regulator}
    await rf.apply_refs(db, Incident, patch, (REGULATOR_REF,), record=obj)
    for k, v in patch.items():
        setattr(obj, k, v)


async def _dpo_roles(db, tenant_id) -> list[str]:
    roles = (await db.scalars(select(Role).where(Role.tenant_id == tenant_id))).all()
    return sorted(r.name for r in roles if clock.is_dpo_role(r.name))


async def _hand_off_breach(db, inc: Incident, user) -> tuple[DataBreach | None, str]:
    """Create (once) the data-breach register entry for an incident flagged as a personal
    data breach, and tell the DPO. Returns the breach (new or existing) and a note for
    the audit trail."""
    if not module_enabled("data_protection"):
        return None, "data protection module not enabled; no breach record created"
    existing = await db.scalar(
        select(DataBreach).where(DataBreach.incident_id == inc.id, DataBreach.deleted.is_(False))
    )
    if existing is not None:
        return existing, f"already linked to {existing.reference}"
    tz = await clock.tenant_zone(db, user.tenant_id)
    breach = DataBreach(
        tenant_id=user.tenant_id,
        reference=await next_reference(db, DataBreach, "BR"),
        title=(inc.title or inc.reference)[:255],
        description=inc.description or "",
        discovered_date=clock.local_date(inc.detected_at or clock.now_utc(), tz),
        occurred_date=clock.local_date(inc.occurred_at, tz),
        records_affected=inc.records_affected or 0,
        severity=inc.severity,
        notification_required=True,
        status=BreachStatus.open,
        owner="",
        root_cause=inc.root_cause or "",
        remediation="",
    )
    breach.incident = inc
    db.add(breach)
    await db.flush()
    dpo = await _dpo_roles(db, user.tenant_id)
    for role_name in dpo:  # Phase 3: addressed to each DPO role, not the whole organisation
        db.add(Notification(
            tenant_id=user.tenant_id,
            role_name=role_name[:64],
            title=f"Personal data breach: {breach.reference} from {inc.reference}",
            body=(
                f"For {', '.join(dpo)}: {inc.reference} {inc.title} was flagged as a personal data "
                f"breach and {breach.reference} opened in the breach register. Assess whether the "
                "regulator and data subjects must be notified (72-hour rule)."
            ),
            category=NotificationCategory.critical,
            entity_type="data_breach",
            entity_id=breach.id,
            link="/data-protection",
            dedup_key=f"{EVENT_PREFIX}personal-data-breach:{breach.id}:{role_name}"[:255],
        ))
    note = (
        f"DPO notified ({', '.join(dpo)})"
        if dpo
        else "no DPO role configured; recorded in the audit trail only"
    )
    await audit.record(
        db, actor=user, action="create", entity_type="data_breach", entity_id=breach.id,
        summary=f"Opened data breach {breach.reference} from incident {inc.reference} ({note})",
        changes={"incident_id": str(inc.id), "dpo_roles": dpo},
    )
    return breach, f"opened {breach.reference}; {note}"


@router.get("", response_model=Page[IncidentRead], dependencies=[Depends(require("incident:read"))])
async def list_incidents(
    db: DbSession,
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    severity: Severity | None = None,
    assignee_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    classification_id: uuid.UUID | None = None,
    is_reportable: bool | None = None,
    near_miss: bool | None = None,
    personal_data_breach: bool | None = None,
    open_only: Annotated[
        bool | None,
        Query(alias="open", description=(
            "true: not resolved or closed (open, triage, investigating, contained) — the "
            "dashboard's open incidents; false: resolved or closed"
        )),
    ] = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IncidentRead]:
    stmt: Select = select(Incident).where(Incident.deleted.is_(False))
    if status_filter is not None:
        stmt = stmt.where(Incident.status == status_filter)
    if open_only is not None:
        # The dashboard counts open incidents with this same predicate.
        is_open = drill_through.incident_open()
        stmt = stmt.where(is_open if open_only else ~is_open)
    if severity is not None:
        stmt = stmt.where(Incident.severity == severity)
    if assignee_id is not None:
        stmt = stmt.where(Incident.assignee_id == assignee_id)
    if category_id is not None:
        stmt = stmt.where(Incident.category_id == category_id)
    if classification_id is not None:
        stmt = stmt.where(Incident.classification_id == classification_id)
    if is_reportable is not None:
        stmt = stmt.where(Incident.is_reportable.is_(is_reportable))
    if near_miss is not None:
        stmt = stmt.where(Incident.near_miss.is_(near_miss))
    if personal_data_breach is not None:
        stmt = stmt.where(Incident.personal_data_breach.is_(personal_data_breach))
    if search:
        stmt = stmt.where(Incident.title.ilike(f"%{search}%") | Incident.reference.ilike(f"%{search}%"))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _INCIDENT_SORTABLE, default=Incident.created_at)
    else:
        stmt = stmt.order_by(Incident.created_at.desc())
    # Load what the list serialises (``schema_loading``), not every link of every link.
    loads = options_for(Incident, IncidentRead)
    rows = (
        await db.scalars(stmt.options(*loads).limit(limit).offset(offset))
    ).all()
    return Page(items=await incident_reads(db, rows), total=total, limit=limit, offset=offset)


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
    await clock.localize_fields(db, user.tenant_id, data, TIMESTAMP_FIELDS)
    notification = {k: data.pop(k) for k in NOTIFICATION_FIELDS if data.get(k) is not None}
    for k in NOTIFICATION_FIELDS:
        data.pop(k, None)
    # The same stamps a status move gives on edit, plus detection (clock.creation_stamps).
    current = {f: data.get(f) for f in clock.TIMELINE_FIELDS}
    data.update(clock.creation_stamps(data.get("status"), current, clock.now_utc()))
    _refuse(incident_problems(data))
    if data.get("is_reportable") and not data.get("regulator_id") and not data.get("regulator"):
        data["regulator"] = settings.default_regulator  # matched to the lookup below
    await rf.apply_refs(db, Incident, data, INCIDENT_REFS)
    obj = Incident(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db)
    obj.controls = await _resolve(db, Control, control_ids)
    obj.vendors = await _resolve(db, Vendor, vendor_ids)
    obj.stages = [
        IncidentStage(tenant_id=user.tenant_id, name=name, order_index=i)
        for i, name in enumerate(DEFAULT_STAGES)
    ]
    obj.regulatory_reports = []
    reg_changes = _sync_reports(obj, user, recompute=True, create_missing=True) if obj.is_reportable else []
    reg_changes += _record_notification(obj, notification)
    db.add(obj)
    await db.flush()
    await _flush_assoc(db, obj.id, asset_ids, risk_ids)
    await db.flush()
    breach_note = ""
    if obj.personal_data_breach:
        _breach, breach_note = await _hand_off_breach(db, obj, user)
    await audit.record(
        db, actor=user, action="create", entity_type="incident", entity_id=obj.id,
        summary=f"Logged incident {obj.reference}: {obj.title}",
        changes={k: v for k, v in (("regulatory", reg_changes), ("data_breach", breach_note)) if v} or None,
    )
    return await incident_read(db, await _fresh(db, obj.id))


@router.get("/summary", response_model=IncidentSummary, dependencies=[Depends(require("incident:read"))],
            summary="Incident posture: counts, regulator notifications, losses and MTTD/MTTC/MTTR")
async def incident_summary(db: DbSession) -> IncidentSummary:
    rows = (await db.scalars(
        select(Incident).where(Incident.deleted.is_(False))
        .options(noload("*"), selectinload(Incident.regulatory_reports))
    )).all()
    return summarize(rows)


def summarize(rows, now=None) -> IncidentSummary:
    """Roll a set of incidents up (pure: the endpoint loads, this counts)."""
    now = now or clock.now_utc()
    by_status: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    pending = overdue = on_time = late = 0
    for i in rows:
        by_status[i.status.value] += 1
        by_severity[i.severity.value] += 1
        c = clock.notification_clock(i.regulatory_reports, now)
        if c.notification_deadline is None and c.notified_at is None:
            continue
        if c.notified_at is None:
            pending += 1
            overdue += 1 if c.notified_on_time is False else 0
        elif c.notified_on_time is True:
            on_time += 1
        elif c.notified_on_time is False:
            late += 1
    times = [clock.response_times(i) for i in rows]
    mttd, n_d = clock.average(t.mttd_hours for t in times)
    mttc, n_c = clock.average(t.mttc_hours for t in times)
    mttr, n_r = clock.average(t.mttr_hours for t in times)
    closed = {IncidentStatus.resolved, IncidentStatus.closed}
    return IncidentSummary(
        total=len(rows),
        open=sum(1 for i in rows if i.status not in closed),
        by_status=dict(by_status),
        by_severity=dict(by_severity),
        reportable=sum(1 for i in rows if i.is_reportable),
        notifications_pending=pending,
        notifications_overdue=overdue,
        notified_on_time=on_time,
        notified_late=late,
        near_misses=sum(1 for i in rows if i.near_miss),
        personal_data_breaches=sum(1 for i in rows if i.personal_data_breach),
        customers_affected=sum(i.customers_affected or 0 for i in rows),
        records_affected=sum(i.records_affected or 0 for i in rows),
        total_cost=clock.loss_total(rows),
        response_times=IncidentAverages(
            mttd_hours=mttd, mttd_count=n_d, mttc_hours=mttc, mttc_count=n_c,
            mttr_hours=mttr, mttr_count=n_r,
        ),
    )


@router.get("/{incident_id}", response_model=IncidentRead, dependencies=[Depends(require("incident:read"))])
async def get_incident(incident_id: uuid.UUID, db: DbSession) -> IncidentRead:
    return await incident_read(db, await _load(db, incident_id))


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
    await clock.localize_fields(db, user.tenant_id, data, TIMESTAMP_FIELDS)
    notification = {k: data.pop(k) for k in NOTIFICATION_FIELDS if k in data}
    for flag in ("near_miss", "personal_data_breach", "is_reportable"):
        if data.get(flag, False) is None:
            data.pop(flag)  # the columns are NOT NULL: an explicit null means "unchanged"

    was_reportable, was_breach = obj.is_reportable, obj.personal_data_breach
    old_detected, old_regulator = obj.detected_at, (obj.regulator_id, obj.regulator)
    # A status move records the step it implies when the user left it blank.
    if "status" in data and data["status"] is not None and data["status"] != obj.status:
        current = {f: data.get(f, getattr(obj, f)) for f in clock.TIMELINE_FIELDS}
        data.update(clock.status_stamps(data["status"], current, clock.now_utc()))
    if set(data) & {*clock.TIMELINE_FIELDS, "near_miss", "cost"}:
        merged = {f: data.get(f, getattr(obj, f)) for f in (*clock.TIMELINE_FIELDS, "near_miss", "cost")}
        _refuse(incident_problems(merged))

    await rf.apply_refs(db, Incident, data, INCIDENT_REFS, record=obj)
    for field, value in data.items():
        setattr(obj, field, value)
    if control_ids is not None:
        obj.controls = await _resolve(db, Control, control_ids)
    if vendor_ids is not None:
        obj.vendors = await _resolve(db, Vendor, vendor_ids)

    reg_changes: list[str] = []
    if obj.is_reportable:
        await _default_regulator(db, obj, data)
        became = not was_reportable
        moved = "detected_at" in data and clock.to_minute(data["detected_at"]) != clock.to_minute(old_detected)
        renamed = (obj.regulator_id, obj.regulator) != old_regulator
        # A reportable incident with no reports at all (flagged before phase 2) gets them
        # on its next edit; one report removed on purpose is not brought back.
        missing = not obj.regulatory_reports
        if became or moved or renamed or missing:
            reg_changes = _sync_reports(obj, user, recompute=became or moved, create_missing=became or missing)
    reg_changes += _record_notification(obj, notification)
    await db.flush()
    await _flush_assoc(db, obj.id, asset_ids, risk_ids)
    await db.flush()
    breach_note = ""
    if obj.personal_data_breach and not was_breach:
        _breach, breach_note = await _hand_off_breach(db, obj, user)
    changes = {"fields": sorted({*data, *notification})}
    if reg_changes:
        changes["regulatory"] = reg_changes
    if breach_note:
        changes["data_breach"] = breach_note
    await audit.record(
        db, actor=user, action="update", entity_type="incident", entity_id=obj.id,
        summary=f"Updated incident {obj.reference}", changes=changes,
    )
    return await incident_read(db, await _fresh(db, obj.id))


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("incident:write"))],
)
async def delete_incident(incident_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, incident_id)
    # (incident, delete) is a dual-control action: whoever logged the incident cannot
    # also make it disappear from the register.
    await delete_guard.enforce(db, entity_type="incident", record=obj, user=user, label="incident")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit.record(db, actor=user, action="delete", entity_type="incident",
                       entity_id=obj.id, summary=f"Archived incident {obj.reference}: {obj.title}")


# ------------------------------------------------------------- loss events
@router.post(
    "/{incident_id}/loss-event",
    response_model=IncidentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("incident:write", "oprisk:write")), Depends(require_module("operational_risk"))],
    summary="Record the incident's loss in the operational loss database",
)
async def create_loss_event(
    incident_id: uuid.UUID, db: DbSession, user: CurrentUser, body: LossFromIncident | None = None
) -> IncidentRead:
    """Create a ``LossEvent`` linked to the incident, pre-filled from it: title, cost as
    the gross loss, occurrence/discovery dates (in the organisation's timezone), owner,
    root cause, linked risks, and the business unit when the incident's assets and risks
    name exactly one. Anything in the body overrides the pre-fill."""
    from app.api.v1.operational_risk import LOSS_REFS  # the loss register's own picker rule
    from app.api.v1.tenant_settings import get_or_create_settings

    inc = await _load(db, incident_id)
    if inc.near_miss:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A near miss has no loss to record. Untick near miss first if money was lost.",
        )
    # One incident is one operational-risk event: Basel's loss-data rules (and SBP's ORM
    # returns built on them) group every financial impact of the same event under one
    # loss record, so a second click must not double-count the loss. Further amounts,
    # recoveries and write-offs are recorded on the existing loss event. The row lock
    # makes two simultaneous clicks queue, so the second sees the first one's record.
    await db.scalar(select(Incident.id).where(Incident.id == inc.id).with_for_update())
    existing = await db.scalar(
        select(LossEvent.reference)
        .where(LossEvent.incident_id == inc.id, LossEvent.deleted.is_(False))
        .order_by(LossEvent.created_at)
        .limit(1)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This incident's loss is already recorded as {existing}. Record further "
                   "amounts or recoveries on that loss event.",
        )
    body = body or LossFromIncident()
    org = await get_or_create_settings(db, user.tenant_id)
    tz = clock.zone(getattr(org, "timezone", None))
    data = {
        "title": (body.title or inc.title)[:255],
        "description": inc.description or "",
        "basel_event_type": body.basel_event_type or BaselEventType.execution_delivery_process_management,
        "business_unit_id": body.business_unit_id or clock.single_unit(inc.assets, inc.risks),
        "gross_loss": body.gross_loss if body.gross_loss is not None else float(inc.cost or 0),
        "recovery": body.recovery or 0,
        "currency": (body.currency or getattr(org, "currency", None) or "PKR").upper(),
        "status": LossEventStatus.open,
        "occurrence_date": clock.local_date(inc.occurred_at or inc.detected_at, tz),
        "discovery_date": clock.local_date(inc.detected_at, tz),
        "root_cause": inc.root_cause or "",
        # The handler's name is matched to an active user the way an import is; a
        # departed handler stays as text rather than refusing the loss.
        "action_owner": inc.assignee or "",
    }
    await rf.apply_refs(db, LossEvent, data, LOSS_REFS)
    loss = LossEvent(tenant_id=user.tenant_id, incident_id=inc.id, **data)
    loss.reference = await next_reference(db, LossEvent, "LOSS")
    loss.risks = list(inc.risks)
    db.add(loss)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="loss_event", entity_id=loss.id,
        summary=f"Logged loss event {loss.reference} from incident {inc.reference}: {loss.title}",
        changes={"incident_id": str(inc.id), "gross_loss": float(loss.gross_loss or 0), "currency": loss.currency},
    )
    await audit.record(
        db, actor=user, action="update", entity_type="incident", entity_id=inc.id,
        summary=f"Recorded loss event {loss.reference} for incident {inc.reference}",
    )
    return await incident_read(db, await _fresh(db, inc.id))


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
    return await incident_read(db, await _fresh(db, incident_id))


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
    return await incident_read(db, await _fresh(db, incident_id))
