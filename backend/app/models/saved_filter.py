"""Saved Filters — named, reusable condition-sets over a model. Personal or shared,
evaluated with the same field/operator engine as dynamic status rules."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SavedFilter(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "saved_filters"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    match_mode: Mapped[str] = mapped_column(String(8), default="all")  # all | any
    # list of {field, operator, value}
    conditions: Mapped[list] = mapped_column(JSON, default=list)

    shared: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    owner_email: Mapped[str] = mapped_column(String(255), default="")
