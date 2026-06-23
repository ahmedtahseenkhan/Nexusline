"""Notifications — cross-module in-app alerts (overdue/expiring/gaps) plus a per-user
last-seen marker for unread counts."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import NotificationCategory


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "notifications"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[NotificationCategory] = mapped_column(
        SAEnum(NotificationCategory, name="notification_category"),
        default=NotificationCategory.info,
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    link: Mapped[str] = mapped_column(String(255), default="")  # frontend path
    # Stable key so re-scanning an unchanged alert does not duplicate it.
    dedup_key: Mapped[str] = mapped_column(String(255), index=True, default="")


class NotificationView(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Per-user 'notifications read up to' marker."""

    __tablename__ = "notification_views"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
