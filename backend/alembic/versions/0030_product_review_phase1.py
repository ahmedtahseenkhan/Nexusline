"""Product review, phase 1: structured data.

* ``tenant_settings`` — currency, timezone, date format, fiscal year, phone country and
  the archive retention window, one row per organisation.
* ``lookups`` — governed lists (risk category, incident type, regulator, country …)
  that replace free text, with an optional parent for two-level lists.
* A picker-backed foreign key beside every free-text owner, business-unit and category
  column (``schema_patches.PHASE1_FK_COLUMNS``), plus ``workflow_owner_id`` on every
  table with an approval lifecycle. Free-text values are matched onto the new keys on
  the next start by ``app.db.fk_backfill``; the old columns stay for one release.
* ``requirements.applicability_justification`` for the Statement of Applicability.

Revision ID: 0030_product_review_phase1
Revises: 0029_product_review_phase0
Create Date: 2026-09-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.core.database import Base
from app.db.schema_patches import (
    PHASE1_FK_COLUMNS,
    PHASE1_TEXT_COLUMNS,
    phase1_ddl_statements,
    workflow_tables,
)

revision = "0030_product_review_phase1"
down_revision = "0029_product_review_phase0"
branch_labels = None
depends_on = None

NEW_TABLES = ("tenant_settings", "lookups")


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[t] for t in NEW_TABLES])
    for statement in phase1_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    for table, col, _ddl in PHASE1_TEXT_COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table in workflow_tables():
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS workflow_owner_id")
    for table, col, _target, _anchor in PHASE1_FK_COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
