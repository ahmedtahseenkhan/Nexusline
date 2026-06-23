"""Org provisioning: permission catalog sync + tenant/role/admin creation.

Shared by the public ``/auth/register-org`` endpoint and the first-run seeder so
both create organizations identically.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_session_tenant
from app.core.permissions import DEFAULT_ROLES, PERMISSION_CATALOG
from app.core.security import hash_password
from app.models.identity import Permission, Role, User
from app.models.tenant import Tenant


async def sync_permission_catalog(db: AsyncSession) -> dict[str, Permission]:
    """Ensure every catalog permission exists (global table). Returns code -> row."""
    existing = {p.code: p for p in (await db.scalars(select(Permission))).all()}
    for code, description in PERMISSION_CATALOG.items():
        perm = existing.get(code)
        if perm is None:
            perm = Permission(code=code, description=description)
            db.add(perm)
            existing[code] = perm
        elif perm.description != description:
            perm.description = description
    await db.flush()
    return existing


async def create_organization(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    admin_email: str,
    admin_password: str,
    admin_full_name: str = "",
) -> tuple[Tenant, User]:
    """Create a tenant with default roles and an initial Admin user.

    Must run inside a transaction. Switches the tenant GUC to the new org so the
    RLS WITH CHECK clauses accept the role/user inserts.
    """
    perms = await sync_permission_catalog(db)

    tenant = Tenant(name=name, slug=slug)
    db.add(tenant)
    await db.flush()  # assigns tenant.id

    # Switch RLS context to the new tenant before inserting tenant-scoped rows.
    await set_session_tenant(db, tenant.id)

    admin_role: Role | None = None
    for role_name, (description, codes) in DEFAULT_ROLES.items():
        role = Role(
            tenant_id=tenant.id,
            name=role_name,
            description=description,
            is_system=True,
        )
        role.permissions = [perms[c] for c in codes]
        db.add(role)
        if role_name == "Admin":
            admin_role = role

    admin = User(
        tenant_id=tenant.id,
        email=admin_email,
        full_name=admin_full_name,
        hashed_password=hash_password(admin_password),
    )
    if admin_role is not None:
        admin.roles = [admin_role]
    db.add(admin)
    await db.flush()
    return tenant, admin
