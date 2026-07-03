"""Collaboration layer — polymorphic comments, tags and attachments that attach to
any record via (entity_type, entity_id). Shared across every module."""
from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Comment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "comments"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    author_email: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A tenant tag library entry."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tag_tenant_name"),)

    name: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#2563eb")


class EntityTag(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Assignment of a tag to a record."""

    __tablename__ = "entity_tags"
    __table_args__ = (
        UniqueConstraint("tag_id", "entity_type", "entity_id", name="uq_entitytag"),
    )

    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)


class Attachment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A document/evidence link attached to a record (URL-based)."""

    __tablename__ = "attachments"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), default="")
    kind: Mapped[str] = mapped_column(String(32), default="link")  # link | document
    added_by_email: Mapped[str] = mapped_column(String(255), default="")


class StoredFile(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """An uploaded binary file attached to any record via (entity_type, entity_id).

    The blob lives on the object store (``app.services.storage``); this row holds its
    metadata and the ``storage_key`` that resolves back to the bytes for download.
    """

    __tablename__ = "stored_files"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_by_email: Mapped[str] = mapped_column(String(255), default="")
