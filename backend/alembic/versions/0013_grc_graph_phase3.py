"""GRC graph — Phase 3: complete the remaining edges.

Link tables: control_assets, vendor_requirements, vendor_controls, asset_threats,
asset_vulnerabilities. Columns: vuln_findings.asset_id, icfr_controls.control_id,
data_breaches.incident_id. Idempotent; safe on fresh or existing databases.

Revision ID: 0013_grc_graph_phase3
Revises: 0012_grc_graph_bia_continuity
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401
from app.core.database import Base

revision = "0013_grc_graph_phase3"
down_revision = "0012_grc_graph_bia_continuity"
branch_labels = None
depends_on = None

_TABLES = [
    "control_assets", "vendor_requirements", "vendor_controls",
    "asset_threats", "asset_vulnerabilities",
]
_COLUMNS = [
    ("vuln_findings", "asset_id", "uuid REFERENCES assets(id) ON DELETE SET NULL"),
    ("icfr_controls", "control_id", "uuid REFERENCES controls(id) ON DELETE SET NULL"),
    ("data_breaches", "incident_id", "uuid REFERENCES incidents(id) ON DELETE SET NULL"),
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
