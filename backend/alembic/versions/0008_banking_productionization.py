"""Banking productionization: asset split (IT vs Information) + gap-analysis modules.

This migration:
  1. Creates the new PostgreSQL enum types that attach to the EXISTING ``assets`` table
     (asset_class / asset_environment / discovery_source) — create_all cannot add these
     because it never recreates an existing table.
  2. Adds the IT/Information/discovery columns to ``assets`` (with server defaults so rows
     that already exist get valid values).
  3. Creates every new module table via metadata create_all (idempotent) — Unified Issues,
     Regulatory Change, ICFR, BIA, Fraud, Delegation of Authority, Scenario+Capital,
     Whistleblowing, Vulnerabilities, ESG, Model Risk, Declarations, Board Governance,
     Data Protection, Outsourcing, Integrations/CCM, Risk Quantification, AI Assist, plus
     the new asset tables (asset_tags / asset_tag_links / asset_dependencies).
  4. Applies row-level-security policies to all tenant-scoped tables.

Safe on fresh or existing databases.

Revision ID: 0008_banking_productionization
Revises: 0007_aml_cft
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. the new modules)
from app.core.database import Base
from app.db.rls import rls_ddl_statements
from app.db.schema_patches import asset_split_ddl_statements

revision = "0008_banking_productionization"
down_revision = "0007_aml_cft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. asset-split enum types + new columns on the pre-existing assets table
    #    (shared with the create_all boot path — one source of truth).
    for statement in asset_split_ddl_statements():
        op.execute(statement)

    # 2. create every new module table (+ their own enum types) that doesn't yet exist.
    Base.metadata.create_all(bind=bind, checkfirst=True)

    # 3. (re)apply RLS across all tenant-scoped tables, including the new ones.
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    # Drop the new module tables (asset column additions are left in place — dropping them
    # would lose IT/Information classification data; remove manually if truly rolling back).
    _drop_tables = [
        "ai_extractions",
        "risk_quantifications",
        "control_test_runs", "automated_control_tests", "connectors",
        "outsourcing_reviews", "outsourcing_arrangements",
        "consent_records", "data_breaches", "dsars", "dpias",
        "meeting_decisions", "committee_meetings", "committees",
        "declarations", "declaration_campaigns",
        "model_validations", "model_inventory",
        "environmental_risk_ratings", "esg_assessments",
        "patch_records", "vuln_findings",
        "whistleblowing_updates", "whistleblowing_reports",
        "capital_calculations", "scenario_analyses",
        "dual_control_rules", "authority_matrix",
        "fraud_control_checks", "fraud_cases", "fraud_risks",
        "bia_dependencies", "bia_assessments",
        "icfr_deficiencies", "icfr_tests", "icfr_controls", "icfr_processes",
        "regulatory_returns", "obligations", "regulatory_changes",
        "issue_updates", "issue_actions", "issues",
        "asset_dependencies", "asset_tag_links", "asset_tags",
    ]
    for table in _drop_tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
