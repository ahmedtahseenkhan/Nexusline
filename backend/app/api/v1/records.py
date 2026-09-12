"""Cross-register record operations: archive/restore, delete impact, and the lifecycle.

Every endpoint here addresses a record by ``(entity_type, id)`` using the shared entity
registry (``services/entity_types.py``), and inherits exactly the owning module's
permissions — reading an archive needs the module's read permission, restoring needs
its write permission, and so on. Nothing module-specific lives here; each register gets
these for free by being registered.

* ``GET  /records/{type}/archived``            archived (soft-deleted) rows, newest first
* ``POST /records/{type}/{id}/restore``        bring an archived row back (409 on a clash)
* ``GET  /records/{type}/{id}/impact``         live linked rows by type, for delete dialogs
* ``GET  /records/{type}/{id}/workflow``       lifecycle state, owner, actions, history
* ``POST /records/{type}/{id}/workflow/{act}`` submit / approve / reject / revise / retire
* ``PUT  /records/{type}/{id}/workflow/owner`` name the approval owner (a user)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession
from app.schemas.common import UserRef
from app.services import (
    audit,
    dual_control,
    entity_types,
    master_data,
    record_impact,
    record_registry,
    record_workflow,
    workflow_engine,
)

router = APIRouter(prefix="/records", tags=["records"])


# ------------------------------------------------------------------ schemas ---
class ArchivedRow(BaseModel):
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    deleted_date: datetime | None = None


class ArchivedPage(BaseModel):
    items: list[ArchivedRow]
    total: int
    limit: int
    offset: int


class ImpactLink(BaseModel):
    type: str
    label: str
    count: int


class ImpactReport(BaseModel):
    entity_type: str
    id: uuid.UUID
    label: str
    links: list[ImpactLink]
    total: int


class RestoreResult(BaseModel):
    entity_type: str
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    label: str = ""


class WorkflowActionBody(BaseModel):
    reason: str | None = None


class WorkflowOwnerBody(BaseModel):
    workflow_owner_id: uuid.UUID | None = None


class WorkflowHistoryItem(BaseModel):
    action: str
    actor_id: uuid.UUID | None = None
    actor_email: str = ""
    at: datetime
    from_state: str | None = None
    to_state: str | None = None
    reason: str = ""
    via: str = ""
    summary: str = ""


class WorkflowStatusRead(BaseModel):
    entity_type: str
    id: uuid.UUID
    label: str
    state: str
    owner: UserRef | None = None
    #: The legacy free-text approval owner, shown when no user is named yet.
    owner_text: str = ""
    #: Whether this user may change the approval owner (the module's write permission).
    can_set_owner: bool = False
    allowed_actions: list[str]
    #: Why approve/reject are not offered to this user, when four-eyes removed them.
    blocked_reason: str | None = None
    #: True while an approval route owns the decision (decide it in the inbox).
    routing: bool = False
    route_instance_id: uuid.UUID | None = None
    history: list[WorkflowHistoryItem]


class TransitionRead(BaseModel):
    entity_type: str
    id: uuid.UUID
    action: str
    previous: str
    state: str
    routed: bool = False
    route_instance_id: uuid.UUID | None = None
    allowed_actions: list[str]


# ------------------------------------------------------------------ helpers ---
def _model(entity_type: str, *, soft_delete: bool = False, workflow: bool = False) -> type:
    model = record_registry.model_for(entity_type)
    label = entity_types.spec(entity_type).label
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} records have no register of their own.",
        )
    if soft_delete and not record_registry.has_soft_delete(model):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} records are not archived, so there is nothing to restore.",
        )
    if workflow and not record_registry.has_workflow(model):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} records have no approval lifecycle.",
        )
    return model


async def _load(
    db: DbSession, user: Any, entity_type: str, model: type, record_id: uuid.UUID,
    *, archived: bool | None = False,
) -> Any:
    """The record, or 404. ``archived``: False = live only, True = archived only,
    None = either."""
    record = await db.get(model, record_id)
    if record is not None and getattr(record, "tenant_id", user.tenant_id) != user.tenant_id:
        record = None
    if record is not None and archived is not None:
        if bool(getattr(record, "deleted", False)) != archived:
            record = None
    if record is None:
        label = entity_types.spec(entity_type).label
        where = " in the archive" if archived else ""
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found{where}")
    return record


def _title_column(model: type):
    cols = model.__table__.c
    for attr in record_registry.TITLE_ATTRIBUTES:
        if attr in cols:
            return getattr(model, attr)
    return None


async def _self_decision_block(db: DbSession, user: Any, entity_type: str, record: Any) -> str | None:
    """Why four-eyes stops this user deciding the record, or None."""
    required, _ = await dual_control.dual_control_required(db, entity_type, "approve")
    if not required:
        return None
    if await record_workflow.last_submitter(db, entity_type, record.id) == user.id:
        return "You submitted this record, so someone independent must approve or reject it."
    if await dual_control.maker_of(db, entity_type, record.id, record=record) == user.id:
        return "You entered this record, so someone independent must approve or reject it."
    return None


async def _actions_for(
    db: DbSession, user: Any, entity_type: str, record: Any, *, routing: bool
) -> tuple[list[str], str | None]:
    actions = record_workflow.actions_for_user(
        record.workflow_status, entity_type, user.permission_codes, routing=routing
    )
    blocked = None
    if any(a in record_workflow.DECISIONS for a in actions):
        blocked = await _self_decision_block(db, user, entity_type, record)
        if blocked:
            actions = [a for a in actions if a not in record_workflow.DECISIONS]
    return actions, blocked


# ---------------------------------------------------------- archive/restore ---
@router.get("/{entity_type}/archived", response_model=ArchivedPage)
async def list_archived(
    entity_type: str,
    db: DbSession,
    user: CurrentUser,
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ArchivedPage:
    """Archived (soft-deleted) records of one type, most recently archived first."""
    entity_types.require_read(user, entity_type)
    model = _model(entity_type, soft_delete=True)
    title_col = _title_column(model)
    has_ref = "reference" in model.__table__.c

    stmt = select(model).where(model.deleted.is_(True))
    if search and search.strip():
        like = f"%{search.strip()}%"
        conditions = []
        if title_col is not None:
            conditions.append(title_col.ilike(like))
        if has_ref:
            conditions.append(model.reference.ilike(like))
        if conditions:
            stmt = stmt.where(or_(*conditions))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = [model.deleted_date.desc().nulls_last()]
    if "updated_at" in model.__table__.c:
        order.append(model.updated_at.desc())
    rows = (await db.scalars(stmt.order_by(*order).limit(limit).offset(offset))).all()
    return ArchivedPage(
        items=[
            ArchivedRow(
                id=r.id,
                reference=record_registry.reference_of(r),
                title=record_registry.title_of(r),
                deleted_date=r.deleted_date,
            )
            for r in rows
        ],
        total=total, limit=limit, offset=offset,
    )


@router.post("/{entity_type}/{record_id}/restore", response_model=RestoreResult)
async def restore_record(
    entity_type: str, record_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> RestoreResult:
    """Bring an archived record back into its register.

    Refused with 409 when a live record now holds its unique name or reference (a
    framework of the same name installed since, say) — rename or archive that one first.
    """
    found = entity_types.require_write(user, entity_type)
    model = _model(entity_type, soft_delete=True)
    record = await _load(db, user, entity_type, model, record_id, archived=True)
    label = record_registry.label_of(record)
    try:
        async with db.begin_nested():
            record.deleted = False
            record.deleted_date = None
            await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{label} can't be restored: a live {found.label.lower()} with the same "
                "name or reference already exists. Rename or archive that one first."
            ),
        ) from None
    summary = f"Restored {found.label.lower()} {label}"
    from app.models.asset import Asset

    if isinstance(record, Asset):
        # Deleting the asset flagged its risks "Asset removed – review"; it is back.
        from app.services.risk_integrity import clear_asset_removed

        cleared = await clear_asset_removed(db, record)
        if cleared:
            summary += f"; cleared the review flag on {cleared} linked risk(s)"
    await audit.record(
        db, actor=user, action="restore", entity_type=entity_type, entity_id=record.id,
        summary=summary[:500],
    )
    return RestoreResult(
        entity_type=entity_type, id=record.id,
        reference=record_registry.reference_of(record),
        title=record_registry.title_of(record), label=label,
    )


# ------------------------------------------------------------------- impact ---
@router.get("/{entity_type}/{record_id}/impact", response_model=ImpactReport)
async def record_impact_report(
    entity_type: str, record_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> ImpactReport:
    """Live records linked to this one, counted by type — what a delete would touch."""
    entity_types.require_read(user, entity_type)
    model = _model(entity_type)
    record = await _load(db, user, entity_type, model, record_id, archived=None)
    links = await record_impact.impact(db, model, record.id)
    return ImpactReport(
        entity_type=entity_type, id=record.id, label=record_registry.label_of(record),
        links=[ImpactLink(**link) for link in links],
        total=sum(link["count"] for link in links),
    )


# ----------------------------------------------------------------- lifecycle ---
@router.get("/{entity_type}/{record_id}/workflow", response_model=WorkflowStatusRead)
async def get_workflow(
    entity_type: str, record_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> WorkflowStatusRead:
    """The record's lifecycle: state, approval owner, what *this* user may do, history."""
    found = entity_types.require_read(user, entity_type)
    model = _model(entity_type, workflow=True)
    record = await _load(db, user, entity_type, model, record_id)
    instance = await workflow_engine.instance_for(db, entity_type, record.id)
    actions, blocked = await _actions_for(db, user, entity_type, record, routing=instance is not None)
    owner_id = getattr(record, "workflow_owner_id", None)
    owners = await master_data.users_by_id(db, [owner_id])
    rows = await record_workflow.history(db, entity_type, record.id)
    return WorkflowStatusRead(
        entity_type=entity_type,
        id=record.id,
        label=record_registry.label_of(record),
        state=record_workflow.state_value(record.workflow_status),
        owner=owners.get(owner_id) if owner_id else None,
        owner_text=getattr(record, "workflow_owner", "") or "",
        can_set_owner=found.write_perm in set(user.permission_codes),
        allowed_actions=actions,
        blocked_reason=blocked,
        routing=instance is not None,
        route_instance_id=instance.id if instance is not None else None,
        history=[WorkflowHistoryItem(**r) for r in rows],
    )


@router.put("/{entity_type}/{record_id}/workflow/owner", response_model=WorkflowStatusRead)
async def set_workflow_owner(
    entity_type: str, record_id: uuid.UUID, body: WorkflowOwnerBody, db: DbSession, user: CurrentUser
) -> WorkflowStatusRead:
    """Name (or clear) the person accountable for taking the record through approval."""
    entity_types.require_write(user, entity_type)
    model = _model(entity_type, workflow=True)
    record = await _load(db, user, entity_type, model, record_id)
    await record_workflow.set_owner(db, user, record, entity_type, body.workflow_owner_id)
    return await get_workflow(entity_type, record_id, db, user)


@router.post("/{entity_type}/{record_id}/workflow/{action}", response_model=TransitionRead)
async def transition(
    entity_type: str,
    record_id: uuid.UUID,
    action: str,
    db: DbSession,
    user: CurrentUser,
    body: WorkflowActionBody | None = None,
) -> TransitionRead:
    """Move the record along its lifecycle: ``submit``, ``approve``, ``reject`` (reason
    required), ``revise`` or ``retire``. Permission, four-eyes and the transition table
    are enforced by :mod:`app.services.record_workflow`."""
    entity_types.require_read(user, entity_type)
    model = _model(entity_type, workflow=True)
    record = await _load(db, user, entity_type, model, record_id)
    result = await record_workflow.apply(
        db, user, record, entity_type, action, (body.reason if body else None)
    )
    routing = result.routed or (
        await workflow_engine.instance_for(db, entity_type, record.id) is not None
    )
    actions, _ = await _actions_for(db, user, entity_type, record, routing=routing)
    return TransitionRead(
        entity_type=entity_type, id=record.id, action=action,
        previous=result.previous, state=result.state,
        routed=result.routed, route_instance_id=result.instance_id,
        allowed_actions=actions,
    )
