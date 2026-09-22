"""Per-organisation MFA enforcement level (off / privileged / everyone).

``tenant_settings.mfa_enforcement`` — NULL means the deployment default
(``MFA_ENFORCEMENT``). Lets an evaluation or UAT install run without two-factor
authentication, and a bank pick its own level unless the deployment locks it.

Revision ID: 0036_mfa_enforcement_level
Revises: 0035_product_decisions
Create Date: 2026-09-22
"""
from __future__ import annotations

from alembic import op

revision = "0036_mfa_enforcement_level"
down_revision = "0035_product_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE IF EXISTS tenant_settings ADD COLUMN IF NOT EXISTS mfa_enforcement VARCHAR(16)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS tenant_settings DROP COLUMN IF EXISTS mfa_enforcement")
