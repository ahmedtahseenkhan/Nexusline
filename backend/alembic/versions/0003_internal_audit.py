"""Internal Audit module tables.

Adds the audit universe / engagements / procedures / findings tables via metadata
create-if-missing and applies RLS to them. Safe on fresh (baseline already made
them) or existing databases.

Revision ID: 0003_internal_audit
Revises: 0002_auth_hardening
Create Date: 2026-07-03
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers metadata
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0003_internal_audit"
down_revision = "0002_auth_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    for table in ("audit_findings", "audit_procedures", "audit_engagements", "auditable_units"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
