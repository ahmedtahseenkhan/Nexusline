"""Saved import mappings for the smart import wizard.

Adds one table. A profile records how a given organisation's spreadsheet columns map
onto a register's fields, so a recurring upload (quarterly risk register, monthly asset
inventory) is applied rather than re-derived — and so successive loads stay consistent
with each other.

New table only: no ALTER on a pre-existing table, so there is nothing to mirror in
``app.db.schema_patches``. Table creation goes through the model metadata and RLS
through ``rls_ddl_statements()`` — the same two sources the boot path uses — so the
Alembic path and the ``create_all`` path cannot drift apart.

Revision ID: 0016_import_profiles
Revises: 0015_audit_trail_lookup_index
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. import_profiles)
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0016_import_profiles"
down_revision = "0015_audit_trail_lookup_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # checkfirst keeps this safe on a database already carrying the table.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    # Re-applying across every tenant-scoped table is idempotent (each policy is
    # dropped before it is recreated) and picks up the new one.
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS import_profiles")
