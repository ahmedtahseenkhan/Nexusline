"""Saved import mappings — how one organisation's spreadsheet columns feed our fields.

A bank's risk register, asset inventory or finding list keeps the same column names
every quarter. Working the mapping out once and saving it here turns every subsequent
upload into a one-click job, and keeps successive loads consistent (the same source
column always lands in the same field, so re-imports are comparable).

``mapping`` is ``{their header: our canonical Column.header}``; ``custom_field_mapping``
is ``{their header: custom_fields.id}`` for columns the org keeps but we have no native
field for.
"""
from __future__ import annotations

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ImportProfile(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "import_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "resource", "name", name="uq_import_profile_name"),
    )

    resource: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    custom_field_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_email: Mapped[str] = mapped_column(String(255), default="")
