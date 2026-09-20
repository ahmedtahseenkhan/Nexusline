"""Shipped questionnaire templates (product review phase 4E).

Written in our own words for Pakistani banks; none of the text is taken from SIG, CAIQ
or any other licensed questionnaire. Each template is versioned (``version``): installing
one copies it into the organisation as a **draft** questionnaire that the bank can edit
and then publish (``services/questionnaire_versions.install_template``). A later release
that improves a template bumps its version; organisations that installed an older one
keep theirs untouched and can install the new one alongside it.

Scoring convention for due-diligence templates: a *stronger* answer scores *higher*, so a
high percentage is a well-controlled provider, and the bands map low percentages to a
high vendor risk rating. The RCSA template's design / operation questions carry
``config.rcsa_role`` so a run against an RCSA writes each line's self-rating
(``services/questionnaire_workflow.apply_rcsa``).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.questionnaire_logic import CHOICE_TYPES

#: Bands for "higher is better" due-diligence templates: the rating is the vendor risk rating.
DUE_DILIGENCE_BANDS: list[dict[str, Any]] = [
    {"label": "Strong", "min_pct": 80, "rating": "low"},
    {"label": "Adequate", "min_pct": 60, "rating": "medium"},
    {"label": "Weak", "min_pct": 40, "rating": "high"},
    {"label": "Inadequate", "min_pct": 0, "rating": "critical"},
]


# ------------------------------------------------------------------ builders ---
def _opt(value: str, label: str, score: float, *, na: bool = False, flag: str | None = None,
         severity: str = "medium") -> dict[str, Any]:
    return {
        "value": value, "label": label, "score": score, "is_na": na,
        "risk_flag": flag is not None, "finding_title": flag or "", "finding_severity": severity,
    }


def yes_no(key: str, text: str, guidance: str = "", *, weight: float = 1, mandatory: bool = True,
           flag: str | None = None, severity: str = "medium", na: bool = True,
           when: dict[str, Any] | None = None) -> dict[str, Any]:
    """A yes / no (/ not applicable) question where "yes" is the strong answer. ``flag``
    is the finding title a "no" raises."""
    options = [_opt("yes", "Yes", 1), _opt("no", "No", 0, flag=flag, severity=severity)]
    if na:
        options.append(_opt("na", "Not applicable", 0, na=True))
    return {"key": key, "text": text, "guidance": guidance, "type": "yes_no_na", "mandatory": mandatory,
            "weight": weight, "conditions": when or {}, "options": options}


def choice(key: str, text: str, options: list[dict[str, Any]], guidance: str = "", *, weight: float = 1,
           mandatory: bool = True, multiple: bool = False, when: dict[str, Any] | None = None,
           config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"key": key, "text": text, "guidance": guidance,
            "type": "multiple_choice" if multiple else "single_choice", "mandatory": mandatory,
            "weight": weight, "conditions": when or {}, "options": options, "config": config or {}}


def field(key: str, text: str, qtype: str, guidance: str = "", *, mandatory: bool = False,
          when: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"key": key, "text": text, "guidance": guidance, "type": qtype, "mandatory": mandatory,
            "weight": 0, "conditions": when or {}, "options": []}


def when_in(question: str, *values: str) -> dict[str, Any]:
    return {"match": "all", "rules": [{"question": question, "op": "in", "values": list(values)}]}


def section(key: str, title: str, description: str, questions: list[dict[str, Any]],
            when: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"key": key, "title": title, "description": description, "conditions": when or {}, "questions": questions}


# ================================================== SBP outsourcing due diligence ===
_SBP_OUTSOURCING = {
    "key": "sbp-outsourcing-due-diligence",
    "version": 1,
    "name": "SBP outsourcing due diligence",
    "purpose": "vendor_due_diligence",
    "description": (
        "Due diligence on a service provider before and during an outsourcing arrangement, "
        "following the themes of the SBP framework for risk management in outsourcing: "
        "materiality, where data sits, sub-contracting, audit and regulator access, "
        "confidentiality, business continuity and exit. Stronger answers score higher; "
        "the band sets the provider's risk rating."
    ),
    "bands": DUE_DILIGENCE_BANDS,
    "sections": [
        section("provider", "Provider and service", "Who the provider is and what it will do for the bank.", [
            field("legal_name", "Registered legal name of the provider", "text", mandatory=True),
            field("service_scope", "Describe the service provided to the bank", "long_text",
                  "Include the business functions supported and the systems or data involved.", mandatory=True),
            choice("materiality", "How does the bank classify this arrangement?", [
                _opt("material", "Material outsourcing", 0),
                _opt("non_material", "Non-material outsourcing", 0),
                _opt("not_outsourcing", "Not outsourcing (purchase of goods or a one-off service)", 0),
            ], "The bank's outsourcing committee decides materiality; the provider may leave this to the bank.",
                weight=0),
            yes_no("ownership_disclosed", "Has the provider disclosed its ultimate beneficial owners and any related parties in the bank's group?",
                   flag="Provider has not disclosed beneficial ownership or related parties", severity="high", na=False),
            yes_no("financials", "Can the provider share audited financial statements for the last two years?",
                   flag="No audited financial statements available", na=False),
        ]),
        section("data", "Data location and confidentiality", "Where bank and customer data is held and who can see it.", [
            choice("data_access", "What bank data will the provider store, process or be able to see?", [
                _opt("none", "None", 0),
                _opt("internal", "Internal business data only", 0),
                _opt("customer", "Customer data, including personal or account data", 0),
            ], weight=0),
            choice("data_location", "Where will the data be stored or processed, including backups and support access?", [
                _opt("pakistan", "In Pakistan only", 2),
                _opt("abroad_approved", "Outside Pakistan, with the approvals the bank needs", 1),
                _opt("abroad_unapproved", "Outside Pakistan, approvals not yet obtained", 0,
                     flag="Bank data held outside Pakistan without the required approvals", severity="critical"),
            ], "Name the countries and data centres in the comment.", weight=2,
                when=when_in("data_access", "internal", "customer")),
            yes_no("confidentiality_clause", "Will the contract bind the provider and its staff to keep bank and customer information confidential, including after the contract ends?",
                   flag="No enforceable confidentiality obligation", severity="high", na=False, weight=2),
            yes_no("customer_data_segregated", "Is the bank's data logically separated from other clients' data?",
                   flag="Bank data is not separated from other clients' data", severity="high",
                   when=when_in("data_access", "customer")),
            yes_no("breach_notice", "Will the provider tell the bank of any breach of bank data without undue delay, and within 24 hours of discovery?",
                   flag="No commitment to notify the bank of a data breach promptly", severity="high", na=False),
        ]),
        section("subcontracting", "Sub-contracting", "Other firms the provider relies on to deliver the service.", [
            yes_no("uses_subcontractors", "Does the provider use sub-contractors for any part of this service?", na=False, weight=0,
                   mandatory=True),
            field("subcontractor_list", "List each sub-contractor, what it does and where it operates", "long_text",
                  mandatory=True, when=when_in("uses_subcontractors", "yes")),
            yes_no("subcontract_consent", "Will the provider obtain the bank's prior written consent before adding or changing a sub-contractor for a material part of the service?",
                   flag="Sub-contracting without the bank's prior consent", severity="high",
                   when=when_in("uses_subcontractors", "yes")),
            yes_no("subcontract_flowdown", "Do the same confidentiality, audit and regulator-access terms flow down to sub-contractors?",
                   flag="Contract terms do not flow down to sub-contractors",
                   when=when_in("uses_subcontractors", "yes")),
        ]),
        section("oversight", "Audit rights and regulator access", "Whether the bank and the State Bank can inspect the service.", [
            yes_no("audit_rights", "Does the contract give the bank, its internal and external auditors the right to audit the provider's premises, systems and records relating to the service?",
                   flag="No right for the bank to audit the provider", severity="high", na=False, weight=2),
            yes_no("regulator_access", "Will the provider give the State Bank of Pakistan and other regulators of the bank direct access to data, records and premises on request?",
                   flag="No regulator access to the provider's records and premises", severity="critical", na=False, weight=2),
            yes_no("independent_assurance", "Can the provider share an independent assurance report on the controls over this service (for example an ISAE 3402 or SOC report) no older than 12 months?",
                   flag="No recent independent assurance report"),
            field("assurance_report", "Upload the latest assurance report", "file_upload",
                  when=when_in("independent_assurance", "yes")),
            yes_no("reporting", "Will the provider report service levels and incidents to the bank at agreed intervals?",
                   flag="No agreed service and incident reporting", na=False),
        ]),
        section("continuity", "Business continuity and exit", "Keeping the service running, and leaving it safely.", [
            yes_no("bcp_exists", "Does the provider maintain a documented business continuity and disaster recovery plan covering this service?",
                   flag="No business continuity plan for the service", severity="high", na=False, weight=2),
            choice("bcp_tested", "When was that plan last tested?", [
                _opt("12m", "Within the last 12 months", 2),
                _opt("24m", "12 to 24 months ago", 1),
                _opt("never", "More than 24 months ago, or never", 0, flag="Continuity plan not tested in the last two years", severity="high"),
            ], when=when_in("bcp_exists", "yes")),
            field("recovery_time", "Recovery time objective for this service, in hours", "number",
                  when=when_in("bcp_exists", "yes")),
            yes_no("bank_in_tests", "Can the bank take part in, or see the results of, those tests?",
                   flag="Bank cannot take part in or see continuity tests", when=when_in("bcp_exists", "yes")),
            yes_no("exit_support", "Does the contract require the provider to support an orderly exit, returning all data in a usable format and then securely deleting it?",
                   flag="No exit support or data return on termination", severity="high", na=False, weight=2),
            yes_no("termination_rights", "Can the bank terminate the arrangement if the regulator directs it, or if the provider breaches confidentiality or security terms?",
                   flag="Bank cannot terminate on regulatory direction or breach", severity="high", na=False),
        ]),
    ],
}


# ===================================================== cloud service security ===
_CLOUD = {
    "key": "cloud-service-security",
    "version": 1,
    "name": "Cloud service security",
    "purpose": "vendor_due_diligence",
    "description": (
        "Security of a cloud service (SaaS, PaaS or IaaS) the bank intends to use: identity and "
        "access, encryption and key management, logging, data residency, incident notification "
        "and independent certifications. Stronger answers score higher."
    ),
    "bands": DUE_DILIGENCE_BANDS,
    "sections": [
        section("model", "Service model", "What kind of cloud service this is.", [
            choice("service_model", "Which service model applies?", [
                _opt("saas", "Software as a service", 0),
                _opt("paas", "Platform as a service", 0),
                _opt("iaas", "Infrastructure as a service", 0),
            ], weight=0),
            choice("deployment", "How is the service deployed?", [
                _opt("public", "Public cloud, shared infrastructure", 0),
                _opt("dedicated", "Dedicated or private cloud", 0),
            ], weight=0),
        ]),
        section("iam", "Identity and access", "Who can reach bank data, and how access is controlled.", [
            yes_no("sso", "Can bank users sign in through the bank's own identity provider (SAML or OpenID Connect)?",
                   flag="Service cannot use the bank's identity provider",
                   when=when_in("service_model", "saas")),
            yes_no("mfa_admin", "Is multi-factor authentication enforced for every administrator, including the provider's own staff?",
                   flag="Administrators are not required to use multi-factor authentication", severity="high", na=False, weight=2),
            yes_no("privileged_review", "Is the provider's privileged access to customer environments approved per request, logged and reviewed at least quarterly?",
                   flag="Provider privileged access is not controlled and reviewed", severity="high", na=False, weight=2),
            yes_no("rbac", "Can the bank define roles and restrict each user to the data and functions they need?",
                   flag="No role-based access control available to the bank", na=False),
        ]),
        section("crypto", "Encryption and key management", "How bank data is protected at rest and in transit.", [
            yes_no("encrypt_transit", "Is all data in transit encrypted with TLS 1.2 or later?",
                   flag="Data in transit not protected with current TLS", severity="high", na=False, weight=2),
            yes_no("encrypt_rest", "Is all bank data encrypted at rest, including backups?",
                   flag="Data at rest or backups not encrypted", severity="high", na=False, weight=2),
            choice("key_control", "Who controls the encryption keys?", [
                _opt("bank_hsm", "The bank, in its own HSM or an external key manager", 3),
                _opt("bank_kms", "The bank, through a customer-managed key in the provider's key service", 2),
                _opt("provider", "The provider only", 0, flag="Encryption keys controlled only by the provider", severity="medium"),
            ], weight=2),
            yes_no("key_rotation", "Are keys rotated at least annually and on suspected compromise?",
                   flag="No key rotation"),
        ]),
        section("logging", "Logging and monitoring", "Evidence of what happened, available to the bank.", [
            yes_no("audit_logs", "Does the service record administrator and user activity in tamper-resistant logs?",
                   flag="No tamper-resistant activity logs", severity="high", na=False, weight=2),
            field("log_retention_days", "How many days are those logs kept?", "number", mandatory=True,
                  when=when_in("audit_logs", "yes")),
            yes_no("siem_export", "Can the bank export the logs to its own security monitoring (SIEM) in near real time?",
                   flag="Logs cannot be sent to the bank's monitoring"),
        ]),
        section("residency", "Data residency", "Where the service keeps bank data.", [
            field("regions", "List every country and region where bank data or backups are held", "long_text", mandatory=True),
            yes_no("region_pinning", "Can the bank restrict storage and processing to regions it approves?",
                   flag="Bank cannot restrict data to approved regions", severity="high", na=False, weight=2),
            yes_no("support_access_abroad", "Do support staff outside Pakistan have any access to bank data?", na=False, weight=0),
            yes_no("support_access_controlled", "Is that access approved per request, time-limited and logged?",
                   flag="Offshore support access to bank data is not controlled", severity="high",
                   when=when_in("support_access_abroad", "yes")),
        ]),
        section("incidents", "Incident notification", "What the bank hears, and when.", [
            choice("incident_notice", "How soon will the provider notify the bank of a security incident affecting its data?", [
                _opt("24h", "Within 24 hours of discovery", 2),
                _opt("72h", "Within 72 hours", 1),
                _opt("none", "No committed time", 0, flag="No committed incident notification time", severity="high"),
            ], weight=2),
            yes_no("forensics", "Will the provider share root-cause findings and support the bank's own investigation?",
                   flag="No support for the bank's incident investigation", na=False),
        ]),
        section("certifications", "Certifications", "Independent evidence of the provider's security.", [
            choice("certs", "Which current certifications or reports cover this service?", [
                _opt("iso27001", "ISO/IEC 27001", 2),
                _opt("iso27017", "ISO/IEC 27017 (cloud security)", 1),
                _opt("iso27018", "ISO/IEC 27018 (personal data in the cloud)", 1),
                _opt("soc2", "SOC 2 Type II", 2),
                _opt("pcidss", "PCI DSS", 1),
                _opt("none", "None", 0, na=False, flag="No independent security certification", severity="high"),
            ], multiple=True),
            field("cert_evidence", "Upload the certificates or the latest report", "file_upload",
                  when={"match": "all", "rules": [{"question": "certs", "op": "not_in", "values": ["none"]},
                                                  {"question": "certs", "op": "answered"}]}),
        ]),
    ],
}


# ========================================= information security baseline ===
_INFOSEC = {
    "key": "third-party-information-security-baseline",
    "version": 1,
    "name": "Information security baseline for third parties",
    "purpose": "vendor_due_diligence",
    "description": (
        "A baseline set of security questions for any third party that handles bank data or "
        "connects to bank systems: governance, people, access, vulnerability management and "
        "secure development. Stronger answers score higher."
    ),
    "bands": DUE_DILIGENCE_BANDS,
    "sections": [
        section("governance", "Security governance", "", [
            yes_no("policy", "Does the organisation have an information security policy approved by senior management and reviewed at least annually?",
                   flag="No approved, current information security policy", severity="high", na=False, weight=2),
            yes_no("owner", "Is a named person accountable for information security?",
                   flag="No one accountable for information security", na=False),
            yes_no("risk_assessment", "Is an information security risk assessment performed at least annually?",
                   flag="No regular security risk assessment", na=False),
        ]),
        section("people", "People", "", [
            yes_no("screening", "Are staff with access to bank data background-checked before joining?",
                   flag="Staff are not screened before access to bank data", na=False),
            yes_no("training", "Do all staff complete security awareness training at least once a year?",
                   flag="No annual security awareness training", na=False),
            yes_no("leavers", "Is access removed within one working day when someone leaves?",
                   flag="Leaver access not removed promptly", severity="high", na=False),
        ]),
        section("access", "Access control", "", [
            yes_no("unique_ids", "Does every user have their own account (no shared logins)?",
                   flag="Shared accounts in use", severity="high", na=False),
            yes_no("mfa_remote", "Is multi-factor authentication required for remote and privileged access?",
                   flag="Remote or privileged access without multi-factor authentication", severity="high", na=False, weight=2),
            yes_no("access_review", "Are user access rights reviewed at least every six months?",
                   flag="Access rights not reviewed regularly", na=False),
        ]),
        section("technical", "Vulnerabilities and malware", "", [
            choice("patching", "How quickly are critical security patches applied?", [
                _opt("14d", "Within 14 days", 2),
                _opt("30d", "Within 30 days", 1),
                _opt("longer", "Longer, or no defined timeline", 0, flag="Critical patches not applied within 30 days", severity="high"),
            ], weight=2),
            yes_no("pentest", "Has an independent penetration test been performed in the last 12 months?",
                   flag="No independent penetration test in the last year"),
            field("pentest_summary", "Upload the executive summary of the latest test", "file_upload",
                  when=when_in("pentest", "yes")),
            yes_no("malware", "Is anti-malware protection installed and kept up to date on all endpoints and servers?",
                   flag="Endpoints or servers without current anti-malware", na=False),
        ]),
        section("development", "Secure development", "Only for providers that build software for the bank.", [
            yes_no("builds_software", "Does the provider develop or customise software for the bank?", na=False, weight=0),
            yes_no("sdlc", "Is security testing (code review or scanning) part of every release?",
                   flag="No security testing in the release process", severity="high",
                   when=when_in("builds_software", "yes")),
            yes_no("env_separation", "Are development, test and production environments separated, with no production customer data in test?",
                   flag="Production data used in non-production environments", severity="high",
                   when=when_in("builds_software", "yes")),
        ]),
    ],
}


# ============================================== business continuity readiness ===
_BCM = {
    "key": "business-continuity-readiness",
    "version": 1,
    "name": "Business continuity readiness",
    "purpose": "vendor_due_diligence",
    "description": (
        "Whether a provider can keep delivering a service to the bank through a disruption: "
        "impact analysis, recovery objectives, alternate sites, testing and crisis communication. "
        "Stronger answers score higher."
    ),
    "bands": DUE_DILIGENCE_BANDS,
    "sections": [
        section("planning", "Planning", "", [
            yes_no("bia", "Has a business impact analysis identified the processes and resources this service depends on?",
                   flag="No business impact analysis for the service", severity="high", na=False, weight=2),
            field("rto_hours", "Recovery time objective for the service (hours)", "number", mandatory=True),
            field("rpo_hours", "Recovery point objective for the service (hours of data that could be lost)", "number", mandatory=True),
            yes_no("plan_owner", "Does the plan name who declares a disruption and who leads the recovery?",
                   flag="No named crisis owner in the continuity plan", na=False),
        ]),
        section("resilience", "Resilience", "", [
            yes_no("alternate_site", "Is there an alternate site or region that can run the service?",
                   flag="No alternate site for the service", severity="high", na=False, weight=2),
            yes_no("backups_offsite", "Are backups kept off-site or in a separate region, and restored in a test at least annually?",
                   flag="Backups not kept separately or not restore-tested", severity="high", na=False, weight=2),
            yes_no("key_people", "Are key staff roles covered by trained deputies?",
                   flag="Key person dependency without deputies", na=False),
        ]),
        section("testing", "Testing", "", [
            choice("last_test", "When was the continuity plan last exercised end to end?", [
                _opt("6m", "Within the last 6 months", 3),
                _opt("12m", "6 to 12 months ago", 2),
                _opt("24m", "12 to 24 months ago", 1),
                _opt("never", "Longer ago, or never", 0, flag="Continuity plan not exercised in the last two years", severity="high"),
            ], weight=2),
            yes_no("rto_met", "Did the last exercise meet the recovery time objective?",
                   flag="Last continuity exercise missed its recovery time objective", severity="high",
                   when=when_in("last_test", "6m", "12m", "24m")),
            field("test_report", "Upload the latest exercise report", "file_upload",
                  when=when_in("last_test", "6m", "12m", "24m")),
        ]),
        section("communication", "Crisis communication", "", [
            yes_no("notify_bank", "Will the provider notify the bank within two hours of invoking its continuity plan?",
                   flag="No prompt notice to the bank when the continuity plan is invoked", na=False),
            yes_no("contact_tree", "Is the bank included in the provider's crisis contact list, reviewed at least annually?",
                   flag="Bank missing from the provider's crisis contact list", na=False),
        ]),
    ],
}


# ====================================================== RCSA control self-assessment ===
RCSA_RATING_OPTIONS: list[dict[str, Any]] = [
    _opt("effective", "Effective", 2),
    _opt("partially_effective", "Partially effective", 1, flag="Control rated partially effective in self-assessment", severity="medium"),
    _opt("ineffective", "Ineffective", 0, flag="Control rated ineffective in self-assessment", severity="high"),
    _opt("not_assessed", "Not assessed", 0, na=True),
]

_RCSA = {
    "key": "rcsa-control-self-assessment",
    "version": 1,
    "name": "Control self-assessment (RCSA)",
    "purpose": "rcsa_control_self_assessment",
    "description": (
        "The first line rates each key control's design and operation. When run from an RCSA, "
        "this section is repeated for each line of the RCSA and the reviewed answers set the "
        "line's control self-rating (the worse of design and operation)."
    ),
    "bands": [
        {"label": "Controls effective", "min_pct": 80, "rating": "low"},
        {"label": "Some weaknesses", "min_pct": 60, "rating": "medium"},
        {"label": "Significant weaknesses", "min_pct": 40, "rating": "high"},
        {"label": "Controls failing", "min_pct": 0, "rating": "critical"},
    ],
    "sections": [
        section("control", "Control", "Rate the control as it operated during the period.", [
            choice("design", "Is the control designed to prevent or detect the risk it addresses?", deepcopy(RCSA_RATING_OPTIONS),
                   "Consider whether the control, if performed as written, would address the risk.",
                   config={"rcsa_role": "design"}),
            choice("operation", "Did the control operate as designed throughout the period?", deepcopy(RCSA_RATING_OPTIONS),
                   "Consider missed performances, exceptions and late reviews.",
                   config={"rcsa_role": "operation"}),
            field("weakness", "Describe the weakness and what is being done about it", "long_text", mandatory=True,
                  when={"match": "any", "rules": [
                      {"question": "design", "op": "in", "values": ["partially_effective", "ineffective"]},
                      {"question": "operation", "op": "in", "values": ["partially_effective", "ineffective"]},
                  ]}),
            field("evidence", "Upload evidence that the control operated", "file_upload"),
        ]),
    ],
}

TEMPLATES: tuple[dict[str, Any], ...] = (_SBP_OUTSOURCING, _CLOUD, _INFOSEC, _BCM, _RCSA)
BY_KEY: dict[str, dict[str, Any]] = {t["key"]: t for t in TEMPLATES}


def get(key: str) -> dict[str, Any] | None:
    template = BY_KEY.get(key)
    return deepcopy(template) if template is not None else None


def summary(template: dict[str, Any]) -> dict[str, Any]:
    questions = [q for s in template["sections"] for q in s["questions"]]
    return {
        "key": template["key"], "version": template["version"], "name": template["name"],
        "purpose": template["purpose"], "description": template["description"],
        "section_count": len(template["sections"]), "question_count": len(questions),
        "scored_question_count": sum(1 for q in questions if q["type"] in CHOICE_TYPES and (q.get("weight") or 0) > 0),
        "risk_flag_count": sum(1 for q in questions for o in q.get("options", []) if o.get("risk_flag")),
    }
