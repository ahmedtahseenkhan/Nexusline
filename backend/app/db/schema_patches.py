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
