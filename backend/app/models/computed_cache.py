"""A per-organisation cache for figures that are expensive to compute and cheap to check.

One row per ``(tenant, key)``: the computed ``value``, the ``fingerprint`` of the data it
was computed from, and when. A reader recomputes the fingerprint (a handful of counts and
latest-change times) and uses the row only while it still matches, so nothing has to hook
every write path to invalidate it. First user: the "strong clause suggestions waiting"
count (``services.clause_suggestions.pending_strong_cached``, phase 4).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class TenantComputedCache(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "tenant_computed_cache"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_tenant_computed_cache_key"),)

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
