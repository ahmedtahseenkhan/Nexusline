"""Default values for the governed lookup lists (``app.models.lookup.LOOKUP_LISTS``).

Called from :func:`app.db.reference_data.ensure_reference_data`, so every organisation
gets them — new ones when they are created, existing ones on the next start. Same
insert-only contract as the rest of the reference data:

* a default is added only if the list has nothing that already means it — matched
  case-insensitively on value *or* label, so a row ``fk_backfill`` made from typed text
  ("credit", "Credit risk" …) is never duplicated by the shipped "Credit";
* nothing is ever updated, re-parented, re-activated or removed. A tenant retires a
  default by deactivating it (a deleted default comes back on the next start, exactly as
  a deleted vendor type does).

Values are stable machine keys; labels are what people read. ``country`` uses the ISO
3166-1 alpha-2 code as its value so "PK", "pk" and "Pakistan" all match on backfill.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.fk_backfill import norm, slug
from app.models.lookup import Lookup


@dataclass(frozen=True)
class SeedValue:
    value: str
    label: str
    description: str = ""
    #: ``value`` of the parent default (two-level lists only).
    parent: str | None = None


def _flat(*labels: str) -> list[SeedValue]:
    return [SeedValue(slug(label), label) for label in labels]


_RISK_L1 = [
    SeedValue("strategic", "Strategic", "Business model, strategy execution and competitive position"),
    SeedValue("credit", "Credit", "Borrower or counterparty default, concentration, collateral"),
    SeedValue("market", "Market", "Interest-rate, FX, equity and commodity price movements"),
    SeedValue("liquidity", "Liquidity", "Funding and cash-flow shortfalls, deposit run-off"),
    SeedValue("operational", "Operational", "Failed processes, people, systems or external events"),
    SeedValue("compliance", "Compliance", "Breach of law, regulation or SBP directives"),
    SeedValue("technology_cyber", "Technology & Cyber", "IT failure, cyber attack, data loss (SBP ETGRM)"),
    SeedValue("reputational", "Reputational", "Loss of trust among customers, regulators or investors"),
    SeedValue("shariah", "Shariah", "Shariah non-compliance in Islamic banking products and operations"),
]
_RISK_L2 = [
    SeedValue("fraud", "Fraud", "Internal and external fraud, including digital-channel fraud", "operational"),
    SeedValue("process_execution", "Process Execution", "Errors in transaction processing and delivery", "operational"),
    SeedValue("third_party", "Third Party", "Outsourcing and vendor failure", "operational"),
    SeedValue("business_continuity", "Business Continuity", "Disruption of critical services and sites", "operational"),
    SeedValue("people", "People", "Key-person dependency, conduct, workplace safety", "operational"),
    SeedValue("information_security", "Information Security", "Confidentiality, integrity and availability of information", "technology_cyber"),
    SeedValue("cyber_threat", "Cyber Threat", "Malware, ransomware, intrusion and denial of service", "technology_cyber"),
    SeedValue("it_operations_change", "IT Operations & Change", "Outages, capacity and failed changes", "technology_cyber"),
    SeedValue("data_protection", "Data Protection", "Personal and customer data privacy", "technology_cyber"),
    SeedValue("aml_cft", "AML/CFT", "Money laundering and terrorist financing", "compliance"),
    SeedValue("regulatory_reporting", "Regulatory Reporting", "Late or inaccurate returns to regulators", "compliance"),
]

_REGULATORS = [
    SeedValue("sbp", "State Bank of Pakistan (SBP)", "Central bank and banking regulator"),
    SeedValue("secp", "Securities and Exchange Commission of Pakistan (SECP)", "Corporate, securities and NBFC regulator"),
    SeedValue("fmu", "Financial Monitoring Unit (FMU)", "Pakistan's financial intelligence unit (STR/CTR filings)"),
    SeedValue("pta", "Pakistan Telecommunication Authority (PTA)", "Telecom and digital-services regulator"),
    SeedValue("fbr", "Federal Board of Revenue (FBR)", "Tax authority"),
    SeedValue("nacta", "National Counter Terrorism Authority (NACTA)", "Proscribed persons and entities lists"),
]

#: (ISO 3166-1 alpha-2, short name)
_COUNTRIES: tuple[tuple[str, str], ...] = (
    ("PK", "Pakistan"), ("AE", "United Arab Emirates"), ("SA", "Saudi Arabia"), ("OM", "Oman"),
    ("QA", "Qatar"), ("KW", "Kuwait"), ("BH", "Bahrain"), ("GB", "United Kingdom"),
    ("US", "United States"), ("CN", "China"), ("IN", "India"), ("SG", "Singapore"),
    ("DE", "Germany"), ("IE", "Ireland"), ("NL", "Netherlands"), ("AF", "Afghanistan"),
    ("BD", "Bangladesh"), ("LK", "Sri Lanka"), ("IR", "Iran"), ("TR", "Turkey"),
    ("EG", "Egypt"), ("JO", "Jordan"), ("MY", "Malaysia"), ("ID", "Indonesia"),
    ("HK", "Hong Kong"), ("JP", "Japan"), ("KR", "South Korea"), ("AU", "Australia"),
    ("CA", "Canada"), ("FR", "France"), ("IT", "Italy"), ("ES", "Spain"),
    ("CH", "Switzerland"), ("BE", "Belgium"), ("LU", "Luxembourg"), ("SE", "Sweden"),
    ("NO", "Norway"), ("DK", "Denmark"), ("FI", "Finland"), ("PL", "Poland"),
    ("RU", "Russia"), ("ZA", "South Africa"), ("KE", "Kenya"), ("NG", "Nigeria"),
    ("BR", "Brazil"), ("MX", "Mexico"), ("NZ", "New Zealand"), ("TH", "Thailand"),
    ("PH", "Philippines"), ("VN", "Vietnam"), ("AZ", "Azerbaijan"), ("KZ", "Kazakhstan"),
    ("UZ", "Uzbekistan"), ("MV", "Maldives"), ("NP", "Nepal"),
)

_INCIDENT_TYPES = [
    SeedValue("internal_fraud", "Internal fraud", "Basel event type 1"),
    SeedValue("external_fraud", "External fraud", "Basel event type 2"),
    SeedValue("employment_practices", "Employment practices & workplace safety", "Basel event type 3"),
    SeedValue("clients_products_practices", "Clients, products & business practices", "Basel event type 4"),
    SeedValue("damage_physical_assets", "Damage to physical assets", "Basel event type 5"),
    SeedValue("business_disruption", "Business disruption & system failures", "Basel event type 6"),
    SeedValue("execution_delivery", "Execution, delivery & process management", "Basel event type 7"),
    SeedValue("cyber_attack", "Cyber attack", "Intrusion, malware, ransomware, denial of service"),
    SeedValue("phishing", "Phishing", "Credential or payment phishing against staff or customers"),
    SeedValue("data_breach", "Data breach", "Unauthorised disclosure of customer or bank data"),
]

#: ISO/IEC 27002:2022 themes (decision 8) — the four kinds of control an ISO 27001 Annex A
#: control belongs to. Values are the theme keys the ISO attributes use.
_CONTROL_CLASSIFICATIONS = [
    SeedValue("organizational", "Organizational",
              "Policies, roles, governance and management arrangements (ISO/IEC 27002:2022 clause 5)"),
    SeedValue("people", "People",
              "Controls carried out by individuals: screening, terms, awareness, discipline (clause 6)"),
    SeedValue("physical", "Physical",
              "Premises, equipment, media and the physical environment (clause 7)"),
    SeedValue("technological", "Technological",
              "Controls built into systems, networks and software (clause 8)"),
]

DEFAULT_LOOKUPS: dict[str, list[SeedValue]] = {
    "risk_category": _RISK_L1 + _RISK_L2,
    # Decision 8 (2026-09-17): the four ISO/IEC 27002:2022 themes. ISO 27001:2022 Annex A
    # is the product's hub framework, and the themes map cleanly onto the NIST
    # administrative / technical / physical split a bank's examiner expects. A control's
    # *nature* (Preventive / Detective / Corrective / Directive) is a separate field, and
    # the start-up repair (``data_repairs`` B10a) retires those from this list — seeding
    # them here would hand every new tenant four classifications the next restart removes.
    "control_classification": _CONTROL_CLASSIFICATIONS,
    "incident_type": _INCIDENT_TYPES,
    "incident_classification": _flat("Public", "Internal", "Confidential", "Restricted"),
    "issue_category": _flat("People", "Process", "Technology", "External"),
    "root_cause_category": _flat("People", "Process", "Technology", "External"),
    # Phase 2: a risk's impact is scored on each dimension; the overall impact is the
    # highest (RiskSetting.impact_mode). Banks commonly rate these five.
    "impact_dimension": _flat("Financial", "Regulatory", "Reputational", "Customer", "Operational"),
    "data_classification": _flat("Public", "Internal", "Confidential", "Restricted"),
    "regulator": _REGULATORS,
    "country": [SeedValue(code.lower(), name, code) for code, name in _COUNTRIES],
    "kri_category": _flat(
        "Operational", "Credit", "Market", "Liquidity", "Compliance & AML",
        "Technology & Cyber", "Fraud", "People", "Third party",
    ),
    "policy_category": _flat(
        "Information Security", "HR", "Finance", "Compliance", "Operations", "Shariah"
    ),
    "vendor_category": _flat(
        "Cloud", "Software", "Payments", "Outsourced operations", "Professional services", "Telecom"
    ),
    "legal_category": _flat(
        "Statute (Act / Ordinance)", "Regulation", "Regulatory circular",
        "Guideline / framework", "International standard", "Contractual obligation",
    ),
}

#: ``(key, value)`` of every shipped default — the lookups API flags these as built-in.
BUILTIN_VALUES: frozenset[tuple[str, str]] = frozenset(
    (key, v.value) for key, values in DEFAULT_LOOKUPS.items() for v in values
)


def match_keys(value: str, label: str) -> set[str]:
    """The spellings a row is known by: value and label, as typed and as slugs."""
    return {k for k in (norm(value), norm(label), slug(value), slug(label)) if k}


def missing_defaults(key: str, existing: Iterable[tuple[str, str]]) -> list[SeedValue]:
    """Defaults for ``key`` that nothing in ``existing`` (``(value, label)`` pairs) means.

    Pure, so the seed's idempotence is testable: feeding back the defaults (or rows
    typed differently but meaning the same thing) returns nothing.
    """
    known: set[str] = set()
    for value, label in existing:
        known |= match_keys(value or "", label or "")
    out: list[SeedValue] = []
    for seed in DEFAULT_LOOKUPS.get(key, []):
        keys = match_keys(seed.value, seed.label)
        if keys & known:
            continue
        out.append(seed)
        known |= keys
    return out


async def deleted_values(db: AsyncSession) -> dict[str, set[str]]:
    """``{list key: {value, …}}`` an administrator has *deleted* from a governed list.

    Deactivating a default leaves its row in place, so the insert-only seed never brings
    it back. Deleting one removes the row, and without this the next start would insert
    it again — so the delete the lookup admin audited (``lookup`` / ``delete``, whose
    ``changes`` carry the list key and the value) is honoured as a decision.
    """
    from app.models.audit import AuditLog

    out: dict[str, set[str]] = {}
    for (changes,) in (
        await db.execute(
            select(AuditLog.changes).where(AuditLog.entity_type == "lookup", AuditLog.action == "delete")
        )
    ).all():
        if not isinstance(changes, dict):
            continue
        key, value = changes.get("key"), changes.get("value")
        if isinstance(key, str) and isinstance(value, str) and value:
            out.setdefault(key, set()).add(value)
    return out


async def ensure_lookup_defaults(db: AsyncSession, tenant_id: UUID) -> int:
    """Insert the defaults this tenant's lists are missing; returns rows added.

    One read of the tenant's lookup rows, then top-level values before children so a
    child can point at a parent inserted in the same pass. A child whose parent the
    tenant no longer has is added at the top level rather than dropped. Values the
    tenant deleted are never re-inserted (:func:`deleted_values`).
    """
    rows = (await db.execute(select(Lookup.id, Lookup.key, Lookup.value, Lookup.label))).all()
    by_key: dict[str, list[tuple[object, str, str]]] = {}
    for rid, key, value, label in rows:
        by_key.setdefault(key, []).append((rid, value, label))
    deleted = await deleted_values(db)

    added = 0
    for key, defaults in DEFAULT_LOOKUPS.items():
        existing = by_key.get(key, [])
        missing = missing_defaults(
            key,
            [(v, lbl) for _rid, v, lbl in existing] + [(v, "") for v in sorted(deleted.get(key, ()))],
        )
        if not missing:
            continue
        order = {seed.value: (i + 1) * 10 for i, seed in enumerate(defaults)}
        index: dict[str, object] = {}
        for rid, value, label in existing:
            for k in match_keys(value, label):
                index.setdefault(k, rid)

        parents = [m for m in missing if m.parent is None]
        children = [m for m in missing if m.parent is not None]
        for seed in parents:
            row = Lookup(
                tenant_id=tenant_id, key=key, value=seed.value, label=seed.label,
                description=seed.description, sort_order=order[seed.value], active=True,
            )
            db.add(row)
            added += 1
            if children:
                await db.flush()
                for k in match_keys(seed.value, seed.label):
                    index.setdefault(k, row.id)
        by_value = {seed.value: seed for seed in defaults}
        for seed in children:
            parent_seed = by_value.get(seed.parent or "")
            parent_id = None
            if parent_seed is not None:
                for k in match_keys(parent_seed.value, parent_seed.label):
                    if k in index:
                        parent_id = index[k]
                        break
            db.add(
                Lookup(
                    tenant_id=tenant_id, key=key, value=seed.value, label=seed.label,
                    description=seed.description, sort_order=order[seed.value],
                    active=True, parent_id=parent_id,
                )
            )
            added += 1
    if added:
        await db.flush()
    return added
