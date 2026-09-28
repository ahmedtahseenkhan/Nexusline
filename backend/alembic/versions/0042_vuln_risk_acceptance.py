"""Risk acceptance of a vulnerability finding: request and decision.

A finding reached ``risk_accepted`` by anyone who could edit it typing the status in.
Accepting a vulnerability's risk instead of fixing it is a risk acceptance, requested by
one person with a reason and an end date and decided by another (dual control
``vuln_finding / accept_risk``, ``api.v1.vulnerability``). These columns hold the open
request and the decision on it; the history is the activity trail. The DDL is shared
with the create_all boot path (``schema_patches.vuln_acceptance_ddl_statements``) and is
idempotent.

Revision ID: 0042_vuln_risk_acceptance
Revises: 0041_capital_snapshot
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

from app.db.schema_patches import (
    VULN_ACCEPTANCE_COLUMNS,
    VULN_ACCEPTANCE_USER_COLUMNS,
    vuln_acceptance_ddl_statements,
)

revision = "0042_vuln_risk_acceptance"
down_revision = "0041_capital_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in vuln_acceptance_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_vuln_findings_acceptance_status")
    for col in (*VULN_ACCEPTANCE_USER_COLUMNS, *(c for c, _ddl in VULN_ACCEPTANCE_COLUMNS)):
        op.execute(f"ALTER TABLE vuln_findings DROP COLUMN IF EXISTS {col}")
