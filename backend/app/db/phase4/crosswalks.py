"""Phase 4C — typed crosswalks and shipped crosswalk content.

``requirement_crosswalks`` gains its type (relationship), provenance (origin, source,
content version, confidence, rationale) and review (approved by / at). Existing rows keep
working: the column defaults backfill them as ``manual`` / ``related``. The new
``crosswalk_rejections`` table (created from metadata; RLS via ``rls.py``) records
shipped rows an organisation rejected so a content upgrade never re-adds them.
Every statement is idempotent.
"""
from __future__ import annotations

TABLES: tuple[str, ...] = ("crosswalk_rejections",)

#: (column, DDL type + default)
COLUMNS: tuple[tuple[str, str], ...] = (
    ("relationship", "VARCHAR(16) NOT NULL DEFAULT 'related'"),
    ("rationale", "TEXT NOT NULL DEFAULT ''"),
    ("source", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("content_version", "VARCHAR(32) NOT NULL DEFAULT ''"),
    ("confidence", "DOUBLE PRECISION"),
    ("origin", "VARCHAR(16) NOT NULL DEFAULT 'manual'"),
    ("approved_by", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("approved_by_id", "UUID"),
    ("approved_at", "TIMESTAMPTZ"),
    ("created_at", "TIMESTAMPTZ DEFAULT now()"),
)


def ddl_statements() -> list[str]:
    out = [
        f"ALTER TABLE requirement_crosswalks ADD COLUMN IF NOT EXISTS {name} {ddl}"
        for name, ddl in COLUMNS
    ]
    # Backfill anything a partial earlier run left empty (NOT NULL defaults cover new rows).
    out.append(
        "UPDATE requirement_crosswalks SET relationship = 'related' "
        "WHERE relationship IS NULL OR relationship NOT IN "
        "('equivalent', 'subset', 'superset', 'intersects', 'related')"
    )
    out.append(
        "UPDATE requirement_crosswalks SET origin = 'manual' "
        "WHERE origin IS NULL OR origin NOT IN ('shipped', 'accepted', 'manual')"
    )
    out.append(
        "CREATE INDEX IF NOT EXISTS ix_requirement_crosswalks_related "
        "ON requirement_crosswalks (related_requirement_id)"
    )
    # Row-level security for the new table (also listed in app/db/rls.py), so a database
    # migrated with 0034 is isolated before the next boot re-applies every policy.
    from app.db.rls import _POLICY, _PREDICATE

    for table in TABLES:
        out.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        out.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        out.append(f"DROP POLICY IF EXISTS {_POLICY} ON {table}")
        out.append(f"CREATE POLICY {_POLICY} ON {table} USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})")
    return out
