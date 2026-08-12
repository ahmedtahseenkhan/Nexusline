"""Fortnightly review cycle, and month-level audit-plan scheduling.

Two small additions that together make "audit this twice a month" expressible:

* ``review_frequency`` gains ``fortnightly``. The finest cycle available before this was
  monthly, so a bank testing a critical control or unit every two weeks had to record it
  as monthly and schedule the second pass by hand.
* ``audit_plan_items.planned_month`` — an optional month within the planned quarter, so a
  plan committing to two audits of the same unit in one month can say so, and the
  assurance calendar places the line on that month rather than mid-quarter.

``ALTER TYPE ... ADD VALUE IF NOT EXISTS`` is legal inside a transaction on PostgreSQL
12+ provided the new value is not *used* in the same transaction — it is not; nothing
here writes 'fortnightly'.

DDL lives in ``app.db.schema_patches`` so this migration and the ``create_all`` boot path
apply exactly the same statements.

Revision ID: 0023_fortnightly_and_plan_month
Revises: 0022_workflow_designer
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.db.schema_patches import fortnightly_ddl_statements

revision = "0023_fortnightly_and_plan_month"
down_revision = "0022_workflow_designer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in fortnightly_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE audit_plan_items DROP COLUMN IF EXISTS planned_month")
    # PostgreSQL cannot remove a value from an enum type. Rebuilding `review_frequency`
    # would rewrite every table that uses it (risks, controls, assets, policies, vendors,
    # auditable units and more) and would fail outright if any row still reads
    # 'fortnightly'. The spare value is harmless, so it is deliberately left in place.
