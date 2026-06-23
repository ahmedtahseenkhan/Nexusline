"""Notifications API — in-app alert feed with a per-user unread count."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.notification import Notification, NotificationView
from app.schemas.notification import NotificationList, NotificationRead
from app.services import notifications as notif_service

router = APIRouter(prefix="/notifications", tags=["notifications"])

_ORDER = {"critical": 0, "warning": 1, "info": 2}


@router.get("", response_model=NotificationList)
async def list_notifications(db: DbSession, user: CurrentUser) -> NotificationList:
    # Refresh the alert feed for this tenant (dedup + auto-resolve), then return it.
    await notif_service.refresh(db, user.tenant_id)

    rows = list((await db.scalars(select(Notification))).all())
    rows.sort(key=lambda n: (_ORDER.get(n.category.value, 3), -n.created_at.timestamp()))

    view = await db.scalar(select(NotificationView).where(NotificationView.user_id == user.id))
    last_seen = view.last_seen_at if view else None

    items: list[NotificationRead] = []
    unseen = 0
    for n in rows:
        seen = last_seen is not None and n.created_at <= last_seen
        if not seen:
            unseen += 1
        nr = NotificationRead.model_validate(n)
        nr.seen = seen
        items.append(nr)
    return NotificationList(items=items, unseen_count=unseen)


@router.post("/seen", status_code=204)
async def mark_seen(db: DbSession, user: CurrentUser) -> None:
    now = datetime.now(timezone.utc)
    view = await db.scalar(select(NotificationView).where(NotificationView.user_id == user.id))
    if view is None:
        db.add(NotificationView(tenant_id=user.tenant_id, user_id=user.id, last_seen_at=now))
    else:
        view.last_seen_at = now
    await db.flush()
