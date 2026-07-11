"""Module registry: the single source of truth for licensable modules and editions.

Every client runs the SAME build; which modules are active is decided per
installation by (a) the signed license file and (b) the ``DISABLED_MODULES``
deploy setting. Core platform capabilities (risk register, controls, compliance,
policies, users, reporting, …) are never gated — only the entries below are.

Each entry maps a module key to:
  - ``title`` / ``category``: what the admin sees in Settings → System.
  - ``routes``: frontend route prefixes the sidebar/route-guard hide when the
    module is off. The API side is gated in ``app/api/v1/router.py`` by attaching
    ``require_module(<key>)`` to that module's router — keep both in sync when
    adding a module.

Editions bundle modules for sales packaging; a license lists editions and/or
individual module keys (see ``app/tools/license.py``).
"""
from __future__ import annotations

MODULES: dict[str, dict] = {
    # --- Islamic banking ---
    "shariah": {
        "title": "Shariah Governance",
        "category": "Islamic Banking",
        "description": "Shariah reviews, rulings, findings, Islamic products and charity ledger.",
        "routes": ["/shariah"],
    },
    # --- Financial crime ---
    "aml": {
        "title": "AML / CFT",
        "category": "Financial Crime",
        "description": "AML risk assessments, STR/SAR tracking and screening registers.",
        "routes": ["/aml"],
    },
    "fraud": {
        "title": "Fraud Risk",
        "category": "Financial Crime",
        "description": "Fraud risk register, cases and anti-fraud control checks.",
        "routes": ["/fraud"],
    },
    "whistleblowing": {
        "title": "Whistleblowing",
        "category": "Financial Crime",
        "description": "Confidential disclosure intake, triage and case management.",
        "routes": ["/whistleblowing"],
    },
    # --- Enterprise risk ---
    "operational_risk": {
        "title": "Operational Risk",
        "category": "Enterprise Risk",
        "description": "RCSA, KRIs and loss-event database.",
        "routes": ["/operational-risk"],
    },
    "scenario_analysis": {
        "title": "Scenario Analysis & Capital",
        "category": "Enterprise Risk",
        "description": "Stress scenarios and capital calculations.",
        "routes": ["/scenario-analysis"],
    },
    "model_risk": {
        "title": "Model Risk",
        "category": "Enterprise Risk",
        "description": "Model inventory and validation lifecycle.",
        "routes": ["/model-risk"],
    },
    "risk_quantification": {
        "title": "Risk Quantification",
        "category": "Enterprise Risk",
        "description": "Monte-Carlo / FAIR-style quantitative risk analysis.",
        "routes": ["/risk-quantification"],
    },
    "icfr": {
        "title": "ICFR",
        "category": "Enterprise Risk",
        "description": "Internal control over financial reporting: scoping, testing, deficiencies.",
        "routes": ["/icfr"],
    },
    # --- Resilience ---
    "continuity": {
        "title": "Business Continuity",
        "category": "Resilience",
        "description": "Continuity plans, tasks and test exercises.",
        "routes": ["/continuity"],
    },
    "bia": {
        "title": "Business Impact Analysis",
        "category": "Resilience",
        "description": "BIA assessments, dependencies, RTO/RPO.",
        "routes": ["/bia"],
    },
    # --- Privacy ---
    "privacy": {
        "title": "Data Privacy (RoPA)",
        "category": "Privacy",
        "description": "Records of processing activities.",
        "routes": ["/privacy"],
    },
    "data_protection": {
        "title": "Data Protection",
        "category": "Privacy",
        "description": "DPIAs, DSARs, consent records and breach register.",
        "routes": ["/data-protection"],
    },
    # --- Audit & assurance ---
    "internal_audit": {
        "title": "Internal Audit",
        "category": "Audit & Assurance",
        "description": "Audit universe, engagements, working papers and findings.",
        "routes": ["/internal-audit"],
    },
    "access_reviews": {
        "title": "Access Reviews",
        "category": "Audit & Assurance",
        "description": "User-access certification campaigns.",
        "routes": ["/access-reviews"],
    },
    "declarations": {
        "title": "Declarations",
        "category": "Audit & Assurance",
        "description": "Conflict-of-interest, gifts and related-party declaration campaigns.",
        "routes": ["/declarations"],
    },
    # --- Governance ---
    "governance_meetings": {
        "title": "Board & Committees",
        "category": "Governance",
        "description": "Committee registers, meetings, decisions and action tracking.",
        "routes": ["/governance"],
    },
    "authority": {
        "title": "Delegation of Authority",
        "category": "Governance",
        "description": "Authority matrix and dual-control rules.",
        "routes": ["/delegation-of-authority"],
    },
    "awareness": {
        "title": "Awareness Training",
        "category": "Governance",
        "description": "Training programs, assignments and completion tracking.",
        "routes": ["/awareness"],
    },
    "esg": {
        "title": "ESG / Green Banking",
        "category": "Governance",
        "description": "ESG assessments and environmental risk ratings.",
        "routes": ["/esg"],
    },
    # --- Technology ---
    "vulnerability": {
        "title": "Vulnerability Management",
        "category": "Technology",
        "description": "Vulnerability findings and patch records.",
        "routes": ["/vulnerabilities"],
    },
    "integrations_ccm": {
        "title": "Integrations & CCM",
        "category": "Technology",
        "description": "Connectors, automated control tests and continuous control monitoring.",
        "routes": ["/integrations"],
    },
    "ai_assist": {
        "title": "AI Assist",
        "category": "Technology",
        "description": "AI-assisted drafting, mapping and summarisation.",
        "routes": ["/ai-assist"],
    },
    # --- Third party ---
    "outsourcing": {
        "title": "Outsourcing & Cloud",
        "category": "Third Party",
        "description": "Outsourcing arrangements register and periodic reviews.",
        "routes": ["/outsourcing"],
    },
    # --- Regulatory ---
    "regulatory_change": {
        "title": "Regulatory Change",
        "category": "Regulatory",
        "description": "Circular/regulation intake, obligations and regulatory returns.",
        "routes": ["/regulatory-change"],
    },
}

# Sales bundles. A license's ``modules`` list may contain edition names, module
# keys, or "all". "core" is valid and adds nothing (the always-on platform).
EDITIONS: dict[str, list[str]] = {
    "core": [],
    "islamic_banking": ["shariah"],
    "financial_crime": ["aml", "fraud", "whistleblowing"],
    "enterprise_risk": [
        "operational_risk",
        "scenario_analysis",
        "model_risk",
        "risk_quantification",
        "icfr",
    ],
    "resilience": ["continuity", "bia"],
    "privacy": ["privacy", "data_protection"],
    "audit": ["internal_audit", "access_reviews", "declarations"],
    "governance": ["governance_meetings", "authority", "awareness", "esg"],
    "technology": ["vulnerability", "integrations_ccm", "ai_assist"],
    "third_party": ["outsourcing"],
    "regulatory": ["regulatory_change"],
}

ALL_MODULE_KEYS: frozenset[str] = frozenset(MODULES)


def expand_modules(entries: list[str]) -> set[str]:
    """Expand a license/CLI ``modules`` list (edition names, module keys, "all")
    into a concrete set of module keys. Unknown entries are ignored so an old
    build tolerates licenses minted for a newer one."""
    out: set[str] = set()
    for raw in entries:
        entry = raw.strip().lower().replace("-", "_")
        if not entry:
            continue
        if entry in ("all", "*"):
            return set(ALL_MODULE_KEYS)
        if entry in EDITIONS:
            out.update(EDITIONS[entry])
        elif entry in MODULES:
            out.add(entry)
    return out
