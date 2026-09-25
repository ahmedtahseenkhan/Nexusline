"""Webhook dispatch — best-effort outbound HTTP with HMAC signing and delivery logging.

``dispatch`` queues the event on the request's session and delivers it only once that
transaction commits, in the background with its own session: a rolled-back change never
announces itself, and a slow or unreachable receiver can no longer hold every save (and
its pooled connection) for the HTTP timeout. Failures never raise to the caller (a
broken integration must not break a GRC operation); every attempt is recorded in
``webhook_deliveries``.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import Webhook, WebhookDelivery

_TIMEOUT = 5.0
_PENDING = "webhook_pending"
_HOOKED = "webhook_hooked"
_tasks: set[asyncio.Task] = set()  # strong refs so running deliveries aren't collected
logger = logging.getLogger("nexusline.webhooks")


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
    """Queue the event for every enabled webhook subscribed to ``entity_type``; it is
    delivered after ``db`` commits. Returns the number of webhooks queued."""
    hooks = (await db.scalars(select(Webhook).where(Webhook.enabled.is_(True)))).all()
    targets = [h for h in hooks if h.matches(entity_type)]
    if not targets:
        return 0
    event = f"{entity_type}.{action}"
    pending = db.info.get(_PENDING)
    if pending is None:
        pending = db.info[_PENDING] = []
        _deliver_after_commit(db)
    # Remember the savepoint the event was raised in: if it rolls back, so does the event.
    savepoint = db.sync_session.get_nested_transaction()
    pending.extend(_Queued(savepoint, (h.tenant_id, h.id, event, payload)) for h in targets)
    return len(targets)


class _Queued(tuple):
    """A queued delivery tagged with the savepoint (or None) it was raised inside."""

    def __new__(cls, savepoint, job):
        return super().__new__(cls, (savepoint, job))


def _inside(tx, savepoint) -> bool:
    while tx is not None:
        if tx is savepoint:
            return True
        tx = tx.parent
    return False


def _deliver_after_commit(db: AsyncSession) -> None:
    """Hook the session once: deliver the queue when the outermost transaction commits,
    drop it when that transaction rolls back. A savepoint rolling back (one bad row of an
    import) must not discard the events of the rows that did save."""
    sync = db.sync_session
    if sync.info.get(_HOOKED):
        return
    sync.info[_HOOKED] = True

    def on_commit(session) -> None:
        # after_commit also fires when a savepoint is released; deliver only once the
        # outermost transaction — the request's own — has committed.
        if session.in_nested_transaction():
            return
        jobs = [job for _, job in session.info.pop(_PENDING, None) or ()]
        if jobs:
            task = asyncio.get_running_loop().create_task(_deliver_jobs(jobs))
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)

    def on_rollback(session, previous_transaction) -> None:
        if previous_transaction.parent is None:
            session.info.pop(_PENDING, None)
            return
        pending = session.info.get(_PENDING)
        if pending and previous_transaction.nested:
            pending[:] = [q for q in pending if not _inside(q[0], previous_transaction)]

    sa_event.listen(sync, "after_commit", on_commit)
    sa_event.listen(sync, "after_soft_rollback", on_rollback)


async def _deliver_jobs(jobs: list[tuple[uuid.UUID, uuid.UUID, str, dict[str, Any]]]) -> None:
    from app.core.database import tenant_session

    by_tenant: dict[uuid.UUID, list[tuple[uuid.UUID, str, dict[str, Any]]]] = {}
    for tenant_id, hook_id, event, payload in jobs:
        by_tenant.setdefault(tenant_id, []).append((hook_id, event, payload))
    for tenant_id, items in by_tenant.items():
        try:
            async with tenant_session(tenant_id) as db:
                for hook_id, event, payload in items:
                    hook = await db.get(Webhook, hook_id)
                    if hook is not None and hook.enabled:
                        await _deliver(db, hook, event, payload)
        except Exception:  # noqa: BLE001 - background; never surfaces to a user
            logger.exception("Webhook delivery failed for tenant %s", tenant_id)
