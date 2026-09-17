"""Phase 4D — continuous control monitoring that runs.

No new tables: executable test definitions, encrypted connector secrets and run details
are columns on the existing CCM tables, plus one signal column on ``controls`` and one
issue source. Every statement is idempotent (``ADD COLUMN IF NOT EXISTS``, guarded
constraints added ``NOT VALID`` as in ``schema_patches.recheck_ddl_statements``), so boot
(``init_db``) and migration ``0034`` can both run it on any database.
"""
from __future__ import annotations

TABLES: tuple[str, ...] = ()

#: (table, column, DDL type + default)
COLUMNS: tuple[tuple[str, str, str], ...] = (
    # connectors
    ("connectors", "config", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ("connectors", "secrets_encrypted", "TEXT NOT NULL DEFAULT ''"),
    ("connectors", "secret_keys", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ("connectors", "timeout_seconds", "INTEGER NOT NULL DEFAULT 30"),
    ("connectors", "last_test_at", "TIMESTAMPTZ"),
    ("connectors", "last_test_ok", "BOOLEAN"),
    ("connectors", "last_test_message", "TEXT NOT NULL DEFAULT ''"),
    # automated_control_tests
    ("automated_control_tests", "check_type", "VARCHAR(48) NOT NULL DEFAULT 'manual'"),
    ("automated_control_tests", "parameters", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ("automated_control_tests", "threshold_max_failures", "INTEGER"),
    ("automated_control_tests", "threshold_max_percent", "NUMERIC(5, 2)"),
    ("automated_control_tests", "population_description", "TEXT NOT NULL DEFAULT ''"),
    ("automated_control_tests", "pass_criterion", "TEXT NOT NULL DEFAULT ''"),
    ("automated_control_tests", "kri_metric", "VARCHAR(24) NOT NULL DEFAULT 'exceptions'"),
    ("automated_control_tests", "last_run_at", "TIMESTAMPTZ"),
    ("automated_control_tests", "failing_since", "DATE"),
    ("automated_control_tests", "last_error", "TEXT NOT NULL DEFAULT ''"),
    # control_test_runs
    ("control_test_runs", "source", "VARCHAR(16) NOT NULL DEFAULT 'manual'"),
    ("control_test_runs", "started_at", "TIMESTAMPTZ"),
    ("control_test_runs", "duration_ms", "INTEGER"),
    ("control_test_runs", "population_size", "INTEGER"),
    ("control_test_runs", "exceptions_count", "INTEGER"),
    ("control_test_runs", "exceptions_sample", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ("control_test_runs", "details", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ("control_test_runs", "metric_value", "NUMERIC(18, 4)"),
    ("control_test_runs", "error_message", "TEXT NOT NULL DEFAULT ''"),
    # controls: the monitoring signal reliance reads
    ("controls", "monitoring_failing_since", "DATE"),
)

#: (table, column, referenced table, ON DELETE)
FK_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("automated_control_tests", "control_id", "controls", "SET NULL"),
    ("automated_control_tests", "kri_id", "key_risk_indicators", "SET NULL"),
    ("automated_control_tests", "issue_id", "issues", "SET NULL"),
    ("control_test_runs", "evidence_id", "evidence", "SET NULL"),
    ("control_test_runs", "issue_id", "issues", "SET NULL"),
    ("control_test_runs", "kri_measurement_id", "kri_measurements", "SET NULL"),
)

#: Link each existing test to its control by reference, when exactly one live control of
#: the same organisation carries it. Tests already linked, or ambiguous, are left alone.
BACKFILL_CONTROL_ID = (
    "UPDATE automated_control_tests t SET control_id = m.control_id FROM ("
    " SELECT t2.id AS test_id, min(c.id::text)::uuid AS control_id"
    " FROM automated_control_tests t2 JOIN controls c"
    "  ON c.tenant_id = t2.tenant_id AND c.deleted = false"
    "  AND lower(trim(c.reference)) = lower(trim(t2.control_ref))"
    " WHERE t2.control_id IS NULL AND trim(coalesce(t2.control_ref, '')) <> ''"
    " GROUP BY t2.id HAVING count(*) = 1"
    ") m WHERE t.id = m.test_id AND t.control_id IS NULL"
)


def ddl_statements() -> list[str]:
    statements: list[str] = [
        "ALTER TYPE issue_source ADD VALUE IF NOT EXISTS 'ccm'",
        "ALTER TYPE connector_type ADD VALUE IF NOT EXISTS 'vuln_scanner'",
    ]
    for table, col, ddl in COLUMNS:
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    for table, col, target, on_delete in FK_COLUMNS:
        name = f"fk_{table}_{col}"[:63]
        statements.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} UUID")
        statements.append(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({col}) REFERENCES {target}(id) ON DELETE {on_delete} NOT VALID; "
            "END IF; END $$;"
        )
        statements.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})")
    statements.append(BACKFILL_CONTROL_ID)
    return statements
