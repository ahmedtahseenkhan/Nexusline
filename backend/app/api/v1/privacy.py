"""Data Privacy API — Records of Processing Activities (RoPA / GDPR Article 30)."""
from __future__ import annotations

import uuid
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import Asset
from app.models.organization import Process
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.risk import Risk
from app.schemas.common import Page
from app.schemas.privacy import RopaCreate, RopaRead, RopaUpdate
from app.services import audit

router = APIRouter(prefix="/processing-activities", tags=["privacy"])


async def _load(db, ropa_id: uuid.UUID) -> ProcessingActivity:
    obj = await db.scalar(
        select(ProcessingActivity)
        .where(ProcessingActivity.id == ropa_id, ProcessingActivity.deleted.is_(False))
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
    count = await db.scalar(select(func.count()).select_from(ProcessingActivity)) or 0
    return f"ROPA-{count + 1:03d}"


@router.get("", response_model=Page[RopaRead], dependencies=[Depends(require("privacy:read"))])
async def list_ropa(
    db: DbSession,
    transfer_gap: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RopaRead]:
    stmt: Select = select(ProcessingActivity).where(ProcessingActivity.deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(ProcessingActivity.name).limit(limit).offset(offset))
    ).all()
    items = [RopaRead.model_validate(r) for r in rows]
    if transfer_gap is not None:
        items = [i for i in items if i.has_transfer_gap == transfer_gap]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=RopaRead, status_code=201, dependencies=[Depends(require("privacy:write"))])
async def create_ropa(body: RopaCreate, db: DbSession, user: CurrentUser) -> RopaRead:
    _links = {"asset_ids", "risk_ids", "process_ids", "policy_ids"}
    data = body.model_dump(exclude=_links)
    obj = ProcessingActivity(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db)
    await _apply_links(db, obj, body.model_dump())
    db.add(obj)
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
