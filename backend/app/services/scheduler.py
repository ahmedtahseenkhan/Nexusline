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
                await _escalate_tat_breaches(db, tenant_name, new)
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Scheduler sweep failed for tenant %s", tenant_id)

    return {"tenants": len(tenants), "new_alerts": total_new, "digests_sent": emailed}


async def _escalate_tat_breaches(db, tenant_name: str, new_alerts: list) -> None:
    """Email the escalation role when a turnaround time is newly breached.

    Notifications are tenant-wide rather than addressed to individuals, so escalation is
    delivered by email — which is also what a bank means by it: the line above the owner
    is told, in writing, and only once per breach because the digest is built from
    *newly created* alerts.
    """
    from app.models.enums import Severity
    from app.services import sla

    breaches = [n for n in new_alerts if (n.dedup_key or "").startswith("tat-breach:")]
    if not breaches:
        return

    by_recipient: dict[str, list] = {}
    for alert in breaches:
        severity = _severity_in(alert.body) or Severity.medium
        for address in await sla.escalation_recipients(db, alert.entity_type, severity):
            by_recipient.setdefault(address, []).append(alert)

    for address, alerts in by_recipient.items():
        subject, html = email.render_digest(f"{tenant_name} — TAT escalation", alerts)
        try:
            await email.send_email([address], subject, html)
        except Exception:  # noqa: BLE001 - one bad address must not stop the sweep
            logger.exception("TAT escalation email failed for %s", address)


def _severity_in(body: str):
    """Recover the severity the breach body names, so the right policy row is used."""
    from app.models.enums import Severity

    lowered = (body or "").lower()
    for severity in (Severity.critical, Severity.high, Severity.medium, Severity.low):
        if f"{severity.value} turnaround" in lowered:
            return severity
    return None


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
