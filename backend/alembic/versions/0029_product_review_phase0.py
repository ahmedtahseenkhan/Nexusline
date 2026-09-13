"""Product review, phase 0: the columns behind "nothing contradicts itself".

* ``risks.needs_review`` / ``review_reason`` — a risk whose asset was deleted, or whose
  residual contradicts its inherent score, is flagged for a person to look at instead of
  being archived by a cleanup button.
* ``ck_risk_residual_le_inherent`` — controls can only reduce a risk. Added ``NOT VALID``
  so the upgrade never fails on a register that already holds a bad row.
* ``frameworks.kind`` — ISO 31000 and ISO 27005 are guidance, not obligations, and leave
  the compliance percentage.
* ``attestations.statement`` / ``scope`` / ``confirmed_by_id`` / ``confirmed_at`` — what
  was certified, and an optional independent second signature.
* ``users.mfa_grace_until`` — when mandatory MFA stops being optional for this user.

Duplicate frameworks and dashboard tiles are merged, and their unique indexes created,
by ``app.db.data_repairs`` on the next start: that needs tenant-scoped ORM work a
migration cannot do under row-level security.

Revision ID: 0029_product_review_phase0
Revises: 0028_scenario_control_references
Create Date: 2026-09-11
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.db.schema_patches import PHASE0_COLUMNS, phase0_ddl_statements

revision = "0029_product_review_phase0"
down_revision = "0028_scenario_control_references"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in phase0_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE risks DROP CONSTRAINT IF EXISTS ck_risk_residual_le_inherent")
    op.execute("DROP INDEX IF EXISTS ix_risks_needs_review")
    op.execute("DROP INDEX IF EXISTS uq_frameworks_tenant_name")
    op.execute("ALTER TABLE dashboard_widgets DROP CONSTRAINT IF EXISTS uq_dashboard_widgets_metric")
    op.execute("DROP INDEX IF EXISTS uq_dashboard_widgets_metric")
    for table, col, _ddl, _default in reversed(PHASE0_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
