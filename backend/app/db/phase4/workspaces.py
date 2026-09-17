"""Phase 4B schema: workspaces, period snapshots, committee members, board-pack sign-off.

New tables come from model metadata (``TABLES``); ``ddl_statements`` adds the new columns
to existing tables. Every statement is idempotent: boot runs them on each start and
migration 0034 once.
"""
from __future__ import annotations

TABLES: tuple[str, ...] = (
    "metric_snapshots",
    "user_workspace_preferences",
    "committee_members",
    "board_pack_brandings",
)

#: (table, column, DDL type and default)
COLUMNS: list[tuple[str, str, str]] = [
    ("committees", "board_pack_sections", "JSONB"),
    # Existing packs were produced before sign-off existed and have already gone to their
    # committees: they arrive as released. The default for new packs is draft (below).
    ("board_packs", "review_state", "VARCHAR(16) DEFAULT 'released' NOT NULL"),
    ("board_packs", "contributor_ids", "JSONB DEFAULT '[]'::jsonb NOT NULL"),
    ("board_packs", "reviewed_at", "TIMESTAMPTZ"),
    ("board_packs", "released_at", "TIMESTAMPTZ"),
    ("board_packs", "commentary", "JSONB DEFAULT '{}'::jsonb NOT NULL"),
    ("board_packs", "content", "JSONB"),
    ("board_packs", "basis", "JSONB DEFAULT '{}'::jsonb NOT NULL"),
    ("board_packs", "distribution", "JSONB DEFAULT '[]'::jsonb NOT NULL"),
]

#: (table, column, referenced table, ON DELETE)
FK_COLUMNS: list[tuple[str, str, str, str]] = [
    ("meeting_decisions", "owner_id", "users", "SET NULL"),
    ("board_packs", "reviewed_by_id", "users", "SET NULL"),
    ("board_packs", "released_by_id", "users", "SET NULL"),
]


def ddl_statements() -> list[str]:
    out: list[str] = []
    for table, col, ddl in COLUMNS:
        out.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    out.append("ALTER TABLE board_packs ALTER COLUMN review_state SET DEFAULT 'draft'")
    for table, col, target, on_delete in FK_COLUMNS:
        name = f"fk_{table}_{col}"[:63]
        out.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} UUID")
        out.append(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}') THEN ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({col}) REFERENCES {target}(id) ON DELETE {on_delete} NOT VALID; "
            "END IF; END $$;"
        )
        out.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})")
    out.append(
        "CREATE INDEX IF NOT EXISTS ix_metric_snapshots_tenant_key_as_of "
        "ON metric_snapshots (tenant_id, key, as_of)"
    )
    return out
