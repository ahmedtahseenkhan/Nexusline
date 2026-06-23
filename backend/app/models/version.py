"""Structured version audit — a point-in-time snapshot of a record's column values,
captured on each mutation, enabling field-level history diffs and one-click restore."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RecordVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "record_versions"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    action: Mapped[str] = mapped_column(String(32), default="update")
    actor_email: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(String(512), default="")
    # Full column snapshot of the record at this version (JSON-serialised scalars).
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
