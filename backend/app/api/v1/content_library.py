"""Framework Content Library — preloaded, installable framework packs.

Ships curated, banking-relevant standards (ISO/IEC 27001:2022 Annex A, NIST CSF 2.0,
SBP ETGRM, PCI DSS 4.0, Basel operational risk, SBP/AAOIFI Shariah governance) as static
Python data. Installing a pack creates a real ``Framework`` and its ``Requirement`` rows
for the tenant using the existing compliance models — no new tables, no new permissions.

Reuses the compliance permission keys: ``compliance:read`` (browse) and
``compliance:write`` (install). Installed frameworks then appear in the Compliance module.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.compliance import Framework, Requirement
from app.schemas.content_library import (
    ContentPackSummary,
    InstallResult,
    InstalledPack,
)
from app.services import audit

router = APIRouter(tags=["content-library"])


# ---------------------------------------------------------------------------
# Pack catalogue. Each pack materialises one Framework + its Requirement rows.
#   Framework fields  : name, version, authority, regulator, scope, description
#   Requirement fields: reference (<- code), title, domain, description
# ---------------------------------------------------------------------------
def _req(code: str, title: str, domain: str, description: str = "") -> dict:
    return {"code": code, "title": title, "domain": domain, "description": description}


# --- 1. ISO/IEC 27001:2022 Annex A — 93 controls across 4 themes -------------
_ISO_27001_ANNEX_A = [
    # A.5 Organizational controls (37)
    _req("A.5.1", "Policies for information security", "Organizational"),
    _req("A.5.2", "Information security roles and responsibilities", "Organizational"),
    _req("A.5.3", "Segregation of duties", "Organizational"),
    _req("A.5.4", "Management responsibilities", "Organizational"),
    _req("A.5.5", "Contact with authorities", "Organizational"),
    _req("A.5.6", "Contact with special interest groups", "Organizational"),
    _req("A.5.7", "Threat intelligence", "Organizational"),
    _req("A.5.8", "Information security in project management", "Organizational"),
    _req("A.5.9", "Inventory of information and other associated assets", "Organizational"),
    _req("A.5.10", "Acceptable use of information and other associated assets", "Organizational"),
    _req("A.5.11", "Return of assets", "Organizational"),
    _req("A.5.12", "Classification of information", "Organizational"),
    _req("A.5.13", "Labelling of information", "Organizational"),
    _req("A.5.14", "Information transfer", "Organizational"),
    _req("A.5.15", "Access control", "Organizational"),
    _req("A.5.16", "Identity management", "Organizational"),
    _req("A.5.17", "Authentication information", "Organizational"),
    _req("A.5.18", "Access rights", "Organizational"),
    _req("A.5.19", "Information security in supplier relationships", "Organizational"),
    _req("A.5.20", "Addressing information security within supplier agreements", "Organizational"),
    _req("A.5.21", "Managing information security in the ICT supply chain", "Organizational"),
    _req("A.5.22", "Monitoring, review and change management of supplier services", "Organizational"),
    _req("A.5.23", "Information security for use of cloud services", "Organizational"),
    _req("A.5.24", "Information security incident management planning and preparation", "Organizational"),
    _req("A.5.25", "Assessment and decision on information security events", "Organizational"),
    _req("A.5.26", "Response to information security incidents", "Organizational"),
    _req("A.5.27", "Learning from information security incidents", "Organizational"),
    _req("A.5.28", "Collection of evidence", "Organizational"),
    _req("A.5.29", "Information security during disruption", "Organizational"),
    _req("A.5.30", "ICT readiness for business continuity", "Organizational"),
    _req("A.5.31", "Legal, statutory, regulatory and contractual requirements", "Organizational"),
    _req("A.5.32", "Intellectual property rights", "Organizational"),
    _req("A.5.33", "Protection of records", "Organizational"),
    _req("A.5.34", "Privacy and protection of personal identifiable information (PII)", "Organizational"),
    _req("A.5.35", "Independent review of information security", "Organizational"),
    _req("A.5.36", "Compliance with policies, rules and standards for information security", "Organizational"),
    _req("A.5.37", "Documented operating procedures", "Organizational"),
    # A.6 People controls (8)
    _req("A.6.1", "Screening", "People"),
    _req("A.6.2", "Terms and conditions of employment", "People"),
    _req("A.6.3", "Information security awareness, education and training", "People"),
    _req("A.6.4", "Disciplinary process", "People"),
    _req("A.6.5", "Responsibilities after termination or change of employment", "People"),
    _req("A.6.6", "Confidentiality or non-disclosure agreements", "People"),
    _req("A.6.7", "Remote working", "People"),
    _req("A.6.8", "Information security event reporting", "People"),
    # A.7 Physical controls (14)
    _req("A.7.1", "Physical security perimeters", "Physical"),
    _req("A.7.2", "Physical entry", "Physical"),
    _req("A.7.3", "Securing offices, rooms and facilities", "Physical"),
    _req("A.7.4", "Physical security monitoring", "Physical"),
    _req("A.7.5", "Protecting against physical and environmental threats", "Physical"),
    _req("A.7.6", "Working in secure areas", "Physical"),
    _req("A.7.7", "Clear desk and clear screen", "Physical"),
    _req("A.7.8", "Equipment siting and protection", "Physical"),
    _req("A.7.9", "Security of assets off-premises", "Physical"),
    _req("A.7.10", "Storage media", "Physical"),
    _req("A.7.11", "Supporting utilities", "Physical"),
    _req("A.7.12", "Cabling security", "Physical"),
    _req("A.7.13", "Equipment maintenance", "Physical"),
    _req("A.7.14", "Secure disposal or re-use of equipment", "Physical"),
    # A.8 Technological controls (34)
    _req("A.8.1", "User endpoint devices", "Technological"),
    _req("A.8.2", "Privileged access rights", "Technological"),
    _req("A.8.3", "Information access restriction", "Technological"),
    _req("A.8.4", "Access to source code", "Technological"),
    _req("A.8.5", "Secure authentication", "Technological"),
    _req("A.8.6", "Capacity management", "Technological"),
    _req("A.8.7", "Protection against malware", "Technological"),
    _req("A.8.8", "Management of technical vulnerabilities", "Technological"),
    _req("A.8.9", "Configuration management", "Technological"),
    _req("A.8.10", "Information deletion", "Technological"),
    _req("A.8.11", "Data masking", "Technological"),
    _req("A.8.12", "Data leakage prevention", "Technological"),
    _req("A.8.13", "Information backup", "Technological"),
    _req("A.8.14", "Redundancy of information processing facilities", "Technological"),
    _req("A.8.15", "Logging", "Technological"),
    _req("A.8.16", "Monitoring activities", "Technological"),
    _req("A.8.17", "Clock synchronization", "Technological"),
    _req("A.8.18", "Use of privileged utility programs", "Technological"),
    _req("A.8.19", "Installation of software on operational systems", "Technological"),
    _req("A.8.20", "Networks security", "Technological"),
    _req("A.8.21", "Security of network services", "Technological"),
    _req("A.8.22", "Segregation of networks", "Technological"),
    _req("A.8.23", "Web filtering", "Technological"),
    _req("A.8.24", "Use of cryptography", "Technological"),
    _req("A.8.25", "Secure development life cycle", "Technological"),
    _req("A.8.26", "Application security requirements", "Technological"),
    _req("A.8.27", "Secure system architecture and engineering principles", "Technological"),
    _req("A.8.28", "Secure coding", "Technological"),
    _req("A.8.29", "Security testing in development and acceptance", "Technological"),
    _req("A.8.30", "Outsourced development", "Technological"),
    _req("A.8.31", "Separation of development, test and production environments", "Technological"),
    _req("A.8.32", "Change management", "Technological"),
    _req("A.8.33", "Test information", "Technological"),
    _req("A.8.34", "Protection of information systems during audit testing", "Technological"),
]

# --- 2. NIST CSF 2.0 — 6 Functions and their Categories ----------------------
_NIST_CSF_2 = [
    # Govern (GV)
    _req("GV", "Govern", "Govern", "Establish and monitor the organization's cybersecurity risk management strategy, expectations and policy."),
    _req("GV.OC", "Organizational Context", "Govern"),
    _req("GV.RM", "Risk Management Strategy", "Govern"),
    _req("GV.RR", "Roles, Responsibilities, and Authorities", "Govern"),
    _req("GV.PO", "Policy", "Govern"),
    _req("GV.OV", "Oversight", "Govern"),
    _req("GV.SC", "Cybersecurity Supply Chain Risk Management", "Govern"),
    # Identify (ID)
    _req("ID", "Identify", "Identify", "Understand the current cybersecurity risks to systems, people, assets, data and capabilities."),
    _req("ID.AM", "Asset Management", "Identify"),
    _req("ID.RA", "Risk Assessment", "Identify"),
    _req("ID.IM", "Improvement", "Identify"),
    # Protect (PR)
    _req("PR", "Protect", "Protect", "Use safeguards to manage the organization's cybersecurity risks."),
    _req("PR.AA", "Identity Management, Authentication, and Access Control", "Protect"),
    _req("PR.AT", "Awareness and Training", "Protect"),
    _req("PR.DS", "Data Security", "Protect"),
    _req("PR.PS", "Platform Security", "Protect"),
    _req("PR.IR", "Technology Infrastructure Resilience", "Protect"),
    # Detect (DE)
    _req("DE", "Detect", "Detect", "Find and analyze possible cybersecurity attacks and compromises."),
    _req("DE.CM", "Continuous Monitoring", "Detect"),
    _req("DE.AE", "Adverse Event Analysis", "Detect"),
    # Respond (RS)
    _req("RS", "Respond", "Respond", "Take action regarding a detected cybersecurity incident."),
    _req("RS.MA", "Incident Management", "Respond"),
    _req("RS.AN", "Incident Analysis", "Respond"),
    _req("RS.CO", "Incident Response Reporting and Communication", "Respond"),
    _req("RS.MI", "Incident Mitigation", "Respond"),
    # Recover (RC)
    _req("RC", "Recover", "Recover", "Restore assets and operations affected by a cybersecurity incident."),
    _req("RC.RP", "Incident Recovery Plan Execution", "Recover"),
    _req("RC.CO", "Incident Recovery Communication", "Recover"),
]

# --- 3. SBP ETGRM — Enterprise Technology Governance & Risk Management --------
_SBP_ETGRM = [
    _req("ETGRM-1.1", "IT governance framework and board oversight", "IT Governance"),
    _req("ETGRM-1.2", "Alignment of IT strategy with business strategy", "IT Governance"),
    _req("ETGRM-1.3", "IT steering committee", "IT Governance"),
    _req("ETGRM-1.4", "IT policies, standards and procedures", "IT Governance"),
    _req("ETGRM-2.1", "Technology risk management framework", "IT Risk Management"),
    _req("ETGRM-2.2", "IT risk identification, assessment and treatment", "IT Risk Management"),
    _req("ETGRM-2.3", "Technology risk appetite and risk reporting", "IT Risk Management"),
    _req("ETGRM-3.1", "Information security governance and CISO function", "Information Security"),
    _req("ETGRM-3.2", "Information security policy", "Information Security"),
    _req("ETGRM-3.3", "Logical access control and identity management", "Information Security"),
    _req("ETGRM-3.4", "Data classification and protection", "Information Security"),
    _req("ETGRM-3.5", "Security monitoring and incident management", "Information Security"),
    _req("ETGRM-4.1", "IT operations management", "IT Operations & Service Delivery"),
    _req("ETGRM-4.2", "Capacity and performance management", "IT Operations & Service Delivery"),
    _req("ETGRM-4.3", "Service level management", "IT Operations & Service Delivery"),
    _req("ETGRM-4.4", "Backup, storage and media management", "IT Operations & Service Delivery"),
    _req("ETGRM-4.5", "Problem and incident management", "IT Operations & Service Delivery"),
    _req("ETGRM-5.1", "System development life cycle (SDLC)", "System Acquisition & Development"),
    _req("ETGRM-5.2", "Change management", "System Acquisition & Development"),
    _req("ETGRM-5.3", "Application and system testing", "System Acquisition & Development"),
    _req("ETGRM-5.4", "Patch and configuration management", "System Acquisition & Development"),
    _req("ETGRM-6.1", "Business continuity planning", "Business Continuity & Disaster Recovery"),
    _req("ETGRM-6.2", "Disaster recovery planning and DR site", "Business Continuity & Disaster Recovery"),
    _req("ETGRM-6.3", "BCP/DR testing and validation", "Business Continuity & Disaster Recovery"),
    _req("ETGRM-7.1", "IT audit function and coverage", "IT Audit"),
    _req("ETGRM-7.2", "IT audit planning, reporting and follow-up", "IT Audit"),
    _req("ETGRM-8.1", "Outsourcing and vendor risk management", "Outsourcing"),
    _req("ETGRM-8.2", "Service provider due diligence and contracting", "Outsourcing"),
    _req("ETGRM-8.3", "Ongoing monitoring of outsourced arrangements", "Outsourcing"),
    _req("ETGRM-9.1", "Cyber security strategy and governance", "Cyber Security"),
    _req("ETGRM-9.2", "Threat and vulnerability management", "Cyber Security"),
    _req("ETGRM-9.3", "Cyber incident response and reporting to SBP", "Cyber Security"),
    _req("ETGRM-9.4", "Security awareness and training", "Cyber Security"),
]

# --- 4. PCI DSS v4.0 — 12 principal requirements -----------------------------
_PCI_DSS_4 = [
    _req("1", "Install and Maintain Network Security Controls", "Build and Maintain a Secure Network and Systems"),
    _req("2", "Apply Secure Configurations to All System Components", "Build and Maintain a Secure Network and Systems"),
    _req("3", "Protect Stored Account Data", "Protect Account Data"),
    _req("4", "Protect Cardholder Data with Strong Cryptography During Transmission Over Open, Public Networks", "Protect Account Data"),
    _req("5", "Protect All Systems and Networks from Malicious Software", "Maintain a Vulnerability Management Program"),
    _req("6", "Develop and Maintain Secure Systems and Software", "Maintain a Vulnerability Management Program"),
    _req("7", "Restrict Access to System Components and Cardholder Data by Business Need to Know", "Implement Strong Access Control Measures"),
    _req("8", "Identify Users and Authenticate Access to System Components", "Implement Strong Access Control Measures"),
    _req("9", "Restrict Physical Access to Cardholder Data", "Implement Strong Access Control Measures"),
    _req("10", "Log and Monitor All Access to System Components and Cardholder Data", "Regularly Monitor and Test Networks"),
    _req("11", "Test Security of Systems and Networks Regularly", "Regularly Monitor and Test Networks"),
    _req("12", "Support Information Security with Organizational Policies and Programs", "Maintain an Information Security Policy"),
]

# --- 5. Basel Operational Risk — event types + sound-management principles ----
_BASEL_OPRISK = [
    # Basel II Level-1 loss event-type categories (7)
    _req("ET1", "Internal Fraud", "Loss Event Types",
         "Losses due to acts intended to defraud, misappropriate property or circumvent the law, involving at least one internal party."),
    _req("ET2", "External Fraud", "Loss Event Types",
         "Losses due to acts intended to defraud, misappropriate property or circumvent the law, by a third party."),
    _req("ET3", "Employment Practices and Workplace Safety", "Loss Event Types",
         "Losses from acts inconsistent with employment, health or safety laws or agreements."),
    _req("ET4", "Clients, Products & Business Practices", "Loss Event Types",
         "Losses from an unintentional or negligent failure to meet a professional obligation to clients, or from the nature or design of a product."),
    _req("ET5", "Damage to Physical Assets", "Loss Event Types",
         "Losses from loss or damage to physical assets from natural disaster or other events."),
    _req("ET6", "Business Disruption and System Failures", "Loss Event Types",
         "Losses from disruption of business or system failures."),
    _req("ET7", "Execution, Delivery & Process Management", "Loss Event Types",
         "Losses from failed transaction processing or process management, and relations with trade counterparties and vendors."),
    # Principles for the Sound Management of Operational Risk (PSMOR) — 11 principles
    _req("P1", "Operational risk culture", "Sound Management Principles",
         "The board and senior management establish a strong risk management culture across the bank."),
    _req("P2", "Operational risk management framework", "Sound Management Principles",
         "The bank develops, implements and maintains a framework fully integrated into overall risk management."),
    _req("P3", "Board establishes and reviews the framework", "Sound Management Principles",
         "The board establishes, approves and periodically reviews the operational risk management framework."),
    _req("P4", "Operational risk appetite and tolerance", "Sound Management Principles",
         "The board approves and reviews a risk appetite and tolerance statement for operational risk."),
    _req("P5", "Governance structure", "Sound Management Principles",
         "Senior management develops a clear, effective and robust governance structure with well-defined lines of responsibility."),
    _req("P6", "Identification and assessment", "Sound Management Principles",
         "Senior management ensures identification and assessment of the operational risk inherent in all material products, activities, processes and systems."),
    _req("P7", "Change management", "Sound Management Principles",
         "Senior management ensures a change management process to assess operational risk in new products, activities, processes and systems."),
    _req("P8", "Monitoring and reporting", "Sound Management Principles",
         "Senior management implements a process to regularly monitor operational risk profiles and material exposures."),
    _req("P9", "Control and mitigation", "Sound Management Principles",
         "The bank maintains a strong control environment using policies, processes, systems and appropriate internal controls and risk mitigation."),
    _req("P10", "Business resiliency and continuity", "Sound Management Principles",
         "The bank establishes business resiliency and continuity plans to operate on an ongoing basis and limit losses in a disruption."),
    _req("P11", "Disclosure", "Sound Management Principles",
         "The bank makes sufficient public disclosure to allow stakeholders to assess its operational risk management approach."),
]

# --- 6. SBP/AAOIFI Shariah Governance ----------------------------------------
_SHARIAH_GOVERNANCE = [
    _req("SG-1", "Board of Directors' oversight of Shariah governance", "Governance & Oversight"),
    _req("SG-2", "Shariah Board — appointment, composition and independence", "Shariah Board"),
    _req("SG-3", "Shariah Board — roles, responsibilities, fatawa and rulings", "Shariah Board"),
    _req("SG-4", "Shariah Compliance Department / function", "Shariah Compliance"),
    _req("SG-5", "Shariah compliance review", "Shariah Compliance"),
    _req("SG-6", "Internal Shariah audit", "Shariah Audit"),
    _req("SG-7", "External Shariah audit", "Shariah Audit"),
    _req("SG-8", "Product development and Shariah approval", "Product Approval"),
    _req("SG-9", "Shariah non-compliance risk management", "Shariah Risk"),
    _req("SG-10", "Purification of non-Shariah-compliant income and charity disbursement", "Purification & Charity"),
    _req("SG-11", "Profit and loss distribution and pool management", "Profit Distribution"),
    _req("SG-12", "Shariah training and awareness", "Capacity Building"),
]


PACKS: list[dict] = [
    {
        "id": "iso-27001-2022-annex-a",
        "name": "ISO/IEC 27001:2022 Annex A",
        "standard": "ISO/IEC 27001:2022",
        "domain": "Information Security",
        "version": "2022",
        "authority": "ISO/IEC",
        "regulator": "",
        "scope": "Information security controls (Annex A) referenced by the ISO/IEC 27001:2022 ISMS.",
        "description": "All 93 Annex A controls across four themes: Organizational, People, Physical and Technological.",
        "requirements": _ISO_27001_ANNEX_A,
    },
    {
        "id": "nist-csf-2-0",
        "name": "NIST CSF 2.0",
        "standard": "NIST Cybersecurity Framework 2.0",
        "domain": "Cybersecurity",
        "version": "2.0",
        "authority": "NIST",
        "regulator": "",
        "scope": "The six Functions and their Categories from the NIST Cybersecurity Framework 2.0.",
        "description": "Govern, Identify, Protect, Detect, Respond and Recover — the 6 Functions with all of their Categories.",
        "requirements": _NIST_CSF_2,
    },
    {
        "id": "sbp-etgrm",
        "name": "SBP ETGRM Framework",
        "standard": "SBP Enterprise Technology Governance & Risk Management Framework",
        "domain": "Technology Governance",
        "version": "2017",
        "authority": "State Bank of Pakistan",
        "regulator": "State Bank of Pakistan",
        "scope": "Enterprise technology governance and risk management for banks and DFIs in Pakistan.",
        "description": "IT governance, risk, information security, operations, SDLC, BCP/DR, IT audit, outsourcing and cyber security domains.",
        "requirements": _SBP_ETGRM,
    },
    {
        "id": "pci-dss-4-0",
        "name": "PCI DSS v4.0",
        "standard": "PCI DSS v4.0",
        "domain": "Payment Card Security",
        "version": "4.0",
        "authority": "PCI Security Standards Council",
        "regulator": "",
        "scope": "Protection of cardholder data across people, process and technology.",
        "description": "The 12 principal requirements of the Payment Card Industry Data Security Standard v4.0.",
        "requirements": _PCI_DSS_4,
    },
    {
        "id": "basel-operational-risk",
        "name": "Basel Operational Risk",
        "standard": "Basel II / Principles for the Sound Management of Operational Risk",
        "domain": "Operational Risk",
        "version": "2011",
        "authority": "Basel Committee on Banking Supervision",
        "regulator": "",
        "scope": "Operational risk loss event taxonomy and sound-management principles for banks.",
        "description": "The 7 Basel II loss event-type categories plus the 11 Principles for the Sound Management of Operational Risk.",
        "requirements": _BASEL_OPRISK,
    },
    {
        "id": "shariah-governance",
        "name": "SBP/AAOIFI Shariah Governance",
        "standard": "SBP Shariah Governance Framework / AAOIFI Governance Standards",
        "domain": "Shariah Governance",
        "version": "2018",
        "authority": "State Bank of Pakistan / AAOIFI",
        "regulator": "State Bank of Pakistan",
        "scope": "Shariah governance for Islamic banking institutions and Islamic banking windows.",
        "description": "Shariah Board, Shariah compliance, internal/external Shariah audit, product approval and purification/charity.",
        "requirements": _SHARIAH_GOVERNANCE,
    },
]

_PACKS_BY_ID = {p["id"]: p for p in PACKS}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _installed_names(db) -> set[str]:
    """Names of non-deleted frameworks in this tenant (RLS-scoped)."""
    rows = (
        await db.scalars(
            select(Framework.name).where(Framework.deleted.is_(False))
        )
    ).all()
    return set(rows)


def _get_pack(pack_id: str) -> dict:
    pack = _PACKS_BY_ID.get(pack_id)
    if pack is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown content pack")
    return pack


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get(
    "/content-library",
    response_model=list[ContentPackSummary],
    dependencies=[Depends(require("compliance:read"))],
)
async def list_packs(db: DbSession) -> list[ContentPackSummary]:
    """List every installable framework pack, flagging which are already installed."""
    installed = await _installed_names(db)
    return [
        ContentPackSummary(
            id=p["id"],
            name=p["name"],
            standard=p["standard"],
            description=p["description"],
            domain=p["domain"],
            requirement_count=len(p["requirements"]),
            installed=p["name"] in installed,
        )
        for p in PACKS
    ]


@router.get(
    "/content-library/installed",
    response_model=list[InstalledPack],
    dependencies=[Depends(require("compliance:read"))],
)
async def list_installed(db: DbSession) -> list[InstalledPack]:
    """List the packs that already exist as frameworks for this tenant."""
    installed = await _installed_names(db)
    return [
        InstalledPack(id=p["id"], name=p["name"])
        for p in PACKS
        if p["name"] in installed
    ]


@router.post(
    "/content-library/{pack_id}/install",
    response_model=InstallResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("compliance:write"))],
)
async def install_pack(pack_id: str, db: DbSession, user: CurrentUser) -> InstallResult:
    """Create a Framework and all of its Requirements for this tenant from a pack."""
    pack = _get_pack(pack_id)

    existing = await db.scalar(
        select(Framework).where(
            Framework.name == pack["name"], Framework.deleted.is_(False)
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{pack['name']} is already installed.",
        )

    fw = Framework(
        tenant_id=user.tenant_id,
        name=pack["name"],
        version=pack.get("version", ""),
        authority=pack.get("authority", ""),
        regulator=pack.get("regulator", ""),
        scope=pack.get("scope", ""),
        description=pack.get("description", ""),
    )
    db.add(fw)
    await db.flush()

    for item in pack["requirements"]:
        db.add(
            Requirement(
                tenant_id=user.tenant_id,
                framework_id=fw.id,
                reference=item["code"],
                title=item["title"],
                domain=item.get("domain", ""),
                description=item.get("description", ""),
            )
        )
    await db.flush()

    count = len(pack["requirements"])
    await audit.record(
        db,
        actor=user,
        action="create",
        entity_type="framework",
        entity_id=fw.id,
        summary=f"Installed framework pack {fw.name} ({count} requirements) from the content library",
    )
    return InstallResult(framework_id=fw.id, name=fw.name, requirement_count=count)
