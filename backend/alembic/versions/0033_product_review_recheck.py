"""Product review re-check (17 September): finish the last findings.

* ``requirements.reference_sort_key`` — clause references sort naturally (A.5.2 < A.5.10).
* ``risk_scenario_templates.asset_kinds`` — scenarios apply to the kinds of asset they fit,
  so a firewall no longer gets money-laundering risks.
* ``risk_settings.review_cadence`` — a risk's rating sets its longest review interval.
* ``tenant_settings.mfa_required_roles`` — the organisation chooses which roles need MFA.
* ``outsourcing_arrangements.substitutability`` / ``concentration_level``.
* ``risk_proposals.source_risk_id`` — candidates rebuilt from pre-queue generated risks.

Revision ID: 0033_product_review_recheck
Revises: 0032_product_review_phase3
Create Date: 2026-09-17
"""
from __future__ import annotations

from alembic import op

from app.db.schema_patches import RECHECK_COLUMNS, RECHECK_FK_COLUMNS, recheck_ddl_statements

revision = "0033_product_review_recheck"
down_revision = "0032_product_review_phase3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in recheck_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_requirements_reference_sort_key")
    for table, col, _target, _od in reversed(RECHECK_FK_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table, col, _ddl in reversed(RECHECK_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
