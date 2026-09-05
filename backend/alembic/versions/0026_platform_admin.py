"""Deployment-operator flag: ``users.is_platform_admin``.

Until now an organisation could only be created by seed script or by the self-service
``POST /auth/register-org``, so in practice every deployment ran on the single org the
seeder made — which is exactly why multi-tenancy had never been exercised with more than
one. This flag is what the operator console checks.

It is a column rather than a permission code on purpose. Permissions are rows in the
tenant-scoped ``roles`` table, so an organisation's own admin can mint a role carrying
any code they please; that is fine while every code only unlocks something inside their
own org, and not fine the moment one unlocks provisioning. The flag sits outside that
blast radius, and it grants no read access to any tenant's business data — the platform
endpoints never open a session scoped to somebody else's organisation.

Defaults to false, so applying this to a live database changes nobody's access. An
existing deployment promotes its first operator deliberately, with a one-line UPDATE.

Revision ID: 0026_platform_admin
Revises: 0025_risk_segment_scoping
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.db.schema_patches import platform_admin_ddl_statements

revision = "0026_platform_admin"
down_revision = "0025_risk_segment_scoping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in platform_admin_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_platform_admin")
