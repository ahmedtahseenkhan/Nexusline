"""Auth hardening + maker-checker + file storage: incremental changes since baseline.

Adds the new tables (stored_files, approval_actions, ldap_configs) via metadata
create-if-missing, the new columns on ``users`` and ``approval_requests`` via
idempotent ``ADD COLUMN IF NOT EXISTS``, and re-applies RLS so the new tenant-scoped
tables are covered. Safe to run whether a database is fresh (baseline already created
everything) or was migrated before these features landed.

Revision ID: 0002_auth_hardening
Revises: 0001_baseline
Create Date: 2026-07-03
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers metadata
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0002_auth_hardening"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_USER_COLUMNS = [
    "ADD COLUMN IF NOT EXISTS auth_source VARCHAR(16) NOT NULL DEFAULT 'local'",
    "ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ADD COLUMN IF NOT EXISTS mfa_secret VARCHAR(64) NOT NULL DEFAULT ''",
    "ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0",
    "ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ",
    "ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ",
]


def upgrade() -> None:
    bind = op.get_bind()
    # New tables (no-op if the baseline create_all already made them).
    Base.metadata.create_all(bind=bind, checkfirst=True)

    for clause in _USER_COLUMNS:
        op.execute(f"ALTER TABLE users {clause}")
    op.execute(
        "ALTER TABLE approval_requests "
        "ADD COLUMN IF NOT EXISTS required_approvals INTEGER NOT NULL DEFAULT 1"
    )

    # Ensure RLS policies exist on the newly added tenant-scoped tables.
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    for col in ("auth_source", "mfa_enabled", "mfa_secret", "failed_login_attempts",
                "locked_until", "password_changed_at"):
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE approval_requests DROP COLUMN IF EXISTS required_approvals")
    op.execute("DROP TABLE IF EXISTS ldap_configs")
    op.execute("DROP TABLE IF EXISTS approval_actions")
    op.execute("DROP TABLE IF EXISTS stored_files")
