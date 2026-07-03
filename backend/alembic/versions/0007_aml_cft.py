"""AML/CFT module tables (screening, STR/SAR, AML risk assessments).

Adds the AML/CFT tables via metadata create-if-missing and applies RLS. Safe on fresh
or existing databases.

Revision ID: 0007_aml_cft
Revises: 0006_regulatory_reporting
Create Date: 2026-07-04
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers metadata
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0007_aml_cft"
down_revision = "0006_regulatory_reporting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    for table in ("screening_cases", "suspicious_activity_reports", "aml_risk_assessments"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
