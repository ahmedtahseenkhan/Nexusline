"""Webhook dispatch — best-effort outbound HTTP with HMAC signing and delivery logging.

Dispatch runs in-request after the triggering write is flushed. Failures never raise
to the caller (a broken integration must not break a GRC operation); every attempt is
recorded in ``webhook_deliveries``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import Webhook, WebhookDelivery

_TIMEOUT = 5.0


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _deliver(db: AsyncSession, hook: Webhook, event: str, payload: dict[str, Any]) -> WebhookDelivery:
    body = json.dumps(payload, default=str).encode()
    headers = {"Content-Type": "application/json", "X-Nexusline-Event": event}
    if hook.secret:
        headers["X-Nexusline-Signature"] = _sign(hook.secret, body)

    status_code: int | None = None
    success = False
    error = ""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(hook.url, content=body, headers=headers)
            status_code = resp.status_code
            success = 200 <= resp.status_code < 300
    except Exception as exc:  # noqa: BLE001 - integrations must fail soft
        error = str(exc)[:500]

    hook.last_status = status_code
    hook.last_delivered_at = datetime.now(timezone.utc)
    delivery = WebhookDelivery(
        tenant_id=hook.tenant_id,
        webhook_id=hook.id,
        event=event,
        status_code=status_code,
        success=success,
        error=error,
        payload=body.decode(),
    )
    db.add(delivery)
    return delivery


async def dispatch(db: AsyncSession, entity_type: str, action: str, payload: dict[str, Any]) -> int:
    """Fire all enabled webhooks subscribed to ``entity_type``. Returns count dispatched."""
    hooks = (await db.scalars(select(Webhook).where(Webhook.enabled.is_(True)))).all()
    targets = [h for h in hooks if h.matches(entity_type)]
    if not targets:
        return 0
    event = f"{entity_type}.{action}"
    for hook in targets:
        await _deliver(db, hook, event, payload)
    await db.flush()
    return len(targets)
