"""Saved report definitions for the report builder.

Until now the platform's reporting was one register export per module with whatever
filter happened to be on screen. A bank's risk function does not work that way: it
asks the same dozen questions every month — critical risks by segment, controls not
tested this year, reportable incidents this quarter — and wants each answered the same
way each time, on screen or as a PDF for the committee pack or an Excel for the
analyst. ``saved_reports`` holds the *question* (subject, filters, columns, sort); the
rows are always read live, so a saved report can neither go stale nor snapshot data its
reader has since lost permission to see.

Tenant-scoped and RLS-protected like every other register.

Revision ID: 0027_saved_reports
Revises: 0026_platform_admin
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. saved_reports)
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0027_saved_reports"
down_revision = "0026_platform_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=[Base.metadata.tables["saved_reports"]],
        checkfirst=True,
    )
    # Idempotent across every table; this is what stamps the new one with its policy.
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS saved_reports")
