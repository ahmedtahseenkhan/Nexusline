"""Risk-scenario templates — generating a risk register from the asset register.

Adds one table. Each row is a reusable "threat exploits vulnerability against this kind
of asset" statement plus how to derive an opening score from the asset's own rating; the
generation endpoint pairs selected assets with the applicable templates and proposes
risks for review.

New table only — nothing to mirror in ``app.db.schema_patches``. The built-in catalogue
lives in code (``app.services.risk_scenarios``) and is copied into this table on demand,
so a bank can retune the library without a release and an upgrade never overwrites its
edits.

Revision ID: 0018_risk_scenario_templates
Revises: 0017_risk_methodology
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. risk_scenario_templates)
from app.core.database import Base
from app.db.rls import rls_ddl_statements

revision = "0018_risk_scenario_templates"
down_revision = "0017_risk_methodology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS risk_scenario_templates")
