"""Regulatory incident reporting — SBP-style breach-notification obligations.

Attaches regulator submissions (initial notification → final report) to an incident,
each with an SLA deadline computed from the incident's detection date, and provides a
cross-incident obligations tracker. Deadlines use configurable SLA windows — verify
the exact values against the current SBP circular.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.models.enums import RegulatoryReportStatus, RegulatoryReportType
from app.models.incident import Incident, RegulatoryReport
from app.schemas.incident import IncidentRead, RegReportCreate, RegReportRead, RegReportUpdate
from app.services import audit

router = APIRouter(tags=["regulatory reporting"])

_READ = Depends(require("incident:read"))
_WRITE = Depends(require("incident:write"))


async def _load_incident(db, incident_id: uuid.UUID) -> Incident:
    # populate_existing forces the selectin relationships to reload even when the
    # incident is already cached in this transaction (e.g. just after adding reports).
    obj = await db.scalar(
        select(Incident)
        .where(Incident.id == incident_id, Incident.deleted.is_(False))
        .options(selectinload(Incident.regulatory_reports), selectinload(Incident.stages),
                 selectinload(Incident.controls), selectinload(Incident.vendors),
                 selectinload(Incident.assets), selectinload(Incident.risks))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return obj


@router.post("/incidents/{incident_id}/regulatory-reports", response_model=IncidentRead,
             status_code=201, dependencies=[_WRITE])
async def add_report(incident_id: uuid.UUID, body: RegReportCreate, db: DbSession, user: CurrentUser) -> IncidentRead:
    inc = await _load_incident(db, incident_id)
    inc.is_reportable = True
    if not inc.regulator:
        inc.regulator = body.regulator or settings.default_regulator
    db.add(RegulatoryReport(tenant_id=user.tenant_id, incident_id=incident_id, **body.model_dump()))
    await db.flush()
    return IncidentRead.model_validate(await _load_incident(db, incident_id))


@router.post("/incidents/{incident_id}/regulatory-reports/generate", response_model=IncidentRead,
             status_code=201, dependencies=[_WRITE],
             summary="Auto-create the standard regulator reports with SLA deadlines")
async def generate_reports(incident_id: uuid.UUID, db: DbSession, user: CurrentUser) -> IncidentRead:
    inc = await _load_incident(db, incident_id)
    inc.is_reportable = True
    regulator = inc.regulator or settings.default_regulator
    inc.regulator = regulator

    anchor = inc.detected_at or inc.occurred_at or date.today()
    initial_days = max(1, ceil(settings.regulatory_initial_report_hours / 24))
    planned = {
        RegulatoryReportType.initial_notification: anchor + timedelta(days=initial_days),
        RegulatoryReportType.final_report: anchor + timedelta(days=settings.regulatory_final_report_days),
    }
    existing = {r.report_type for r in inc.regulatory_reports}
    for rtype, deadline in planned.items():
        if rtype not in existing:
            db.add(RegulatoryReport(
                tenant_id=user.tenant_id, incident_id=incident_id, regulator=regulator,
                report_type=rtype, deadline=deadline,
            ))
    await db.flush()
    await audit.record(db, actor=user, action="update", entity_type="incident", entity_id=incident_id,
                       summary=f"Generated {regulator} regulatory reports for {inc.reference}")
    return IncidentRead.model_validate(await _load_incident(db, incident_id))


@router.patch("/regulatory-reports/{report_id}", response_model=RegReportRead, dependencies=[_WRITE])
async def update_report(report_id: uuid.UUID, body: RegReportUpdate, db: DbSession) -> RegReportRead:
    obj = await db.scalar(select(RegulatoryReport).where(RegulatoryReport.id == report_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    data = body.model_dump(exclude_unset=True)
    # Stamp the submission date when marked submitted/acknowledged and none supplied.
    if data.get("status") in (RegulatoryReportStatus.submitted, RegulatoryReportStatus.acknowledged) \
            and not obj.submitted_at and "submitted_at" not in data:
        obj.submitted_at = date.today()
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    return RegReportRead.model_validate(obj)


@router.delete("/regulatory-reports/{report_id}", status_code=204, dependencies=[_WRITE])
async def delete_report(report_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(RegulatoryReport).where(RegulatoryReport.id == report_id))
    if obj is not None:
        await db.delete(obj)


class RegReportTrackerRow(RegReportRead):
    model_config = ConfigDict(from_attributes=True)
    incident_reference: str = ""
    incident_title: str = ""


@router.get("/regulatory-reports", response_model=list[RegReportTrackerRow], dependencies=[_READ],
            summary="Cross-incident regulatory obligations tracker")
async def list_reports(
    db: DbSession,
    status_filter: Annotated[RegulatoryReportStatus | None, Query(alias="status")] = None,
    overdue: bool = False,
) -> list[RegReportTrackerRow]:
    stmt = select(RegulatoryReport).options(selectinload(RegulatoryReport.incident))
    if status_filter is not None:
        stmt = stmt.where(RegulatoryReport.status == status_filter)
    stmt = stmt.order_by(RegulatoryReport.deadline.is_(None), RegulatoryReport.deadline)
    rows = (await db.scalars(stmt)).all()

    out: list[RegReportTrackerRow] = []
    for r in rows:
        if overdue and not r.is_overdue:
            continue
        row = RegReportTrackerRow.model_validate(r)
        if r.incident is not None:
            row.incident_reference = r.incident.reference
            row.incident_title = r.incident.title
        out.append(row)
    return out
