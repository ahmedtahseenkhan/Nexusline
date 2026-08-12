"""User-defined multi-stage approval routing.

Four new tables: ``workflow_definitions`` and ``workflow_stages`` describe a route;
``workflow_instances`` and ``workflow_instance_stages`` record one record travelling it.

Each stage raises a real ``ApprovalRequest``, so the inbox, N-eyes counting, segregation
of duties and the audit trail are the ones that already exist rather than a second
implementation. A record type with no enabled definition keeps the fixed lifecycle the
platform has always had, which is what makes this safe to add to a running install.

New tables only, so there is nothing to mirror in ``app.db.schema_patches``.

Revision ID: 0022_workflow_designer
Revises: 0021_audit_plan_programs
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. the workflow tables)
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0022_workflow_designer"
down_revision = "0021_audit_plan_programs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    for table in (
        "workflow_instance_stages",
        "workflow_instances",
        "workflow_stages",
        "workflow_definitions",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for enum_name in (
        "workflow_stage_status",
        "workflow_instance_status",
        "workflow_timeout_action",
        "approver_mode",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
