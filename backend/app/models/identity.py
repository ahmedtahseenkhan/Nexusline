"""Users, roles and permissions (RBAC).

- ``permissions`` is a global catalog (not tenant-scoped).
- ``roles`` and ``users`` are tenant-scoped (each org gets its own seeded roles).
- ``user_roles`` / ``role_permissions`` are association tables, accessed only via
  relationships from the RLS-protected parents.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        Uuid,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Global permission catalog, e.g. ``risk:write``."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class Role(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_role_tenant_name"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, lazy="selectin"
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    @property
    def role_names(self) -> list[str]:
        return [r.name for r in self.roles]

    @property
    def permission_codes(self) -> list[str]:
        codes: set[str] = set()
        for role in self.roles:
            for perm in role.permissions:
                codes.add(perm.code)
        return sorted(codes)
