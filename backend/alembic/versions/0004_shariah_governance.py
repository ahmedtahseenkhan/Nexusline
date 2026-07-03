"""Islamic / Shariah Governance module tables.

Adds Shariah rulings, Islamic products, Shariah reviews, SNC findings and the charity
(purification) ledger via metadata create-if-missing, and applies RLS. Safe on fresh
or existing databases.

Revision ID: 0004_shariah_governance
Revises: 0003_internal_audit
Create Date: 2026-07-03
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers metadata
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0004_shariah_governance"
down_revision = "0003_internal_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    for table in ("charity_disbursements", "shariah_findings", "shariah_reviews",
                  "islamic_products", "shariah_rulings"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
