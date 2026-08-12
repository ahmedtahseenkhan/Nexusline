"""Idempotent schema patches for columns added to PRE-EXISTING tables.

``Base.metadata.create_all`` (the dev boot path in ``init_db``) creates missing *tables*
but can never ALTER an existing one. The asset split (IT vs Information asset) added
columns + enum types to the already-existing ``assets`` table, so those additions live
here and are applied by BOTH the create_all boot path AND the Alembic migration — a
single source of truth, each statement written to be safely re-runnable.
"""
from __future__ import annotations

# enum types referenced by the new columns on the existing assets table.
ASSET_ENUMS: dict[str, tuple[str, ...]] = {
    "asset_class": ("it_asset", "information_asset"),
    "asset_environment": ("production", "dr", "uat", "staging", "development", "not_applicable"),
    "discovery_source": (
        "manual", "active_directory", "intune_mdm", "cmdb",
        "network_scan", "cloud_connector", "edr", "import_csv",
    ),
}

# (column name, DDL type, server default or None for nullable).
ASSET_COLUMNS: list[tuple[str, str, str | None]] = [
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


# --- risk methodology (configurable matrix + suggested residual) -------------
# Columns added to the pre-existing `risks` and `risk_settings` tables.
RISK_COLUMNS: list[tuple[str, str, str, str | None]] = [
    # (table, column, DDL type, server default or None for nullable)
    ("risk_settings", "matrix_size", "INTEGER", "5"),
    ("risks", "suggested_residual_likelihood", "INTEGER", None),
    ("risks", "suggested_residual_impact", "INTEGER", None),
    ("risks", "suggested_residual_rationale", "TEXT", "''"),
    ("risks", "residual_accepted_by", "UUID", None),
    ("risks", "residual_accepted_at", "DATE", None),
    ("risks", "residual_override_reason", "TEXT", "''"),
]

# The 1..5 scale checks predate the configurable matrix and would reject a 6x6 register.
# The database can only police the widest scale any tenant may choose; the tenant's own
# `matrix_size` is enforced in the API layer, since a check constraint cannot vary by
# RLS tenant. Dropping before adding keeps the pair re-runnable.
RISK_SCALE_CONSTRAINTS: list[tuple[str, str]] = [
    ("ck_risk_inh_likelihood", "inherent_likelihood BETWEEN 1 AND 6"),
    ("ck_risk_inh_impact", "inherent_impact BETWEEN 1 AND 6"),
    ("ck_risk_res_likelihood", "residual_likelihood IS NULL OR residual_likelihood BETWEEN 1 AND 6"),
    ("ck_risk_res_impact", "residual_impact IS NULL OR residual_impact BETWEEN 1 AND 6"),
]


def risk_methodology_ddl_statements() -> list[str]:
    """Idempotent DDL for the configurable risk matrix and residual suggestion.

    Applied by BOTH the ``create_all`` boot path and the Alembic migration, exactly like
    :func:`asset_split_ddl_statements` — one source of truth, every statement safely
    re-runnable.
    """
    statements: list[str] = []
    for table, col, ddl_type, default in RISK_COLUMNS:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        not_null = " NOT NULL" if default is not None else ""
        statements.append(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl_type}{default_clause}{not_null}"
        )
    for name, expression in RISK_SCALE_CONSTRAINTS:
        statements.append(f"ALTER TABLE risks DROP CONSTRAINT IF EXISTS {name}")
        statements.append(f"ALTER TABLE risks ADD CONSTRAINT {name} CHECK ({expression})")
    return statements


# --- turnaround-time (TAT) clock ---------------------------------------------
# Two columns on each SLA-bearing register. There is deliberately no `tat_start_date`:
# the clock starts when the record was raised, which `created_at` already records, and a
# third column would be a copy that can drift.
TAT_TABLES: tuple[str, ...] = ("risks", "issues", "audit_findings", "incidents")


def tat_ddl_statements() -> list[str]:
    """Idempotent DDL for the TAT columns, shared by the boot path and the migration."""
    statements: list[str] = []
    for table in TAT_TABLES:
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tat_due_date DATE")
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tat_breached_at DATE")
        # The dashboard widget and the breach scan both filter on the due date.
        statements.append(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tat_due ON {table} (tat_due_date)"
        )
    return statements


# --- audit provenance ---------------------------------------------------------
# Columns added to the pre-existing audit_engagements table so internal, statutory,
# regulatory (SBP) and certification audits share one register and one findings pipeline.
AUDIT_TYPE_VALUES: tuple[str, ...] = (
    "internal", "external_statutory", "regulatory", "certification",
)
AUDIT_COLUMNS: list[tuple[str, str, str | None]] = [
    ("audit_type", "audit_type", "'internal'"),
    ("auditor_firm", "VARCHAR(200)", "''"),
    ("report_reference", "VARCHAR(120)", "''"),
    ("report_date", "DATE", None),
]


def audit_type_ddl_statements() -> list[str]:
    """Idempotent DDL for the audit-provenance columns and their enum type."""
    values = ", ".join(f"'{v}'" for v in AUDIT_TYPE_VALUES)
    statements = [
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'audit_type') "
        f"THEN CREATE TYPE audit_type AS ENUM ({values}); END IF; END $$;"
    ]
    for col, ddl_type, default in AUDIT_COLUMNS:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        not_null = " NOT NULL" if default is not None else ""
        statements.append(
            "ALTER TABLE audit_engagements ADD COLUMN IF NOT EXISTS "
            f"{col} {ddl_type}{default_clause}{not_null}"
        )
    statements.append(
        "CREATE INDEX IF NOT EXISTS ix_audit_engagements_audit_type "
        "ON audit_engagements (audit_type)"
    )
    return statements


def fortnightly_ddl_statements() -> list[str]:
    """Add the fortnightly review cycle and month-level audit-plan scheduling.

    ``ALTER TYPE ... ADD VALUE IF NOT EXISTS`` is legal inside a transaction on
    PostgreSQL 12+ as long as the new value is not *used* in the same transaction, which
    it is not here — the value is only written once the migration has committed.
    """
    return [
        "ALTER TYPE review_frequency ADD VALUE IF NOT EXISTS 'fortnightly' BEFORE 'monthly'",
        "ALTER TABLE audit_plan_items ADD COLUMN IF NOT EXISTS planned_month INTEGER",
    ]


def asset_split_ddl_statements() -> list[str]:
    """Idempotent DDL: create the enum types, then add the new asset columns.

    Order matters — the enum columns need their types to exist first. Every statement
    is a no-op if already applied (``CREATE TYPE`` guarded by a DO block, columns via
    ``ADD COLUMN IF NOT EXISTS``), so this is safe on fresh and existing databases.
    """
    statements: list[str] = []
    for name, values in ASSET_ENUMS.items():
        vals = ", ".join(f"'{v}'" for v in values)
        statements.append(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') "
            f"THEN CREATE TYPE {name} AS ENUM ({vals}); END IF; END $$;"
        )
    for col, ddl_type, default in ASSET_COLUMNS:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        not_null = " NOT NULL" if default is not None else ""
        statements.append(
            f"ALTER TABLE assets ADD COLUMN IF NOT EXISTS {col} {ddl_type}{default_clause}{not_null}"
        )
    return statements
