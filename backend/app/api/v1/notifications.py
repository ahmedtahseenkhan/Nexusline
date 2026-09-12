"""Notifications API — the signed-in user's alert feed with a per-user unread count.

``GET /notifications`` returns what this user should see: alerts addressed to them,
alerts addressed to a role they hold, and alerts addressed to everyone (the record named
nobody the scanner could resolve). ``?mine=true`` narrows it to the first two. A user
who is reached twice for one condition (as the owner and as a member of the escalation
role, say) sees it once — the row addressed to them personally.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.notification import Notification, NotificationView
from app.schemas.notification import NotificationList, NotificationRead
from app.services import email as email_service
from app.services import notifications as notif_service

router = APIRouter(prefix="/notifications", tags=["notifications"])

_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _feed_ids(user_id, role_names, *, mine: bool):
    """Ids of the rows this user sees — one per alert condition (``dedup_key`` without
    its recipient), preferring the row addressed to the user personally, then the
    oldest (so a condition's unread state doesn't flip between rows)."""
    condition = func.split_part(Notification.dedup_key, notif_service.RECIPIENT_SEPARATOR, 1)
    personal_first = case((Notification.user_id == user_id, 0), else_=1)
    return (
        select(Notification.id)
        .where(notif_service.visible_clause(user_id, role_names, mine=mine))
        .distinct(condition)
        .order_by(condition, personal_first, Notification.created_at.asc())
    ).subquery()


@router.get("", response_model=NotificationList)
async def list_notifications(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    mine: bool = Query(default=False, description="Only alerts addressed to me or to one of my roles"),
    fresh: bool = Query(
        default=True,
        description="Re-scan before answering. The bell passes false: it re-scans at most once a minute.",
    ),
) -> NotificationList:
    # Refresh the alert feed for this tenant (dedup + address + group + auto-resolve),
    # then return one page of what this user sees, most urgent first. The unseen count
    # and the per-category tallies are over the user's whole feed, so the bell and the
    # page headline stay right.
    if fresh:
        await notif_service.refresh(db, user.tenant_id)
    else:
        await notif_service.refresh_if_stale(db, user.tenant_id)

    roles = list(user.role_names)
    ids = _feed_ids(user.id, roles, mine=mine)
    in_feed = Notification.id.in_(select(ids.c.id))

    view = await db.scalar(select(NotificationView).where(NotificationView.user_id == user.id))
    last_seen = view.last_seen_at if view else None

    counts = {
        getattr(cat, "value", cat): int(n)
        for cat, n in (
            await db.execute(select(Notification.category, func.count()).where(in_feed).group_by(Notification.category))
        ).all()
    }
    total = sum(counts.values())

    def unseen_where(*extra):
        stmt = select(func.count()).select_from(Notification).where(in_feed, *extra)
        return stmt.where(Notification.created_at > last_seen) if last_seen is not None else stmt

    unseen = int(await db.scalar(unseen_where()) or 0)
    mine_ids = _feed_ids(user.id, roles, mine=True)
    unseen_mine = int(await db.scalar(
        unseen_where(Notification.id.in_(select(mine_ids.c.id)))
    ) or 0)

    rank = case(
        *[(Notification.category == cat, pos) for cat, pos in _ORDER.items()], else_=len(_ORDER)
    )
    rows = (
        await db.scalars(
            select(Notification).where(in_feed)
            .order_by(rank, Notification.created_at.desc(), Notification.id)
            .offset(offset).limit(limit)
        )
    ).all()

    items: list[NotificationRead] = []
    for n in rows:
        nr = NotificationRead.model_validate(n)
        nr.seen = last_seen is not None and n.created_at <= last_seen
        nr.audience = notif_service.audience_of(n, user.id)
        items.append(nr)
    return NotificationList(
        items=items, unseen_count=unseen, unseen_mine=unseen_mine, total=total, limit=limit,
        offset=offset, counts=counts, mine=mine,
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
