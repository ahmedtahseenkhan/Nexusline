"""Audit provenance: who performed the audit, and the report they issued.

Adds ``audit_type`` (internal / external statutory / regulatory / certification),
``auditor_firm``, ``report_reference`` and ``report_date`` to ``audit_engagements``.

The point is that every audit a bank is subject to shares one register and one findings
pipeline. Without the discriminator, "how many SBP inspection findings are still open?"
has no answer short of a separate spreadsheet per auditor — which is exactly what the
platform is meant to replace. Existing rows default to ``internal``, which is what the
module held before this migration.

Column and enum DDL lives in ``app.db.schema_patches`` so this migration and the
``create_all`` boot path apply exactly the same statements.

Revision ID: 0020_audit_provenance
Revises: 0019_sla_engine
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.db.schema_patches import audit_type_ddl_statements

revision = "0020_audit_provenance"
down_revision = "0019_sla_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in audit_type_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_engagements_audit_type")
    for column in ("audit_type", "auditor_firm", "report_reference", "report_date"):
        op.execute(f"ALTER TABLE audit_engagements DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TYPE IF EXISTS audit_type")
