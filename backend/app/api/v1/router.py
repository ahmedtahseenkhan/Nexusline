"""Aggregate all v1 routers.

Licensable modules are registered through :func:`_gated`, which attaches a
``require_module(<key>)`` dependency so a disabled/unlicensed module rejects API
calls with 403 — hiding it in the UI alone is not enough. Keys must exist in
``app.core.modules.MODULES``; core platform routers register plainly.
"""
from fastapi import APIRouter, Depends

from app.services.modules import require_module

from app.api.v1 import (
    access_reviews,
    ai_assist,
    aml,
    approvals,
    assessments,
    attestations,
    assets,
    audit,
    authority,
    bia,
    versions,
    auth,
    awareness,
    collab,
    compliance,
    continuity,
    controls,
    custom_fields,
    content_library,
    dashboard,
    dataio,
    data_protection,
    declaration,
    esg,
    evidence,
    exceptions,
    filters,
    fraud,
    goals,
    governance,
    icfr,
    incidents,
    integrations,
    internal_audit,
    issues,
    ldap,
    model_risk,
    notifications,
    operational_risk,
    organization,
    outsourcing,
    pdf,
    policies,
    privacy,
    projects,
    regulatory,
    regulatory_change,
    reports,
    risk_program,
    risk_quant,
    risks,
    scenario,
    search,
    shariah,
    sso,
    system,
    status_rules,
    threats,
    users,
    vendors,
    vulnerability,
    webhooks,
    whistleblowing,
)

api_router = APIRouter(prefix="/api/v1")


def _gated(router, module_key: str) -> None:
    api_router.include_router(router, dependencies=[Depends(require_module(module_key))])


api_router.include_router(auth.router)
api_router.include_router(sso.router)
api_router.include_router(ldap.router)
api_router.include_router(dashboard.router)
api_router.include_router(risks.router)
api_router.include_router(risk_program.router)
api_router.include_router(threats.router)
api_router.include_router(controls.router)
api_router.include_router(assets.router)
api_router.include_router(assets.labels_router)
api_router.include_router(assets.tags_router)
api_router.include_router(assets.media_types_router)
api_router.include_router(assets.class_router)
api_router.include_router(compliance.router)
api_router.include_router(evidence.router)
api_router.include_router(exceptions.router)
api_router.include_router(projects.router)
api_router.include_router(goals.router)
_gated(internal_audit.router, "internal_audit")
_gated(shariah.router, "shariah")
_gated(operational_risk.router, "operational_risk")
_gated(aml.router, "aml")
# --- Banking-productionization modules (gap-analysis build) ---
api_router.include_router(issues.router)
_gated(regulatory_change.router, "regulatory_change")
_gated(icfr.router, "icfr")
_gated(bia.router, "bia")
_gated(fraud.router, "fraud")
_gated(authority.router, "authority")
_gated(scenario.router, "scenario_analysis")
_gated(whistleblowing.router, "whistleblowing")
_gated(vulnerability.router, "vulnerability")
_gated(esg.router, "esg")
_gated(model_risk.router, "model_risk")
_gated(declaration.router, "declarations")
_gated(governance.router, "governance_meetings")
_gated(data_protection.router, "data_protection")
_gated(outsourcing.router, "outsourcing")
_gated(integrations.router, "integrations_ccm")
api_router.include_router(content_library.router)
_gated(risk_quant.router, "risk_quantification")
_gated(ai_assist.router, "ai_assist")
_gated(continuity.router, "continuity")
_gated(privacy.router, "privacy")
_gated(access_reviews.router, "access_reviews")
_gated(awareness.router, "awareness")
api_router.include_router(notifications.router)
api_router.include_router(approvals.router)
api_router.include_router(custom_fields.router)
api_router.include_router(reports.router)
api_router.include_router(pdf.router)
api_router.include_router(collab.router)
api_router.include_router(webhooks.router)
api_router.include_router(status_rules.router)
api_router.include_router(attestations.router)
api_router.include_router(filters.router)
api_router.include_router(incidents.router)
api_router.include_router(regulatory.router)
api_router.include_router(policies.router)
api_router.include_router(vendors.router)
api_router.include_router(vendors.types_router)
api_router.include_router(assessments.router)
api_router.include_router(organization.router)
api_router.include_router(audit.router)
api_router.include_router(versions.router)
api_router.include_router(users.router)
api_router.include_router(dataio.router)
api_router.include_router(search.router)
api_router.include_router(system.router)
