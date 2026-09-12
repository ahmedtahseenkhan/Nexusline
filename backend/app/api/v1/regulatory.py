"""Regulatory incident reporting — SBP-style breach-notification obligations.

Attaches regulator submissions (initial notification → final report) to an incident,
each with an SLA deadline computed from the incident's detection time, and provides a
cross-incident obligations tracker. Deadlines use configurable SLA windows — verify
the exact values against the current SBP circular.

Phase 2: deadlines and submissions are timestamps, and the deadline rule lives in
``services.incident_clock`` — the incident form (marking an incident reportable) and the
"generate" action below both go through it, so there is one source of truth.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.models.enums import RegulatoryReportStatus
from app.models.incident import Incident, RegulatoryReport
from app.schemas.incident import IncidentRead, RegReportCreate, RegReportRead, RegReportUpdate
from app.api.v1.incidents import (
    REGULATOR_REF,
    REPORT_REFS,
    REPORT_REGULATOR_REF,
    _default_regulator,
    _sync_reports,
    incident_read,
)
from app.services import audit
from app.services import incident_clock as clock
from app.services import ref_fields as rf

#: Everything a report's read shows beside its keys.
_REPORT_READ_REFS = REPORT_REFS + (REPORT_REGULATOR_REF,)
_REPORT_TIMESTAMPS = ("deadline", "submitted_at")

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
                 selectinload(Incident.assets), selectinload(Incident.risks),
                 selectinload(Incident.loss_events), selectinload(Incident.data_breaches))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return obj


async def _set_regulator(db, inc: Incident, patch: dict) -> None:
    """Name the incident's regulator, keeping ``regulator_id`` and the text in step."""
    await rf.apply_refs(db, Incident, patch, (REGULATOR_REF,), record=inc)
    for k, v in patch.items():
        setattr(inc, k, v)


@router.post("/incidents/{incident_id}/regulatory-reports", response_model=IncidentRead,
             status_code=201, dependencies=[_WRITE])
async def add_report(incident_id: uuid.UUID, body: RegReportCreate, db: DbSession, user: CurrentUser) -> IncidentRead:
    inc = await _load_incident(db, incident_id)
    inc.is_reportable = True
    if not inc.regulator and not inc.regulator_id:
        # The incident's regulator is whoever this first report goes to.
        await _set_regulator(db, inc, {"regulator_id": body.regulator_id} if body.regulator_id
                             else {"regulator": body.regulator or settings.default_regulator})
    data = body.model_dump()
    await clock.localize_fields(db, user.tenant_id, data, _REPORT_TIMESTAMPS)
    if data.get("regulator_id") is None and (not body.regulator or body.regulator == inc.regulator):
        # A report is owed to the incident's regulator unless another is named.
        data["regulator_id"], data["regulator"] = inc.regulator_id, inc.regulator or body.regulator
        if data["regulator_id"] is None:
            data.pop("regulator_id")  # leave the text to be matched
    await rf.apply_refs(db, RegulatoryReport, data, _REPORT_READ_REFS)
    report = RegulatoryReport(tenant_id=user.tenant_id, incident_id=incident_id, **data)
    db.add(report)
    await db.flush()
    await audit.record(db, actor=user, action="update", entity_type="incident", entity_id=incident_id,
                       summary=f"Added a {report.regulator} {report.report_type.value.replace('_', ' ')} "
                               f"to {inc.reference}")
    return await incident_read(db, await _load_incident(db, incident_id))


@router.post("/incidents/{incident_id}/regulatory-reports/generate", response_model=IncidentRead,
             status_code=201, dependencies=[_WRITE],
             summary="Auto-create the standard regulator reports with SLA deadlines")
async def generate_reports(incident_id: uuid.UUID, db: DbSession, user: CurrentUser) -> IncidentRead:
    """Create whichever of the initial notification and final report the incident does
    not have yet, with deadlines from detection (initial: +N hours to the minute; final:
    +M days). Existing reports are left as they are."""
    inc = await _load_incident(db, incident_id)
    inc.is_reportable = True
    await _default_regulator(db, inc, {})
    changes = _sync_reports(inc, user, recompute=False, create_missing=True)
    await db.flush()
    await audit.record(db, actor=user, action="update", entity_type="incident", entity_id=incident_id,
                       summary=f"Generated {inc.regulator} regulatory reports for {inc.reference}",
                       changes={"regulatory": changes})
    return await incident_read(db, await _load_incident(db, incident_id))


@router.patch("/regulatory-reports/{report_id}", response_model=RegReportRead, dependencies=[_WRITE])
async def update_report(
    report_id: uuid.UUID, body: RegReportUpdate, db: DbSession, user: CurrentUser = None
) -> RegReportRead:
    obj = await db.scalar(select(RegulatoryReport).where(RegulatoryReport.id == report_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    data = body.model_dump(exclude_unset=True)
    if user is not None:
        await clock.localize_fields(db, user.tenant_id, data, _REPORT_TIMESTAMPS)
    await rf.apply_refs(db, RegulatoryReport, data, _REPORT_READ_REFS, record=obj)
    # Stamp the submission time when marked submitted/acknowledged and none supplied:
    # it is the moment the regulator was notified, which the incident's clock reads.
    if data.get("status") in (RegulatoryReportStatus.submitted, RegulatoryReportStatus.acknowledged) \
            and not obj.submitted_at and "submitted_at" not in data:
        obj.submitted_at = clock.now_utc()
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if user is not None:  # always, through the API (``user`` is only absent in direct calls)
        await audit.record(
            db, actor=user, action="update", entity_type="incident", entity_id=obj.incident_id,
            summary=f"Updated the {obj.regulator} {obj.report_type.value.replace('_', ' ')} "
                    f"({obj.status.value})",
            changes={"report_id": str(obj.id), "fields": sorted(data)},
        )
    read = RegReportRead.model_validate(obj)
    await rf.fill_refs(db, [(obj, read)], _REPORT_READ_REFS)
    return read


@router.delete("/regulatory-reports/{report_id}", status_code=204, dependencies=[_WRITE])
async def delete_report(report_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await db.scalar(select(RegulatoryReport).where(RegulatoryReport.id == report_id))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await audit.record(
        db, actor=user, action="update", entity_type="incident", entity_id=obj.incident_id,
        summary=f"Removed the {obj.regulator} {obj.report_type.value.replace('_', ' ')}",
        changes={"report_id": str(obj.id), "deadline": obj.deadline.isoformat() if obj.deadline else None},
    )
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

    pairs: list = []
    for r in rows:
        if overdue and not r.is_overdue:
            continue
        row = RegReportTrackerRow.model_validate(r)
        if r.incident is not None:
            row.incident_reference = r.incident.reference
            row.incident_title = r.incident.title
        pairs.append((r, row))
    await rf.fill_refs(db, pairs, _REPORT_READ_REFS)
    return [row for _, row in pairs]
