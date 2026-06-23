"""Dashboard widgets — tenant-wide KPI dashboard configuration for the report builder."""
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DashboardWidget(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "dashboard_widgets"

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    viz: Mapped[str] = mapped_column(String(16), default="number")  # number | bar | donut
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
