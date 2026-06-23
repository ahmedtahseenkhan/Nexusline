"""Tenant (organization) model. This table is NOT tenant-scoped — it is the registry
of tenants itself, so it carries no RLS policy."""
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
