"""Webhooks API — manage outbound integrations, inspect deliveries, send test events."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.webhook import Webhook, WebhookDelivery
from app.schemas.webhook import (
    WebhookCreate,
    WebhookDeliveryRead,
    WebhookRead,
    WebhookUpdate,
)
from app.services import webhooks as wh_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=[Depends(require("integration:manage"))])


async def _load(db, webhook_id: uuid.UUID) -> Webhook:
    obj = await db.scalar(select(Webhook).where(Webhook.id == webhook_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return obj


@router.get("", response_model=list[WebhookRead])
async def list_webhooks(db: DbSession) -> list[WebhookRead]:
    rows = (await db.scalars(select(Webhook).order_by(Webhook.created_at.desc()))).all()
    return [WebhookRead.model_validate(r) for r in rows]


@router.post("", response_model=WebhookRead, status_code=201)
async def create_webhook(body: WebhookCreate, db: DbSession, user: CurrentUser) -> WebhookRead:
    obj = Webhook(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return WebhookRead.model_validate(obj)


@router.patch("/{webhook_id}", response_model=WebhookRead)
async def update_webhook(webhook_id: uuid.UUID, body: WebhookUpdate, db: DbSession) -> WebhookRead:
    obj = await _load(db, webhook_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return WebhookRead.model_validate(obj)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _load(db, webhook_id))


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
