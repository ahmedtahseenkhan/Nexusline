"""Scenario library: which controls address each scenario.

Install a framework and you get its clauses; generate risks and you get a register.
The question between them — for this threat, which of our controls are supposed to be
in the way? — was answered by hand, risk by risk. Each scenario now carries the
catalogue references of the controls that address it (ISO 27001 Annex A, CIS v8, SBP
Cybersecurity), and the generator resolves them against the organisation's own
catalogue when it proposes a risk. The mapping says "meant to address"; whether a
control works stays a human judgement, so residual still equals inherent until
somebody assesses it.

Existing rows get an empty value; re-running "Install library" backfills them from the
shipped mapping without touching anything a tenant edited.

Revision ID: 0028_scenario_control_references
Revises: 0027_saved_reports
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.db.schema_patches import scenario_control_references_ddl_statements

revision = "0028_scenario_control_references"
down_revision = "0027_saved_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in scenario_control_references_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE risk_scenario_templates DROP COLUMN IF EXISTS control_references")
