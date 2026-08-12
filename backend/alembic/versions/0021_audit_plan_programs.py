"""Annual audit plan, reusable audit programmes and their steps.

Four new tables:

* ``audit_plans`` / ``audit_plan_items`` — what the assurance function committed to
  cover this year, so "did we do what we told the board we would do?" is a number
  rather than an argument. Board sign-off reuses the existing ``ApprovalRequest``
  inbox rather than a plan-specific approval mechanism.
* ``audit_programs`` / ``audit_program_steps`` — reusable checklists, generatable from
  an installed framework's requirements and instantiated onto an engagement as ordinary
  ``AuditProcedure`` working papers.

New tables only, so there is nothing to mirror in ``app.db.schema_patches``.

Revision ID: 0021_audit_plan_programs
Revises: 0020_audit_provenance
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. the new tables)
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0021_audit_plan_programs"
down_revision = "0020_audit_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    # Children first — the FKs cascade, but dropping in order keeps this readable.
    for table in (
        "audit_program_steps",
        "audit_programs",
        "audit_plan_items",
        "audit_plans",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP TYPE IF EXISTS audit_plan_status")
