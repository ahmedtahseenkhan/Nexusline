"""Helper to append to the activity log / audit trail."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.identity import User


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
