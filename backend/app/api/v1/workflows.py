"""Workflow designer: define an approval route, and watch a record travel it.

The designer writes definitions; :mod:`app.services.workflow_engine` drives them. Every
stage raises a real approval request, so nothing here duplicates approving — and a
record type with no enabled definition keeps the fixed lifecycle it has always had.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.workflow import (
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowInstanceStatus,
    WorkflowStage,
)
from app.schemas.common import Page
from app.schemas.workflow import (
    DefinitionCreate,
    DefinitionRead,
    DefinitionUpdate,
    InstanceRead,
    StageCreate,
    StageRead,
    StageUpdate,
    StartRequest,
    StartResult,
)
from app.services import audit as audit_log
from app.services import entity_types, workflow_engine

router = APIRouter(prefix="/workflows", tags=["workflows"])

_READ = Depends(require("workflow:read"))
#: Designing a route is an administrative act, not an ordinary workflow submission —
#: it decides who may approve what, so it sits with the automation permissions.
_DESIGN = Depends(require("automation:manage"))


async def _load(db: DbSession, definition_id: uuid.UUID) -> WorkflowDefinition:
    obj = await db.scalar(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.id == definition_id)
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    return obj


def _definition_read(definition: WorkflowDefinition) -> DefinitionRead:
    return DefinitionRead(
        id=definition.id, entity_type=definition.entity_type, name=definition.name,
        description=definition.description, enabled=definition.enabled,
        stage_count=definition.stage_count, created_at=definition.created_at,
        stages=[StageRead.model_validate(s) for s in definition.stages],
    )


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------
@router.get("/entity-types", response_model=list[dict], dependencies=[_READ])
async def routable_entity_types(_: CurrentUser) -> list[dict]:
    """Record types a route can be defined for — the shared entity registry."""
    return [
        {"key": key, "label": spec.label}
        for key, spec in sorted(entity_types.ENTITY_TYPES.items(), key=lambda kv: kv[1].label)
    ]


@router.get("/definitions", response_model=Page[DefinitionRead], dependencies=[_READ])
async def list_definitions(
    db: DbSession,
    entity_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DefinitionRead]:
    stmt = select(WorkflowDefinition)
    if entity_type:
        stmt = stmt.where(WorkflowDefinition.entity_type == entity_type)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(
            stmt.order_by(WorkflowDefinition.entity_type, WorkflowDefinition.name)
            .limit(limit).offset(offset)
        )
    ).all()
    return Page(
        items=[_definition_read(d) for d in rows], total=total, limit=limit, offset=offset
    )


@router.post("/definitions", response_model=DefinitionRead, status_code=201, dependencies=[_DESIGN])
async def create_definition(
    body: DefinitionCreate, db: DbSession, user: CurrentUser
) -> DefinitionRead:
    if entity_types.ENTITY_TYPES.get(body.entity_type) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{body.entity_type}' is not a routable record type",
        )
    definition = WorkflowDefinition(
        tenant_id=user.tenant_id,
        entity_type=body.entity_type,
        name=body.name,
        description=body.description,
    )
    db.add(definition)
    await db.flush()
    for index, stage in enumerate(body.stages, start=1):
        payload = stage.model_dump()
        # The list order is the stage order; an explicit index only overrides it.
        payload["order_index"] = payload.get("order_index") or index
        db.add(WorkflowStage(tenant_id=user.tenant_id, definition_id=definition.id, **payload))
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="workflow_definition",
        entity_id=definition.id,
        summary=f"Created workflow '{definition.name}' for {definition.entity_type}",
    )
    return _definition_read(await _load(db, definition.id))


@router.patch("/definitions/{definition_id}", response_model=DefinitionRead, dependencies=[_DESIGN])
async def update_definition(
    definition_id: uuid.UUID, body: DefinitionUpdate, db: DbSession, user: CurrentUser
) -> DefinitionRead:
    """Rename, describe, or switch a route on.

    Enabling one route disables any other for the same record type: two enabled routes
    would leave "which approval applied?" unanswerable, which is precisely the question
    an auditor asks.
    """
    definition = await _load(db, definition_id)
    data = body.model_dump(exclude_unset=True)

    if data.get("enabled"):
        if not definition.stages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A route with no stages cannot be enabled — add at least one stage",
            )
        others = (
            await db.scalars(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.entity_type == definition.entity_type,
                    WorkflowDefinition.id != definition.id,
                    WorkflowDefinition.enabled.is_(True),
                )
            )
        ).all()
        for other in others:
            other.enabled = False

    for name, value in data.items():
        setattr(definition, name, value)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="workflow_definition",
        entity_id=definition.id,
        summary=f"Updated workflow '{definition.name}'",
        changes={k: str(v) for k, v in data.items()},
    )
    return _definition_read(await _load(db, definition_id))


@router.delete("/definitions/{definition_id}", status_code=204, dependencies=[_DESIGN])
async def delete_definition(
    definition_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> None:
    definition = await _load(db, definition_id)
    live = await db.scalar(
        select(func.count())
        .select_from(WorkflowInstance)
        .where(
            WorkflowInstance.definition_id == definition_id,
            WorkflowInstance.status == WorkflowInstanceStatus.in_progress,
        )
    )
    if live:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{live} record(s) are still routing through this workflow — "
                "disable it instead, so those approvals can finish"
            ),
        )
    name = definition.name
    await db.delete(definition)
    await audit_log.record(
        db, actor=user, action="delete", entity_type="workflow_definition",
        entity_id=definition_id, summary=f"Deleted workflow '{name}'",
    )


# ------------------------------------------------------------------ stages ---
@router.post(
    "/definitions/{definition_id}/stages",
    response_model=DefinitionRead, status_code=201, dependencies=[_DESIGN],
)
async def add_stage(
    definition_id: uuid.UUID, body: StageCreate, db: DbSession, user: CurrentUser
) -> DefinitionRead:
    definition = await _load(db, definition_id)
    payload = body.model_dump()
    # 0 (the default) means append to the end of the route.
    payload["order_index"] = payload.get("order_index") or (len(definition.stages) + 1)
    db.add(WorkflowStage(tenant_id=user.tenant_id, definition_id=definition_id, **payload))
    await db.flush()
    return _definition_read(await _load(db, definition_id))


@router.patch("/stages/{stage_id}", response_model=StageRead, dependencies=[_DESIGN])
async def update_stage(stage_id: uuid.UUID, body: StageUpdate, db: DbSession) -> StageRead:
    stage = await db.scalar(select(WorkflowStage).where(WorkflowStage.id == stage_id))
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage not found")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(stage, name, value)
    await db.flush()
    return StageRead.model_validate(stage)


@router.delete("/stages/{stage_id}", status_code=204, dependencies=[_DESIGN])
async def delete_stage(stage_id: uuid.UUID, db: DbSession) -> None:
    stage = await db.scalar(select(WorkflowStage).where(WorkflowStage.id == stage_id))
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage not found")
    await db.delete(stage)


# --------------------------------------------------------------- instances ---
@router.post("/start", response_model=StartResult, dependencies=[Depends(require("workflow:write"))])
async def start_workflow(
    body: StartRequest, db: DbSession, user: CurrentUser
) -> StartResult:
    """Send a record down its route.

    Returns ``started=False`` when the record type has no enabled route — which is the
    platform's default and not an error, so callers can offer the button unconditionally.
    """
    entity_types.require_write(user, body.entity_type)
    instance = await workflow_engine.start(
        db,
        tenant_id=user.tenant_id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        entity_label=body.entity_label,
        link=body.link,
        requested_by=user.id,
        requested_by_email=user.email,
        record_owner_email=body.record_owner_email,
    )
    if instance is None:
        return StartResult(
            started=False,
            reason=f"No approval route is enabled for {body.entity_type}",
        )
    await audit_log.record(
        db, actor=user, action="submit", entity_type=body.entity_type, entity_id=body.entity_id,
        summary=f"Started approval route for {body.entity_label or body.entity_type}",
    )
    return StartResult(started=True, instance=InstanceRead.model_validate(instance))


@router.get("/instance", response_model=InstanceRead | None, dependencies=[_READ])
async def get_instance(
    entity_type: str, entity_id: uuid.UUID, db: DbSession
) -> InstanceRead | None:
    """The live route for one record, for the progress strip. ``null`` when not routing."""
    instance = await workflow_engine.instance_for(db, entity_type, entity_id)
    return InstanceRead.model_validate(instance) if instance else None


@router.get("/instances", response_model=Page[InstanceRead], dependencies=[_READ])
async def list_instances(
    db: DbSession,
    entity_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[InstanceRead]:
    stmt = select(WorkflowInstance)
    if entity_type:
        stmt = stmt.where(WorkflowInstance.entity_type == entity_type)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(
            stmt.order_by(WorkflowInstance.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return Page(
        items=[InstanceRead.model_validate(r) for r in rows],
        total=total, limit=limit, offset=offset,
    )


@router.post(
    "/instances/{instance_id}/cancel",
    response_model=InstanceRead,
    dependencies=[Depends(require("workflow:write"))],
)
async def cancel_instance(
    instance_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> InstanceRead:
    instance = await db.scalar(
        select(WorkflowInstance).where(WorkflowInstance.id == instance_id)
    )
    if instance is None:
        raise HTTPException(status_code=404, detail="Workflow instance not found")
    if instance.status != WorkflowInstanceStatus.in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This route already finished as {instance.status.value}",
        )
    await workflow_engine.cancel(db, instance)
    await audit_log.record(
        db, actor=user, action="cancel", entity_type=instance.entity_type,
        entity_id=instance.entity_id,
        summary=f"Cancelled the approval route for {instance.entity_label}",
    )
    return InstanceRead.model_validate(instance)
