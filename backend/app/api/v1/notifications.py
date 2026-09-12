"""Notifications API — in-app alert feed with a per-user unread count."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.notification import Notification, NotificationView
from app.schemas.notification import NotificationList, NotificationRead
from app.services import email as email_service
from app.services import notifications as notif_service

router = APIRouter(prefix="/notifications", tags=["notifications"])

_ORDER = {"critical": 0, "warning": 1, "info": 2}


@router.get("", response_model=NotificationList)
async def list_notifications(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> NotificationList:
    # Refresh the alert feed for this tenant (dedup + group + auto-resolve), then return
    # one page of it, most urgent first. The unseen count and the per-category tallies
    # are taken over the whole feed so the bell and the page headline stay right.
    await notif_service.refresh(db, user.tenant_id)

    rows = list((await db.scalars(select(Notification))).all())
    rows.sort(key=lambda n: (_ORDER.get(n.category.value, 3), -n.created_at.timestamp()))

    view = await db.scalar(select(NotificationView).where(NotificationView.user_id == user.id))
    last_seen = view.last_seen_at if view else None

    def is_seen(n: Notification) -> bool:
        return last_seen is not None and n.created_at <= last_seen

    unseen = sum(1 for n in rows if not is_seen(n))
    counts = Counter(n.category.value for n in rows)
    items: list[NotificationRead] = []
    for n in rows[offset: offset + limit]:
        nr = NotificationRead.model_validate(n)
        nr.seen = is_seen(n)
        items.append(nr)
    return NotificationList(
        items=items, unseen_count=unseen, total=len(rows), limit=limit, offset=offset,
        counts=dict(counts),
    )


@router.post("/seen", status_code=204)
async def mark_seen(db: DbSession, user: CurrentUser) -> None:
    now = datetime.now(timezone.utc)
    view = await db.scalar(select(NotificationView).where(NotificationView.user_id == user.id))
    if view is None:
        db.add(NotificationView(tenant_id=user.tenant_id, user_id=user.id, last_seen_at=now))
    else:
        view.last_seen_at = now
    await db.flush()


class EmailStatus(BaseModel):
    smtp_configured: bool
    sent: bool
    recipient: str


@router.post("/test-email", response_model=EmailStatus, dependencies=[Depends(require("role:write"))])
async def send_test_email(user: CurrentUser) -> EmailStatus:
    """Send a test email to the current admin to verify SMTP configuration.

    In dev (no SMTP configured) this returns ``sent=false`` and the message is logged
    rather than delivered — the endpoint still confirms the pipeline is wired.
    """
    html = (
        '<div style="font-family:system-ui,Arial,sans-serif">'
        "<h2>NexusLine SMTP test</h2>"
        "<p>If you can read this, outbound email is working.</p></div>"
    )
    sent = await email_service.send_email(user.email, "NexusLine SMTP test", html)
    return EmailStatus(
        smtp_configured=email_service.is_configured(), sent=sent, recipient=user.email
    )
