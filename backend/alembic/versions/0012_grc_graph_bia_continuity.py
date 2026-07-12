"""GRC graph — Phase 2: link BIA and continuity into the org/asset/risk graph.

  - bia_assessments += process_id  (the real process; process_name kept as label)
  - bia_dependencies += asset_id, vendor_id  (the real resource; name kept as fallback)
  - continuity_plans += bia_id, and ↔ assets/risks via continuity_plan_assets/_risks

Columns via ADD COLUMN IF NOT EXISTS; link tables via create_all. Safe & idempotent.

Revision ID: 0012_grc_graph_bia_continuity
Revises: 0011_grc_graph_oprisk
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401
from app.core.database import Base

revision = "0012_grc_graph_bia_continuity"
down_revision = "0011_grc_graph_oprisk"
branch_labels = None
depends_on = None

_TABLES = ["continuity_plan_assets", "continuity_plan_risks"]
_COLUMNS = [
    ("bia_assessments", "process_id", "uuid REFERENCES processes(id) ON DELETE SET NULL"),
    ("bia_dependencies", "asset_id", "uuid REFERENCES assets(id) ON DELETE SET NULL"),
    ("bia_dependencies", "vendor_id", "uuid REFERENCES vendors(id) ON DELETE SET NULL"),
    ("continuity_plans", "bia_id", "uuid REFERENCES bia_assessments(id) ON DELETE SET NULL"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for table, col, decl in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {decl}")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})")
    Base.metadata.create_all(
        bind=bind, checkfirst=True, tables=[Base.metadata.tables[t] for t in _TABLES]
    )


def downgrade() -> None:
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for table, col, _ in _COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
