"""Whistleblowing & Case Management API — confidential-disclosure intake, triage and
investigation case handling.

Anonymous reports are masked on read (the client hides name/contact) and are reachable
only through a tokenized ``tracking_code`` two-way channel, generated on intake. Every
case-log line lands as a :class:`WhistleUpdate`. Audit trail on intake and whenever a
case is substantiated or closed.
"""
from __future__ import annotations

import secrets
import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.whistleblowing import (
    WhistleblowingReport,
    WhistleCategory,
    WhistleStatus,
    WhistleUpdate,
)
from app.schemas.common import Page
from app.schemas.whistleblowing import (
    WhistleReportCreate,
    WhistleReportRead,
    WhistleReportUpdate,
    WhistleUpdateCreate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["whistleblowing"])

_READ = Depends(require("whistle:read"))
_WRITE = Depends(require("whistle:write"))

# Statuses that mean an investigation has concluded (drive the audit trail + is_open).
_CLOSED_STATES = (WhistleStatus.substantiated, WhistleStatus.unsubstantiated, WhistleStatus.closed)


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _load_report(db, rid) -> WhistleblowingReport:
    obj = await db.scalar(
        select(WhistleblowingReport)
        .where(WhistleblowingReport.id == rid, WhistleblowingReport.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return obj


# ============================================================== reports ===
@router.get("/whistleblowing", response_model=Page[WhistleReportRead], dependencies=[_READ])
async def list_reports(
    db: DbSession,
    search: str | None = None,
    status: WhistleStatus | None = None,
    category: WhistleCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[WhistleReportRead]:
    stmt = select(WhistleblowingReport).where(WhistleblowingReport.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                WhistleblowingReport.title.ilike(like),
                WhistleblowingReport.description.ilike(like),
                WhistleblowingReport.reference.ilike(like),
                WhistleblowingReport.tracking_code.ilike(like),
                WhistleblowingReport.assigned_to.ilike(like),
            )
        )
    if status is not None:
        stmt = stmt.where(WhistleblowingReport.status == status)
    if category is not None:
        stmt = stmt.where(WhistleblowingReport.category == category)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(
            WhistleblowingReport.received_date.is_(None),
            WhistleblowingReport.received_date.desc(),
            WhistleblowingReport.created_at.desc(),
        ).limit(limit).offset(offset)
    )).all()
    return Page(items=[WhistleReportRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/whistleblowing", response_model=WhistleReportRead, status_code=201, dependencies=[_WRITE])
async def create_report(body: WhistleReportCreate, db: DbSession, user: CurrentUser) -> WhistleReportRead:
    data = body.model_dump()
    # Confidentiality guarantee must hold server-side, not just in the intake form: when
    # the report is anonymous, never persist reporter identity, so it cannot leak via any
    # read, export or integration path.
    if data.get("anonymous"):
        data["reporter_name"] = ""
        data["reporter_contact"] = ""
    obj = WhistleblowingReport(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, WhistleblowingReport, "WB")
    # Mint a tokenized two-way channel code if the intake did not carry one.
    if not obj.tracking_code:
        obj.tracking_code = "WBX-" + secrets.token_hex(4).upper()
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="whistleblowing_report",
                           entity_id=obj.id, summary=f"Received whistleblowing report {obj.reference}: {obj.title}")
    return WhistleReportRead.model_validate(await _load_report(db, obj.id))


@router.get("/whistleblowing/{rid}", response_model=WhistleReportRead, dependencies=[_READ])
async def get_report(rid: uuid.UUID, db: DbSession) -> WhistleReportRead:
    return WhistleReportRead.model_validate(await _load_report(db, rid))


@router.patch("/whistleblowing/{rid}", response_model=WhistleReportRead, dependencies=[_WRITE])
async def update_report(rid: uuid.UUID, body: WhistleReportUpdate, db: DbSession, user: CurrentUser) -> WhistleReportRead:
    obj = await _load_report(db, rid)
    prev_status = obj.status
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)
    # If the report is (or becomes) anonymous, keep identity scrubbed on every edit.
    if obj.anonymous:
        obj.reporter_name = ""
        obj.reporter_contact = ""
    await db.flush()
    # Audit the case conclusion (substantiated / closed) when it first happens.
    if obj.status != prev_status and obj.status in (WhistleStatus.substantiated, WhistleStatus.closed):
        await audit_log.record(db, actor=user, action="update", entity_type="whistleblowing_report",
                               entity_id=obj.id,
                               summary=f"Whistleblowing case {obj.reference} {obj.status.value}")
    return WhistleReportRead.model_validate(await _load_report(db, rid))


@router.delete("/whistleblowing/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_report(rid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_report(db, rid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================================= case log ===
@router.post("/whistleblowing/{rid}/updates", response_model=WhistleReportRead, status_code=201, dependencies=[_WRITE])
async def add_update(rid: uuid.UUID, body: WhistleUpdateCreate, db: DbSession, user: CurrentUser) -> WhistleReportRead:
    await _load_report(db, rid)
    db.add(WhistleUpdate(tenant_id=user.tenant_id, report_id=rid, **body.model_dump()))
    await db.flush()
    return WhistleReportRead.model_validate(await _load_report(db, rid))


# =============================================================== summary ===
class WhistleSummary(BaseModel):
    total: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    open_investigations: int
    substantiated: int
    substantiated_rate: float


@router.get("/whistleblowing-summary", response_model=WhistleSummary, dependencies=[_READ],
            summary="Whistleblowing roll-up: cases by status/category, open investigations and substantiated rate")
async def whistleblowing_summary(db: DbSession) -> WhistleSummary:
    reports = (await db.scalars(
        select(WhistleblowingReport).where(WhistleblowingReport.deleted.is_(False))
    )).all()

    by_status: dict[str, int] = defaultdict(int)
    by_category: dict[str, int] = defaultdict(int)
    open_investigations = 0
    substantiated = 0
    concluded = 0
    for r in reports:
        by_status[r.status.value] += 1
        by_category[r.category.value] += 1
        if r.is_open:
            open_investigations += 1
        if r.status in _CLOSED_STATES:
            concluded += 1
        if r.status == WhistleStatus.substantiated:
            substantiated += 1

    # Rate = substantiated as a share of concluded investigations.
    substantiated_rate = round(substantiated / concluded * 100, 1) if concluded else 0.0

    return WhistleSummary(
        total=len(reports),
        by_status=dict(by_status),
        by_category=dict(by_category),
        open_investigations=open_investigations,
        substantiated=substantiated,
        substantiated_rate=substantiated_rate,
    )
