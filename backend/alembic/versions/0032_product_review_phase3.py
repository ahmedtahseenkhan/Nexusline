"""Product review, phase 3: differentiate.

* ``risk_proposals`` (+ ``risk_proposal_assets``) — generated risks queue for a person to
  accept, merge or reject instead of flooding the register; ``risks.parent_id`` /
  ``risks.level`` give an enterprise → category → scenario hierarchy.
* ``notifications.user_id`` / ``role_name`` — alerts addressed to a person or a role;
  ``action_tokens`` — single-use links to approve or reject from an email.
* ``tenant_settings.enabled_modules`` / ``onboarding_completed_at`` — an organisation
  switches modules on within its licence during onboarding.
* ``board_packs`` and ``committees.board_pack_days_before`` — generated committee packs.
* ``connectors.ingest_token_hash`` — monitoring tools push evidence and test results.

Revision ID: 0032_product_review_phase3
Revises: 0031_product_review_phase2
Create Date: 2026-09-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.core.database import Base
from app.db.schema_patches import PHASE3_COLUMNS, PHASE3_FK_COLUMNS, phase3_ddl_statements

revision = "0032_product_review_phase3"
down_revision = "0031_product_review_phase2"
branch_labels = None
depends_on = None

NEW_TABLES = ("risk_proposals", "risk_proposal_assets", "action_tokens", "board_packs")


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[t] for t in NEW_TABLES])
    for statement in phase3_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_risks_level")
    for table, col, _target, _od in reversed(PHASE3_FK_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table, col, _ddl in reversed(PHASE3_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
