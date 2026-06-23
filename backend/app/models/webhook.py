"""Webhooks — outbound HTTP integrations fired on record events (audit pipeline)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Webhook(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "webhooks"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    secret: Mapped[str] = mapped_column(String(255), default="")
    # CSV of entity types to subscribe to, or "*" for all.
    events: Mapped[str] = mapped_column(String(512), default="*")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def matches(self, entity_type: str) -> bool:
        if not self.enabled:
            return False
        subs = {s.strip() for s in self.events.split(",") if s.strip()}
        return "*" in subs or entity_type in subs


class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "webhook_deliveries"

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(128), default="")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str] = mapped_column(String(512), default="")
    payload: Mapped[str] = mapped_column(Text, default="")
