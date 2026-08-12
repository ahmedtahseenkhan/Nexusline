"""Built-in risk-scenario library, and the pure arithmetic that turns one into a risk.

An asset register is the input a bank already has; a risk register is the thing it is
asked to produce. ISO 27005 says how to get from one to the other — a risk is a *threat*
exploiting a *vulnerability* against an *asset* — but doing it by hand for a few thousand
assets is what stops the register from ever being finished.

This module supplies the missing middle: a catalogue of threat/vulnerability pairs, each
knowing which kinds of asset it applies to and how to derive an opening score from that
asset's own criticality. The generation endpoint pairs every selected asset with every
applicable scenario and proposes a risk. **Nothing here scores a risk on its own** — the
proposals are pre-filled starting points that a risk owner edits and commits, which is
the difference between a helpful register and a fabricated one.

Everything is pure (no DB, no FastAPI) so the scoring rules are unit-testable, and the
catalogue is static data versioned with the code — a tenant installs it into its own
editable ``risk_scenario_templates`` table and takes it from there.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.enums import AssetClass, Criticality

__all__ = [
    "CATALOGUE",
    "IMPACT_RULES",
    "ScenarioSpec",
    "applies_to_asset",
    "impact_for",
    "likelihood_for",
    "scale",
    "title_for",
]

# --- impact derivation rules ------------------------------------------------
#: Impact follows the *data's* business value — the ISO 27005 primary-asset view.
RULE_BUSINESS_VALUE = "from_business_value"
#: Impact follows the asset's overall criticality rating.
RULE_CRITICALITY = "from_criticality"
#: Impact follows the highest of the asset's confidentiality/integrity/availability.
RULE_CIA_MAX = "from_cia_max"
#: Impact follows one specific security property (set ``impact_property``).
RULE_PROPERTY = "from_property"
#: Impact is whatever the scenario says, regardless of the asset.
RULE_FIXED = "fixed"

IMPACT_RULES = (
    RULE_BUSINESS_VALUE, RULE_CRITICALITY, RULE_CIA_MAX, RULE_PROPERTY, RULE_FIXED,
)

_CRITICALITY_RANK: dict[Criticality, int] = {
    Criticality.low: 1,
    Criticality.medium: 2,
    Criticality.high: 3,
    Criticality.critical: 4,
}


@dataclass(frozen=True)
class ScenarioSpec:
    """One catalogue entry, before it is installed into a tenant's editable table."""

    reference: str
    title: str  # may contain "{asset}"
    description: str
    category: str
    asset_classes: tuple[str, ...]  # empty = every kind of asset
    threat: str
    vulnerability: str
    likelihood: int  # expressed on a 1-5 scale; rescaled to the tenant's matrix
    impact_rule: str
    impact_property: str = ""  # confidentiality | integrity | availability
    fixed_impact: int = 0  # 1-5 scale, only for RULE_FIXED
    treatment_hint: str = ""


_INFO = (AssetClass.information_asset.value,)
_IT = (AssetClass.it_asset.value,)
_BOTH: tuple[str, ...] = ()


def _s(*args, **kwargs) -> ScenarioSpec:
    return ScenarioSpec(*args, **kwargs)


# ---------------------------------------------------------------------------
# The catalogue. Threat and vulnerability wording follows ISO/IEC 27005 Annex A
# families, narrowed to what actually shows up in a bank's register.
# ---------------------------------------------------------------------------
CATALOGUE: tuple[ScenarioSpec, ...] = (
    # --- Unauthorised access & identity ------------------------------------
    _s("RS-001", "Unauthorised access to {asset}",
       "An attacker or unauthorised insider obtains access to the asset because access rights are not "
       "restricted, reviewed or revoked in line with least privilege.",
       "Access Control", _BOTH, "Unauthorised access", "Excessive or unreviewed access rights",
       3, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Enforce role-based access, quarterly recertification and joiner/mover/leaver automation."),
    _s("RS-002", "Privileged account misuse on {asset}",
       "A privileged or administrative account is used beyond its authorised purpose, with no independent "
       "review of privileged activity.",
       "Access Control", _BOTH, "Privilege abuse", "Unmonitored privileged accounts",
       3, RULE_CRITICALITY,
       treatment_hint="Vault privileged credentials, enforce session recording and four-eyes on admin actions."),
    _s("RS-003", "Credential compromise affecting {asset}",
       "User credentials are phished, guessed or reused from a breached third party, granting an attacker "
       "legitimate-looking access.",
       "Access Control", _BOTH, "Credential theft", "Weak or single-factor authentication",
       4, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Enforce MFA for all remote and privileged access; monitor for credential stuffing."),
    _s("RS-004", "Shared or generic accounts obscure accountability on {asset}",
       "Activity cannot be attributed to an individual because accounts are shared between staff.",
       "Access Control", _BOTH, "Loss of accountability", "Shared or generic accounts",
       3, RULE_PROPERTY, impact_property="integrity",
       treatment_hint="Eliminate shared accounts; where unavoidable, vault and check out per use."),
    # --- Data confidentiality ----------------------------------------------
    _s("RS-005", "Data leakage from {asset}",
       "Customer or confidential data leaves the institution through email, removable media, cloud storage "
       "or an unmanaged endpoint.",
       "Data Protection", _INFO, "Data exfiltration", "No data loss prevention on egress channels",
       3, RULE_BUSINESS_VALUE,
       treatment_hint="Deploy DLP on mail, web and endpoints; block unapproved removable media."),
    _s("RS-006", "Unauthorised disclosure of {asset} to third parties",
       "Data is shared with an outsourcing partner, vendor or regulator without an approved basis, agreement "
       "or protection requirement.",
       "Data Protection", _INFO, "Improper disclosure", "No data-sharing agreement or classification handling rules",
       2, RULE_BUSINESS_VALUE,
       treatment_hint="Require a data-sharing agreement and classification-based handling rules before release."),
    _s("RS-007", "Data at rest in {asset} is not encrypted",
       "Stored data is readable to anyone who obtains the underlying media, backup or database file.",
       "Data Protection", _BOTH, "Theft of storage media", "Missing encryption at rest",
       2, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Encrypt at rest with managed keys; separate key custody from data custody."),
    _s("RS-008", "Data in transit to or from {asset} is intercepted",
       "Traffic is captured or modified because it traverses the network without adequate transport security.",
       "Data Protection", _BOTH, "Interception of communications", "Weak or absent transport encryption",
       2, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Enforce TLS 1.2+ with certificate pinning on sensitive channels; retire legacy protocols."),
    _s("RS-009", "Retention of {asset} beyond its lawful or business need",
       "Data is kept after its retention period, increasing breach exposure and regulatory liability.",
       "Data Protection", _INFO, "Regulatory non-compliance", "No enforced retention or disposal schedule",
       3, RULE_BUSINESS_VALUE,
       treatment_hint="Define retention per data category and automate secure disposal at expiry."),
    _s("RS-010", "Insecure disposal of {asset}",
       "Media or records are decommissioned without secure erasure, leaving recoverable data.",
       "Data Protection", _BOTH, "Recovery of discarded data", "No secure disposal procedure",
       2, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Certified media sanitisation with destruction certificates retained as evidence."),
    # --- Malware, cyber attack ---------------------------------------------
    _s("RS-011", "Ransomware encrypts {asset}",
       "Malware encrypts the asset and its reachable backups, halting the service until recovery or payment.",
       "Cyber Security", _BOTH, "Ransomware", "Insufficient segmentation and immutable backup",
       3, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Immutable offline backups, tested restore, network segmentation and EDR containment."),
    _s("RS-012", "Malware infection of {asset}",
       "Malicious code executes on the asset through email, removable media or a compromised update.",
       "Cyber Security", _IT, "Malicious code", "Inadequate endpoint protection or patching",
       3, RULE_CRITICALITY,
       treatment_hint="EDR with behavioural detection, application allow-listing and controlled update channels."),
    _s("RS-013", "Exploitation of an unpatched vulnerability in {asset}",
       "A known vulnerability remains unpatched past its remediation window and is exploited.",
       "Cyber Security", _IT, "Exploitation of known vulnerability", "Missing or delayed patching",
       3, RULE_CRITICALITY,
       treatment_hint="Risk-based patch SLAs by severity, with exception approval and compensating controls."),
    _s("RS-014", "Denial of service against {asset}",
       "The service is made unavailable to customers by volumetric or application-layer attack.",
       "Cyber Security", _BOTH, "Denial of service", "No upstream scrubbing or rate limiting",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Upstream DDoS scrubbing, rate limiting and a tested traffic-diversion runbook."),
    _s("RS-015", "Web application attack against {asset}",
       "Injection, broken authentication or insecure direct object reference is exploited against an "
       "internet-facing interface.",
       "Cyber Security", _IT, "Application-layer attack", "Insecure application code or configuration",
       3, RULE_CRITICALITY,
       treatment_hint="Secure SDLC with SAST/DAST gates, WAF in blocking mode and annual penetration testing."),
    _s("RS-016", "Insecure configuration of {asset}",
       "The asset is deployed with default credentials, unnecessary services or a permissive baseline.",
       "Cyber Security", _IT, "Misconfiguration", "No hardened build standard",
       3, RULE_CRITICALITY,
       treatment_hint="Hardened baselines per platform with automated drift detection."),
    _s("RS-017", "Compromise of {asset} through a supply-chain update",
       "A trusted software update or library introduces malicious code.",
       "Cyber Security", _IT, "Supply-chain compromise", "Unverified software provenance",
       2, RULE_CRITICALITY,
       treatment_hint="Verify signatures, maintain an SBOM and stage updates before production release."),
    # --- Availability & continuity ------------------------------------------
    _s("RS-018", "Prolonged outage of {asset}",
       "Hardware failure, capacity exhaustion or a failed change makes the asset unavailable beyond its "
       "recovery time objective.",
       "Business Continuity", _BOTH, "Service interruption", "Single point of failure",
       3, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Remove single points of failure; test failover against the stated RTO."),
    _s("RS-019", "Backup of {asset} cannot be restored",
       "Backups exist but have never been successfully restored, or do not cover the required recovery point.",
       "Business Continuity", _BOTH, "Data loss", "Untested backup and recovery",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Schedule restore tests, record results as evidence and measure against the RPO."),
    _s("RS-020", "Disaster-recovery failover for {asset} does not work when invoked",
       "The DR environment is out of date, under-capacity or has never been exercised end to end.",
       "Business Continuity", _IT, "Failure of recovery arrangements", "Untested or stale DR environment",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Annual full failover exercise with business sign-off on the achieved RTO/RPO."),
    _s("RS-021", "Loss of key personnel supporting {asset}",
       "Knowledge of the asset is concentrated in one person, with no documented procedures or trained backup.",
       "Business Continuity", _BOTH, "Loss of key personnel", "Key-person dependency",
       3, RULE_CRITICALITY,
       treatment_hint="Document run-books, cross-train a named deputy and enforce mandatory leave."),
    _s("RS-022", "Utility or facility failure affecting {asset}",
       "Power, cooling or physical access to the hosting facility fails for a sustained period.",
       "Business Continuity", _IT, "Environmental failure", "Inadequate facility resilience",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Redundant power and cooling with tested generator run-ups."),
    # --- Change, integrity, operations --------------------------------------
    _s("RS-023", "Unauthorised change to {asset}",
       "A change is applied without approval, testing or the ability to roll back.",
       "Change Management", _BOTH, "Unauthorised change", "Inadequate change control",
       3, RULE_PROPERTY, impact_property="integrity",
       treatment_hint="Enforce CAB approval, segregated deployment rights and automated rollback."),
    _s("RS-024", "Data integrity failure in {asset}",
       "Records are corrupted or silently altered by faulty processing, migration or reconciliation gaps.",
       "Operations", _BOTH, "Data corruption", "No integrity or reconciliation controls",
       2, RULE_PROPERTY, impact_property="integrity",
       treatment_hint="Automated reconciliation with break reporting and independent review."),
    _s("RS-025", "Processing error in {asset} goes undetected",
       "A manual or batch processing error is not detected before it affects customers or reporting.",
       "Operations", _BOTH, "Processing error", "Insufficient validation and exception reporting",
       3, RULE_PROPERTY, impact_property="integrity",
       treatment_hint="Input validation, exception queues with owners, and daily control totals."),
    _s("RS-026", "Segregation of duties conflict around {asset}",
       "One individual can initiate and approve the same sensitive action.",
       "Operations", _BOTH, "Internal fraud", "Segregation of duties conflict",
       2, RULE_CRITICALITY,
       treatment_hint="Enforce maker-checker in the system; review SoD conflicts quarterly."),
    _s("RS-027", "Insufficient logging and monitoring of {asset}",
       "Security-relevant events are not logged, retained or reviewed, so an incident goes unnoticed.",
       "Operations", _BOTH, "Undetected compromise", "Inadequate logging and monitoring",
       3, RULE_CRITICALITY,
       treatment_hint="Forward logs to the SIEM with use-cases, alerting thresholds and retention."),
    _s("RS-028", "Capacity of {asset} is exceeded",
       "Growth in volume outstrips capacity, degrading service before anyone notices.",
       "Operations", _IT, "Capacity exhaustion", "No capacity monitoring or forecasting",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Capacity thresholds with trend-based forecasting and a documented upgrade path."),
    _s("RS-029", "{asset} runs on unsupported or end-of-life technology",
       "The platform no longer receives security fixes from its vendor.",
       "Operations", _IT, "Unsupported technology", "End-of-life software or hardware",
       3, RULE_CRITICALITY,
       treatment_hint="Maintain a lifecycle register with funded upgrade plans ahead of end-of-support."),
    # --- Third party & outsourcing ------------------------------------------
    _s("RS-030", "Third-party failure disrupts {asset}",
       "An outsourced provider or cloud service supporting the asset fails, and the contract provides no "
       "enforceable recovery commitment.",
       "Third Party", _BOTH, "Third-party service failure", "Inadequate contractual or exit arrangements",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Contractual RTOs with penalties, a tested exit plan and a named alternative provider."),
    _s("RS-031", "Third-party staff access {asset} without adequate control",
       "Vendor or contractor personnel hold standing access without supervision, screening or revocation.",
       "Third Party", _BOTH, "Third-party misuse", "Uncontrolled vendor access",
       3, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Time-bound, supervised and recorded vendor access, revoked at contract close."),
    _s("RS-032", "Concentration risk on the provider supporting {asset}",
       "A single provider supports several critical services, so one failure has systemic impact.",
       "Third Party", _BOTH, "Provider concentration", "No alternative provider or exit capability",
       2, RULE_CRITICALITY,
       treatment_hint="Assess concentration at portfolio level and maintain a viable substitution path."),
    # --- Physical -----------------------------------------------------------
    _s("RS-033", "Theft or loss of {asset}",
       "The asset — or the device holding it — is stolen or lost outside the premises.",
       "Physical Security", _IT, "Theft", "Inadequate physical protection or device encryption",
       2, RULE_CRITICALITY,
       treatment_hint="Full-disk encryption, asset tagging, remote wipe and a loss-reporting procedure."),
    _s("RS-034", "Unauthorised physical access to {asset}",
       "Someone reaches the asset's location without an authorised, logged entry.",
       "Physical Security", _IT, "Unauthorised physical access", "Weak physical access control",
       2, RULE_CRITICALITY,
       treatment_hint="Badge control with anti-passback, visitor escort and periodic access reviews."),
    _s("RS-035", "Fire, flood or natural hazard affecting {asset}",
       "An environmental event damages the asset or its hosting location.",
       "Physical Security", _IT, "Natural hazard", "Insufficient environmental protection",
       1, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Detection and suppression systems, geographically separated DR, tested evacuation."),
    # --- Compliance & regulatory ---------------------------------------------
    _s("RS-036", "Regulatory non-compliance involving {asset}",
       "The asset is handled in a way that breaches a regulatory obligation, attracting censure or penalty.",
       "Compliance", _BOTH, "Regulatory breach", "Obligations not mapped to controls",
       2, RULE_BUSINESS_VALUE,
       treatment_hint="Map obligations to controls with named owners and evidence of operation."),
    _s("RS-037", "Cross-border transfer of {asset} without a lawful basis",
       "Data leaves the jurisdiction — often via a cloud service — without the approvals data-sovereignty "
       "rules require.",
       "Compliance", _INFO, "Unlawful data transfer", "No data-residency control",
       2, RULE_BUSINESS_VALUE,
       treatment_hint="Pin data residency contractually and technically; obtain approval before any transfer."),
    _s("RS-038", "Customer data in {asset} is processed without a lawful basis or consent",
       "Personal data is used for a purpose the customer never agreed to.",
       "Compliance", _INFO, "Privacy breach", "No consent or purpose-limitation control",
       2, RULE_BUSINESS_VALUE,
       treatment_hint="Record purpose and lawful basis in the RoPA; enforce purpose limitation in systems."),
    _s("RS-039", "Records supporting {asset} cannot be produced for an audit or inspection",
       "Evidence of control operation is missing, incomplete or not retrievable within the time allowed.",
       "Compliance", _BOTH, "Inability to evidence compliance", "No evidence retention",
       2, RULE_CRITICALITY,
       treatment_hint="Attach evidence to controls as they operate rather than reconstructing at audit time."),
    # --- Fraud ---------------------------------------------------------------
    _s("RS-040", "Internal fraud committed through {asset}",
       "An employee manipulates the asset for personal gain, exploiting weak monitoring or SoD.",
       "Financial Crime", _BOTH, "Internal fraud", "Insufficient monitoring of sensitive transactions",
       2, RULE_CRITICALITY,
       treatment_hint="Behavioural analytics on sensitive transactions with independent investigation."),
    _s("RS-041", "External fraud against customers via {asset}",
       "Attackers use the channel to defraud customers through social engineering or account takeover.",
       "Financial Crime", _BOTH, "External fraud", "Weak transaction authentication or anomaly detection",
       3, RULE_CRITICALITY,
       treatment_hint="Step-up authentication on risk signals plus real-time anomaly scoring."),
    _s("RS-042", "{asset} is used to move funds linked to money laundering",
       "The channel processes transactions that should have been detected and reported.",
       "Financial Crime", _BOTH, "Money laundering", "Inadequate transaction monitoring rules",
       2, RULE_CRITICALITY,
       treatment_hint="Tune monitoring scenarios, test coverage annually and escalate to the FMU on time."),
)


# ---------------------------------------------------------------------------
# Pure scoring helpers
# ---------------------------------------------------------------------------
def scale(value: int, matrix_size: int, from_size: int = 5) -> int:
    """Rescale a 1..``from_size`` catalogue value onto a 1..``matrix_size`` matrix.

    Rounds up so the top of one scale maps to the top of the other and nothing ever
    lands on 0 — a scenario that means "almost certain" must not become "rare" on a
    3x3 register.
    """
    if matrix_size == from_size:
        return max(1, min(value, matrix_size))
    scaled = math.ceil(value * matrix_size / from_size)
    return max(1, min(scaled, matrix_size))


def _from_criticality(level: Criticality | None, matrix_size: int) -> int:
    """Map a four-band criticality onto the tenant's scale (low..critical -> 1..size)."""
    rank = _CRITICALITY_RANK.get(level or Criticality.medium, 2)
    return scale(rank, matrix_size, from_size=len(_CRITICALITY_RANK))


@dataclass(frozen=True)
class AssetFacts:
    """The asset attributes scoring depends on, lifted out of the ORM row.

    Keeping the engine off the ORM means the derivation rules can be tested exhaustively
    without a database, and a future asset field cannot silently change scoring.
    """

    name: str
    asset_class: str
    criticality: Criticality
    business_value: Criticality
    confidentiality: Criticality
    integrity: Criticality
    availability: Criticality


def applies_to_asset(spec: ScenarioSpec, facts: AssetFacts) -> bool:
    """True when the scenario is relevant to this kind of asset.

    An empty ``asset_classes`` means "any asset" — most scenarios are class-specific
    (a DR failover scenario is meaningless against a data record), and proposing an
    irrelevant risk is the fastest way to make a generated register untrustworthy.
    """
    return not spec.asset_classes or facts.asset_class in spec.asset_classes


def impact_for(spec: ScenarioSpec, facts: AssetFacts, matrix_size: int) -> int:
    """Derive the opening impact score from the asset's own rating."""
    if spec.impact_rule == RULE_FIXED:
        return scale(spec.fixed_impact or 3, matrix_size)
    if spec.impact_rule == RULE_BUSINESS_VALUE:
        return _from_criticality(facts.business_value, matrix_size)
    if spec.impact_rule == RULE_CIA_MAX:
        worst = max(
            (facts.confidentiality, facts.integrity, facts.availability),
            key=lambda c: _CRITICALITY_RANK[c],
        )
        return _from_criticality(worst, matrix_size)
    if spec.impact_rule == RULE_PROPERTY:
        chosen = {
            "confidentiality": facts.confidentiality,
            "integrity": facts.integrity,
            "availability": facts.availability,
        }.get(spec.impact_property, facts.criticality)
        return _from_criticality(chosen, matrix_size)
    return _from_criticality(facts.criticality, matrix_size)


def likelihood_for(spec: ScenarioSpec, facts: AssetFacts, matrix_size: int) -> int:
    """The scenario's own base likelihood, rescaled to the tenant's matrix.

    Deliberately *not* derived from the asset: how often a threat materialises is a
    property of the threat and the environment, not of how much the asset is worth.
    Conflating the two double-counts criticality and pushes every important asset to
    the top-right corner of the heat map.
    """
    return scale(spec.likelihood, matrix_size)


def title_for(spec: ScenarioSpec, facts: AssetFacts) -> str:
    """Render the scenario title for one asset — also the de-duplication key."""
    if "{asset}" in spec.title:
        return spec.title.replace("{asset}", facts.name)
    return f"{spec.title} — {facts.name}"
