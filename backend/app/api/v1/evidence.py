"""Evidence collection API — audit-readiness artifacts attached to controls."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.compliance import Requirement
from app.models.control import Control
from app.models.evidence import Evidence
from app.schemas.common import Page
from app.schemas.evidence import EvidenceCreate, EvidenceRead, EvidenceUpdate
from app.services import audit

router = APIRouter(tags=["evidence"])


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
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EvidenceRead]:
    stmt = select(Evidence)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Evidence.title.ilike(like) | Evidence.reference.ilike(like))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _EVIDENCE_SORTABLE, default=Evidence.created_at)
    else:
        stmt = stmt.order_by(Evidence.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(
        items=[EvidenceRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post(
    "/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("control:write"))],
)
async def create_evidence(body: EvidenceCreate, db: DbSession, user: CurrentUser) -> EvidenceRead:
    control = await _control_or_400(db, body.control_id)
    obj = Evidence(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="evidence", entity_id=obj.id,
        summary=f"Collected evidence '{obj.title}' for control {control.reference or control.name}",
    )
    obj = await _evidence_or_404(db, obj.id)
    return EvidenceRead.model_validate(obj)


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceRead,
    dependencies=[Depends(require("control:read"))],
)
async def get_evidence(evidence_id: uuid.UUID, db: DbSession) -> EvidenceRead:
    return EvidenceRead.model_validate(await _evidence_or_404(db, evidence_id))


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
    if "control_id" in data and data["control_id"] is not None:
        await _control_or_400(db, data["control_id"])
    for field, value in data.items():
        setattr(obj, field, value)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="evidence", entity_id=obj.id,
        summary=f"Updated evidence '{obj.title}'",
    )
    return EvidenceRead.model_validate(await _evidence_or_404(db, obj.id))


@router.get(
    "/controls/{control_id}/evidence",
    response_model=list[EvidenceRead],
    dependencies=[Depends(require("control:read"))],
)
async def evidence_for_control(control_id: uuid.UUID, db: DbSession) -> list[EvidenceRead]:
    rows = (
        await db.scalars(select(Evidence).where(Evidence.control_id == control_id))
    ).all()
    return [EvidenceRead.model_validate(r) for r in rows]


@router.get(
    "/requirements/{requirement_id}/evidence",
    response_model=list[EvidenceRead],
    dependencies=[Depends(require("compliance:read"))],
    summary="Evidence demonstrating a requirement (via its mapped controls)",
)
async def evidence_for_requirement(requirement_id: uuid.UUID, db: DbSession) -> list[EvidenceRead]:
    req = await db.scalar(select(Requirement).where(Requirement.id == requirement_id))
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
    control_ids = [c.id for c in req.controls]
    if not control_ids:
        return []
    rows = (
        await db.scalars(select(Evidence).where(Evidence.control_id.in_(control_ids)))
    ).all()
    return [EvidenceRead.model_validate(r) for r in rows]


@router.delete(
    "/evidence/{evidence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("control:write"))],
)
async def delete_evidence(evidence_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _evidence_or_404(db, evidence_id))
