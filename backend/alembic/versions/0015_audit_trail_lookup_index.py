"""Index audit_logs by the record it describes.

Two access patterns now read the trail by subject rather than by time:

  1. The Activity Log page filters by ``entity_type`` (and drills into a single
     record's history by ``entity_id``).
  2. Runtime maker-checker resolves a record's *maker* from its earliest ``create``
     entry (``services/dual_control.maker_of``), which runs on every four-eyes
     decision — filing a SAR, publishing a policy, recording a control audit.

Without this index both are sequential scans over a table that only ever grows.
The composite covers ``entity_type`` alone as well, since it is the leading column.

``CREATE INDEX IF NOT EXISTS`` keeps the migration safe on fresh or existing
databases and re-runnable; the name matches SQLAlchemy's ``index=True`` convention so
the Alembic path and the ``create_all`` boot path converge on one schema.

Revision ID: 0015_audit_trail_lookup_index
Revises: 0014_grc_graph_obligations
Create Date: 2026-08-11
"""
from __future__ import annotations

from alembic import op

revision = "0015_audit_trail_lookup_index"
down_revision = "0014_grc_graph_obligations"
branch_labels = None
depends_on = None

_INDEX = "ix_audit_logs_entity"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} "
        "ON audit_logs (entity_type, entity_id, created_at)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
