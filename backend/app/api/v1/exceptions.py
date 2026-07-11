"""Exceptions Management API — time-boxed acceptance of risk/policy/compliance gaps."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, delete, func, insert, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import Asset, assets_exceptions
from app.models.compliance import Requirement
from app.models.control import Control
from app.models.enums import ExceptionStatus, ExceptionType
from app.models.exception import ExceptionRecord
from app.models.policy import Policy
from app.models.risk import Risk
from app.schemas.common import Page
from app.schemas.exception import (
    ExceptionCreate,
    ExceptionDecision,
    ExceptionRead,
    ExceptionUpdate,
)
from app.services.refs import next_reference
from app.services import audit

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


async def _load(db, exc_id: uuid.UUID) -> ExceptionRecord:
    obj = await db.scalar(
        select(ExceptionRecord).where(ExceptionRecord.id == exc_id, ExceptionRecord.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found")
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


async def _apply_links(db, obj: ExceptionRecord, body) -> None:
    """Apply the four writable M2M relationships via plain assignment.

    Safe to call pre-flush in CREATE (object PENDING) and post-load in UPDATE.
    Assets are handled separately by ``_flush_assets`` because ``ExceptionRecord.assets``
    is a ``viewonly`` reverse view (writable side lives on ``Asset.exceptions``).
    """
    data = body if isinstance(body, dict) else body.model_dump(exclude_unset=True)
    if "risk_ids" in data and data["risk_ids"] is not None:
        obj.risks = await _resolve(db, Risk, data["risk_ids"])
    if "policy_ids" in data and data["policy_ids"] is not None:
        obj.policies = await _resolve(db, Policy, data["policy_ids"])
    if "requirement_ids" in data and data["requirement_ids"] is not None:
        obj.requirements = await _resolve(db, Requirement, data["requirement_ids"])
    if "control_ids" in data and data["control_ids"] is not None:
        obj.controls = await _resolve(db, Control, data["control_ids"])


async def _flush_assets(db, exc_id: uuid.UUID, body) -> None:
    """Write the viewonly ``assets`` link by managing the ``assets_exceptions`` join
    table directly. Must run after the exception row has an id (post-flush)."""
    data = body if isinstance(body, dict) else body.model_dump(exclude_unset=True)
    if "asset_ids" not in data or data["asset_ids"] is None:
        return
    await _resolve(db, Asset, data["asset_ids"])  # validate ids exist
    await db.execute(delete(assets_exceptions).where(assets_exceptions.c.exception_id == exc_id))
    if data["asset_ids"]:
        await db.execute(
            insert(assets_exceptions),
            [{"exception_id": exc_id, "asset_id": aid} for aid in data["asset_ids"]],
        )


async def _next_ref(db) -> str:
    return await next_reference(db, ExceptionRecord, "EXC")


@router.get("", response_model=Page[ExceptionRead], dependencies=[Depends(require("exception:read"))])
async def list_exceptions(
    db: DbSession,
    status_filter: Annotated[ExceptionStatus | None, Query(alias="status")] = None,
    type_filter: Annotated[ExceptionType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ExceptionRead]:
    stmt: Select = select(ExceptionRecord).where(ExceptionRecord.deleted.is_(False))
    if status_filter is ExceptionStatus.expired:
        # `expired` is a derived state, never persisted — an approved exception past its
        # expiry. Translate the filter to that computed condition so the view works.
        stmt = stmt.where(
            ExceptionRecord.status == ExceptionStatus.approved,
            ExceptionRecord.expires_at.is_not(None),
            ExceptionRecord.expires_at < date.today(),
        )
    elif status_filter is not None:
        stmt = stmt.where(ExceptionRecord.status == status_filter)
    if type_filter is not None:
        stmt = stmt.where(ExceptionRecord.exception_type == type_filter)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(ExceptionRecord.created_at.desc()).limit(limit).offset(offset))
    ).all()
    return Page(items=[ExceptionRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ExceptionRead, status_code=201, dependencies=[Depends(require("exception:write"))])
async def create_exception(body: ExceptionCreate, db: DbSession, user: CurrentUser) -> ExceptionRead:
    data = body.model_dump(
        exclude={"risk_ids", "policy_ids", "requirement_ids", "control_ids", "asset_ids"}
    )
    obj = ExceptionRecord(tenant_id=user.tenant_id, requested_by=user.id, **data)
    obj.reference = await _next_ref(db)
    await _apply_links(db, obj, body)  # writable M2M, PENDING/pre-flush is fine
    db.add(obj)
    await db.flush()
    await _flush_assets(db, obj.id, body)  # viewonly assets: needs obj.id
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="exception", entity_id=obj.id,
        summary=f"Requested exception {obj.reference}: {obj.title}",
    )
    return ExceptionRead.model_validate(await _load(db, obj.id))


@router.get("/{exc_id}", response_model=ExceptionRead, dependencies=[Depends(require("exception:read"))])
async def get_exception(exc_id: uuid.UUID, db: DbSession) -> ExceptionRead:
    return ExceptionRead.model_validate(await _load(db, exc_id))


@router.patch("/{exc_id}", response_model=ExceptionRead, dependencies=[Depends(require("exception:write"))])
async def update_exception(exc_id: uuid.UUID, body: ExceptionUpdate, db: DbSession) -> ExceptionRead:
    obj = await _load(db, exc_id)
    # Maker-checker: approval/rejection is a checker action and must go through
    # /decision (which requires exception:approve). Block those target states here so a
    # holder of only exception:write can't self-approve via a plain PATCH.
    if body.status in (ExceptionStatus.approved, ExceptionStatus.rejected) and body.status != obj.status:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Use the approve/reject decision action; status cannot be set to "
            f"'{body.status.value}' via edit.",
        )
    await _apply_links(db, obj, body)
    data = body.model_dump(
        exclude_unset=True,
        exclude={"risk_ids", "policy_ids", "requirement_ids", "control_ids", "asset_ids"},
    )
    for f, v in data.items():
        setattr(obj, f, v)
    await db.flush()
    await _flush_assets(db, obj.id, body)
    await db.flush()
    return ExceptionRead.model_validate(await _load(db, obj.id))


@router.post(
    "/{exc_id}/decision",
    response_model=ExceptionRead,
    dependencies=[Depends(require("exception:approve"))],
    summary="Approve or reject a pending exception",
)
async def decide_exception(
    exc_id: uuid.UUID, body: ExceptionDecision, db: DbSession, user: CurrentUser
) -> ExceptionRead:
    obj = await _load(db, exc_id)
    if obj.status != ExceptionStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Exception already {obj.status.value}"
        )
    obj.approver_id = user.id
    obj.decided_at = date.today()
    obj.status = ExceptionStatus.approved if body.approve else ExceptionStatus.rejected
    await db.flush()
    await audit.record(
        db, actor=user, action="decide", entity_type="exception", entity_id=obj.id,
        summary=f"{'Approved' if body.approve else 'Rejected'} exception {obj.reference}",
        changes={"note": body.note} if body.note else {},
    )
    return ExceptionRead.model_validate(await _load(db, obj.id))


@router.post(
    "/{exc_id}/close",
    response_model=ExceptionRead,
    dependencies=[Depends(require("exception:write"))],
    summary="Close an exception early",
)
async def close_exception(exc_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ExceptionRead:
    obj = await _load(db, exc_id)
    obj.status = ExceptionStatus.closed
    obj.closure_date = date.today()
    await db.flush()
    await audit.record(
        db, actor=user, action="close", entity_type="exception", entity_id=obj.id,
        summary=f"Closed exception {obj.reference}",
    )
    return ExceptionRead.model_validate(await _load(db, obj.id))


@router.delete("/{exc_id}", status_code=204, dependencies=[Depends(require("exception:write"))])
async def delete_exception(exc_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, exc_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
