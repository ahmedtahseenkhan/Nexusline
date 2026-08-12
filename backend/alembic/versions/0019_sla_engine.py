"""Turnaround-time (TAT) clock: policy table plus the derived window on four registers.

* ``sla_policies`` — target days, early-warning threshold and escalation role per
  (record type, severity). Absent rows fall back to shipped defaults, so a fresh
  installation measures something sensible before anyone opens the settings screen.
* ``tat_due_date`` / ``tat_breached_at`` on ``risks``, ``issues``, ``audit_findings``
  and ``incidents``, with an index on the due date because both the dashboard widget
  and the breach scan filter on it.

There is deliberately no ``tat_start_date``: the clock starts when the record was
raised, which ``created_at`` already records, and a third column would be a copy that
can drift. Column DDL lives in ``app.db.schema_patches`` so this migration and the
``create_all`` boot path apply exactly the same statements.

Revision ID: 0019_sla_engine
Revises: 0018_risk_scenario_templates
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. sla_policies)
from app.core.database import Base
from app.db.rls import rls_ddl_statements
from app.db.schema_patches import tat_ddl_statements

revision = "0019_sla_engine"
down_revision = "0018_risk_scenario_templates"
branch_labels = None
depends_on = None

_TAT_TABLES = ("risks", "issues", "audit_findings", "incidents")


def upgrade() -> None:
    # 1. TAT columns on the four pre-existing registers (create_all cannot ALTER).
    for statement in tat_ddl_statements():
        op.execute(statement)
    # 2. sla_policies.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    # 3. Tenant isolation, including the new table.
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sla_policies")
    for table in _TAT_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_tat_due")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tat_due_date")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tat_breached_at")
