"""Custom Fields — per-tenant, per-model field definitions and an EAV value store so
each org can extend any module's records with their own fields."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import CustomFieldType

# Models that may be extended with custom fields (the UI dropdown).
CUSTOM_FIELD_MODELS = [
    "risk", "control", "asset", "vendor", "policy", "incident", "project",
    "goal", "exception", "processing_activity", "continuity_plan", "framework",
]


class CustomField(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "custom_fields"

    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    field_type: Mapped[CustomFieldType] = mapped_column(
        SAEnum(CustomFieldType, name="custom_field_type"),
        default=CustomFieldType.text,
        nullable=False,
    )
    options: Mapped[str] = mapped_column(Text, default="")  # one option per line (select)
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    help_text: Mapped[str] = mapped_column(String(255), default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CustomFieldValue(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "custom_field_values"
    __table_args__ = (
        UniqueConstraint("custom_field_id", "entity_id", name="uq_cfv_field_entity"),
    )

    custom_field_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
