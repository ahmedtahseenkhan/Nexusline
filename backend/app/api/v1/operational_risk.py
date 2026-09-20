"""Operational Risk API — RCSA campaigns, Key Risk Indicators and the Basel loss database."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.database import tenant_session
from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.enums import KriDirection, KriStatus
from app.models.identity import Role
from app.models.risk import Risk, RiskAppetite
from app.models.operational_risk import (
    BASEL_EVENT_TYPES_L2,
    BASEL_L1_LABELS,
    BASEL_L2_LABELS,
    basel_l2_error,
    KeyRiskIndicator,
    KriEscalation,
    KriMeasurement,
    LossEvent,
    RcsaAssessment,
    RcsaRisk,
)
from app.models.tenant import Tenant
from app.schemas.common import GraphRef, Page
from app.schemas.operational_risk import (
    FeedResult,
    FeedTokenIssued,
    KriAppetiteRef,
    KriCreate,
    KriEscalationCreate,
    KriEscalationRead,
    KriEscalationUpdate,
    KriRead,
    KriUpdate,
    MeasurementFeed,
    LossEventCreate,
    LossEventRead,
    LossEventUpdate,
    MeasurementCreate,
    RcsaCreate,
    RcsaRead,
    RcsaRiskCreate,
    RcsaRiskRead,
    RcsaRiskUpdate,
    RcsaUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log
from app.services import master_data
from app.services import notifications
from app.services import ref_fields as rf
from app.services import fx
from app.schemas.fx import MoneyTotalRead, UnconvertedAmount
from app.services.rate_limit import RateLimiter, too_many_requests

router = APIRouter(tags=["operational risk"])

_READ = Depends(require("oprisk:read"))
_WRITE = Depends(require("oprisk:write"))

# Phase 1 picker fields and the legacy text each one keeps in step (services/ref_fields).
RCSA_REFS = (
    rf.user("assessor_id", "assessor"),
    rf.unit("business_unit_id", "business_unit"),
    rf.process("process_id", "process"),
    rf.WORKFLOW_OWNER,
)
RCSA_LINE_REFS = (
    rf.lookup(RcsaRisk, "category_id", "category"),
    rf.user("action_owner_id", "action_owner"),
)
KRI_REFS = (
    rf.user("owner_id", "owner"),
    rf.unit("business_unit_id", "business_area"),
    rf.lookup(KeyRiskIndicator, "category_id", "category"),
    rf.WORKFLOW_OWNER,
    rf.user("data_provider_id", None),  # phase 2: picked only, no legacy text
)
ESCALATION_REFS = (rf.user("escalate_to_id", None),)
LOSS_REFS = (
    rf.user("action_owner_id", "action_owner"),
    rf.unit("business_unit_id", "business_line"),
    rf.WORKFLOW_OWNER,
)


async def _rcsa_reads(db, rows) -> list[RcsaRead]:
    """RCSA read models with people, units, processes and categories resolved in one
    query per kind across the campaigns and their risk lines."""
    items = [RcsaRead.model_validate(r) for r in rows]
    pairs: list = []
    for row, item in zip(rows, items):
        pairs.append((row, item))
        pairs.extend(zip(row.risks, item.risks))
    await rf.fill_refs(db, pairs, RCSA_REFS + RCSA_LINE_REFS)
    return items


async def _reads(db, schema, rows, fields) -> list:
    items = [schema.model_validate(r) for r in rows]
    await rf.fill_refs(db, list(zip(rows, items)), fields)
    return items


async def _audit_delete(db, user, entity_type: str, obj, label: str) -> None:
    await audit_log.record(
        db, actor=user, action="delete", entity_type=entity_type, entity_id=obj.id,
        summary=f"Archived {label} {obj.reference}",
    )


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _resolve(db, model, ids):
    if not ids:
        return []
    return list(
        (
            await db.scalars(
                select(model).where(model.id.in_(ids), model.deleted.is_(False))
            )
        ).all()
    )


# ==================================================================== RCSA ===
async def _load_rcsa(db, rid) -> RcsaAssessment:
    obj = await db.scalar(
        select(RcsaAssessment)
        .where(RcsaAssessment.id == rid, RcsaAssessment.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="RCSA not found")
    return obj


_RCSA_SORTABLE = {
    "reference": RcsaAssessment.reference,
    "title": RcsaAssessment.title,
    "business_unit": RcsaAssessment.business_unit,
    "status": RcsaAssessment.status,
    "due_date": RcsaAssessment.due_date,
    "created_at": RcsaAssessment.created_at,
}


@router.get("/rcsa", response_model=Page[RcsaRead], dependencies=[_READ])
async def list_rcsa(db: DbSession, search: str | None = None,
                    business_unit_id: uuid.UUID | None = None,
                    assessor_id: uuid.UUID | None = None,
                    sort_by: Annotated[str | None, Query()] = None,
                    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                    limit: Annotated[int, Query(ge=1, le=200)] = 100,
                    offset: Annotated[int, Query(ge=0)] = 0) -> Page[RcsaRead]:
    stmt = select(RcsaAssessment).where(RcsaAssessment.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(RcsaAssessment.title.ilike(like), RcsaAssessment.reference.ilike(like),
                             RcsaAssessment.business_unit.ilike(like)))
    if business_unit_id is not None:
        stmt = stmt.where(RcsaAssessment.business_unit_id == business_unit_id)
    if assessor_id is not None:
        stmt = stmt.where(RcsaAssessment.assessor_id == assessor_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _RCSA_SORTABLE, default=RcsaAssessment.created_at)
    else:
        stmt = stmt.order_by(RcsaAssessment.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=await _rcsa_reads(db, rows), total=total, limit=limit, offset=offset)


@router.post("/rcsa", response_model=RcsaRead, status_code=201, dependencies=[_WRITE])
async def create_rcsa(body: RcsaCreate, db: DbSession, user: CurrentUser) -> RcsaRead:
    data = body.model_dump()
    await rf.apply_refs(db, RcsaAssessment, data, RCSA_REFS)
    obj = RcsaAssessment(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, RcsaAssessment, "RCSA")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="rcsa_assessment",
                           entity_id=obj.id, summary=f"Opened RCSA {obj.reference}: {obj.title}")
    return (await _rcsa_reads(db, [await _load_rcsa(db, obj.id)]))[0]


@router.get("/rcsa/{rid}", response_model=RcsaRead, dependencies=[_READ])
async def get_rcsa(rid: uuid.UUID, db: DbSession) -> RcsaRead:
    return (await _rcsa_reads(db, [await _load_rcsa(db, rid)]))[0]


@router.patch("/rcsa/{rid}", response_model=RcsaRead, dependencies=[_WRITE])
async def update_rcsa(rid: uuid.UUID, body: RcsaUpdate, db: DbSession) -> RcsaRead:
    obj = await _load_rcsa(db, rid)
    data = body.model_dump(exclude_unset=True)
    await rf.apply_refs(db, RcsaAssessment, data, RCSA_REFS, record=obj)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return (await _rcsa_reads(db, [await _load_rcsa(db, rid)]))[0]


@router.delete("/rcsa/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_rcsa(rid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_rcsa(db, rid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _audit_delete(db, user, "rcsa_assessment", obj, "RCSA")


@router.post("/rcsa/{rid}/risks", response_model=RcsaRead, status_code=201, dependencies=[_WRITE])
async def add_rcsa_risk(rid: uuid.UUID, body: RcsaRiskCreate, db: DbSession, user: CurrentUser) -> RcsaRead:
    await _load_rcsa(db, rid)
    data = body.model_dump()
    await rf.apply_refs(db, RcsaRisk, data, RCSA_LINE_REFS)
    db.add(RcsaRisk(tenant_id=user.tenant_id, assessment_id=rid, **data))
    await db.flush()
    return (await _rcsa_reads(db, [await _load_rcsa(db, rid)]))[0]


@router.patch("/rcsa-risks/{line_id}", response_model=RcsaRiskRead, dependencies=[_WRITE])
async def update_rcsa_risk(line_id: uuid.UUID, body: RcsaRiskUpdate, db: DbSession) -> RcsaRiskRead:
    obj = await _get(db, RcsaRisk, line_id, "RCSA risk")
    data = body.model_dump(exclude_unset=True)
    await rf.apply_refs(db, RcsaRisk, data, RCSA_LINE_REFS, record=obj)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return (await _reads(db, RcsaRiskRead, [obj], RCSA_LINE_REFS))[0]


@router.delete("/rcsa-risks/{line_id}", status_code=204, dependencies=[_WRITE])
async def delete_rcsa_risk(line_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(RcsaRisk).where(RcsaRisk.id == line_id))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(obj)


# ===================================================================== KRIs ===
# Phase 2 (F-14). A KRI now carries its definition and data lineage, a within-range
# direction, the appetite it measures, escalations per level and an integration feed.
#
# Threshold rules (:func:`threshold_refusal`, a 422 naming the problem):
#   * higher_is_worse — warning < limit (amber comes before red as the value rises);
#   * lower_is_worse  — warning > limit (amber comes before red as the value falls);
#   * within_range    — lower_bound < upper_bound, both required; no warning threshold
#     (it is amber as soon as it leaves the range); limit_threshold, if set, is the
#     tolerance beyond the range at which it turns red (see models.kri_status);
#   * a KRI may have no thresholds only while it has no value.
# Bounds are kept only for within-range KRIs: switching the direction away clears them.
#
# Escalation: a reading that moves a KRI *up* into amber or red raises an event
# notification naming that level's escalation target and action (services.notifications
# .raise_kri_escalation) and an ``escalate`` audit entry.
#
# Feed: ``POST /kris/{id}/feed-token`` issues a token once (only its SHA-256 is kept);
# an integration then posts readings to ``POST /kris/{id}/measurements/feed`` with
# ``Authorization: Bearer <token>`` and no user session. The token starts with the
# organisation's id (``<tenant hex>.<secret>``) so the endpoint can open that
# organisation's row-level-security scope before it can even see the KRI; the secret
# part is what is checked, in constant time, against the stored hash.

THRESHOLD_FIELDS = frozenset({
    "direction", "warning_threshold", "limit_threshold", "lower_bound", "upper_bound", "current_value",
})
_RANK = {KriStatus.no_data: 0, KriStatus.green: 0, KriStatus.amber: 1, KriStatus.red: 2}
#: Actor written on audit entries made by an integration through the feed.
FEED_ACTOR = "KRI feed"
FEED_TOKEN_BYTES = 32


def _fmt(value) -> str:
    v = float(value)
    return str(int(v)) if v.is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")


def _flt(value) -> float | None:
    return float(value) if value is not None else None


def threshold_refusal(direction, warning, limit, lower, upper, *, has_value: bool) -> str | None:
    """Why this KRI's thresholds can't be saved, or None. Pure. See the section notes."""
    direction = KriDirection(getattr(direction, "value", direction))
    warning, limit, lower, upper = _flt(warning), _flt(limit), _flt(lower), _flt(upper)
    if direction == KriDirection.within_range:
        if lower is None or upper is None:
            return "A within-range KRI needs both a lower and an upper bound."
        if lower >= upper:
            return f"The lower bound ({_fmt(lower)}) must be below the upper bound ({_fmt(upper)})."
        if warning is not None:
            return (
                "A within-range KRI turns amber as soon as it leaves its range, so it has no "
                "warning threshold — leave it empty. Set the limit as the tolerance: how far "
                "beyond the range it may go before it turns red."
            )
        if limit is not None and limit < 0:
            return "The tolerance (limit) of a within-range KRI is a distance beyond the range; it can't be negative."
        return None
    if warning is None and limit is None:
        return "This KRI has a value, so it needs a warning or a limit threshold." if has_value else None
    if warning is not None and limit is not None:
        if direction == KriDirection.higher_is_worse and not warning < limit:
            return (
                f"For a higher-is-worse KRI the warning threshold ({_fmt(warning)}) must be below "
                f"the limit ({_fmt(limit)}): it turns amber before it turns red as the value rises."
            )
        if direction == KriDirection.lower_is_worse and not warning > limit:
            return (
                f"For a lower-is-worse KRI the warning threshold ({_fmt(warning)}) must be above "
                f"the limit ({_fmt(limit)}): it turns amber before it turns red as the value falls."
            )
    return None


def escalation_level(before: KriStatus, after: KriStatus) -> str | None:
    """The escalation a reading triggers, or None. Pure.

    Only a move *up* into amber or red escalates (green/no data → amber, anything below
    red → red). Improving from red to amber, or staying at a level, raises nothing."""
    if after in (KriStatus.amber, KriStatus.red) and _RANK[after] > _RANK.get(before, 0):
        return after.value
    return None


def future_date_refusal(as_of: date, today: date) -> str | None:
    """A reading can't be dated after today (the organisation's today). Pure."""
    if as_of > today:
        return f"as_of_date: {as_of.isoformat()} is in the future; date the reading today ({today.isoformat()}) or earlier."
    return None


def new_feed_token(tenant_id: uuid.UUID) -> str:
    """``<tenant hex>.<random secret>`` — the prefix scopes the lookup, the secret proves it."""
    return f"{tenant_id.hex}.{secrets.token_urlsafe(FEED_TOKEN_BYTES)}"


def feed_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def feed_token_tenant(token: str) -> uuid.UUID | None:
    """The organisation a feed token belongs to, or None when it isn't shaped like one. Pure."""
    prefix, sep, secret = (token or "").partition(".")
    if not sep or len(secret) < 20:
        return None
    try:
        return uuid.UUID(hex=prefix)
    except ValueError:
        return None


def feed_token_matches(token: str, stored_hash: str) -> bool:
    """Constant-time check of a presented token against the stored hash. Pure."""
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(feed_token_hash(token), stored_hash)


def merged_thresholds(record, data: dict) -> dict:
    """The KRI's threshold fields as they will be after this write. Pure."""
    return {f: data[f] if f in data else getattr(record, f, None) for f in THRESHOLD_FIELDS}


def check_thresholds(state: dict) -> None:
    """422 when the (merged) threshold state breaks a rule. Mutates nothing."""
    refusal = threshold_refusal(
        state.get("direction") or KriDirection.higher_is_worse,
        state.get("warning_threshold"), state.get("limit_threshold"),
        state.get("lower_bound"), state.get("upper_bound"),
        has_value=state.get("current_value") is not None,
    )
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)


def clear_bounds_off_range(record, data: dict) -> None:
    """Bounds belong to within-range KRIs only; any other direction clears them."""
    direction = data.get("direction", getattr(record, "direction", None)) or KriDirection.higher_is_worse
    if KriDirection(getattr(direction, "value", direction)) == KriDirection.within_range:
        return
    for f in ("lower_bound", "upper_bound"):
        if data.get(f) is not None or getattr(record, f, None) is not None:
            data[f] = None


async def _check_appetite(db, appetite_id) -> None:
    if appetite_id is None:
        return
    if await db.get(RiskAppetite, appetite_id) is None:
        raise HTTPException(
            status_code=422,
            detail="appetite_id: pick a risk appetite (Risk register → Risk methodology → appetite by category).",
        )


async def _check_role(db, name: str | None) -> str:
    """The role's stored name for ``name`` (case-insensitive), '' for none; 422 if unknown."""
    name = (name or "").strip()
    if not name:
        return ""
    row = await db.scalar(select(Role).where(func.lower(Role.name) == name.lower()))
    if row is None:
        raise HTTPException(status_code=422, detail=f"escalate_to_role: no role named '{name}' in this organisation.")
    return row.name


async def _load_kri(db, kid) -> KeyRiskIndicator:
    obj = await db.scalar(
        select(KeyRiskIndicator)
        .where(KeyRiskIndicator.id == kid, KeyRiskIndicator.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="KRI not found")
    return obj


async def _escalation_reads(db, rows) -> list[KriEscalationRead]:
    items = [KriEscalationRead.model_validate(e) for e in rows]
    await rf.fill_refs(db, list(zip(rows, items)), ESCALATION_REFS)
    return items


async def _kri_reads(db, rows) -> list[KriRead]:
    """KRI read models with people, units, categories, escalation targets and the
    appetite's category label resolved — one query per kind for the whole page."""
    items = await _reads(db, KriRead, rows, KRI_REFS)
    pairs = [pair for row, item in zip(rows, items) for pair in zip(row.escalations, item.escalations)]
    await rf.fill_refs(db, pairs, ESCALATION_REFS)
    appetites = [row.appetite for row in rows if row.appetite is not None]
    labels = await master_data.lookups_by_id(db, [a.category_id for a in appetites])
    for row, item in zip(rows, items):
        a = row.appetite
        if a is None:
            continue
        label = labels.get(a.category_id)
        item.appetite_ref = KriAppetiteRef(
            id=a.id, category_id=a.category_id, category_label=label.label if label else "",
            appetite_score=a.appetite_score, tolerance_score=a.tolerance_score, statement=a.statement or "",
        )
    return items


async def _kri_read(db, kid) -> KriRead:
    return (await _kri_reads(db, [await _load_kri(db, kid)]))[0]


async def _today(db, tenant_id) -> date:
    """Today in the organisation's timezone (Settings → Organisation)."""
    from app.services import incident_clock

    return incident_clock.local_date(incident_clock.now_utc(), await incident_clock.tenant_zone(db, tenant_id))


@dataclass
class Reading:
    measurement: KriMeasurement
    before: KriStatus
    after: KriStatus
    advanced: bool
    level: str | None = None
    escalation: dict | None = None


async def record_reading(db, kri: KeyRiskIndicator, *, value: float, as_of: date | None,
                         notes: str, tenant_id) -> Reading:
    """Record one reading — the manual form and the feed share this — and escalate.

    Refuses a reading on a KRI without usable thresholds and one dated in the future.
    The KRI's current value (which drives RAG status) only advances when the reading is
    the latest — back-filling an older reading must not rewrite the live status or
    regress last_measured_date — so only an advancing reading can escalate."""
    refusal = threshold_refusal(
        kri.direction, kri.warning_threshold, kri.limit_threshold, kri.lower_bound, kri.upper_bound,
        has_value=True,
    )
    if refusal:
        raise HTTPException(status_code=422, detail=f"Set this KRI's thresholds before recording a value. {refusal}")
    today = await _today(db, tenant_id)
    as_of = as_of or today
    refusal = future_date_refusal(as_of, today)
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)
    before = kri.status
    m = KriMeasurement(id=uuid.uuid4(), tenant_id=tenant_id, kri_id=kri.id, value=value,
                       as_of_date=as_of, notes=notes or "")
    db.add(m)
    advanced = kri.last_measured_date is None or as_of >= kri.last_measured_date
    if advanced:
        kri.current_value = value
        kri.last_measured_date = as_of
    after = kri.status
    reading = Reading(measurement=m, before=before, after=after, advanced=advanced)
    reading.level = escalation_level(before, after) if advanced else None
    if reading.level:
        reading.escalation = await notifications.raise_kri_escalation(
            db, kri, reading.level, value=value, as_of=as_of, measurement_id=m.id,
        )
    await db.flush()
    return reading


def reading_audit(kri, reading: Reading, via: str) -> list[dict]:
    """The audit entries a reading writes (``measure``, plus ``escalate`` when it
    escalated), as keyword sets for ``audit.record``. Pure."""
    m = reading.measurement
    entries = [dict(
        action="measure", entity_type="key_risk_indicator", entity_id=kri.id,
        summary=(f"Recorded {_fmt(m.value)}{(' ' + kri.unit) if kri.unit else ''} for KRI "
                 f"{kri.reference} as of {m.as_of_date} ({via}) — {reading.after.value.replace('_', ' ')}"),
        changes={"value": float(m.value), "as_of_date": str(m.as_of_date), "via": via,
                 "status_from": reading.before.value, "status_to": reading.after.value,
                 "current_value_updated": reading.advanced},
    )]
    if reading.level and reading.escalation is not None:
        e = reading.escalation
        entries.append(dict(
            action="escalate", entity_type="key_risk_indicator", entity_id=kri.id,
            summary=(f"KRI {kri.reference} turned {reading.level} at {_fmt(m.value)}; "
                     + (f"escalated to {e['target']}" if e.get("target") else "no escalation target set")),
            changes={"level": reading.level, "value": float(m.value), "target": e.get("target", ""),
                     "action": e.get("action", ""), "notification": e.get("dedup_key", ""), "via": via},
        ))
    return entries


async def _feed_audit(db, tenant_id, entry: dict) -> None:
    """Audit an integration's change as the ``KRI feed`` actor (no user is signed in)."""
    from app.models.audit import AuditLog
    from app.services import webhooks

    db.add(AuditLog(tenant_id=tenant_id, actor_id=None, actor_email=FEED_ACTOR, **entry))
    await webhooks.dispatch(
        db, entity_type=entry["entity_type"], action=entry["action"],
        payload={"event": f"{entry['entity_type']}.{entry['action']}", "entity_type": entry["entity_type"],
                 "entity_id": str(entry["entity_id"]), "summary": entry["summary"], "actor": FEED_ACTOR,
                 "changes": entry.get("changes", {})},
    )


# `status` / `is_breached` are computed from current_value vs thresholds, so they are not
# DB columns and cannot be sorted server-side; current_value is the sortable proxy.
_KRI_SORTABLE = {
    "reference": KeyRiskIndicator.reference,
    "name": KeyRiskIndicator.name,
    "category": KeyRiskIndicator.category,
    "owner": KeyRiskIndicator.owner,
    "current_value": KeyRiskIndicator.current_value,
    "last_measured_date": KeyRiskIndicator.last_measured_date,
    "created_at": KeyRiskIndicator.created_at,
}


@router.get("/kris", response_model=Page[KriRead], dependencies=[_READ])
async def list_kris(db: DbSession, search: str | None = None,
                    owner_id: uuid.UUID | None = None,
                    category_id: uuid.UUID | None = None,
                    business_unit_id: uuid.UUID | None = None,
                    sort_by: Annotated[str | None, Query()] = None,
                    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                    limit: Annotated[int, Query(ge=1, le=200)] = 100,
                    offset: Annotated[int, Query(ge=0)] = 0) -> Page[KriRead]:
    stmt = select(KeyRiskIndicator).where(KeyRiskIndicator.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(KeyRiskIndicator.name.ilike(like), KeyRiskIndicator.reference.ilike(like),
                             KeyRiskIndicator.category.ilike(like), KeyRiskIndicator.owner.ilike(like)))
    if owner_id is not None:
        stmt = stmt.where(KeyRiskIndicator.owner_id == owner_id)
    if category_id is not None:
        stmt = stmt.where(KeyRiskIndicator.category_id == category_id)
    if business_unit_id is not None:
        stmt = stmt.where(KeyRiskIndicator.business_unit_id == business_unit_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _KRI_SORTABLE, default=KeyRiskIndicator.name)
    else:
        stmt = stmt.order_by(KeyRiskIndicator.name)
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=await _kri_reads(db, rows), total=total, limit=limit, offset=offset)


@router.get("/kri-escalation-roles", response_model=list[GraphRef], dependencies=[_READ],
            summary="Roles a KRI escalation can name")
async def list_escalation_roles(db: DbSession) -> list[GraphRef]:
    rows = (await db.scalars(select(Role).order_by(Role.name))).all()
    return [GraphRef(id=r.id, name=r.name) for r in rows]


@router.post("/kris", response_model=KriRead, status_code=201, dependencies=[_WRITE])
async def create_kri(body: KriCreate, db: DbSession, user: CurrentUser) -> KriRead:
    data = body.model_dump(exclude={"risk_ids"})
    clear_bounds_off_range(None, data)
    check_thresholds(merged_thresholds(None, data))
    await _check_appetite(db, data.get("appetite_id"))  # data_provider_id: checked by apply_refs
    await rf.apply_refs(db, KeyRiskIndicator, data, KRI_REFS)
    obj = KeyRiskIndicator(tenant_id=user.tenant_id, **data)
    obj.risks = await _resolve(db, Risk, body.risk_ids)
    obj.reference = await _next_ref(db, KeyRiskIndicator, "KRI")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="key_risk_indicator",
                           entity_id=obj.id, summary=f"Defined KRI {obj.reference}: {obj.name}")
    return await _kri_read(db, obj.id)


@router.get("/kris/{kid}", response_model=KriRead, dependencies=[_READ])
async def get_kri(kid: uuid.UUID, db: DbSession) -> KriRead:
    return await _kri_read(db, kid)


@router.patch("/kris/{kid}", response_model=KriRead, dependencies=[_WRITE])
async def update_kri(kid: uuid.UUID, body: KriUpdate, db: DbSession, user: CurrentUser) -> KriRead:
    obj = await _load_kri(db, kid)
    data = body.model_dump(exclude_unset=True, exclude={"risk_ids"})
    if data.get("direction", 0) is None:
        data.pop("direction")  # the column is required; null means "leave it"
    if THRESHOLD_FIELDS & data.keys():
        clear_bounds_off_range(obj, data)
        check_thresholds(merged_thresholds(obj, data))
    if "appetite_id" in data and data["appetite_id"] != obj.appetite_id:
        await _check_appetite(db, data["appetite_id"])
    await rf.apply_refs(db, KeyRiskIndicator, data, KRI_REFS, record=obj)
    changed = sorted(k for k, v in data.items() if getattr(obj, k, None) != v)
    for k, v in data.items():
        setattr(obj, k, v)
    if body.risk_ids is not None:
        obj.risks = await _resolve(db, Risk, body.risk_ids)
        changed.append("risk_ids")
    await db.flush()
    await audit_log.record(db, actor=user, action="update", entity_type="key_risk_indicator",
                           entity_id=obj.id, summary=f"Updated KRI {obj.reference}: {obj.name}",
                           changes={"fields": changed})
    return await _kri_read(db, kid)


@router.delete("/kris/{kid}", status_code=204, dependencies=[_WRITE])
async def delete_kri(kid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_kri(db, kid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _audit_delete(db, user, "key_risk_indicator", obj, "KRI")


@router.post("/kris/{kid}/measurements", response_model=KriRead, status_code=201, dependencies=[_WRITE])
async def add_measurement(kid: uuid.UUID, body: MeasurementCreate, db: DbSession, user: CurrentUser) -> KriRead:
    kri = await _load_kri(db, kid)
    reading = await record_reading(db, kri, value=body.value, as_of=body.as_of_date,
                                   notes=body.notes, tenant_id=user.tenant_id)
    for entry in reading_audit(kri, reading, via="entered in the app"):
        await audit_log.record(db, actor=user, **entry)
    return await _kri_read(db, kid)


# ------------------------------------------------------------ KRI escalations ---
@router.get("/kris/{kid}/escalations", response_model=list[KriEscalationRead], dependencies=[_READ])
async def list_escalations(kid: uuid.UUID, db: DbSession) -> list[KriEscalationRead]:
    kri = await _load_kri(db, kid)
    return await _escalation_reads(db, list(kri.escalations))


async def _load_escalation(db, kid, eid) -> KriEscalation:
    row = await db.scalar(select(KriEscalation).where(KriEscalation.id == eid, KriEscalation.kri_id == kid))
    if row is None:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return row


async def _describe_escalation(db, e) -> str:
    """"red: Jane Doe and the CRO role — Freeze wires", for the activity trail."""
    people = await master_data.users_by_id(db, [e.escalate_to_id])
    return f"{e.level}: {notifications.escalation_target_text(e, people) or 'nobody'} — {e.action}"


@router.post("/kris/{kid}/escalations", response_model=KriEscalationRead, status_code=201, dependencies=[_WRITE],
             summary="Say who is told, and what they do, when the KRI turns amber or red")
async def create_escalation(kid: uuid.UUID, body: KriEscalationCreate, db: DbSession, user: CurrentUser) -> KriEscalationRead:
    kri = await _load_kri(db, kid)
    if any(e.level == body.level for e in kri.escalations):
        raise HTTPException(status_code=409, detail=f"This KRI already has a {body.level} escalation; edit that one.")
    await master_data.check_user(db, body.escalate_to_id, "escalate_to_id")
    role = await _check_role(db, body.escalate_to_role)
    row = KriEscalation(tenant_id=user.tenant_id, kri_id=kid, level=body.level,
                        escalate_to_id=body.escalate_to_id, escalate_to_role=role, action=body.action.strip())
    db.add(row)
    await db.flush()
    await audit_log.record(db, actor=user, action="add_escalation", entity_type="key_risk_indicator",
                           entity_id=kid, summary=f"Set the {body.level} escalation of KRI {kri.reference}",
                           changes={"escalation": await _describe_escalation(db, row)})
    return (await _escalation_reads(db, [row]))[0]


@router.patch("/kris/{kid}/escalations/{eid}", response_model=KriEscalationRead, dependencies=[_WRITE])
async def update_escalation(kid: uuid.UUID, eid: uuid.UUID, body: KriEscalationUpdate,
                            db: DbSession, user: CurrentUser) -> KriEscalationRead:
    kri = await _load_kri(db, kid)
    row = await _load_escalation(db, kid, eid)
    data = body.model_dump(exclude_unset=True)
    level = data.get("level") or row.level
    if level != row.level and any(e.level == level and e.id != row.id for e in kri.escalations):
        raise HTTPException(status_code=409, detail=f"This KRI already has a {level} escalation; edit that one.")
    to_id = data["escalate_to_id"] if "escalate_to_id" in data else row.escalate_to_id
    if "escalate_to_id" in data and to_id != row.escalate_to_id:
        await master_data.check_user(db, to_id, "escalate_to_id")
    role = await _check_role(db, data["escalate_to_role"]) if "escalate_to_role" in data else row.escalate_to_role
    action = (data["action"] if data.get("action") is not None else row.action).strip()
    if to_id is None and not role:
        raise HTTPException(status_code=422, detail="Name a person (escalate_to_id) or a role (escalate_to_role) to escalate to.")
    if not action:
        raise HTTPException(status_code=422, detail="action: say what must be done when the KRI reaches this level.")
    before = await _describe_escalation(db, row)
    row.level, row.escalate_to_id, row.escalate_to_role, row.action = level, to_id, role, action
    await db.flush()
    await audit_log.record(db, actor=user, action="update_escalation", entity_type="key_risk_indicator",
                           entity_id=kid, summary=f"Changed the {level} escalation of KRI {kri.reference}",
                           changes={"from": before, "to": await _describe_escalation(db, row)})
    return (await _escalation_reads(db, [row]))[0]


@router.delete("/kris/{kid}/escalations/{eid}", status_code=204, dependencies=[_WRITE])
async def delete_escalation(kid: uuid.UUID, eid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    kri = await _load_kri(db, kid)
    row = await _load_escalation(db, kid, eid)
    snapshot = await _describe_escalation(db, row)
    await db.delete(row)
    await db.flush()
    await audit_log.record(db, actor=user, action="remove_escalation", entity_type="key_risk_indicator",
                           entity_id=kid, summary=f"Removed the {row.level} escalation of KRI {kri.reference}",
                           changes={"escalation": snapshot})


# ------------------------------------------------------------------ KRI feed ---
def feed_endpoint(kid) -> str:
    return f"/api/v1/kris/{kid}/measurements/feed"


@router.post("/kris/{kid}/feed-token", response_model=FeedTokenIssued, status_code=201, dependencies=[_WRITE],
             summary="Issue (or rotate) the KRI's integration token — shown once")
async def issue_feed_token(kid: uuid.UUID, db: DbSession, user: CurrentUser) -> FeedTokenIssued:
    kri = await _load_kri(db, kid)
    rotated = bool(kri.feed_token_hash)
    token = new_feed_token(user.tenant_id)
    kri.feed_token_hash = feed_token_hash(token)
    await db.flush()
    await audit_log.record(db, actor=user, action="feed_token_issue", entity_type="key_risk_indicator",
                           entity_id=kid,
                           summary=f"{'Rotated' if rotated else 'Issued'} the feed token of KRI {kri.reference}",
                           changes={"rotated": rotated})
    return FeedTokenIssued(
        kri_id=kid, token=token, endpoint=feed_endpoint(kid), header=f"Authorization: Bearer {token}",
        note=("Copy it now: only a hash is kept, so it can't be shown again. "
              + ("The previous token stopped working. " if rotated else "")
              + 'POST {"value": 1.5, "as_of_date": "YYYY-MM-DD", "notes": "…"} to the endpoint with this header.'),
    )


@router.delete("/kris/{kid}/feed-token", status_code=204, dependencies=[_WRITE],
               summary="Revoke the KRI's integration token")
async def revoke_feed_token(kid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    kri = await _load_kri(db, kid)
    if not kri.feed_token_hash:
        return
    kri.feed_token_hash = ""
    await db.flush()
    await audit_log.record(db, actor=user, action="feed_token_revoke", entity_type="key_risk_indicator",
                           entity_id=kid, summary=f"Revoked the feed token of KRI {kri.reference}")


_FEED_AUTH = HTTPBearer(
    auto_error=False, scheme_name="KriFeedToken",
    description="The KRI's feed token from POST /kris/{id}/feed-token (not a user session).",
)
#: A KRI feed posts a reading a day, or a few an hour from a monitoring job: 20 in a burst,
#: then one every 3 seconds per KRI, across every API worker when Redis is up.
KRI_FEED_LIMIT = RateLimiter("kri-feed", capacity=20, per_second=1 / 3)


async def _feed_rate_check(tenant_id: uuid.UUID, kid: uuid.UUID) -> None:
    """429 (with ``Retry-After``) when this KRI's feed is over its rate."""
    decision = await KRI_FEED_LIMIT.hit(f"{tenant_id}:{kid}")
    if not decision.allowed:
        raise too_many_requests(decision, "readings for this KRI")


def _feed_denied() -> HTTPException:
    """One answer for every failure (no token, malformed, unknown org, wrong or revoked
    token, archived KRI), so a caller learns nothing about which part was wrong."""
    return HTTPException(
        status_code=401, detail="Invalid or revoked KRI feed token.", headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/kris/{kid}/measurements/feed", response_model=FeedResult, status_code=201,
             summary="Post a reading from an integration (feed token, no user session)")
async def feed_measurement(
    kid: uuid.UUID,
    body: MeasurementFeed,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_FEED_AUTH)] = None,
) -> FeedResult:
    """Record a KRI reading sent by a monitoring system or CCM connector.

    ``Authorization: Bearer <token>`` where the token was issued by ``POST
    /kris/{id}/feed-token``; the body is ``{"value": 12.5, "as_of_date": "2026-09-12",
    "notes": "…"}`` (date optional, defaults to today, never in the future). A wrong,
    revoked or other-KRI token is a 401. The reading goes through the same rules as one
    entered by hand — thresholds must be set, only the latest reading moves the current
    value, and a move into amber or red raises the escalation — and is audited as
    ``KRI feed``. The reply carries only the new status, never names or history.
    """
    token = creds.credentials if creds is not None and (creds.scheme or "").lower() == "bearer" else ""
    tenant_id = feed_token_tenant(token)
    if tenant_id is None:
        raise _feed_denied()
    # Before any database work, so a flood of posts (valid token or not) stays cheap.
    await _feed_rate_check(tenant_id, kid)
    async with tenant_session(tenant_id) as db:
        tenant = await db.get(Tenant, tenant_id)
        kri = None
        if tenant is not None and tenant.is_active:
            kri = await db.scalar(
                select(KeyRiskIndicator).where(KeyRiskIndicator.id == kid, KeyRiskIndicator.deleted.is_(False))
            )
        if kri is None or not feed_token_matches(token, kri.feed_token_hash):
            raise _feed_denied()
        reading = await record_reading(db, kri, value=body.value, as_of=body.as_of_date,
                                       notes=body.notes, tenant_id=tenant_id)
        for entry in reading_audit(kri, reading, via=FEED_ACTOR):
            await _feed_audit(db, tenant_id, entry)
        await db.flush()
        return FeedResult(
            kri_id=kri.id, reference=kri.reference, measurement_id=reading.measurement.id,
            status=kri.status, current_value=_flt(kri.current_value),
            last_measured_date=kri.last_measured_date, escalated=reading.level,
        )


# =============================================================== loss events ===
# `net_loss` is computed (gross − recovery), not a DB column, so it is not sortable.
_LOSS_SORTABLE = {
    "reference": LossEvent.reference,
    "title": LossEvent.title,
    "basel_event_type": LossEvent.basel_event_type,
    "basel_event_type_l2": LossEvent.basel_event_type_l2,
    "business_line": LossEvent.business_line,
    "gross_loss": LossEvent.gross_loss,
    "recovery": LossEvent.recovery,
    "status": LossEvent.status,
    "occurrence_date": LossEvent.occurrence_date,
    "created_at": LossEvent.created_at,
}


@router.get("/loss-events", response_model=Page[LossEventRead], dependencies=[_READ])
async def list_loss_events(db: DbSession, search: str | None = None,
                           business_unit_id: uuid.UUID | None = None,
                           action_owner_id: uuid.UUID | None = None,
                           sort_by: Annotated[str | None, Query()] = None,
                           sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                           limit: Annotated[int, Query(ge=1, le=200)] = 100,
                           offset: Annotated[int, Query(ge=0)] = 0) -> Page[LossEventRead]:
    stmt = select(LossEvent).where(LossEvent.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(LossEvent.title.ilike(like), LossEvent.reference.ilike(like),
                             LossEvent.business_line.ilike(like)))
    if business_unit_id is not None:
        stmt = stmt.where(LossEvent.business_unit_id == business_unit_id)
    if action_owner_id is not None:
        stmt = stmt.where(LossEvent.action_owner_id == action_owner_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _LOSS_SORTABLE, default=LossEvent.occurrence_date)
    else:
        stmt = stmt.order_by(LossEvent.occurrence_date.is_(None), LossEvent.occurrence_date.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=await _reads(db, LossEventRead, rows, LOSS_REFS), total=total, limit=limit, offset=offset)


def check_loss_taxonomy(record, patch: dict) -> None:
    """Decision 5: the level-2 category must sit under the level-1 event type the record
    will have after ``patch``. Changing the level-1 type without a fitting level-2 is
    refused rather than silently clearing the category. Normalises ``patch`` in place."""
    if patch.get("basel_event_type_l2") is None:
        patch.pop("basel_event_type_l2", None)
    else:
        patch["basel_event_type_l2"] = patch["basel_event_type_l2"].strip()
    if "basel_event_type" in patch and patch["basel_event_type"] is None:
        patch.pop("basel_event_type")
    l1 = patch.get("basel_event_type", getattr(record, "basel_event_type", None))
    l2 = patch.get("basel_event_type_l2", getattr(record, "basel_event_type_l2", "") or "")
    error = basel_l2_error(l1, l2)
    if error:
        raise HTTPException(status_code=422, detail=error)


@router.post("/loss-events", response_model=LossEventRead, status_code=201, dependencies=[_WRITE])
async def create_loss_event(body: LossEventCreate, db: DbSession, user: CurrentUser) -> LossEventRead:
    data = body.model_dump(exclude={"risk_ids"})
    if not data.get("currency"):  # decision 4: blank = the reporting currency, stored explicitly
        data["currency"] = await fx.reporting_currency(db, user.tenant_id)
    await rf.apply_refs(db, LossEvent, data, LOSS_REFS)
    obj = LossEvent(tenant_id=user.tenant_id, **data)
    obj.risks = await _resolve(db, Risk, body.risk_ids)
    obj.reference = await _next_ref(db, LossEvent, "LOSS")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="loss_event",
                           entity_id=obj.id, summary=f"Logged loss event {obj.reference}: {obj.title}")
    return (await _reads(db, LossEventRead, [await _get(db, LossEvent, obj.id, "Loss event")], LOSS_REFS))[0]


@router.patch("/loss-events/{lid}", response_model=LossEventRead, dependencies=[_WRITE])
async def update_loss_event(lid: uuid.UUID, body: LossEventUpdate, db: DbSession) -> LossEventRead:
    obj = await _get(db, LossEvent, lid, "Loss event")
    data = body.model_dump(exclude_unset=True, exclude={"risk_ids"})
    check_loss_taxonomy(obj, data)
    if "currency" in data and not data["currency"]:
        data["currency"] = await fx.reporting_currency(db, obj.tenant_id)
    await rf.apply_refs(db, LossEvent, data, LOSS_REFS, record=obj)
    for k, v in data.items():
        setattr(obj, k, v)
    if body.risk_ids is not None:
        obj.risks = await _resolve(db, Risk, body.risk_ids)
    await db.flush()
    return (await _reads(db, LossEventRead, [obj], LOSS_REFS))[0]


@router.delete("/loss-events/{lid}", status_code=204, dependencies=[_WRITE])
async def delete_loss_event(lid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _get(db, LossEvent, lid, "Loss event")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await _audit_delete(db, user, "loss_event", obj, "loss event")


class BaselCategory(BaseModel):
    value: str
    label: str
    examples: str = ""


class BaselEventTypeNode(BaseModel):
    value: str
    label: str
    level2: list[BaselCategory]


@router.get("/loss-events-taxonomy", response_model=list[BaselEventTypeNode], dependencies=[_READ],
            summary="Basel II event types: 7 level-1 types with their 20 level-2 categories")
async def loss_taxonomy() -> list[BaselEventTypeNode]:
    return basel_taxonomy()


def basel_taxonomy() -> list[BaselEventTypeNode]:
    """Basel II Annex 9, level 1 → level 2, in the Accord's order. Pure."""
    return [
        BaselEventTypeNode(
            value=l1, label=label,
            level2=[BaselCategory(value=k, label=n, examples=e) for k, p, n, e in BASEL_EVENT_TYPES_L2 if p == l1],
        )
        for l1, label in BASEL_L1_LABELS.items()
    ]


LOSS_CONVERSION_BASIS = (
    "Each loss converts at the rate in force on its accounting date (the date it was booked), "
    "else its discovery date, else its occurrence date; an event with none of these dates converts "
    "at today's rate."
)


class LossSummaryL2Row(BaseModel):
    #: "" = events not yet categorised at level 2.
    basel_event_type_l2: str
    label: str
    count: int
    gross_loss: float
    net_loss: float


class LossSummaryRow(BaseModel):
    basel_event_type: str
    label: str = ""
    count: int
    #: Converted to the reporting currency; amounts with no rate are excluded (see
    #: ``unconverted_count`` here and ``LossSummary.unconverted``).
    gross_loss: float
    net_loss: float
    unconverted_count: int = 0
    level2: list[LossSummaryL2Row] = []


class LossSummary(BaseModel):
    rows: list[LossSummaryRow]
    total_gross: float
    total_net: float
    total_count: int
    #: Decision 4: every amount above is in this currency.
    reporting_currency: str = "PKR"
    #: Which date each event converts at.
    conversion_basis: str = LOSS_CONVERSION_BASIS
    #: Gross amounts with no exchange rate on or before their date, never added in.
    unconverted: list[UnconvertedAmount] = []
    gross: MoneyTotalRead = MoneyTotalRead()
    net: MoneyTotalRead = MoneyTotalRead()


def summarise_losses(events, book: fx.RateBook) -> LossSummary:
    """Loss roll-up by Basel level 1 and level 2, in the reporting currency. Pure.

    Every event is counted; only converted amounts are summed. An event whose currency has
    no rate on or before its conversion date is listed in ``unconverted`` instead.
    """
    gross_all, net_all = fx.MoneyTotal(book), fx.MoneyTotal(book)
    groups: dict[str, dict] = {}
    for e in events:
        l1 = getattr(e.basel_event_type, "value", e.basel_event_type)
        l2 = (getattr(e, "basel_event_type_l2", "") or "").strip()
        on = fx.loss_conversion_date(e)
        g = groups.setdefault(l1, {"gross": fx.MoneyTotal(book), "net": fx.MoneyTotal(book), "l2": {}})
        sub = g["l2"].setdefault(l2, {"gross": fx.MoneyTotal(book), "net": fx.MoneyTotal(book)})
        gross = e.gross_loss or 0
        net = float(gross) - float(e.recovery or 0)
        for total in (gross_all, g["gross"], sub["gross"]):
            total.add(gross, e.currency, on)
        for total in (net_all, g["net"], sub["net"]):
            total.add(net, e.currency, on)
    order = list(BASEL_L1_LABELS)
    rows = []
    for l1 in sorted(groups, key=lambda k: order.index(k) if k in order else len(order)):
        g = groups[l1]
        l2_order = [k for k, p, _n, _e in BASEL_EVENT_TYPES_L2 if p == l1]
        level2 = [
            LossSummaryL2Row(
                basel_event_type_l2=k, label=BASEL_L2_LABELS.get(k, "Not categorised at level 2"),
                count=v["gross"].count, gross_loss=fx.money(v["gross"].total), net_loss=fx.money(v["net"].total),
            )
            for k, v in sorted(g["l2"].items(), key=lambda kv: l2_order.index(kv[0]) if kv[0] in l2_order else 99)
        ]
        rows.append(LossSummaryRow(
            basel_event_type=l1, label=BASEL_L1_LABELS.get(l1, l1), count=g["gross"].count,
            gross_loss=fx.money(g["gross"].total), net_loss=fx.money(g["net"].total),
            unconverted_count=g["gross"].unconverted_count, level2=level2,
        ))
    gross_d = gross_all.as_dict()
    return LossSummary(
        rows=rows,
        total_gross=gross_d["total"],
        total_net=fx.money(net_all.total),
        total_count=gross_all.count,
        reporting_currency=book.reporting_currency,
        unconverted=[UnconvertedAmount(**u) for u in gross_d["unconverted"]],
        gross=MoneyTotalRead(**gross_d),
        net=MoneyTotalRead(**net_all.as_dict()),
    )


@router.get("/loss-events-summary", response_model=LossSummary, dependencies=[_READ],
            summary="Operational loss roll-up by Basel event type (levels 1 and 2), in the reporting currency")
async def loss_summary(db: DbSession, user: CurrentUser) -> LossSummary:
    events = (await db.scalars(select(LossEvent).where(LossEvent.deleted.is_(False)))).all()
    return summarise_losses(events, await fx.load_rate_book(db, user.tenant_id))
