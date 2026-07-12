"""GRC graph — Phase 2: link audit findings into the core graph.

Audit findings were dead-ends (engagement FK only). This adds the link tables so a
finding can be raised against the controls / risks / requirements it concerns, and those
records can show the findings against them.

New tables: audit_finding_controls, audit_finding_risks, audit_finding_requirements.
Created via metadata create_all (idempotent) — the same source-of-truth pattern as 0008.
Safe on fresh or existing databases.

Revision ID: 0010_grc_graph_audit_findings
Revises: 0009_performance_indexes
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.core.database import Base

revision = "0010_grc_graph_audit_findings"
down_revision = "0009_performance_indexes"
branch_labels = None
depends_on = None

_TABLES = ["audit_finding_controls", "audit_finding_risks", "audit_finding_requirements"]


def upgrade() -> None:
    bind = op.get_bind()
    # create_all only builds tables that don't yet exist (checkfirst) — here, the three
    # new audit-finding link tables. They carry no tenant_id, so no RLS policy is needed.
    Base.metadata.create_all(
        bind=bind, checkfirst=True,
        tables=[Base.metadata.tables[t] for t in _TABLES],
    )


def downgrade() -> None:
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
