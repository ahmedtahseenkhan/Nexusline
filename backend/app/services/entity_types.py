"""Canonical registry of the polymorphic ``entity_type`` strings, with their permissions.

Several cross-cutting surfaces attach to *any* record by a ``(entity_type, entity_id)``
pair rather than a foreign key: comments, tags, attachments and file uploads
(``collab``), the review/attestation cadence (``attestations``), and custom-field values.
Without a registry those strings were unvalidated and unauthorised — a typo silently
created an orphan row, and a user with read-only access to a module could still write to
its records through the shared panel.

This module is the single place that answers two questions:

* **Is this a real entity type?** Anything not listed is rejected, so orphan rows can no
  longer be created by a typo or a crafted request.
* **What may this user do to it?** Each type carries its owning module's read and write
  permission codes, so the shared panels inherit exactly the access rules of the module
  the record belongs to.

Read paths validate the type but deliberately do *not* fail on legacy rows: existing
data written before this registry existed stays visible.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from app.models.identity import User


@dataclass(frozen=True)
class EntitySpec:
    label: str
    read_perm: str
    write_perm: str


def _spec(label: str, module: str, *, read: str | None = None, write: str | None = None) -> EntitySpec:
    return EntitySpec(label=label, read_perm=read or f"{module}:read", write_perm=write or f"{module}:write")


# entity_type -> owning module's permissions. Keep in sync with CUSTOM_FIELD_MODELS in
# models/custom_field.py; that list is a subset of these keys.
ENTITY_TYPES: dict[str, EntitySpec] = {
    # --- core graph ---
    "risk": _spec("Risk", "risk"),
    "control": _spec("Control", "control"),
    "policy": _spec("Policy", "policy"),
    "requirement": _spec("Requirement", "compliance"),
    "framework": _spec("Framework", "compliance"),
    "compliance_finding": _spec("Compliance finding", "compliance"),
    "asset": _spec("Asset", "asset"),
    "incident": _spec("Incident", "incident"),
    "exception": _spec("Exception", "exception"),
    "issue": _spec("Issue", "issue"),
    "evidence": _spec("Evidence", "control"),
    "project": _spec("Project", "project"),
    "goal": _spec("Goal", "goal"),
    "threat": _spec("Threat", "risk"),
    "vulnerability": _spec("Vulnerability", "risk"),
    # --- organization ---
    "business_unit": _spec("Business unit", "org"),
    "process": _spec("Process", "org"),
    "legal": _spec("Legal register entry", "org"),
    "committee": _spec("Committee", "governance"),
    "committee_meeting": _spec("Committee meeting", "governance"),
    "authority_matrix": _spec("Authority matrix", "authority"),
    "dual_control_rule": _spec("Dual-control rule", "authority"),
    # --- third party ---
    "vendor": _spec("Third party", "vendor"),
    "service_contract": _spec("Service contract", "vendor"),
    "outsourcing_arrangement": _spec("Outsourcing arrangement", "outsourcing"),
    "assessment": _spec("Assessment", "assessment"),
    "questionnaire": _spec("Questionnaire", "assessment"),
    # --- assurance ---
    "audit_engagement": _spec("Audit engagement", "internal_audit"),
    "audit_finding": _spec("Audit finding", "internal_audit"),
    "auditable_unit": _spec("Auditable unit", "internal_audit"),
    "access_review": _spec("Access review", "review"),
    "declaration_campaign": _spec("Declaration campaign", "declaration"),
    "icfr_process": _spec("ICFR process", "icfr"),
    "icfr_control": _spec("ICFR control", "icfr"),
    "icfr_deficiency": _spec("ICFR deficiency", "icfr"),
    # --- operational risk ---
    "rcsa_assessment": _spec("RCSA assessment", "oprisk"),
    "key_risk_indicator": _spec("Key risk indicator", "oprisk"),
    "loss_event": _spec("Loss event", "oprisk"),
    "scenario_analysis": _spec("Scenario analysis", "scenario"),
    "risk_quantification": _spec("Risk quantification", "riskquant"),
    "model_inventory": _spec("Model", "modelrisk"),
    "model_validation": _spec("Model validation", "modelrisk"),
    # --- resilience ---
    "continuity_plan": _spec("Continuity plan", "bcp"),
    "bia_assessment": _spec("Business impact analysis", "bia"),
    "vuln_finding": _spec("Vulnerability finding", "vuln"),
    "patch_record": _spec("Patch record", "vuln"),
    # --- privacy & data protection ---
    "processing_activity": _spec("Processing activity", "privacy"),
    "data_breach": _spec("Data breach", "dpo"),
    "dpia": _spec("DPIA", "dpo"),
    "dsar": _spec("Data subject request", "dpo"),
    "consent_record": _spec("Consent record", "dpo"),
    # --- financial crime ---
    "aml_risk_assessment": _spec("AML risk assessment", "aml"),
    "suspicious_activity_report": _spec("SAR / STR", "aml"),
    "screening_case": _spec("Screening case", "aml"),
    "fraud_risk": _spec("Fraud risk", "fraud"),
    "fraud_case": _spec("Fraud case", "fraud"),
    "whistleblowing_report": _spec("Whistleblowing report", "whistle"),
    # --- Islamic banking ---
    "shariah_review": _spec("Shariah review", "shariah"),
    "shariah_ruling": _spec("Shariah ruling", "shariah"),
    "shariah_finding": _spec("Shariah finding", "shariah"),
    "islamic_product": _spec("Islamic product", "shariah"),
    # --- regulatory & reporting ---
    "regulatory_change": _spec("Regulatory change", "regchange"),
    "obligation": _spec("Obligation", "regchange"),
    "regulatory_return": _spec("Regulatory return", "regchange"),
    "regulatory_report": _spec("Regulatory report", "incident"),
    # --- other modules ---
    "awareness_program": _spec("Awareness program", "awareness"),
    "esg_assessment": _spec("ESG assessment", "esg"),
    "environmental_risk_rating": _spec("Environmental risk rating", "esg"),
    "declaration": _spec("Declaration", "declaration"),
    "connector": _spec("Connector", "ccm"),
    "automated_control_test": _spec("Automated control test", "ccm"),
}


def spec(entity_type: str) -> EntitySpec:
    """Look up an entity type, rejecting anything unregistered with a 422."""
    found = ENTITY_TYPES.get(entity_type)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown entity type '{entity_type}'",
        )
    return found


def require_read(user: User, entity_type: str) -> EntitySpec:
    """Validate the type and assert the user may read that module's records."""
    found = spec(entity_type)
    if found.read_perm not in set(user.permission_codes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires permission(s): {found.read_perm}",
        )
    return found


def require_write(user: User, entity_type: str) -> EntitySpec:
    """Validate the type and assert the user may write that module's records.

    This is what stops a read-only user annotating, tagging, attesting or
    custom-fielding a record they can only view.
    """
    found = spec(entity_type)
    if found.write_perm not in set(user.permission_codes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires permission(s): {found.write_perm}",
        )
    return found
