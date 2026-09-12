"""Product review, phase 2: record depth.

* Controls: nature, automation, key flag, operating frequency, ISO 27002 attributes,
  design vs operating effectiveness, test procedure; scope by business unit and process.
* Control tests: a workpaper (type, period, population, sample, exceptions, conclusion),
  reviewer sign-off, the issue a failure opened; evidence attaches to a test.
* Issues: links to risks, controls, requirements, assets and third parties; root cause;
  independent validation; a log of every due-date move.
* Risks: cause / event / consequence, type, velocity, source, target, rationale, last
  assessed; impact by dimension; appetite per category; treatment actions; severity
  bands and a cell-by-cell heat map on the settings.
* Incidents: occurred/detected/resolved (and regulatory deadlines) become timezone-aware
  timestamps; contained-at, customers/records affected, personal-data-breach, near miss.
* KRIs: definition, numerator/denominator, data source and provider, leading/lagging,
  range bounds, appetite link, feed token, escalation per level; daily and weekly.
* Policies: approving authority, effective date, supersedes, applicability.
* Third parties: legal entity, relationship owner, data classification and residency,
  sub-contractors, spend, tier, certifications with expiry; contract currency; owner and
  country on outsourcing arrangements.

Revision ID: 0031_product_review_phase2
Revises: 0030_product_review_phase1
Create Date: 2026-09-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.core.database import Base
from app.db.schema_patches import PHASE2_COLUMNS, PHASE2_FK_COLUMNS, phase2_ddl_statements

revision = "0031_product_review_phase2"
down_revision = "0030_product_review_phase1"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "control_business_units", "control_processes",
    "issue_risks", "issue_controls", "issue_requirements", "issue_assets", "issue_vendors",
    "issue_due_date_changes",
    "risk_impact_dimensions", "risk_appetites", "risk_treatment_actions",
    "kri_escalations",
    "policy_business_units", "policy_roles",
    "vendor_processes", "vendor_subcontractors", "vendor_data_residency", "vendor_certifications",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[t] for t in NEW_TABLES])
    for statement in phase2_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    # Timestamp columns are left as timestamps; converting back would lose the time.
    for table, col, _target in reversed(PHASE2_FK_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table, col, _ddl in reversed(PHASE2_COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
