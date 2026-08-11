"""Helpers to append to the activity log / audit trail.

Two entry points, because audit has two shapes:

* :func:`record` — a business record changed, attributed to an authenticated ``User``.
  Also snapshots a version and fans the event out to subscribed webhooks.
* :func:`record_auth` — an authentication or session event. These must be written even
  when there is *no* authenticated user to attribute them to (a failed login, a lockout,
  an unknown email), which is precisely the class of event a bank examiner asks for
  first. Nothing is version-snapshotted — there is no record to snapshot.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.identity import User

# entity_type used for authentication/session events.
AUTH_ENTITY = "auth"


async def record(
    db: AsyncSession,
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    summary: str,
    changes: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=actor.tenant_id,
            actor_id=actor.id,
            actor_email=actor.email,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            changes=changes or {},
        )
    )

    # Capture a structured version snapshot of the record (best-effort).
    from app.services import versioning

    if action in ("create", "update", "review", "attest", "decide", "publish", "map_controls"):
        await versioning.capture(db, entity_type, entity_id, actor.email, action, summary)

    # Fan out the event to any subscribed webhooks (best-effort; never raises).
    from app.services import webhooks

    await webhooks.dispatch(
        db,
        entity_type=entity_type,
        action=action,
        payload={
            "event": f"{entity_type}.{action}",
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "summary": summary,
            "actor": actor.email,
            "changes": changes or {},
        },
    )


async def record_auth(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    actor_email: str,
    action: str,
    summary: str,
    changes: dict[str, Any] | None = None,
) -> None:
    """Append an authentication/session event to the trail.

    ``actor_id`` is None when the email did not resolve to a user — the attempt is still
    recorded against the tenant, since "somebody tried to log in as X" is the event that
    matters. Callers must already have the tenant GUC set on ``db`` (RLS scopes the
    insert); a login for an unknown organization has no tenant to attribute and is not
    recorded.

    Events still fan out to subscribed webhooks so a SIEM can consume them, but never
    carry credentials — ``changes`` should hold only non-sensitive context such as the
    authentication method or the reason for a failure.
    """
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,
            entity_type=AUTH_ENTITY,
            entity_id=actor_id,
            summary=summary,
            changes=changes or {},
        )
    )

    from app.services import webhooks

    await webhooks.dispatch(
        db,
        entity_type=AUTH_ENTITY,
        action=action,
        payload={
            "event": f"{AUTH_ENTITY}.{action}",
            "entity_type": AUTH_ENTITY,
            "entity_id": str(actor_id) if actor_id else None,
            "summary": summary,
            "actor": actor_email,
            "changes": changes or {},
        },
    )
