"""Data Privacy API — Records of Processing Activities (RoPA / GDPR Article 30)."""
from __future__ import annotations

import uuid
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, and_, func, not_, or_, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.asset import Asset
from app.models.enums import DpiaStatus
from app.models.organization import Process
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.risk import Risk
from app.schemas.common import Page
from app.schemas.privacy import RopaCreate, RopaRead, RopaUpdate
from app.services.refs import next_reference
from app.services import audit

router = APIRouter(prefix="/processing-activities", tags=["privacy"])


def _loads():
    """Eager-load every relationship RopaRead serialises so model_validate never
    triggers a lazy IO load outside the async greenlet."""
    return (
        selectinload(ProcessingActivity.business_unit),
        selectinload(ProcessingActivity.assets),
        selectinload(ProcessingActivity.risks),
        selectinload(ProcessingActivity.processes),
        selectinload(ProcessingActivity.policies),
    )


async def _load(db, ropa_id: uuid.UUID) -> ProcessingActivity:
    obj = await db.scalar(
        select(ProcessingActivity)
        .where(ProcessingActivity.id == ropa_id, ProcessingActivity.deleted.is_(False))
        .options(*_loads())
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return obj


async def _resolve(db, model, ids: Sequence[uuid.UUID]) -> list:
    if not ids:
        return []
    rows = (await db.scalars(select(model).where(model.id.in_(ids)))).all()
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown {model.__name__.lower()} id(s): {sorted(map(str, missing))}",
        )
    return list(rows)


async def _apply_links(db, obj: ProcessingActivity, data: dict) -> None:
    if data.get("asset_ids") is not None:
        obj.assets = await _resolve(db, Asset, data["asset_ids"])
    if data.get("risk_ids") is not None:
        obj.risks = await _resolve(db, Risk, data["risk_ids"])
    if data.get("process_ids") is not None:
        obj.processes = await _resolve(db, Process, data["process_ids"])
    if data.get("policy_ids") is not None:
        obj.policies = await _resolve(db, Policy, data["policy_ids"])


async def _next_ref(db) -> str:
    return await next_reference(db, ProcessingActivity, "ROPA")


_ROPA_SORTABLE = {
    "reference": ProcessingActivity.reference,
    "name": ProcessingActivity.name,
    "status": ProcessingActivity.status,
    "lawful_basis": ProcessingActivity.lawful_basis,
    "created_at": ProcessingActivity.created_at,
}


def _transfer_gap_clause():
    """A transfer gap = cross-border transfer with no documented safeguard. Mirrors the
    ``ProcessingActivity.has_transfer_gap`` property, but as a SQL predicate so the filter
    runs in the database (the previous implementation filtered AFTER pagination, which
    silently dropped rows and produced a wrong ``total``)."""
    return and_(
        ProcessingActivity.cross_border_transfer.is_(True),
        or_(
            ProcessingActivity.transfer_safeguard.is_(None),
            func.trim(ProcessingActivity.transfer_safeguard) == "",
        ),
    )


def _dpia_outstanding_clause():
    """DPIA required but not yet completed — mirrors ``dpia_outstanding``."""
    return and_(
        ProcessingActivity.dpia_required.is_(True),
        ProcessingActivity.dpia_status != DpiaStatus.completed,
    )


@router.get("", response_model=Page[RopaRead], dependencies=[Depends(require("privacy:read"))])
async def list_ropa(
    db: DbSession,
    search: str | None = None,
    transfer_gap: Annotated[bool | None, Query()] = None,
    dpia_outstanding: Annotated[bool | None, Query()] = None,
    special_category: Annotated[bool | None, Query()] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RopaRead]:
    stmt: Select = select(ProcessingActivity).where(ProcessingActivity.deleted.is_(False))
    if search:
        stmt = stmt.where(
            ProcessingActivity.name.ilike(f"%{search}%")
            | ProcessingActivity.reference.ilike(f"%{search}%")
        )
    if transfer_gap is not None:
        clause = _transfer_gap_clause()
        stmt = stmt.where(clause if transfer_gap else not_(clause))
    if dpia_outstanding is not None:
        clause = _dpia_outstanding_clause()
        stmt = stmt.where(clause if dpia_outstanding else not_(clause))
    if special_category is not None:
        stmt = stmt.where(ProcessingActivity.special_category.is_(special_category))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _ROPA_SORTABLE, default=ProcessingActivity.name)
    else:
        stmt = stmt.order_by(ProcessingActivity.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[RopaRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=RopaRead, status_code=201, dependencies=[Depends(require("privacy:write"))])
async def create_ropa(body: RopaCreate, db: DbSession, user: CurrentUser) -> RopaRead:
    _links = {"asset_ids", "risk_ids", "process_ids", "policy_ids"}
    data = body.model_dump(exclude=_links)
    obj = ProcessingActivity(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db)
    db.add(obj)
    # Assign relationships while the row is PENDING (pre-flush) — these are writable
    # (non-viewonly) selectin relationships, so plain assignment writes the join rows
    # on flush without a MissingGreenlet lazy-load.
    await _apply_links(db, obj, body.model_dump())
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="processing_activity", entity_id=obj.id,
        summary=f"Created RoPA {obj.reference}: {obj.name}",
    )
    return RopaRead.model_validate(await _load(db, obj.id))


@router.get("/{ropa_id}", response_model=RopaRead, dependencies=[Depends(require("privacy:read"))])
async def get_ropa(ropa_id: uuid.UUID, db: DbSession) -> RopaRead:
    return RopaRead.model_validate(await _load(db, ropa_id))


@router.patch("/{ropa_id}", response_model=RopaRead, dependencies=[Depends(require("privacy:write"))])
async def update_ropa(ropa_id: uuid.UUID, body: RopaUpdate, db: DbSession) -> RopaRead:
    _links = {"asset_ids", "risk_ids", "process_ids", "policy_ids"}
    obj = await _load(db, ropa_id)
    full = body.model_dump(exclude_unset=True)
    await _apply_links(db, obj, full)
    for f, v in body.model_dump(exclude_unset=True, exclude=_links).items():
        setattr(obj, f, v)
    await db.flush()
    return RopaRead.model_validate(await _load(db, obj.id))


@router.delete("/{ropa_id}", status_code=204, dependencies=[Depends(require("privacy:write"))])
async def delete_ropa(ropa_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, ropa_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
