"""Webhooks API — manage outbound integrations, inspect deliveries, send test events."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.webhook import Webhook, WebhookDelivery
from app.schemas.common import Page
from app.schemas.webhook import (
    WebhookCreate,
    WebhookDeliveryRead,
    WebhookRead,
    WebhookUpdate,
)
from app.services import audit as audit_log
from app.services import webhooks as wh_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=[Depends(require("integration:manage"))])

_WEBHOOK_SORTABLE = {
    "name": Webhook.name,
    "url": Webhook.url,
    "events": Webhook.events,
    "last_status": Webhook.last_status,
    "created_at": Webhook.created_at,
}


async def _load(db, webhook_id: uuid.UUID) -> Webhook:
    obj = await db.scalar(select(Webhook).where(Webhook.id == webhook_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return obj


@router.get("", response_model=Page[WebhookRead])
async def list_webhooks(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[WebhookRead]:
    stmt = select(Webhook)
    if search:
        stmt = stmt.where(Webhook.name.ilike(f"%{search}%") | Webhook.url.ilike(f"%{search}%"))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _WEBHOOK_SORTABLE, default=Webhook.created_at)
    else:
        stmt = stmt.order_by(Webhook.created_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[WebhookRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=WebhookRead, status_code=201)
async def create_webhook(body: WebhookCreate, db: DbSession, user: CurrentUser) -> WebhookRead:
    obj = Webhook(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    # A webhook streams record data off-platform, so its lifecycle is audited.
    await audit_log.record(
        db, actor=user, action="create", entity_type="webhook", entity_id=obj.id,
        summary=f"Created webhook '{obj.name}' → {obj.url}", changes={"events": obj.events},
    )
    return WebhookRead.model_validate(obj)


@router.patch("/{webhook_id}", response_model=WebhookRead)
async def update_webhook(
    webhook_id: uuid.UUID, body: WebhookUpdate, db: DbSession, user: CurrentUser
) -> WebhookRead:
    obj = await _load(db, webhook_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    await audit_log.record(
        db, actor=user, action="update", entity_type="webhook", entity_id=obj.id,
        summary=f"Updated webhook '{obj.name}'", changes=changes,
    )
    return WebhookRead.model_validate(obj)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, webhook_id)
    await audit_log.record(
        db, actor=user, action="delete", entity_type="webhook", entity_id=obj.id,
        summary=f"Deleted webhook '{obj.name}' → {obj.url}",
    )
    await db.delete(obj)


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryRead])
async def list_deliveries(webhook_id: uuid.UUID, db: DbSession) -> list[WebhookDeliveryRead]:
    await _load(db, webhook_id)
    rows = (
        await db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(50)
        )
    ).all()
    return [WebhookDeliveryRead.model_validate(r) for r in rows]


@router.post("/{webhook_id}/test", response_model=WebhookDeliveryRead)
async def test_webhook(webhook_id: uuid.UUID, db: DbSession, user: CurrentUser) -> WebhookDeliveryRead:
    hook = await _load(db, webhook_id)
    delivery = await wh_service._deliver(
        db,
        hook,
        "ping.test",
        {"event": "ping.test", "message": "Test delivery from Nexusline", "actor": user.email,
         "timestamp": datetime.now(timezone.utc).isoformat()},
    )
    await db.flush()
    await db.refresh(delivery)
    return WebhookDeliveryRead.model_validate(delivery)
