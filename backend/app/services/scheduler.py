"""Lightweight in-process background scheduler.

Runs a periodic sweep across every tenant: refreshes the cross-module alert set and
emails a digest of newly raised alerts to that tenant's active users. Implemented as
a plain asyncio task (no external scheduler dependency) started/stopped by the app
lifespan. Each tenant is processed in its own RLS-scoped transaction, and one
tenant's failure never aborts the sweep.

This is what turns the notification engine from "computed on page load" into a true
time-driven reminder/chasing system (eramba's cron model).
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import system_session, tenant_session
from app.models.identity import User
from app.models.tenant import Tenant
from app.services import email, notifications

logger = logging.getLogger("nexusline.scheduler")

_task: asyncio.Task | None = None


async def run_sweep() -> dict:
    """One full pass over all tenants. Returns a small run summary (also used by the
    manual trigger endpoint)."""
    async with system_session() as db:
        tenants = [(t.id, t.name) for t in (await db.scalars(select(Tenant))).all()]

    total_new = 0
    emailed = 0
    for tenant_id, tenant_name in tenants:
        try:
            async with tenant_session(tenant_id) as db:
                new = await notifications.refresh(db, tenant_id)
                if not new:
                    continue
                total_new += len(new)
                recipients = [
                    u.email
                    for u in (await db.scalars(select(User))).all()
                    if u.email and u.is_active
                ]
                if recipients:
                    subject, html = email.render_digest(tenant_name, new)
                    if await email.send_email(recipients, subject, html):
                        emailed += 1
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Scheduler sweep failed for tenant %s", tenant_id)

    return {"tenants": len(tenants), "new_alerts": total_new, "digests_sent": emailed}


async def _loop() -> None:
    interval = max(60, settings.scheduler_interval_minutes * 60)
    logger.info("Scheduler started (every %s min)", settings.scheduler_interval_minutes)
    while True:
        try:
            summary = await run_sweep()
            logger.info("Scheduler sweep: %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(interval)


def start() -> None:
    global _task
    if not settings.scheduler_enabled or _task is not None:
        return
    _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
