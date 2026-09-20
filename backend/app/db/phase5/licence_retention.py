"""Phase 5 schema for decisions 1–3 (licence, retention, MFA).

Licence state is deployment-wide and computed from the licence file, so it needs no table;
per-stage warning de-duplication uses the notification ``dedup_key`` and the audit trail.
Retention only moves its column default to ten years (existing organisations still on 90
days are moved by the boot repair ``data_repairs.upgrade_retention_default``).
"""
from __future__ import annotations

TABLES: tuple[str, ...] = ()


def ddl_statements() -> list[str]:
    return [
        "ALTER TABLE IF EXISTS tenant_settings ALTER COLUMN retention_days SET DEFAULT 3650",
    ]
