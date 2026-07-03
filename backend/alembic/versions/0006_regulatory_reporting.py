"""Regulatory incident reporting: reportability fields on incidents + reports table.

Adds ``is_reportable`` / ``regulator`` columns to ``incidents`` (idempotent) and the
``regulatory_reports`` table via metadata create-if-missing, then applies RLS. Safe on
fresh or existing databases.

Revision ID: 0006_regulatory_reporting
Revises: 0005_operational_risk
Create Date: 2026-07-03
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers metadata
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0006_regulatory_reporting"
down_revision = "0005_operational_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS is_reportable BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS regulator VARCHAR(64) NOT NULL DEFAULT ''")
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS regulatory_reports")
    op.execute("ALTER TABLE incidents DROP COLUMN IF EXISTS is_reportable")
    op.execute("ALTER TABLE incidents DROP COLUMN IF EXISTS regulator")
