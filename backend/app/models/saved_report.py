"""Saved Reports — a named report definition: subject, filters, columns, sort.

A report is a *question* the organisation asks repeatedly — "critical risks in Digital
Banking, by owner", "controls not tested this year", "reportable incidents this quarter"
— and the point of saving one is that the question is asked the same way every month,
by whoever is on shift, and answered from live data. The definition is stored; the
rows never are, so a saved report can never go stale or leak a snapshot of data the
reader no longer has permission to see.

Personal or shared, like saved filters. The ``definition`` JSON is validated against the
subject registry in ``services.report_builder`` on every run, so a column or filter
retired from the registry degrades to "ignored", not to a crash on a report somebody
saved a year ago.
"""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SavedReport(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "saved_reports"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    #: Registry key — "risks", "controls", "incidents".
    subject: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: {filters: {key: value}, columns: [key], sort_by, sort_dir, include_details}
    definition: Mapped[dict] = mapped_column(JSON, default=dict)

    shared: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    owner_email: Mapped[str] = mapped_column(String(255), default="")
