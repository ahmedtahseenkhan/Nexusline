"""Lightweight in-process background scheduler.

Runs a periodic sweep across every tenant: lapses risk acceptances whose approval has
run out, refreshes the cross-module alert set, emails each active user a digest of what
is new *for them*, and purges records archived for longer than the tenant's retention
window (``TenantSettings.retention_days``, default 90). Implemented as a plain asyncio
task (no external scheduler dependency) started/stopped by the app lifespan. Each tenant
is processed in its own RLS-scoped transaction, and one tenant's failure never aborts
the sweep.

**Digests (phase 3).** Each user is e-mailed only the alerts addressed to them, to a
role they hold, or to everyone — never everyone's everything — that were raised since
their last digest, each linking to its record (``settings.app_base_url``). An approval
the user may decide carries Approve / Reject links with a fresh single-use token
(``services/action_tokens.py``). A turnaround-time breach reaches the SLA policy's
escalation role through that role's members' digests (the subject says so). Users with
nothing new get nothing. The "last digest" marker is the audit entry each sent digest
writes (``notification_digest`` / ``digest``, one per person), which is also the trail
of who was told what, and when; a user who has never had one starts from
:data:`FIRST_DIGEST_LOOKBACK_SWEEPS` sweeps back.

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
from app.models.tenant import Tenant
from app.services import action_tokens, audit, board_pack, email, notifications, risk_acceptance

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
    board_packs = 0
    snapshot_rows = 0
    ccm_runs = 0
    questionnaire_actions = 0
    for tenant_id, tenant_name in tenants:
        # Housekeeping runs in its own transaction first, so a purge problem can never
        # hold back the alerts and digests below (and vice versa).
        try:
            async with tenant_session(tenant_id) as db:
                purged += sum((await purge_archived(db, tenant_id)).values())
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Retention purge failed for tenant %s", tenant_id)
        # Period snapshots (phase 4B): at each month end, and once reconstructed for the
        # last four quarter ends. Before board packs, so a pack sees today's snapshot.
        try:
            from app.services import snapshots

            async with tenant_session(tenant_id) as db:
                snapshot_rows += await snapshots.run_due(db, tenant_id)
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Period snapshot failed for tenant %s", tenant_id)
        # Board packs due for upcoming committee meetings (phase 3), in their own
        # transaction: a pack that cannot be built is kept as a failed pack, never lost,
        # and never holds back the alerts below. Audited as the system actor.
        try:
            async with tenant_session(tenant_id) as db:
                board_packs += len(await board_pack.generate_due_packs(db, tenant_id))
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Board pack generation failed for tenant %s", tenant_id)
        # Continuous control monitoring (phase 4D): run the tests that are due, each in its
        # own transaction under an advisory lock, and raise overdue alerts. Before the
        # alerts and digests, so a failure found now reaches today's digest.
        try:
            from app.services import ccm_runner

            ccm = await ccm_runner.run_due_for_tenant(tenant_id)
            ccm_runs += ccm.runs
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Continuous monitoring runs failed for tenant %s", tenant_id)
        # Questionnaires (phase 4E): reminders before the due date, overdue alerts and
        # recurring re-issues, in their own transaction and before the digests so an
        # overdue event reaches today's digest.
        try:
            from app.services import questionnaire_workflow

            async with tenant_session(tenant_id) as db:
                q_due = await questionnaire_workflow.run_due(db, tenant_id, tenant_name)
                questionnaire_actions += sum(q_due.values())
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Questionnaire reminders failed for tenant %s", tenant_id)
        try:
            async with tenant_session(tenant_id) as db:
                # State first, alerts second: lapsing an acceptance puts its risk back in
                # the register, and the scan that follows must see that new state or the
                # digest would describe a register one sweep out of date.
                lapsed = await risk_acceptance.expire_lapsed(db, tenant_id)
                lapsed_acceptances += lapsed.expired
                new = await notifications.refresh(db, tenant_id)
                total_new += len(new)
                emailed += await send_digests(db, tenant_id, tenant_name)
                await action_tokens.purge_stale(db)
        except Exception:  # noqa: BLE001 - isolate per-tenant failures
            logger.exception("Scheduler sweep failed for tenant %s", tenant_id)

    return {
        "tenants": len(tenants),
        "new_alerts": total_new,
        "digests_sent": emailed,
        "acceptances_expired": lapsed_acceptances,
        "records_purged": purged,
        "board_packs_generated": board_packs,
        "snapshot_rows": snapshot_rows,
        "ccm_runs": ccm_runs,
        "questionnaire_actions": questionnaire_actions,
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


# ------------------------------------------------------------------ digests ---
#: A user who has never had a digest gets what was raised this many sweeps back, so the
#: first per-person digest after an upgrade doesn't re-send alerts everyone was already
#: e-mailed about.
FIRST_DIGEST_LOOKBACK_SWEEPS = 2
#: A digest never reaches further back than this; older alerts are in the feed and My Work.
MAX_DIGEST_LOOKBACK = timedelta(days=7)
#: The audit entry a sent digest writes — one per person, the "last digest" marker.
DIGEST_ENTITY = "notification_digest"
DIGEST_ACTION = "digest"
_DIGEST_RANK = {"critical": 0, "warning": 1, "info": 2}


def digest_for(rows, *, user_id, role_names, since) -> list:
    """The notifications to e-mail one person. Pure.

    Visible to them (addressed to them, to one of their roles, or to everyone), raised
    after ``since``, one per alert condition (the row addressed to them personally when
    they were reached twice), most urgent first."""
    roles = set(role_names)
    picked: dict = {}
    for n in rows:
        if since is not None and n.created_at <= since:
            continue
        if not notifications.is_visible(n, user_id, roles):
            continue
        key = notifications.base_key(n.dedup_key)
        current = picked.get(key)
        if current is None or (n.user_id == user_id and current.user_id != user_id):
            picked[key] = n
    return sorted(
        picked.values(),
        key=lambda n: (_DIGEST_RANK.get(getattr(n.category, "value", n.category), 3), n.created_at),
    )


def escalations_in(rows, user_id) -> int:
    """How many turnaround-time breaches reached this user through a role (the SLA
    escalation), rather than as the record's owner. Pure."""
    return sum(
        1 for n in rows
        if notifications.family_of(n.dedup_key or "") == "tat-breach" and n.user_id != user_id and n.role_name
    )


def digest_since(last: datetime | None, now: datetime, interval_minutes: int) -> datetime:
    """Where one person's next digest starts. Pure."""
    floor = now - MAX_DIGEST_LOOKBACK
    if last is None:
        last = now - timedelta(minutes=max(1, interval_minutes) * FIRST_DIGEST_LOOKBACK_SWEEPS)
    return max(last, floor)


async def last_digests(db) -> dict:
    """``{user id: when their last digest was sent}``, from the digest audit entries."""
    from sqlalchemy import func

    from app.models.audit import AuditLog

    rows = await db.execute(
        select(AuditLog.entity_id, func.max(AuditLog.created_at))
        .where(AuditLog.entity_type == DIGEST_ENTITY, AuditLog.action == DIGEST_ACTION)
        .group_by(AuditLog.entity_id)
    )
    return {uid: at for uid, at in rows.all() if uid is not None}


async def send_digests(db, tenant_id: uuid.UUID, tenant_name: str, now: datetime | None = None) -> int:
    """E-mail each active user their own digest; returns how many were dispatched.

    Pending approvals the reader may decide carry Approve / Reject links with a fresh
    token (minted only when SMTP is configured — nobody receives the dev fallback). A
    digest is recorded (the marker for the next one) only when it was actually sent,
    so a failed send is retried with the next sweep's."""
    from sqlalchemy.orm import selectinload

    from app.models.approval import ApprovalRequest
    from app.models.enums import ApprovalStatus
    from app.models.notification import Notification

    now = now or datetime.now(timezone.utc)
    directory = await notifications.load_directory(db)
    people = [u for u in directory.users.values() if u.is_active and u.email]
    if not people:
        return 0
    last = await last_digests(db)
    since = {u.id: digest_since(last.get(u.id), now, settings.scheduler_interval_minutes) for u in people}
    rows = (
        await db.scalars(select(Notification).where(Notification.created_at > min(since.values())))
    ).all()
    if not rows:
        return 0

    approvals: dict = {}
    pending_ids = {
        n.entity_id for n in rows
        if n.entity_id is not None and notifications.family_of(n.dedup_key or "") == "approval-pending"
    }
    if pending_ids and email.is_configured():
        approvals = {
            a.id: a for a in (
                await db.scalars(
                    select(ApprovalRequest)
                    .where(ApprovalRequest.id.in_(pending_ids), ApprovalRequest.status == ApprovalStatus.pending)
                    .options(selectinload(ApprovalRequest.actions))
                )
            ).all()
        }

    # Phase 4: route stages assigned to a role pass the same eligibility rule as the
    # Approvals page, so a digest never carries a link its reader would be refused.
    gates = await notifications.load_stage_gates(db, list(approvals.values()), directory) if approvals else {}
    sent = 0
    for person in people:
        mine = digest_for(rows, user_id=person.id, role_names=person.roles, since=since[person.id])
        if not mine:
            continue
        pairs = []
        if approvals and action_tokens.enabled():
            permissions = directory.permissions_of(person.id)
            for n in mine:
                approval = approvals.get(n.entity_id) if notifications.family_of(n.dedup_key) == "approval-pending" else None
                if approval is None or notifications.approval_refusal(
                    approval, user_id=person.id, email=person.email, permissions=permissions,
                    voted_ids=[a.actor_id for a in approval.actions],
                    role_names=person.roles, stage=gates.get(approval.id),
                ) is not None:
                    continue
                token = await action_tokens.issue_token(
                    db, tenant_id=tenant_id, user_id=person.id, approval_id=approval.id, now=now,
                )
                pairs.append((approval.id, token))
        subject, html, text = email.render_user_digest(
            tenant_name, mine, recipient_name=person.full_name or person.email,
            decisions=action_tokens.links_for(pairs), escalations=escalations_in(mine, person.id),
        )
        if await email.send_email([person.email], subject, html, text):
            sent += 1
            await audit.record_system(
                db, tenant_id=tenant_id, action=DIGEST_ACTION, entity_type=DIGEST_ENTITY,
                entity_id=person.id,
                summary=f"Emailed {person.email} a digest of {len(mine)} alert(s)"[:500],
                changes={"count": len(mine), "notifications": [str(n.id) for n in mine[:50]],
                         "decision_links": len(pairs)},
            )
    await db.flush()
    return sent


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
