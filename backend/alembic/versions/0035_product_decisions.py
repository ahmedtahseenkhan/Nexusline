"""Product decisions (plan §11): licence grace and read-only mode, 10-year retention, MFA for
every password user, reporting currency with exchange rates, Basel level-2 event types,
approval before attestation, reviewed-only test counts, ISO 27002 theme classifications.

Workstream schema lives in ``app.db.phase5.<stream>``.

Revision ID: 0035_product_decisions
Revises: 0034_product_review_phase4
Create Date: 2026-09-17
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.core.database import Base
from app.db.phase5 import all_ddl_statements, all_tables

revision = "0035_product_decisions"
down_revision = "0034_product_review_phase4"
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
