"""Delegation-of-authority limits on the decisions that carry an amount.

The authority matrix is now checked when a risk acceptance, an exception, an operational
loss event or an outsourcing arrangement is approved (``services.authority_limits``):

* ``authority_category`` gains ``exception``, ``operational_loss`` and ``outsourcing`` —
  an organisation adds matrix lines in them to put those approvals under a mandate.
* ``risk_acceptances`` records the exposure being accepted (``exposure_amount``,
  ``exposure_currency``, ``exposure_basis``), fixed when acceptance is requested.
* ``exceptions`` records the exposure an exception leaves uncovered
  (``exposure_amount``, ``exposure_currency``).

The DDL is shared with the create_all boot path
(``schema_patches.authority_amount_ddl_statements``) and is idempotent.

Revision ID: 0040_authority_amounts
Revises: 0039_tag_name_unique
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

from app.db.schema_patches import AUTHORITY_AMOUNT_COLUMNS, authority_amount_ddl_statements

revision = "0040_authority_amounts"
down_revision = "0039_tag_name_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in authority_amount_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum type; the categories stay (unused).
    for table, col, _ddl in reversed(AUTHORITY_AMOUNT_COLUMNS):
        op.execute(f"ALTER TABLE IF EXISTS {table} DROP COLUMN IF EXISTS {col}")
