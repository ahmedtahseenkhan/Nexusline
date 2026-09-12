"""Governed lookup lists: the values a field may take, managed per organisation.

Replaces free text wherever a field names a category rather than describing something:
risk category, incident type, regulator, country. One table keyed by ``key`` (the list)
so a new list needs seed rows, not a new table and router. ``parent_id`` gives a
two-level list where one is needed (risk category L1 → L2).

``value`` is the stable machine key and ``label`` what people read; renaming a label
never breaks a record that points at the row. Rows are deactivated, not deleted, once
anything uses them.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


#: Every governed list: key -> (name people read, whether existing free text may seed it).
#: A list that may be seeded from text turns each distinct value already typed into the
#: field into a lookup row on the first start after the upgrade, so an organisation's own
#: categories carry over; ``country`` only matches, because "Karachi, PK" is not a country.
LOOKUP_LISTS: dict[str, tuple[str, bool]] = {
    "risk_category": ("Risk category", True),
    "control_classification": ("Control classification", True),
    "issue_category": ("Issue category", True),
    "incident_type": ("Incident type", True),
    "incident_classification": ("Incident classification", True),
    "regulator": ("Regulator", True),
    "kri_category": ("KRI category", True),
    "policy_category": ("Policy category", True),
    "legal_category": ("Legal category", True),
    "vendor_category": ("Third-party category", True),
    "country": ("Country", False),
    "root_cause_category": ("Root-cause category", False),
}


class Lookup(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "lookups"
    __table_args__ = (UniqueConstraint("tenant_id", "key", "value", name="uq_lookups_key_value"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookups.id", ondelete="SET NULL"), nullable=True, index=True
    )
