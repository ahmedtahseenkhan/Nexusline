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

revision = "0008_banking_productionization"
down_revision = "0007_aml_cft"
branch_labels = None
depends_on = None


# New enum types that are only referenced by columns added to the pre-existing assets table.
_ASSET_ENUMS = {
    "asset_class": ("it_asset", "information_asset"),
    "asset_environment": ("production", "dr", "uat", "staging", "development", "not_applicable"),
    "discovery_source": (
        "manual", "active_directory", "intune_mdm", "cmdb",
        "network_scan", "cloud_connector", "edr", "import_csv",
    ),
}

# New columns on assets: (name, DDL type, server default or None).
_ASSET_COLUMNS: list[tuple[str, str, str | None]] = [
    ("asset_class", "asset_class", "'information_asset'"),
    ("business_value", "criticality", "'medium'"),
    ("information_owner", "VARCHAR(200)", "''"),
    ("data_categories", "TEXT", "''"),
    ("records_volume", "VARCHAR(120)", "''"),
    ("self_assessed", "BOOLEAN", "false"),
    ("assessed_by", "VARCHAR(200)", "''"),
    ("assessed_date", "DATE", None),
    ("replacement_cost", "NUMERIC(18,2)", "0"),
    ("currency", "VARCHAR(8)", "'PKR'"),
    ("rto_hours", "INTEGER", None),
    ("rpo_hours", "INTEGER", None),
    ("environment", "asset_environment", "'production'"),
    ("location", "VARCHAR(200)", "''"),
    ("hostname", "VARCHAR(200)", "''"),
    ("ip_address", "VARCHAR(64)", "''"),
    ("serial_number", "VARCHAR(120)", "''"),
    ("manufacturer", "VARCHAR(120)", "''"),
    ("model_number", "VARCHAR(120)", "''"),
    ("os_version", "VARCHAR(120)", "''"),
    ("discovery_source", "discovery_source", "'manual'"),
    ("external_id", "VARCHAR(200)", "''"),
    ("auto_discovered", "BOOLEAN", "false"),
    ("last_seen", "DATE", None),
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. enum types for the new assets columns (idempotent).
    for name, values in _ASSET_ENUMS.items():
        vals = ", ".join(f"'{v}'" for v in values)
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') "
            f"THEN CREATE TYPE {name} AS ENUM ({vals}); END IF; END $$;"
        )

    # 2. add the new columns to assets (guarded so re-runs are safe).
    for col, ddl_type, default in _ASSET_COLUMNS:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        not_null = " NOT NULL" if default is not None else ""
        op.execute(
            f"ALTER TABLE assets ADD COLUMN IF NOT EXISTS {col} {ddl_type}{default_clause}{not_null}"
        )

    # 3. create every new module table (+ their own enum types) that doesn't yet exist.
    Base.metadata.create_all(bind=bind, checkfirst=True)

    # 4. (re)apply RLS across all tenant-scoped tables, including the new ones.
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
