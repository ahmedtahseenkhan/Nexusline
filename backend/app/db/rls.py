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
    "asset_tags",
    "asset_dependencies",
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
    "regulatory_reports",
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
    "auditable_units",
    "audit_engagements",
    "audit_procedures",
    "audit_findings",
    "shariah_rulings",
    "islamic_products",
    "shariah_reviews",
    "shariah_findings",
    "charity_disbursements",
    "rcsa_assessments",
    "rcsa_risks",
    "key_risk_indicators",
    "kri_measurements",
    "loss_events",
    "screening_cases",
    "suspicious_activity_reports",
    "aml_risk_assessments",
    # Banking-productionization modules
    "issues",
    "issue_actions",
    "issue_updates",
    "regulatory_changes",
    "obligations",
    "regulatory_returns",
    "icfr_processes",
    "icfr_controls",
    "icfr_tests",
    "icfr_deficiencies",
    "bia_assessments",
    "bia_dependencies",
    "fraud_risks",
    "fraud_cases",
    "fraud_control_checks",
    "authority_matrix",
    "dual_control_rules",
    "scenario_analyses",
    "capital_calculations",
    "whistleblowing_reports",
    "whistleblowing_updates",
    "vuln_findings",
    "patch_records",
    "esg_assessments",
    "environmental_risk_ratings",
    "model_inventory",
    "model_validations",
    "declaration_campaigns",
    "declarations",
    "committees",
    "committee_meetings",
    "meeting_decisions",
    "dpias",
    "dsars",
    "data_breaches",
    "consent_records",
    "outsourcing_arrangements",
    "outsourcing_reviews",
    "connectors",
    "automated_control_tests",
    "control_test_runs",
    "risk_quantifications",
    "ai_extractions",
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
    "approval_actions",
    "custom_fields",
    "custom_field_values",
    "dashboard_widgets",
    "comments",
    "tags",
    "entity_tags",
    "attachments",
    "stored_files",
    "webhooks",
    "webhook_deliveries",
    "status_rules",
    "attestations",
    "saved_filters",
    "sso_configs",
    "ldap_configs",
]

_POLICY = "tenant_isolation"
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def rls_ddl_statements() -> list[str]:
    """The full list of RLS DDL statements as plain SQL strings.

    Shared by the async boot path (``apply_rls_policies``) and the synchronous
    Alembic baseline migration, so the policy definition lives in exactly one place.
    """
    statements: list[str] = []
    for table in TENANT_SCOPED_TABLES:
        statements.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        statements.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        statements.append(f"DROP POLICY IF EXISTS {_POLICY} ON {table}")
        statements.append(
            f"CREATE POLICY {_POLICY} ON {table} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )
    return statements


async def apply_rls_policies(conn: AsyncConnection) -> None:
    for statement in rls_ddl_statements():
        await conn.execute(text(statement))


async def _main() -> None:
    from app.core.database import engine

    async with engine.begin() as conn:
        await apply_rls_policies(conn)
    await engine.dispose()
    print(f"Applied RLS policies to {len(TENANT_SCOPED_TABLES)} tables.")


if __name__ == "__main__":
    asyncio.run(_main())
