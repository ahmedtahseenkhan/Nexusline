"""Append-only activity log / audit trail."""
from __future__ import annotations

import uuid

from sqlalchemy import String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # create/update/delete/...
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    changes: Mapped[dict] = mapped_column(JSONB, default=dict)
