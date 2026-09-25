"""Idempotent schema patches for columns added to PRE-EXISTING tables.

``Base.metadata.create_all`` (the dev boot path in ``init_db``) creates missing *tables*
but can never ALTER an existing one. The asset split (IT vs Information asset) added
columns + enum types to the already-existing ``assets`` table, so those additions live
here and are applied by BOTH the create_all boot path AND the Alembic migration — a
single source of truth, each statement written to be safely re-runnable.
"""
from __future__ import annotations

from app.core.risk_scale import MAX_MATRIX_SIZE

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

# The original 1..5 scale checks predate the configurable matrix and would reject a
# wider register; every later widening (6x6, then 10x10) has to walk the same path. The
# database can only police the widest scale any tenant may choose — `MAX_MATRIX_SIZE`,
# the single source of truth also used by the ORM constraints and the Pydantic
# validators; the tenant's own `matrix_size` is enforced in the API layer, since a check
# constraint cannot vary by RLS tenant. Dropping before adding keeps the pair
# re-runnable, so an installation already at 6 is simply re-stamped at 10.
_CEILING = MAX_MATRIX_SIZE

RISK_SCALE_CONSTRAINTS: list[tuple[str, str, str]] = [
    # (table, constraint name, expression)
    ("risks", "ck_risk_inh_likelihood", f"inherent_likelihood BETWEEN 1 AND {_CEILING}"),
    ("risks", "ck_risk_inh_impact", f"inherent_impact BETWEEN 1 AND {_CEILING}"),
    ("risks", "ck_risk_res_likelihood",
     f"residual_likelihood IS NULL OR residual_likelihood BETWEEN 1 AND {_CEILING}"),
    ("risks", "ck_risk_res_impact",
     f"residual_impact IS NULL OR residual_impact BETWEEN 1 AND {_CEILING}"),
    # The scale-definition rungs have to widen with the matrix, or a bank on a 1..10
    # scale can set the scores but never write down what rungs 7..10 mean.
    ("risk_matrix_levels", "ck_risk_matrix_level", f"level BETWEEN 1 AND {_CEILING}"),
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
    statements.extend(risk_scale_constraint_statements())
    return statements


def risk_scale_constraint_statements() -> list[str]:
    """Re-stamp each scale check at the current ceiling, skipping absent tables.

    The table guard matters for one caller: migration 0017 applies these patches *before*
    its ``create_all`` builds ``risk_matrix_levels``, so an unguarded ALTER would break a
    fresh migrate-from-zero. Where the table is missing there is nothing to widen anyway —
    ``create_all`` will build it from the ORM, which reads the same ceiling.
    """
    out: list[str] = []
    for table, name, expression in RISK_SCALE_CONSTRAINTS:
        out.append(
            f"DO $$ BEGIN IF to_regclass('public.{table}') IS NOT NULL THEN "
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}; "
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}); "
            f"END IF; END $$;"
        )
    return out


# --- scenario -> control mapping ---------------------------------------------
def scenario_control_references_ddl_statements() -> list[str]:
    """The control-references column on the scenario library, for installs whose
    ``risk_scenario_templates`` predates it. Empty by default; the library re-install
    backfills it from the shipped mapping."""
    return [
        "ALTER TABLE risk_scenario_templates ADD COLUMN IF NOT EXISTS control_references "
        "TEXT DEFAULT '' NOT NULL",
    ]


# --- platform administration --------------------------------------------------
def platform_admin_ddl_statements() -> list[str]:
    """The deployment-operator flag on the pre-existing ``users`` table.

    A column rather than a permission code: permissions live in tenant-scoped ``roles``
    rows, so an organisation's own admin could otherwise grant themselves the run of the
    whole platform. Defaults to false, so applying this to a live database changes
    nobody's access.
    """
    return [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin "
        "BOOLEAN DEFAULT false NOT NULL",
    ]


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


# --- product review, phase 0 --------------------------------------------------
# Columns added to pre-existing tables by the 11 Sep 2026 product-review remediation.
PHASE0_COLUMNS: list[tuple[str, str, str, str | None]] = [
    # (table, column, DDL type, server default or None for nullable)
    ("risks", "needs_review", "BOOLEAN", "false"),
    ("risks", "review_reason", "TEXT", "''"),
    ("frameworks", "kind", "VARCHAR(16)", "'compliance'"),
    ("attestations", "statement", "TEXT", "''"),
    ("attestations", "scope", "TEXT", "''"),
    ("attestations", "confirmed_by_id", "UUID", None),
    ("attestations", "confirmed_at", "DATE", None),
    ("users", "mfa_grace_until", "TIMESTAMPTZ", None),
]


def phase0_ddl_statements() -> list[str]:
    """Idempotent DDL for the product-review phase-0 columns and the residual check.

    The residual check is added ``NOT VALID``: it binds every write from now on without
    failing the upgrade on a register that already holds a residual above inherent. Those
    rows are flagged for review by ``app.db.data_repairs`` instead of being rewritten, and
    the check lets a flagged row through (see ``RESIDUAL_NOT_ABOVE_INHERENT``).

    The two uniqueness rules (one framework per name, one tile per metric) are *not*
    here: existing duplicates have to be merged first, which needs tenant-scoped ORM
    work, so ``data_repairs`` creates those indexes after it has cleaned up.
    """
    statements: list[str] = []
    for table, col, ddl_type, default in PHASE0_COLUMNS:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        not_null = " NOT NULL" if default is not None else ""
        statements.append(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl_type}{default_clause}{not_null}"
        )
    statements.append("CREATE INDEX IF NOT EXISTS ix_risks_needs_review ON risks (needs_review)")
    from app.models.risk import RESIDUAL_NOT_ABOVE_INHERENT

    # Drop and re-add so a changed expression reaches existing installs; a NOT VALID
    # check is added without scanning the table, so this is cheap on every boot.
    statements.append("ALTER TABLE risks DROP CONSTRAINT IF EXISTS ck_risk_residual_le_inherent")
    statements.append(
        "ALTER TABLE risks ADD CONSTRAINT ck_risk_residual_le_inherent "
        f"CHECK ({RESIDUAL_NOT_ABOVE_INHERENT}) NOT VALID"
    )
    return statements


# --- product review, phase 1: structured data ------------------------------------
# A picker-backed foreign key beside every free-text owner, unit and category column.
# The free-text column stays for one release: existing values are matched onto the new
# key by ``app.db.fk_backfill`` on start-up, and anything that doesn't match is kept as
# text so nothing a user typed is lost.
PHASE1_FK_COLUMNS = [
    ("risks", "treatment_owner_id", "users", "treatment_owner"),
    ("risks", "category_id", "lookups", "category"),
    ("controls", "owner_id", "users", "owner"),
    ("controls", "operator_id", "users", "owner"),
    ("controls", "classification_id", "lookups", "classification"),
    ("control_audits", "tested_by_id", "users", "auditor"),
    ("issues", "owner_id", "users", "owner"),
    ("issues", "business_unit_id", "business_units", "business_unit"),
    ("issues", "category_id", "lookups", "category"),
    ("issue_actions", "owner_id", "users", "owner"),
    ("issue_updates", "author_id", "users", "author"),
    ("incidents", "assignee_id", "users", "assignee"),
    ("incidents", "reported_by_id", "users", "reported_by"),
    ("incidents", "category_id", "lookups", "category"),
    ("incidents", "classification_id", "lookups", "classification"),
    ("incidents", "regulator_id", "lookups", "regulator"),
    ("regulatory_reports", "submitted_by_id", "users", "submitted_by"),
    ("key_risk_indicators", "owner_id", "users", "owner"),
    ("key_risk_indicators", "business_unit_id", "business_units", "business_area"),
    ("key_risk_indicators", "category_id", "lookups", "category"),
    ("policies", "owner_id", "users", "owner"),
    ("policies", "category_id", "lookups", "category"),
    ("policy_reviews", "reviewer_id", "users", "reviewer"),
    ("business_units", "manager_id", "users", "manager"),
    ("processes", "owner_id", "users", "owner"),
    ("legals", "category_id", "lookups", "category"),
    ("goals", "owner_id", "users", "owner"),
    ("loss_events", "action_owner_id", "users", "action_owner"),
    ("loss_events", "business_unit_id", "business_units", "business_line"),
    ("rcsa_assessments", "assessor_id", "users", "assessor"),
    ("rcsa_assessments", "business_unit_id", "business_units", "business_unit"),
    ("rcsa_assessments", "process_id", "processes", "process"),
    ("rcsa_risks", "action_owner_id", "users", "action_owner"),
    ("rcsa_risks", "category_id", "lookups", "category"),
    ("vendors", "category_id", "lookups", "category"),
    ("vendors", "country_id", "lookups", "location"),
]


PHASE1_TEXT_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, DDL) — plain columns
    ("requirements", "applicability_justification", "TEXT DEFAULT '' NOT NULL"),
]


def workflow_tables() -> list[str]:
    """Every table whose model carries ``WorkflowMixin`` (and so ``workflow_owner_id``)."""
    import app.models  # noqa: F401 - registers every mapper
    from app.core.database import Base
    from app.models.base import WorkflowMixin

    return sorted(
        m.class_.__tablename__
        for m in Base.registry.mappers
        if issubclass(m.class_, WorkflowMixin) and hasattr(m.class_, "__tablename__")
    )


def phase1_ddl_statements() -> list[str]:
    """Idempotent DDL for the phase-1 columns on pre-existing tables.

    New tables (``tenant_settings``, ``lookups``) come from ``create_all``. Foreign keys
    are added ``NOT VALID`` and guarded by name, so the upgrade never scans or fails on a
    large table, and re-running it is a no-op.
    """
    statements: list[str] = []

    def fk(table: str, col: str, target: str) -> None:
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} UUID")
        name = f"fk_{table}_{col}"[:63]
        statements.append(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({col}) REFERENCES {target}(id) ON DELETE SET NULL NOT VALID; "
            "END IF; END $$;"
        )
        statements.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})"[:200])

    for table, col, target, _anchor in PHASE1_FK_COLUMNS:
        fk(table, col, target)
    for table in workflow_tables():
        fk(table, "workflow_owner_id", "users")
    for table, col, ddl in PHASE1_TEXT_COLUMNS:
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    return statements


# --- product review, phase 2: record depth -------------------------------------------
# (table, column, DDL). Foreign keys use PHASE2_FK_COLUMNS below.
PHASE2_COLUMNS: list[tuple[str, str, str]] = [
    ("controls", "nature", "VARCHAR(16)"),
    ("controls", "automation", "VARCHAR(24)"),
    ("controls", "is_key", "BOOLEAN DEFAULT false NOT NULL"),
    ("controls", "operating_frequency", "VARCHAR(16)"),
    ("controls", "iso27002_attributes", "JSONB DEFAULT '{}'::jsonb NOT NULL"),
    ("controls", "design_effectiveness", "control_effectiveness DEFAULT 'not_assessed' NOT NULL"),
    ("controls", "operating_effectiveness", "control_effectiveness DEFAULT 'not_assessed' NOT NULL"),
    ("controls", "effectiveness_override_reason", "TEXT DEFAULT '' NOT NULL"),
    ("controls", "test_procedure", "TEXT DEFAULT '' NOT NULL"),
    ("controls", "evidence_expected", "TEXT DEFAULT '' NOT NULL"),
    ("control_audits", "test_type", "VARCHAR(16)"),
    ("control_audits", "period_start", "DATE"),
    ("control_audits", "period_end", "DATE"),
    ("control_audits", "population_size", "INTEGER"),
    ("control_audits", "sample_size", "INTEGER"),
    ("control_audits", "sample_method", "VARCHAR(32) DEFAULT '' NOT NULL"),
    ("control_audits", "exceptions_count", "INTEGER DEFAULT 0 NOT NULL"),
    ("control_audits", "exceptions_detail", "TEXT DEFAULT '' NOT NULL"),
    ("control_audits", "conclusion", "TEXT DEFAULT '' NOT NULL"),
    # Tests recorded before reviews existed are "legacy", not "pending" (see below).
    ("control_audits", "review_status", "VARCHAR(16) DEFAULT 'legacy' NOT NULL"),
    ("control_audits", "reviewed_at", "TIMESTAMPTZ"),
    ("control_audits", "review_note", "TEXT DEFAULT '' NOT NULL"),
    ("issues", "validated_at", "TIMESTAMPTZ"),
    ("issues", "validation_result", "VARCHAR(16)"),
    ("issues", "validation_note", "TEXT DEFAULT '' NOT NULL"),
    ("risks", "cause", "TEXT DEFAULT '' NOT NULL"),
    ("risks", "event", "TEXT DEFAULT '' NOT NULL"),
    ("risks", "consequence", "TEXT DEFAULT '' NOT NULL"),
    ("risks", "risk_type", "VARCHAR(24)"),
    ("risks", "velocity", "VARCHAR(16)"),
    ("risks", "identified_date", "DATE"),
    ("risks", "source", "VARCHAR(24)"),
    ("risks", "target_likelihood", "INTEGER"),
    ("risks", "target_impact", "INTEGER"),
    ("risks", "assessment_rationale", "TEXT DEFAULT '' NOT NULL"),
    ("risks", "last_assessed_at", "TIMESTAMPTZ"),
    ("risk_settings", "severity_bands", "JSONB DEFAULT '{}'::jsonb NOT NULL"),
    ("risk_settings", "matrix_cells", "JSONB DEFAULT '{}'::jsonb NOT NULL"),
    ("risk_settings", "impact_mode", "VARCHAR(16) DEFAULT 'max' NOT NULL"),
    ("incidents", "contained_at", "TIMESTAMPTZ"),
    ("incidents", "customers_affected", "INTEGER"),
    ("incidents", "records_affected", "INTEGER"),
    ("incidents", "personal_data_breach", "BOOLEAN DEFAULT false NOT NULL"),
    ("incidents", "near_miss", "BOOLEAN DEFAULT false NOT NULL"),
    ("key_risk_indicators", "definition", "TEXT DEFAULT '' NOT NULL"),
    ("key_risk_indicators", "numerator", "TEXT DEFAULT '' NOT NULL"),
    ("key_risk_indicators", "denominator", "TEXT DEFAULT '' NOT NULL"),
    ("key_risk_indicators", "data_source", "TEXT DEFAULT '' NOT NULL"),
    ("key_risk_indicators", "indicator_type", "VARCHAR(16)"),
    ("key_risk_indicators", "lower_bound", "NUMERIC(18,4)"),
    ("key_risk_indicators", "upper_bound", "NUMERIC(18,4)"),
    ("key_risk_indicators", "feed_token_hash", "VARCHAR(128) DEFAULT '' NOT NULL"),
    ("policies", "effective_date", "DATE"),
    ("vendors", "legal_name", "VARCHAR(255) DEFAULT '' NOT NULL"),
    ("vendors", "registration_number", "VARCHAR(120) DEFAULT '' NOT NULL"),
    ("vendors", "annual_spend", "NUMERIC(18,2)"),
    ("vendors", "spend_currency", "VARCHAR(3) DEFAULT '' NOT NULL"),
    ("vendors", "inherent_tier", "VARCHAR(16)"),
    ("vendors", "tier_override_reason", "TEXT DEFAULT '' NOT NULL"),
    ("service_contracts", "currency", "VARCHAR(3) DEFAULT '' NOT NULL"),
]

PHASE2_FK_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, target table)
    ("control_audits", "reviewed_by_id", "users"),
    ("control_audits", "raised_issue_id", "issues"),
    ("evidence", "control_audit_id", "control_audits"),
    ("issues", "root_cause_category_id", "lookups"),
    ("issues", "validated_by_id", "users"),
    ("risks", "identified_by_id", "users"),
    ("risks", "last_assessed_by_id", "users"),
    ("regulatory_reports", "regulator_id", "lookups"),
    ("key_risk_indicators", "data_provider_id", "users"),
    ("key_risk_indicators", "appetite_id", "risk_appetites"),
    ("policies", "approving_authority_id", "committees"),
    ("policies", "supersedes_id", "policies"),
    ("vendors", "relationship_owner_id", "users"),
    ("vendors", "data_classification_id", "lookups"),
    ("outsourcing_arrangements", "owner_id", "users"),
    ("outsourcing_arrangements", "country_id", "lookups"),
]

#: Date columns that become timezone-aware timestamps: (table, column, time of day the
#: stored date is taken to mean). A regulator's clock runs in hours, not days. Existing
#: dates are read in Asia/Karachi, the default organisation timezone; a deadline keeps
#: its whole day, so no deadline moves earlier.
PHASE2_TIMESTAMP_COLUMNS: list[tuple[str, str, str]] = [
    ("incidents", "occurred_at", "00:00"),
    ("incidents", "detected_at", "00:00"),
    ("incidents", "resolved_at", "00:00"),
    ("regulatory_reports", "deadline", "23:59"),
    ("regulatory_reports", "submitted_at", "00:00"),
]

#: New enum values: (type, value, position clause).
PHASE2_ENUM_VALUES: list[tuple[str, str, str]] = [
    ("test_result", "passed_with_exceptions", "AFTER 'passed'"),
    ("review_frequency", "daily", "BEFORE 'fortnightly'"),
    ("review_frequency", "weekly", "BEFORE 'fortnightly'"),
    ("kri_direction", "within_range", ""),
]


def phase2_ddl_statements() -> list[str]:
    """Idempotent DDL for phase 2 on pre-existing tables. New tables (link tables, risk
    appetite/impact/actions, KRI escalations, vendor certifications, issue date changes)
    come from ``create_all``."""
    statements: list[str] = []
    for type_name, value, position in PHASE2_ENUM_VALUES:
        statements.append(
            f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}' {position}".rstrip()
        )
    for table, col, ddl in PHASE2_COLUMNS:
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    # Existing tests were added as "legacy" above; tests recorded from now on need review.
    statements.append("ALTER TABLE control_audits ALTER COLUMN review_status SET DEFAULT 'pending'")
    for table, col, target in PHASE2_FK_COLUMNS:
        name = f"fk_{table}_{col}"[:63]
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} UUID")
        statements.append(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({col}) REFERENCES {target}(id) ON DELETE SET NULL NOT VALID; "
            "END IF; END $$;"
        )
        statements.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})")
    for table, col, time_of_day in PHASE2_TIMESTAMP_COLUMNS:
        statements.append(
            "DO $$ BEGIN IF (SELECT data_type FROM information_schema.columns "
            f"WHERE table_schema = 'public' AND table_name = '{table}' AND column_name = '{col}') = 'date' "
            f"THEN ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMPTZ USING "
            f"(({col} + time '{time_of_day}')::timestamp AT TIME ZONE 'Asia/Karachi'); "
            "END IF; END $$;"
        )
    return statements


# --- product review, phase 3: differentiate -------------------------------------------
PHASE3_COLUMNS: list[tuple[str, str, str]] = [
    ("risks", "level", "INTEGER"),
    ("notifications", "role_name", "VARCHAR(64) DEFAULT '' NOT NULL"),
    ("tenant_settings", "enabled_modules", "JSONB"),
    ("tenant_settings", "onboarding_completed_at", "TIMESTAMPTZ"),
    ("committees", "board_pack_days_before", "INTEGER"),
    ("connectors", "ingest_token_hash", "VARCHAR(128) DEFAULT '' NOT NULL"),
]

PHASE3_FK_COLUMNS: list[tuple[str, str, str, str]] = [
    # (table, column, target, on delete)
    ("risks", "parent_id", "risks", "SET NULL"),
    ("notifications", "user_id", "users", "CASCADE"),
]


def phase3_ddl_statements() -> list[str]:
    """Idempotent DDL for phase 3 on pre-existing tables; new tables (risk proposals,
    action tokens, board packs) come from ``create_all``."""
    statements: list[str] = []
    for table, col, ddl in PHASE3_COLUMNS:
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    for table, col, target, on_delete in PHASE3_FK_COLUMNS:
        name = f"fk_{table}_{col}"[:63]
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} UUID")
        statements.append(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({col}) REFERENCES {target}(id) ON DELETE {on_delete} NOT VALID; "
            "END IF; END $$;"
        )
        statements.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})")
    statements.append("CREATE INDEX IF NOT EXISTS ix_risks_level ON risks (level)")
    return statements


# --- product review re-check (17 Sep): finish the last findings ---------------------------
RECHECK_COLUMNS: list[tuple[str, str, str]] = [
    # Natural sort for clause references (A.5.2 before A.5.10), filled on write + boot.
    ("requirements", "reference_sort_key", "VARCHAR(255) DEFAULT '' NOT NULL"),
    # Comma-separated asset kinds a scenario applies to (network device, payment system…).
    # Empty = every asset of the scenario's classes.
    ("risk_scenario_templates", "asset_kinds", "VARCHAR(255) DEFAULT '' NOT NULL"),
    # Severity → longest allowed review frequency, e.g. {"critical": "monthly"}.
    ("risk_settings", "review_cadence", "JSONB DEFAULT '{}'::jsonb NOT NULL"),
    # Roles that must use MFA in this organisation. NULL = the deployment default.
    ("tenant_settings", "mfa_required_roles", "JSONB"),
    ("outsourcing_arrangements", "substitutability", "VARCHAR(16) DEFAULT '' NOT NULL"),
    ("outsourcing_arrangements", "concentration_level", "VARCHAR(16) DEFAULT '' NOT NULL"),
]

RECHECK_FK_COLUMNS: list[tuple[str, str, str, str]] = [
    # A candidate made from a pre-queue generated risk remembers the archived original.
    ("risk_proposals", "source_risk_id", "risks", "SET NULL"),
]


def recheck_ddl_statements() -> list[str]:
    """Idempotent DDL for the 17 September re-check fixes."""
    statements: list[str] = []
    for table, col, ddl in RECHECK_COLUMNS:
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    for table, col, target, on_delete in RECHECK_FK_COLUMNS:
        name = f"fk_{table}_{col}"[:63]
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} UUID")
        statements.append(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({col}) REFERENCES {target}(id) ON DELETE {on_delete} NOT VALID; "
            "END IF; END $$;"
        )
        statements.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})")
    statements.append(
        "CREATE INDEX IF NOT EXISTS ix_requirements_reference_sort_key "
        "ON requirements (framework_id, reference_sort_key)"
    )
    statements.extend(tag_name_unique_statements())
    statements.extend(capital_snapshot_ddl_statements())
    statements.extend(vuln_acceptance_ddl_statements())
    return statements


# Tags that differ only by case or spacing ("KYC", " kyc ") are one tag: the oldest keeps
# its id and the others' assignments move onto it, then the index keeps it that way.
# Merge before trimming — trimming first would collide on the exact-name constraint.
_TAG_KEY = "lower(btrim(regexp_replace(name, '\\s+', ' ', 'g')))"
_TAG_DUPLICATES = (
    "SELECT id, first_value(id) OVER ("
    f"PARTITION BY tenant_id, {_TAG_KEY} ORDER BY created_at, id) AS keep FROM tags"
)


def tag_name_unique_statements() -> list[str]:
    """Idempotent: merge case/spacing duplicates, normalise names, add the unique index."""
    return [
        "UPDATE entity_tags et SET tag_id = d.keep "
        f"FROM ({_TAG_DUPLICATES}) d WHERE et.tag_id = d.id AND d.id <> d.keep "
        "AND NOT EXISTS (SELECT 1 FROM entity_tags x WHERE x.tag_id = d.keep "
        "AND x.entity_type = et.entity_type AND x.entity_id = et.entity_id)",
        f"DELETE FROM tags t USING ({_TAG_DUPLICATES}) d WHERE t.id = d.id AND d.id <> d.keep",
        "UPDATE tags SET name = btrim(regexp_replace(name, '\\s+', ' ', 'g')) "
        "WHERE name <> btrim(regexp_replace(name, '\\s+', ' ', 'g'))",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_tenant_lower_name ON tags (tenant_id, lower(name))",
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


# A final SMA capital calculation freezes the exchange rate, bucket edges and figures it
# used (models.scenario.CapitalCalculation, migration 0041_capital_snapshot).
CAPITAL_SNAPSHOT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("final_at", "TIMESTAMP WITH TIME ZONE"),
    ("final_by", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ("final_fx_factor", "NUMERIC(24, 10)"),
    ("final_bucket_1", "NUMERIC(24, 2)"),
    ("final_bucket_2", "NUMERIC(24, 2)"),
    ("final_basis", "TEXT NOT NULL DEFAULT ''"),
    ("final_bucket", "INTEGER"),
    ("final_bic", "NUMERIC(24, 2)"),
    ("final_loss_component", "NUMERIC(24, 2)"),
    ("final_ilm", "NUMERIC(12, 6)"),
    ("final_orc", "NUMERIC(24, 2)"),
)


def capital_snapshot_ddl_statements() -> list[str]:
    """Idempotent DDL: the frozen-basis columns on ``capital_calculations``."""
    return [
        f"ALTER TABLE capital_calculations ADD COLUMN IF NOT EXISTS {col} {ddl}"
        for col, ddl in CAPITAL_SNAPSHOT_COLUMNS
    ]


# --- delegation-of-authority limits on decisions that carry an amount (0040) ----------
#: Categories of the authority matrix the GRC decisions are checked against
#: (services.authority_limits), added to the pre-existing ``authority_category`` type.
AUTHORITY_CATEGORY_VALUES: tuple[str, ...] = ("exception", "operational_loss", "outsourcing")

AUTHORITY_AMOUNT_COLUMNS: list[tuple[str, str, str]] = [
    # The exposure a risk acceptance accepts, fixed when it is requested.
    ("risk_acceptances", "exposure_amount", "NUMERIC(18,2)"),
    ("risk_acceptances", "exposure_currency", "VARCHAR(8) DEFAULT '' NOT NULL"),
    ("risk_acceptances", "exposure_basis", "VARCHAR(40) DEFAULT '' NOT NULL"),
    # The exposure an exception leaves uncovered.
    ("exceptions", "exposure_amount", "NUMERIC(18,2)"),
    ("exceptions", "exposure_currency", "VARCHAR(8) DEFAULT '' NOT NULL"),
]


def authority_amount_ddl_statements() -> list[str]:
    """Idempotent DDL for authority-matrix limits: the new categories and the amounts.

    ``ALTER TYPE ... ADD VALUE IF NOT EXISTS`` is legal inside a transaction on
    PostgreSQL 12+ as long as the new value is not used in the same transaction."""
    statements = [
        f"ALTER TYPE authority_category ADD VALUE IF NOT EXISTS '{value}'"
        for value in AUTHORITY_CATEGORY_VALUES
    ]
    statements.extend(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}"
        for table, col, ddl in AUTHORITY_AMOUNT_COLUMNS
    )
    return statements


# --- risk acceptance of a vulnerability finding (0042) ---------------------------------
#: The request and decision that move a finding to ``risk_accepted``
#: (models.vulnerability.VulnFinding, api.v1.vulnerability, migration 0042).
VULN_ACCEPTANCE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("acceptance_status", "VARCHAR(16) NOT NULL DEFAULT ''"),
    ("acceptance_reason", "TEXT NOT NULL DEFAULT ''"),
    ("acceptance_until", "DATE"),
    ("acceptance_requested_at", "TIMESTAMP WITH TIME ZONE"),
    ("acceptance_decided_at", "TIMESTAMP WITH TIME ZONE"),
    ("acceptance_decision_note", "TEXT NOT NULL DEFAULT ''"),
)
VULN_ACCEPTANCE_USER_COLUMNS: tuple[str, ...] = ("acceptance_requested_by_id", "acceptance_decided_by_id")


def vuln_acceptance_ddl_statements() -> list[str]:
    """Idempotent DDL: the risk-acceptance columns on ``vuln_findings``."""
    statements = [
        f"ALTER TABLE vuln_findings ADD COLUMN IF NOT EXISTS {col} {ddl}"
        for col, ddl in VULN_ACCEPTANCE_COLUMNS
    ]
    for col in VULN_ACCEPTANCE_USER_COLUMNS:
        name = f"fk_vuln_findings_{col}"[:63]
        statements.append(f"ALTER TABLE vuln_findings ADD COLUMN IF NOT EXISTS {col} UUID")
        statements.append(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN ALTER TABLE vuln_findings ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({col}) REFERENCES users(id) ON DELETE SET NULL NOT VALID; "
            "END IF; END $$;"
        )
    statements.append(
        "CREATE INDEX IF NOT EXISTS ix_vuln_findings_acceptance_status ON vuln_findings (acceptance_status)"
    )
    return statements
