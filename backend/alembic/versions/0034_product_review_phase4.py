"""Product review, phase 4: differentiate for real.

Workstream schema lives in ``app.db.phase4.<stream>``: board and assurance workspaces,
typed crosswalks, continuous control monitoring, and the questionnaire engine.

Revision ID: 0034_product_review_phase4
Revises: 0033_product_review_recheck
Create Date: 2026-09-17
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.core.database import Base
from app.db.phase4 import all_ddl_statements, all_tables

revision = "0034_product_review_phase4"
down_revision = "0033_product_review_recheck"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[t] for t in all_tables()]
    if tables:
        Base.metadata.create_all(bind, tables=tables)
    for statement in all_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    # Additive and idempotent; restore from backup to go back.
    pass
