"""Lightweight in-process background scheduler.

Runs a periodic sweep across every tenant: lapses risk acceptances whose approval has
run out, refreshes the cross-module alert set, emails a digest of newly raised alerts to
that tenant's active users, and purges records archived for longer than the tenant's
retention window (``TenantSettings.retention_days``, default 90). Implemented as a plain asyncio task (no external
scheduler dependency) started/stopped by the app lifespan. Each tenant is processed in
its own RLS-scoped transaction, and one tenant's failure never aborts the sweep.

This is what turns the notification engine from "computed on page load" into a true
time-driven reminder/chasing system (eramba's cron model).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, delete, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import system_session, tenant_session
from app.models.identity import User
from app.models.tenant import Tenant
from app.services import email, notifications, risk_acceptance

logger = logging.getLogger("nexusline.scheduler")

_task: asyncio.Task | None = None


async def run_sweep() -> dict:
    """One full pass over all tenants. Returns a small run summary (also used by the
    manual trigger endpoint)."""
    async with system_session() as db:
        tenants = [(t.id, t.name) for t in (await db.scalars(select(Tenant))).all()]

    total_new = 0
    emailed = 0
    lapsed_acceptances = 0
    purged = 0
    for tenant_id, tenant_name in tenants:
        # Housekeeping runs in its own transaction first, so a purge problem can never
        # hold back the alerts and digests below (and vice versa).
        try:
            async with tenant_session(tenant_id) as db:
                purged += sum((await purge_archived(db, tenant_id)).values())
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Retention purge failed for tenant %s", tenant_id)
        try:
            async with tenant_session(tenant_id) as db:
                # State first, alerts second: lapsing an acceptance puts its risk back in
                # the register, and the scan that follows must see that new state or the
                # digest would describe a register one sweep out of date.
                lapsed = await risk_acceptance.expire_lapsed(db, tenant_id)
                lapsed_acceptances += lapsed.expired
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

    return {
        "tenants": len(tenants),
        "new_alerts": total_new,
        "digests_sent": emailed,
        "acceptances_expired": lapsed_acceptances,
        "records_purged": purged,
    }


# ------------------------------------------------------------ retention purge ---
#: Registers whose archived rows are purged after the retention window.
RETENTION_ENTITY_TYPES: tuple[str, ...] = (
    "risk", "control", "asset", "issue", "policy", "incident", "vendor",
)
DEFAULT_RETENTION_DAYS = 90
#: Rows purged per register per sweep — a large backlog drains over several sweeps
#: rather than holding one long transaction.
PURGE_BATCH = 500


def retention_cutoff(now: datetime, retention_days: int | None) -> datetime:
    """Rows archived before this instant are due for purging. Pure.

    No setting means the default window; a window below one day is treated as one day,
    so a mistyped 0 can never purge a record the moment it is archived.
    """
    days = DEFAULT_RETENTION_DAYS if retention_days is None else max(1, int(retention_days))
    return now - timedelta(days=days)


def purge_candidates(model: type, cutoff: datetime, tenant_id: uuid.UUID | None = None) -> Select:
    """Archived rows of ``model`` older than ``cutoff``. Pure (builds the statement).

    Only rows that are archived *and* carry an archive date are eligible: a row marked
    deleted without a date (older code paths) is never purged, because nobody can say
    how long it has been in the archive.
    """
    stmt = select(model).where(
        model.deleted.is_(True),
        model.deleted_date.is_not(None),
        model.deleted_date < cutoff,
    )
    if tenant_id is not None:
        stmt = stmt.where(model.tenant_id == tenant_id)
    return stmt.order_by(model.deleted_date.asc()).limit(PURGE_BATCH)


async def purge_archived(db, tenant_id: uuid.UUID, now: datetime | None = None) -> dict[str, int]:
    """Hard-delete this tenant's records archived longer than its retention window.

    Each row is deleted in its own SAVEPOINT: a row something still references through
    a restricting foreign key is skipped (and logged) rather than failing the batch. One
    summary audit entry per register that had anything purged or kept. Returns
    ``{entity_type: rows purged}``.
    """
    from app.models.settings import TenantSettings
    from app.services import audit, record_registry

    days = await db.scalar(
        select(TenantSettings.retention_days).where(TenantSettings.tenant_id == tenant_id)
    )
    window = DEFAULT_RETENTION_DAYS if days is None else max(1, int(days))
    cutoff = retention_cutoff(now or datetime.now(timezone.utc), window)

    out: dict[str, int] = {}
    for entity_type in RETENTION_ENTITY_TYPES:
        model = record_registry.model_for(entity_type)
        if model is None or not record_registry.has_soft_delete(model):
            continue
        rows = (await db.scalars(purge_candidates(model, cutoff, tenant_id))).all()
        if not rows:
            continue
        labels = [(row.id, record_registry.label_of(row)) for row in rows]
        for row in rows:
            db.expunge(row)  # deleted by statement below; nothing stale may re-flush
        done: list[str] = []
        kept: list[str] = []
        for row_id, label in labels:
            try:
                async with db.begin_nested():
                    await db.execute(
                        delete(model)
                        .where(model.id == row_id)
                        .execution_options(synchronize_session=False)
                    )
                done.append(label)
            except IntegrityError:
                kept.append(label)
                logger.warning(
                    "Retention purge kept %s %s: still referenced by another record",
                    entity_type, row_id,
                )
        out[entity_type] = len(done)
        type_label = record_registry.type_label(entity_type, model).lower()
        summary = (
            f"Purged {len(done)} archived {type_label} record(s) older than {window} days"
            + (f"; kept {len(kept)} still referenced elsewhere" if kept else "")
        )
        await audit.record_system(
            db, tenant_id=tenant_id, action="purge", entity_type=entity_type, entity_id=None,
            summary=summary[:500],
            changes={
                "retention_days": window,
                "cutoff": cutoff.isoformat(),
                "purged": len(done),
                "kept": len(kept),
                "purged_records": done[:100],
                "kept_records": kept[:100],
            },
        )
    return out


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
