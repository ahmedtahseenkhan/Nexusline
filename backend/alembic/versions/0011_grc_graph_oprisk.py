"""GRC graph — Phase 2: reconcile operational risk with the enterprise graph.

RCSA lines, KRIs and loss events were islands (free-text). This links them:
  - rcsa_risks    += risk_id, control_id  (the enterprise risk + control a line assesses)
  - key_risk_indicators ↔ risks via kri_risks (a KRI indicates enterprise risks)
  - loss_events   += incident_id, and ↔ risks via loss_event_risks

Columns added with ADD COLUMN IF NOT EXISTS; link tables via create_all (idempotent).
Safe on fresh or existing databases.

Revision ID: 0011_grc_graph_oprisk
Revises: 0010_grc_graph_audit_findings
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401
from app.core.database import Base

revision = "0011_grc_graph_oprisk"
down_revision = "0010_grc_graph_audit_findings"
branch_labels = None
depends_on = None

_TABLES = ["kri_risks", "loss_event_risks"]
_COLUMNS = [
    ("rcsa_risks", "risk_id", "uuid REFERENCES risks(id) ON DELETE SET NULL"),
    ("rcsa_risks", "control_id", "uuid REFERENCES controls(id) ON DELETE SET NULL"),
    ("loss_events", "incident_id", "uuid REFERENCES incidents(id) ON DELETE SET NULL"),
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
