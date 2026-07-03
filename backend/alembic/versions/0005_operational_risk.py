"""Operational Risk module tables (RCSA, KRIs, Basel loss database).

Adds the operational-risk tables via metadata create-if-missing and applies RLS.
Safe on fresh or existing databases.

Revision ID: 0005_operational_risk
Revises: 0004_shariah_governance
Create Date: 2026-07-03
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers metadata
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0005_operational_risk"
down_revision = "0004_shariah_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    for table in ("kri_measurements", "key_risk_indicators", "rcsa_risks",
                  "rcsa_assessments", "loss_events"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
