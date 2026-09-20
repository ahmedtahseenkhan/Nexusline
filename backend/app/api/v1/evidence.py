"""Evidence collection API — audit-readiness artifacts attached to controls, and to the
control tests they support."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.compliance import Requirement
from app.models.control import Control, ControlAudit
from app.models.evidence import Evidence
from app.schemas.common import Page
from app.schemas.control import REVIEW_REVIEWED, ControlTestRef
from app.schemas.evidence import (
    EvidenceCreate,
    EvidenceRead,
    EvidenceUpdate,
    evidence_status_problem,
)
from app.services import audit

router = APIRouter(tags=["evidence"])

SIGNED_OFF = (
    "This evidence supports a reviewed control test; the signed-off workpaper cannot lose it. "
    "Record a new test if the evidence was wrong."
)


async def _evidence_or_404(db, evidence_id: uuid.UUID) -> Evidence:
    obj = await db.scalar(
        select(Evidence).where(Evidence.id == evidence_id).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
    return obj


async def _control_or_400(db, control_id: uuid.UUID) -> Control:
    control = await db.get(Control, control_id)
    if control is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown control")
    return control


async def _test_of(db, control_id: uuid.UUID, audit_id: uuid.UUID | None) -> ControlAudit | None:
    """The control test an evidence item is attached to — which must be a test of the
    same control (422 otherwise)."""
    if audit_id is None:
        return None
    test = await db.get(ControlAudit, audit_id)
    if test is None or test.control_id != control_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="control_audit_id: pick a test of the same control.",
        )
    return test


async def _is_signed_off(db, audit_id: uuid.UUID | None) -> bool:
    if audit_id is None:
        return False
    test = await db.get(ControlAudit, audit_id)
    return test is not None and test.review_status == REVIEW_REVIEWED


async def _reads(db, rows) -> list[EvidenceRead]:
    """Read models with the supporting test resolved — one query for the page."""
    items = [EvidenceRead.model_validate(r) for r in rows]
    ids = {r.control_audit_id for r in rows if r.control_audit_id}
    if ids:
        tests = {
            t.id: ControlTestRef.model_validate(t)
            for t in (await db.scalars(select(ControlAudit).where(ControlAudit.id.in_(ids)))).all()
        }
        for item in items:
            item.control_audit = tests.get(item.control_audit_id)
    return items


async def _read(db, obj: Evidence) -> EvidenceRead:
    return (await _reads(db, [obj]))[0]


_EVIDENCE_SORTABLE = {
    "title": Evidence.title,
    "reference": Evidence.reference,
    "evidence_type": Evidence.evidence_type,
    "status": Evidence.status,
    "collected_at": Evidence.collected_at,
    "valid_until": Evidence.valid_until,
    "created_at": Evidence.created_at,
}


@router.get("/evidence", response_model=Page[EvidenceRead], dependencies=[Depends(require("control:read"))])
async def list_evidence(
    db: DbSession,
    search: str | None = None,
    control_id: Annotated[uuid.UUID | None, Query(description="Evidence of one control.")] = None,
    control_audit_id: Annotated[uuid.UUID | None, Query(description="Evidence supporting one control test.")] = None,
    unattached: Annotated[bool | None, Query(description="True: evidence not supporting any test yet.")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EvidenceRead]:
    stmt = select(Evidence)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Evidence.title.ilike(like) | Evidence.reference.ilike(like))
    if control_id is not None:
        stmt = stmt.where(Evidence.control_id == control_id)
    if control_audit_id is not None:
        stmt = stmt.where(Evidence.control_audit_id == control_audit_id)
    if unattached is True:
        stmt = stmt.where(Evidence.control_audit_id.is_(None))
    elif unattached is False:
        stmt = stmt.where(Evidence.control_audit_id.is_not(None))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _EVIDENCE_SORTABLE, default=Evidence.created_at)
    else:
        stmt = stmt.order_by(Evidence.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=await _reads(db, rows), total=total, limit=limit, offset=offset)


@router.post(
    "/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("control:write"))],
)
async def create_evidence(body: EvidenceCreate, db: DbSession, user: CurrentUser) -> EvidenceRead:
    control = await _control_or_400(db, body.control_id)
    test = await _test_of(db, body.control_id, body.control_audit_id)
    obj = Evidence(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="evidence", entity_id=obj.id,
        summary=f"Collected evidence '{obj.title}' for control {control.reference or control.name}"
        + (f" (supports the test of {test.conducted_date})" if test is not None else ""),
    )
    return await _read(db, await _evidence_or_404(db, obj.id))


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceRead,
    dependencies=[Depends(require("control:read"))],
)
async def get_evidence(evidence_id: uuid.UUID, db: DbSession) -> EvidenceRead:
    return await _read(db, await _evidence_or_404(db, evidence_id))


@router.patch(
    "/evidence/{evidence_id}",
    response_model=EvidenceRead,
    dependencies=[Depends(require("control:write"))],
)
async def update_evidence(
    evidence_id: uuid.UUID, body: EvidenceUpdate, db: DbSession, user: CurrentUser
) -> EvidenceRead:
    obj = await _evidence_or_404(db, evidence_id)
    data = body.model_dump(exclude_unset=True)
    if "control_id" in data and data["control_id"] is None:
        data.pop("control_id")  # evidence always belongs to a control
    moves_control = "control_id" in data and data["control_id"] != obj.control_id
    moves_test = "control_audit_id" in data and data["control_audit_id"] != obj.control_audit_id
    if (moves_control or moves_test) and await _is_signed_off(db, obj.control_audit_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SIGNED_OFF)
    if moves_control:
        await _control_or_400(db, data["control_id"])
        if not moves_test:
            data["control_audit_id"] = None  # a test of the old control no longer applies
    if data.get("control_audit_id") is not None:
        await _test_of(db, data.get("control_id", obj.control_id), data["control_audit_id"])
    problem = evidence_status_problem(
        data.get("status", obj.status), data.get("collected_at", obj.collected_at)
    )
    if problem and ("status" in data or "collected_at" in data):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
    for field, value in data.items():
        setattr(obj, field, value)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="evidence", entity_id=obj.id,
        summary=f"Updated evidence '{obj.title}'",
        changes={k: str(v) for k, v in data.items() if k in ("control_id", "control_audit_id", "status")},
    )
    return await _read(db, await _evidence_or_404(db, obj.id))


@router.get(
    "/controls/{control_id}/evidence",
    response_model=list[EvidenceRead],
    dependencies=[Depends(require("control:read"))],
)
async def evidence_for_control(control_id: uuid.UUID, db: DbSession) -> list[EvidenceRead]:
    rows = (
        await db.scalars(select(Evidence).where(Evidence.control_id == control_id).order_by(Evidence.title))
    ).all()
    return await _reads(db, rows)


@router.get(
    "/requirements/{requirement_id}/evidence",
    response_model=list[EvidenceRead],
    dependencies=[Depends(require("compliance:read"))],
    summary="Evidence demonstrating a requirement (via its mapped controls)",
)
async def evidence_for_requirement(requirement_id: uuid.UUID, db: DbSession) -> list[EvidenceRead]:
    req = await db.scalar(
        select(Requirement).where(
            Requirement.id == requirement_id, Requirement.deleted.is_(False)
        )
    )
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
    control_ids = [c.id for c in req.controls]
    if not control_ids:
        return []
    rows = (
        await db.scalars(select(Evidence).where(Evidence.control_id.in_(control_ids)))
    ).all()
    return await _reads(db, rows)


@router.delete(
    "/evidence/{evidence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("control:write"))],
)
async def delete_evidence(evidence_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Delete an evidence item. Evidence cited by a reviewed control test is part of a
    signed-off workpaper and cannot be deleted (409)."""
    obj = await _evidence_or_404(db, evidence_id)
    if await _is_signed_off(db, obj.control_audit_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SIGNED_OFF)
    title, oid = obj.title, obj.id
    await db.delete(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="delete", entity_type="evidence", entity_id=oid,
        summary=f"Deleted evidence '{title}'",
    )
