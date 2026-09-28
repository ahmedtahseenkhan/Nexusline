"""Freeze the basis of a final SMA capital calculation.

A calculation marked final kept only its inputs; BIC / ILM / ORC and the Basel bucket
edges were recomputed at today's exchange rate on every read, so a later EUR rate
change quietly restated capital already reported. The ``final_*`` columns hold the
exchange factor, bucket edges, basis text and results frozen at finalisation (and who
finalised it, when). Calculations already final are left unfrozen: the rate they were
reported at is not recorded anywhere, and freezing today's rate would put a figure on
record that was never filed. They read live, flagged as such, until reopened and
finalised again (``api.v1.scenario``). The DDL is shared with the create_all boot path
(``schema_patches.capital_snapshot_ddl_statements``) and is idempotent.

Revision ID: 0041_capital_snapshot
Revises: 0040_authority_amounts
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

from app.db.schema_patches import CAPITAL_SNAPSHOT_COLUMNS, capital_snapshot_ddl_statements

revision = "0041_capital_snapshot"
down_revision = "0040_authority_amounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in capital_snapshot_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    for col, _ddl in CAPITAL_SNAPSHOT_COLUMNS:
        op.execute(f"ALTER TABLE capital_calculations DROP COLUMN IF EXISTS {col}")
