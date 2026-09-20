"""Phase 4: workspaces and period snapshots.

* **MetricSnapshot** — one figure (appetite for a category, compliance for a framework,
  a KRI's value …) as it stood on a date. Written at each month end by the scheduler
  (``services/snapshots.py``) and once, where the records allow, reconstructed for past
  quarter ends. Trends on the board home and board packs for a past period read these,
  so a number shown for June is the number June had, not today's.
* **UserWorkspacePreference** — the page a person chose to start on (My Work, the
  dashboard, the assurance workspace or the board home). No row = the default for their
  line of defence.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class MetricSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "as_of", "key", "dimension", name="uq_metric_snapshot"),
    )

    as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: What is measured, e.g. ``appetite.category``, ``compliance.framework``, ``kri.value``.
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Which one of it: a category, framework or KRI id; blank for an organisation total.
    dimension: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: scheduler | backfill | manual
    source: Mapped[str] = mapped_column(String(16), default="scheduler", nullable=False)


class UserWorkspacePreference(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "user_workspace_preferences"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_workspace_preference"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: my_work | dashboard | assurance | board
    workspace: Mapped[str] = mapped_column(String(24), nullable=False)
