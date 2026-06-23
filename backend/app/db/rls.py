"""PostgreSQL Row-Level Security policies for tenant isolation.

Each tenant-scoped table gets a policy that only exposes rows whose ``tenant_id``
matches the transaction-local GUC ``app.current_tenant`` (set in
``app.core.database``). ``FORCE ROW LEVEL SECURITY`` ensures the policy applies even
to the table owner, so a buggy or compromised application query still cannot cross
tenants.

When the GUC is empty/unset, ``NULLIF(..., '')::uuid`` evaluates to NULL and the
comparison yields no rows — i.e. the system fails *closed*.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Tables carrying a tenant_id that must be isolated.
TENANT_SCOPED_TABLES: list[str] = [
    "roles",
    "users",
    "audit_logs",
    "record_versions",
    "assets",
    "asset_labels",
    "asset_media_types",
    "asset_classification_types",
    "asset_classifications",
    "asset_reviews",
    "controls",
    "control_audits",
    "control_maintenances",
    "threats",
    "vulnerabilities",
    "risks",
    "risk_acceptances",
    "risk_settings",
    "frameworks",
    "requirements",
    "compliance_findings",
    "evidence",
    "incidents",
    "incident_stages",
    "policies",
    "policy_acknowledgments",
    "policy_reviews",
    "vendors",
    "vendor_types",
    "service_contracts",
    "business_units",
    "processes",
    "legals",
    "exceptions",
    "projects",
    "project_tasks",
    "project_expenses",
    "goals",
    "goal_audits",
    "questionnaires",
    "questions",
    "question_options",
    "assessments",
    "assessment_answers",
    "assessment_findings",
    "continuity_plans",
    "continuity_tasks",
    "continuity_tests",
    "processing_activities",
    "access_reviews",
    "access_review_items",
    "awareness_programs",
    "awareness_questions",
    "awareness_options",
    "training_records",
    "notifications",
    "notification_views",
    "approval_requests",
    "custom_fields",
    "custom_field_values",
    "dashboard_widgets",
    "comments",
    "tags",
    "entity_tags",
    "attachments",
    "webhooks",
    "webhook_deliveries",
    "status_rules",
    "attestations",
    "saved_filters",
    "sso_configs",
]

_POLICY = "tenant_isolation"
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


async def apply_rls_policies(conn: AsyncConnection) -> None:
    for table in TENANT_SCOPED_TABLES:
        await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        await conn.execute(text(f"DROP POLICY IF EXISTS {_POLICY} ON {table}"))
        await conn.execute(
            text(
                f"CREATE POLICY {_POLICY} ON {table} "
                f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
            )
        )


async def _main() -> None:
    from app.core.database import engine

    async with engine.begin() as conn:
        await apply_rls_policies(conn)
    await engine.dispose()
    print(f"Applied RLS policies to {len(TENANT_SCOPED_TABLES)} tables.")


if __name__ == "__main__":
    asyncio.run(_main())
