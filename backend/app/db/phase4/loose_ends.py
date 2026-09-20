"""Phase 4A — loose ends from the 17 September re-check.

One new table: ``tenant_computed_cache`` (``models.computed_cache``), which holds the
pending clause-suggestion count so the controls, compliance and dashboard hints stop
rescanning up to 1,000 controls on every page load. Tenant-scoped (RLS). No column
changes, so ``ddl_statements`` is empty.
"""
from __future__ import annotations

TABLES: tuple[str, ...] = ("tenant_computed_cache",)


def ddl_statements() -> list[str]:
    return []
