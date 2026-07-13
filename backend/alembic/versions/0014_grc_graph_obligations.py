"""GRC graph: map obligations to requirements / policies / controls.

Replaces the free-text mapped_policies / mapped_controls columns on obligations with real
link tables so a regulatory obligation connects to the framework requirements it derives
from and the policies/controls that satisfy it. Idempotent.

Revision ID: 0014_grc_graph_obligations
Revises: 0013_grc_graph_phase3
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401
from app.core.database import Base

revision = "0014_grc_graph_obligations"
down_revision = "0013_grc_graph_phase3"
branch_labels = None
depends_on = None

_TABLES = ["obligation_requirements", "obligation_policies", "obligation_controls"]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind, checkfirst=True, tables=[Base.metadata.tables[t] for t in _TABLES]
    )


def downgrade() -> None:
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
