"""Dynamic Status Rules — admin-defined conditions that auto-apply a colored label to
records of a model when a field matches (e.g. risk score >= 15 -> 'Above Tolerance')."""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class StatusRule(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "status_rules"

    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(16), nullable=False)  # eq/ne/gt/gte/lt/lte/contains/overdue/is_true/is_false/not_empty
    value: Mapped[str] = mapped_column(String(255), default="")
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#dc2626")
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
