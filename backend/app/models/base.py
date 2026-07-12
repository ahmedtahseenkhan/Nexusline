"""Shared column mixins for all models."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = [
    "Base",
    "UUIDPrimaryKeyMixin",
    "TimestampMixin",
    "TenantMixin",
    "SoftDeleteMixin",
    "WorkflowMixin",
    "WorkflowState",
]


class WorkflowState(str, enum.Enum):
    """eramba record approval lifecycle (`workflow_status`)."""

    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    retired = "retired"


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantMixin:
    """Adds the tenant foreign key that RLS policies filter on.

    Every tenant-scoped table includes this. The column is listed in
    ``app/db/rls.py`` so a policy is generated for it.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class SoftDeleteMixin:
    """eramba soft-delete envelope. List queries should filter ``deleted == False``."""

    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowMixin:
    """eramba approval lifecycle (`workflow_status` / `workflow_owner`)."""

    workflow_status: Mapped[WorkflowState] = mapped_column(
        SAEnum(WorkflowState, name="workflow_state"),
        default=WorkflowState.draft,
        nullable=False,
    )
    workflow_owner: Mapped[str] = mapped_column(String(200), default="")
