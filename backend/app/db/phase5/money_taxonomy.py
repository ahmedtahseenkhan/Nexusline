"""Phase 5 schema for decisions 4 and 5 (reporting currency, Basel level-2 event types).

* ``fx_rates`` — new table, created from model metadata (``app.models.fx``) with its
  ``created_by_id`` foreign key, so it needs no ALTER.
* ``loss_events.basel_event_type_l2`` — the Basel II level-2 category. Existing events stay
  blank: nothing reliable says which level-2 category an old event was, so none is guessed.
* ``outsourcing_arrangements.contract_value`` / ``contract_currency`` — the value of the
  arrangement in its own currency (blank = reporting currency). Owner and country
  already exist as ``owner_id`` / ``country_id`` (phase 2).
"""
from __future__ import annotations

TABLES: tuple[str, ...] = ("fx_rates",)

#: (table, column, DDL type and default)
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("loss_events", "basel_event_type_l2", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("outsourcing_arrangements", "contract_value", "NUMERIC(18, 2)"),
    ("outsourcing_arrangements", "contract_currency", "VARCHAR(3) NOT NULL DEFAULT ''"),
)


def ddl_statements() -> list[str]:
    statements: list[str] = []
    for table, col, ddl in COLUMNS:
        statements.append(f"ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    statements.append(
        "CREATE INDEX IF NOT EXISTS ix_loss_events_basel_event_type_l2 ON loss_events (basel_event_type_l2)"
    )
    statements.append(
        "CREATE INDEX IF NOT EXISTS ix_fx_rates_lookup "
        "ON fx_rates (tenant_id, reporting_currency, currency, effective_date)"
    )
    return statements
