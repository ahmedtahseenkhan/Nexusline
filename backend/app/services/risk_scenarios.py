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
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.models.enums import AssetClass, Criticality

__all__ = [
    "ASSET_KINDS",
    "ASSET_KIND_LABELS",
    "ASSET_KIND_VALUES",
    "AssetKind",
    "CATALOGUE",
    "FITS",
    "WRONG_CLASS",
    "WRONG_KIND",
    "classify_asset",
    "kind_labels",
    "library_kinds_for",
    "parse_kinds",
    "scenario_fit",
    "IMPACT_RULES",
    "ScenarioSpec",
    "applies_to_asset",
    "impact_for",
    "likelihood_for",
    "scale",
    "title_for",
    # phase 3: the candidate queue
    "PROPOSAL_STATUSES",
    "CommitPlan",
    "KeyOwner",
    "NewCandidate",
    "PairIn",
    "Placement",
    "ProposalFacts",
    "candidate_title",
    "dedupe_key",
    "group_subject",
    "group_title",
    "key_owners",
    "match_generated_title",
    "merge_candidates",
    "merge_refs",
    "place_asset",
    "plan_commit",
    "scope_label",
    "split_refs",
    "survivor_of",
    "title_patterns",
    "worst_scores",
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
    #: Catalogue-spelled references of the controls that address this scenario, from
    #: ``services.control_mapping``. Resolved against the organisation's own catalogue
    #: at generation time; unresolved ones are reported, never invented.
    control_references: tuple[str, ...] = ()
    #: The asset kinds (:data:`ASSET_KINDS`) the scenario fits, on top of
    #: ``asset_classes``. Empty = every kind.
    asset_kinds: tuple[str, ...] = ()


_INFO = (AssetClass.information_asset.value,)
_IT = (AssetClass.it_asset.value,)
_BOTH: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Asset kinds (re-check of 17 Sep 2026, F-04).
#
# The asset class (information / IT) is too coarse to pick scenarios: "internal fraud
# committed through Firewall" and "ransomware encrypts Firewall" were proposed because
# a firewall is an IT asset like any other. An asset is also given a small, fixed set of
# *kinds* — what it is, and for systems and data what business it serves — derived from
# fields the register already has (media type, tags, name and technical identifiers,
# data categories). A scenario names the kinds it fits.
# ---------------------------------------------------------------------------
KIND_NETWORK = "network_device"
KIND_SERVER = "server"
KIND_END_USER = "end_user_device"
KIND_APPLICATION = "application"
KIND_DATABASE = "database"
KIND_CLOUD = "cloud_service"
KIND_FACILITY = "facility"
KIND_PEOPLE = "people"
KIND_IT_OTHER = "it_other"
KIND_INFORMATION = "information"
KIND_CORE_BANKING = "core_banking"
KIND_PAYMENT = "payment_system"
KIND_CHANNEL = "customer_channel"
KIND_CUSTOMER_DATA = "customer_data"

#: What the asset *is*.
KIND_GROUP_WHAT = "What the asset is"
#: What business the system or data *serves* — the kinds financial-crime scenarios need.
KIND_GROUP_SERVES = "What it serves"


@dataclass(frozen=True)
class AssetKind:
    value: str
    label: str
    description: str
    group: str


ASSET_KINDS: tuple[AssetKind, ...] = (
    AssetKind(KIND_NETWORK, "Network device",
              "Firewalls, routers, switches, load balancers, VPN and wireless equipment", KIND_GROUP_WHAT),
    AssetKind(KIND_SERVER, "Server or host",
              "Physical and virtual servers, mainframes, storage and HSMs", KIND_GROUP_WHAT),
    AssetKind(KIND_END_USER, "End-user device",
              "Laptops, desktops, phones, tablets, printers, ATMs and kiosks", KIND_GROUP_WHAT),
    AssetKind(KIND_APPLICATION, "Application",
              "Business applications, portals, middleware and APIs", KIND_GROUP_WHAT),
    AssetKind(KIND_DATABASE, "Database or data store",
              "Databases, data warehouses and data lakes", KIND_GROUP_WHAT),
    AssetKind(KIND_CLOUD, "Cloud or IT service",
              "SaaS, cloud hosting and managed IT services", KIND_GROUP_WHAT),
    AssetKind(KIND_FACILITY, "Facility",
              "Data centres, DR sites, branches and offices", KIND_GROUP_WHAT),
    AssetKind(KIND_PEOPLE, "People", "Staff, contractors and roles", KIND_GROUP_WHAT),
    AssetKind(KIND_IT_OTHER, "Other IT asset",
              "An IT asset whose type the register does not say", KIND_GROUP_WHAT),
    AssetKind(KIND_INFORMATION, "Information or records",
              "Any information asset: records, datasets, documents", KIND_GROUP_WHAT),
    AssetKind(KIND_CORE_BANKING, "Core banking",
              "The core banking system and the assets that run it", KIND_GROUP_SERVES),
    AssetKind(KIND_PAYMENT, "Payment system",
              "SWIFT, RAAST, RTGS, card switches, payment gateways and POS", KIND_GROUP_SERVES),
    AssetKind(KIND_CHANNEL, "Customer channel",
              "Internet and mobile banking, ATMs, wallets, website and contact centre", KIND_GROUP_SERVES),
    AssetKind(KIND_CUSTOMER_DATA, "Customer or financial data",
              "Customer, account, card, transaction and other financial data", KIND_GROUP_SERVES),
)
ASSET_KIND_VALUES: frozenset[str] = frozenset(k.value for k in ASSET_KINDS)
ASSET_KIND_LABELS: dict[str, str] = {k.value: k.label for k in ASSET_KINDS}

_PRIMARY_IT = frozenset({
    KIND_NETWORK, KIND_SERVER, KIND_END_USER, KIND_APPLICATION, KIND_DATABASE, KIND_CLOUD,
    KIND_FACILITY, KIND_PEOPLE,
})
#: Kinds that never carry a business function: a "Payments Firewall" is still a firewall,
#: and fraud is not committed through it.
_NO_FUNCTION = frozenset({KIND_NETWORK, KIND_FACILITY, KIND_PEOPLE})


def _rx(*alternatives: str) -> re.Pattern:
    return re.compile("|".join(alternatives), re.IGNORECASE)


#: Keyword recognisers per kind, matched on whole words. Deliberately conservative:
#: a wrong kind hides a scenario, so an unrecognised IT asset falls back to "other IT
#: asset", which most technical scenarios include.
_KIND_WORDS: dict[str, re.Pattern] = {
    KIND_NETWORK: _rx(
        r"\bfire[\s-]?walls?\b", r"\brouters?\b", r"(?<!card )(?<!payment )\bswitch(?:es)?\b",
        r"\bload[\s-]?balancers?\b", r"\bvpn\b", r"\bwan\b", r"\bsd[\s-]?wan\b", r"\blan\b", r"\bmpls\b",
        r"\bwi[\s-]?fi\b", r"\bwireless\b", r"\baccess[\s-]+points?\b", r"\bids\b", r"\bips\b",
        r"\bproxy\b", r"\bwaf\b", r"\bdmz\b", r"\bnetwork\b", r"\bfortigate\b", r"\bfortinet\b",
        r"\bpalo[\s-]?alto\b", r"\bcheck[\s-]?point\b", r"\bjuniper\b", r"\bcisco\b", r"\bsophos\b",
        r"\bmikrotik\b", r"\baruba\b", r"\bf5\b", r"\bpan-os\b", r"\bfortios\b", r"\bjunos\b",
        r"\bnx-os\b", r"\bios[\s-]?xe\b",
    ),
    KIND_SERVER: _rx(
        r"\bservers?\b", r"\bhosts?\b", r"\bvms?\b", r"\bvirtual[\s-]+machines?\b", r"\bhypervisors?\b",
        r"\besxi?\b", r"\bvmware\b", r"\bhyper-v\b", r"\bmainframes?\b", r"\bas/?400\b", r"\biseries\b",
        r"\bstorage\b", r"\bsan\b", r"\bnas\b", r"\bhsms?\b", r"\bdomain[\s-]+controllers?\b",
        r"\bpoweredge\b", r"\bproliant\b", r"\bucs\b", r"\blinux\b", r"\bunix\b", r"\baix\b",
        r"\bsolaris\b", r"\brhel\b", r"\bred[\s-]?hat\b", r"\bubuntu\b", r"\bcentos\b",
    ),
    KIND_END_USER: _rx(
        r"\blaptops?\b", r"\bdesktops?\b", r"\bworkstations?\b", r"\bnotebooks?\b", r"\bpcs?\b",
        r"\bendpoints?\b", r"\bmobile[\s-]+(?:phones?|devices?|handsets?)\b", r"\bsmart[\s-]?phones?\b",
        r"\btablets?\b", r"\bipads?\b", r"\biphones?\b", r"\bprinters?\b", r"\bthin[\s-]+clients?\b",
        r"\batms?\b", r"\bkiosks?\b", r"\bcdms?\b", r"\bwindows[\s-]+(?:7|8|10|11)\b", r"\bmacos\b",
        r"\bandroid\b",
    ),
    KIND_DATABASE: _rx(
        r"\bdatabases?\b", r"\bdbs?\b", r"\bsql\b", r"\bmssql\b", r"\bmysql\b", r"\bpostgres(?:ql)?\b",
        r"\bmongo(?:db)?\b", r"\boracle[\s-]+(?:db|database|rac)\b", r"\bdb2\b", r"\bdata[\s-]?warehouses?\b",
        r"\bdwh\b", r"\bdata[\s-]?lakes?\b", r"\bdata[\s-]?stores?\b", r"\bdata[\s-]?marts?\b",
    ),
    KIND_APPLICATION: _rx(
        r"\bapplications?\b", r"\bapps?\b", r"\bsoftware\b", r"\bsystems?\b", r"\bportals?\b", r"\berp\b",
        r"\bcrm\b", r"\bsap\b", r"\bplatforms?\b", r"\bsuite\b", r"\bmiddleware\b", r"\bapis?\b",
        r"\bgateways?\b", r"\bweb[\s-]?sites?\b",
    ),
    KIND_CLOUD: _rx(
        r"\bcloud\b", r"\bsaas\b", r"\biaas\b", r"\bpaas\b", r"\baws\b", r"\bazure\b", r"\bgcp\b",
        r"\bgoogle[\s-]+workspace\b", r"\b(?:office|microsoft)[\s-]?365\b", r"\bo365\b", r"\bsalesforce\b",
        r"\bhosting\b", r"\bhosted\b", r"\bmanaged[\s-]+services?\b",
    ),
    KIND_FACILITY: _rx(
        r"\bdata[\s-]?cent(?:er|re)s?\b", r"\bdr[\s-]+sites?\b", r"\bdisaster[\s-]+recovery[\s-]+sites?\b",
        r"\bbranch(?:es)?\b", r"\boffices?\b", r"\bbuildings?\b", r"\bpremises\b", r"\bvaults?\b",
        r"\bserver[\s-]+rooms?\b", r"\bcampus\b", r"(?<!data )\bwarehouses?\b",
    ),
    KIND_PEOPLE: _rx(r"\bstaff\b", r"\bpersonnel\b", r"\bemployees?\b", r"\bcontractors?\b", r"\bworkforce\b"),
    KIND_CORE_BANKING: _rx(
        r"\bcore[\s-]*banking\b", r"\bcbs\b", r"\bt24\b", r"\btemenos\b", r"\bfinacle\b", r"\bflex\s?cube\b",
        r"\bbancs\b", r"\bsymbols\b", r"\bimal\b",
    ),
    KIND_PAYMENT: _rx(
        r"\bpayments?\b", r"\bswift\b", r"\braast\b", r"\brtgs\b", r"\bprism\b", r"\b1[\s-]?link\b",
        r"\bone[\s-]?link\b", r"\bcard[\s-]+(?:switch|management|issuing|acquiring|processing)\b",
        r"\bpostilion\b", r"\bbase\s?24\b", r"\beuronet\b", r"\bpaypak\b", r"\bpos\b", r"\bremittances?\b",
        r"\bclearing\b", r"\bnift\b", r"\bibft\b", r"\b(?:funds?|wire)[\s-]+transfers?\b", r"\bvisa\b",
        r"\bmastercard\b", r"\bunionpay\b",
    ),
    KIND_CHANNEL: _rx(
        r"\b(?:internet|online|mobile|digital|phone|sms|whatsapp|branchless)[\s-]?banking\b",
        r"\be-?banking\b", r"\bnet[\s-]?banking\b", r"\batms?\b", r"\bcdms?\b", r"\bkiosks?\b", r"\bivr\b",
        r"\b(?:call|contact)[\s-]+cent(?:er|re)s?\b", r"\bweb[\s-]?sites?\b", r"\b(?:web|customer)[\s-]+portal\b",
        r"\bwallets?\b", r"\b(?:mobile|banking)[\s-]+apps?\b",
    ),
    KIND_CUSTOMER_DATA: _rx(
        r"\bcustomers?\b", r"\bclients?\b", r"\bcardholders?\b", r"\bcard[\s-]+data\b", r"\bpan\b",
        r"\bpii\b", r"\bpersonal[\s-]+data\b", r"\bkyc\b", r"\bcif\b", r"\baccounts?\b",
        r"\btransactions?\b", r"\bfinancial\b", r"\bbalances?\b", r"\bloans?\b", r"\bdeposits?\b",
        r"\bpayroll\b", r"\bsalar(?:y|ies)\b", r"\bledgers?\b",
    ),
}

#: eramba's built-in media types (``reference_data.BUILTIN_MEDIA_TYPES``), normalised.
#: ``None`` means the type is refined by keywords (hardware, software).
_MEDIA_KINDS: dict[str, frozenset[str] | None] = {
    "network": frozenset({KIND_NETWORK}),
    "hardware": None,
    "software": None,
    "it service": frozenset({KIND_CLOUD}),
    "it services": frozenset({KIND_CLOUD}),
    "facilities": frozenset({KIND_FACILITY}),
    "facility": frozenset({KIND_FACILITY}),
    "people": frozenset({KIND_PEOPLE}),
    "data asset": frozenset({KIND_INFORMATION}),
    "financial": frozenset({KIND_INFORMATION, KIND_CUSTOMER_DATA}),
}


def _words(kind: str, *texts: str) -> bool:
    pattern = _KIND_WORDS[kind]
    return any(pattern.search(t) for t in texts if t)


def classify_asset(
    *,
    asset_class: str,
    name: str = "",
    media_type: str = "",
    tags: Iterable[str] = (),
    hostname: str = "",
    os_version: str = "",
    manufacturer: str = "",
    model_number: str = "",
    data_categories: str = "",
) -> frozenset[str]:
    """The kinds of one asset. Pure; every asset gets at least one kind.

    1. **What it is.** An information asset is *information*. An IT asset takes its kind
       from the media type — Network, IT Service, Facilities, People directly; Hardware
       is a network device, end-user device or (by default) a server, and Software a
       database or (by default) an application, by keywords in its name, tags, hostname,
       OS, manufacturer and model. A custom or missing media type falls back to those
       keywords (facility and people from the name only, so a ``DC-Karachi`` tag does
       not make a server a building). An IT asset still unrecognised is *other IT asset*.
    2. **What it serves** — core banking, payment system, customer channel — from
       keywords in the name, tags and media type, never the description or hostname
       (a firewall "protecting the core banking server" is not core banking). Network
       devices, facilities and people never serve a function.
    3. **Customer or financial data** — from the data categories, the Financial media
       type, or the name of an information asset or database.
    """
    info = asset_class == AssetClass.information_asset.value
    media = " ".join((media_type or "").lower().split())
    tag_text = " ".join(t for t in tags if t)
    technical = (name, tag_text, hostname, os_version, manufacturer, model_number)
    functional = (name, tag_text, media_type)

    kinds: set[str] = set()
    from_media = _MEDIA_KINDS.get(media, ()) if media else ()
    if info:
        kinds.add(KIND_INFORMATION)
        kinds |= set(from_media or ()) & {KIND_CUSTOMER_DATA}
    elif media == "hardware":
        found = {k for k in (KIND_NETWORK, KIND_END_USER, KIND_SERVER) if _words(k, *technical)}
        kinds |= found or {KIND_SERVER}
    elif media == "software":
        kinds.add(KIND_DATABASE if _words(KIND_DATABASE, *technical) else KIND_APPLICATION)
        if _words(KIND_CLOUD, *technical):
            kinds.add(KIND_CLOUD)
    elif from_media:
        kinds |= set(from_media)
    else:
        text = (*technical, media_type)
        for kind in (KIND_NETWORK, KIND_SERVER, KIND_END_USER, KIND_DATABASE, KIND_APPLICATION, KIND_CLOUD):
            if _words(kind, *text):
                kinds.add(kind)
        for kind in (KIND_FACILITY, KIND_PEOPLE):
            if _words(kind, name, media_type):
                kinds.add(kind)
    if not info and not (kinds & _PRIMARY_IT):
        kinds.add(KIND_IT_OTHER)

    what = kinds - {KIND_CUSTOMER_DATA}
    if not what <= _NO_FUNCTION:
        for kind in (KIND_CORE_BANKING, KIND_PAYMENT, KIND_CHANNEL):
            if _words(kind, *functional):
                kinds.add(kind)
        if _words(KIND_CUSTOMER_DATA, data_categories) or (
            (info or KIND_DATABASE in kinds) and _words(KIND_CUSTOMER_DATA, name, tag_text)
        ):
            kinds.add(KIND_CUSTOMER_DATA)
    return frozenset(kinds)


def parse_kinds(value: str | Iterable[str] | None) -> tuple[tuple[str, ...], list[str]]:
    """``"payment_system, Core_Banking"`` -> ``(("core_banking", "payment_system"), [])``:
    known kinds (sorted, no repeats) and the unknown spellings, in order."""
    parts = value.split(",") if isinstance(value, str) else list(value or ())
    known: set[str] = set()
    unknown: list[str] = []
    for part in parts:
        kind = (part or "").strip().lower()
        if not kind:
            continue
        if kind in ASSET_KIND_VALUES:
            known.add(kind)
        elif kind not in unknown:
            unknown.append(kind)
    return tuple(sorted(known)), unknown


def kind_labels(kinds: Iterable[str]) -> list[str]:
    """Kinds as people read them, in vocabulary order."""
    wanted = set(kinds)
    return [k.label for k in ASSET_KINDS if k.value in wanted]


# Which scenarios fit which kinds. Named sets so the catalogue reads as a decision.
_IT_ALL = (
    KIND_NETWORK, KIND_SERVER, KIND_END_USER, KIND_APPLICATION, KIND_DATABASE, KIND_CLOUD,
    KIND_CORE_BANKING, KIND_PAYMENT, KIND_CHANNEL, KIND_IT_OTHER,
)
_DATA = (KIND_INFORMATION, KIND_CUSTOMER_DATA)


def _all_but(*excluded: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    return tuple(k for k in _IT_ALL if k not in excluded) + extra


#: Systems and data alike.
_K_ANY = _IT_ALL + _DATA
#: Anything someone administers or depends on — not individual end-user devices.
_K_MANAGED = _all_but(KIND_END_USER, extra=_DATA)
#: Where data is stored and can be encrypted or read — not network devices.
_K_HOLDS_DATA = _all_but(KIND_NETWORK, extra=_DATA)
#: Physical media that is decommissioned.
_K_MEDIA = (KIND_SERVER, KIND_END_USER, KIND_NETWORK, KIND_DATABASE, KIND_IT_OTHER) + _DATA
#: Where malicious code runs — not network devices or provider-run services.
_K_RUNS_CODE = _all_but(KIND_NETWORK, KIND_CLOUD)
#: Reachable services that can be flooded.
_K_REACHABLE = (
    KIND_NETWORK, KIND_SERVER, KIND_APPLICATION, KIND_CLOUD, KIND_CORE_BANKING, KIND_PAYMENT,
    KIND_CHANNEL, KIND_IT_OTHER,
)
#: Application-layer interfaces.
_K_APPLICATIONS = (KIND_APPLICATION, KIND_CLOUD, KIND_CORE_BANKING, KIND_PAYMENT, KIND_CHANNEL)
#: Hosted infrastructure with capacity, DR and suppliers.
_K_HOSTED = _all_but(KIND_END_USER)
#: Where records are processed and duties segregated.
_K_PROCESSING = (
    KIND_APPLICATION, KIND_DATABASE, KIND_CLOUD, KIND_CORE_BANKING, KIND_PAYMENT, KIND_CHANNEL,
    KIND_IT_OTHER,
) + _DATA
#: Things in a building the bank runs.
_K_ON_PREMISES = _all_but(KIND_END_USER, KIND_CLOUD, extra=(KIND_FACILITY,))
#: Portable equipment — only devices recognised as such: "theft of SWIFT Alliance" is
#: not a risk anyone would write.
_K_PORTABLE = (KIND_END_USER,)
#: Equipment in a room, and the room.
_K_PHYSICAL = (KIND_SERVER, KIND_NETWORK, KIND_IT_OTHER, KIND_FACILITY)
#: Financial crime: only where money moves or customer and financial data lives.
_K_FRAUD_INTERNAL = (KIND_CORE_BANKING, KIND_PAYMENT, KIND_CHANNEL, KIND_CUSTOMER_DATA)
_K_FRAUD_EXTERNAL = (KIND_CORE_BANKING, KIND_PAYMENT, KIND_CHANNEL)


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
       treatment_hint="Enforce role-based access, quarterly recertification and joiner/mover/leaver automation.",
       asset_kinds=_K_ANY),
    _s("RS-002", "Privileged account misuse on {asset}",
       "A privileged or administrative account is used beyond its authorised purpose, with no independent "
       "review of privileged activity.",
       "Access Control", _BOTH, "Privilege abuse", "Unmonitored privileged accounts",
       3, RULE_CRITICALITY,
       treatment_hint="Vault privileged credentials, enforce session recording and four-eyes on admin actions.",
       asset_kinds=_K_MANAGED),
    _s("RS-003", "Credential compromise affecting {asset}",
       "User credentials are phished, guessed or reused from a breached third party, granting an attacker "
       "legitimate-looking access.",
       "Access Control", _BOTH, "Credential theft", "Weak or single-factor authentication",
       4, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Enforce MFA for all remote and privileged access; monitor for credential stuffing.",
       asset_kinds=_K_ANY),
    _s("RS-004", "Shared or generic accounts obscure accountability on {asset}",
       "Activity cannot be attributed to an individual because accounts are shared between staff.",
       "Access Control", _BOTH, "Loss of accountability", "Shared or generic accounts",
       3, RULE_PROPERTY, impact_property="integrity",
       treatment_hint="Eliminate shared accounts; where unavoidable, vault and check out per use.",
       asset_kinds=_K_MANAGED),
    # --- Data confidentiality ----------------------------------------------
    _s("RS-005", "Data leakage from {asset}",
       "Customer or confidential data leaves the institution through email, removable media, cloud storage "
       "or an unmanaged endpoint.",
       "Data Protection", _INFO, "Data exfiltration", "No data loss prevention on egress channels",
       3, RULE_BUSINESS_VALUE,
       treatment_hint="Deploy DLP on mail, web and endpoints; block unapproved removable media.",
       asset_kinds=_DATA),
    _s("RS-006", "Unauthorised disclosure of {asset} to third parties",
       "Data is shared with an outsourcing partner, vendor or regulator without an approved basis, agreement "
       "or protection requirement.",
       "Data Protection", _INFO, "Improper disclosure", "No data-sharing agreement or classification handling rules",
       2, RULE_BUSINESS_VALUE,
       treatment_hint="Require a data-sharing agreement and classification-based handling rules before release.",
       asset_kinds=_DATA),
    _s("RS-007", "Data at rest in {asset} is not encrypted",
       "Stored data is readable to anyone who obtains the underlying media, backup or database file.",
       "Data Protection", _BOTH, "Theft of storage media", "Missing encryption at rest",
       2, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Encrypt at rest with managed keys; separate key custody from data custody.",
       asset_kinds=_K_HOLDS_DATA),
    _s("RS-008", "Data in transit to or from {asset} is intercepted",
       "Traffic is captured or modified because it traverses the network without adequate transport security.",
       "Data Protection", _BOTH, "Interception of communications", "Weak or absent transport encryption",
       2, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Enforce TLS 1.2+ with certificate pinning on sensitive channels; retire legacy protocols.",
       asset_kinds=_K_ANY),
    _s("RS-009", "Retention of {asset} beyond its lawful or business need",
       "Data is kept after its retention period, increasing breach exposure and regulatory liability.",
       "Data Protection", _INFO, "Regulatory non-compliance", "No enforced retention or disposal schedule",
       3, RULE_BUSINESS_VALUE,
       treatment_hint="Define retention per data category and automate secure disposal at expiry.",
       asset_kinds=_DATA),
    _s("RS-010", "Insecure disposal of {asset}",
       "Media or records are decommissioned without secure erasure, leaving recoverable data.",
       "Data Protection", _BOTH, "Recovery of discarded data", "No secure disposal procedure",
       2, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Certified media sanitisation with destruction certificates retained as evidence.",
       asset_kinds=_K_MEDIA),
    # --- Malware, cyber attack ---------------------------------------------
    _s("RS-011", "Ransomware encrypts {asset}",
       "Malware encrypts the asset and its reachable backups, halting the service until recovery or payment.",
       "Cyber Security", _BOTH, "Ransomware", "Insufficient segmentation and immutable backup",
       3, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Immutable offline backups, tested restore, network segmentation and EDR containment.",
       asset_kinds=_K_HOLDS_DATA),
    _s("RS-012", "Malware infection of {asset}",
       "Malicious code executes on the asset through email, removable media or a compromised update.",
       "Cyber Security", _IT, "Malicious code", "Inadequate endpoint protection or patching",
       3, RULE_CRITICALITY,
       treatment_hint="EDR with behavioural detection, application allow-listing and controlled update channels.",
       asset_kinds=_K_RUNS_CODE),
    _s("RS-013", "Exploitation of an unpatched vulnerability in {asset}",
       "A known vulnerability remains unpatched past its remediation window and is exploited.",
       "Cyber Security", _IT, "Exploitation of known vulnerability", "Missing or delayed patching",
       3, RULE_CRITICALITY,
       treatment_hint="Risk-based patch SLAs by severity, with exception approval and compensating controls.",
       asset_kinds=_IT_ALL),
    _s("RS-014", "Denial of service against {asset}",
       "The service is made unavailable to customers by volumetric or application-layer attack.",
       "Cyber Security", _BOTH, "Denial of service", "No upstream scrubbing or rate limiting",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Upstream DDoS scrubbing, rate limiting and a tested traffic-diversion runbook.",
       asset_kinds=_K_REACHABLE),
    _s("RS-015", "Web application attack against {asset}",
       "Injection, broken authentication or insecure direct object reference is exploited against an "
       "internet-facing interface.",
       "Cyber Security", _IT, "Application-layer attack", "Insecure application code or configuration",
       3, RULE_CRITICALITY,
       treatment_hint="Secure SDLC with SAST/DAST gates, WAF in blocking mode and annual penetration testing.",
       asset_kinds=_K_APPLICATIONS),
    _s("RS-016", "Insecure configuration of {asset}",
       "The asset is deployed with default credentials, unnecessary services or a permissive baseline.",
       "Cyber Security", _IT, "Misconfiguration", "No hardened build standard",
       3, RULE_CRITICALITY,
       treatment_hint="Hardened baselines per platform with automated drift detection.",
       asset_kinds=_IT_ALL),
    _s("RS-017", "Compromise of {asset} through a supply-chain update",
       "A trusted software update or library introduces malicious code.",
       "Cyber Security", _IT, "Supply-chain compromise", "Unverified software provenance",
       2, RULE_CRITICALITY,
       treatment_hint="Verify signatures, maintain an SBOM and stage updates before production release.",
       asset_kinds=_IT_ALL),
    # --- Availability & continuity ------------------------------------------
    _s("RS-018", "Prolonged outage of {asset}",
       "Hardware failure, capacity exhaustion or a failed change makes the asset unavailable beyond its "
       "recovery time objective.",
       "Business Continuity", _BOTH, "Service interruption", "Single point of failure",
       3, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Remove single points of failure; test failover against the stated RTO.",
       asset_kinds=_K_MANAGED),
    _s("RS-019", "Backup of {asset} cannot be restored",
       "Backups exist but have never been successfully restored, or do not cover the required recovery point.",
       "Business Continuity", _BOTH, "Data loss", "Untested backup and recovery",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Schedule restore tests, record results as evidence and measure against the RPO.",
       asset_kinds=_K_MANAGED),
    _s("RS-020", "Disaster-recovery failover for {asset} does not work when invoked",
       "The DR environment is out of date, under-capacity or has never been exercised end to end.",
       "Business Continuity", _IT, "Failure of recovery arrangements", "Untested or stale DR environment",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Annual full failover exercise with business sign-off on the achieved RTO/RPO.",
       asset_kinds=_K_HOSTED),
    _s("RS-021", "Loss of key personnel supporting {asset}",
       "Knowledge of the asset is concentrated in one person, with no documented procedures or trained backup.",
       "Business Continuity", _BOTH, "Loss of key personnel", "Key-person dependency",
       3, RULE_CRITICALITY,
       treatment_hint="Document run-books, cross-train a named deputy and enforce mandatory leave.",
       asset_kinds=_K_MANAGED + (KIND_PEOPLE,)),
    _s("RS-022", "Utility or facility failure affecting {asset}",
       "Power, cooling or physical access to the hosting facility fails for a sustained period.",
       "Business Continuity", _IT, "Environmental failure", "Inadequate facility resilience",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Redundant power and cooling with tested generator run-ups.",
       asset_kinds=_K_ON_PREMISES),
    # --- Change, integrity, operations --------------------------------------
    _s("RS-023", "Unauthorised change to {asset}",
       "A change is applied without approval, testing or the ability to roll back.",
       "Change Management", _BOTH, "Unauthorised change", "Inadequate change control",
       3, RULE_PROPERTY, impact_property="integrity",
       treatment_hint="Enforce CAB approval, segregated deployment rights and automated rollback.",
       asset_kinds=_K_MANAGED),
    _s("RS-024", "Data integrity failure in {asset}",
       "Records are corrupted or silently altered by faulty processing, migration or reconciliation gaps.",
       "Operations", _BOTH, "Data corruption", "No integrity or reconciliation controls",
       2, RULE_PROPERTY, impact_property="integrity",
       treatment_hint="Automated reconciliation with break reporting and independent review.",
       asset_kinds=_K_PROCESSING),
    _s("RS-025", "Processing error in {asset} goes undetected",
       "A manual or batch processing error is not detected before it affects customers or reporting.",
       "Operations", _BOTH, "Processing error", "Insufficient validation and exception reporting",
       3, RULE_PROPERTY, impact_property="integrity",
       treatment_hint="Input validation, exception queues with owners, and daily control totals.",
       asset_kinds=_K_PROCESSING),
    _s("RS-026", "Segregation of duties conflict around {asset}",
       "One individual can initiate and approve the same sensitive action.",
       "Operations", _BOTH, "Internal fraud", "Segregation of duties conflict",
       2, RULE_CRITICALITY,
       treatment_hint="Enforce maker-checker in the system; review SoD conflicts quarterly.",
       asset_kinds=_K_PROCESSING),
    _s("RS-027", "Insufficient logging and monitoring of {asset}",
       "Security-relevant events are not logged, retained or reviewed, so an incident goes unnoticed.",
       "Operations", _BOTH, "Undetected compromise", "Inadequate logging and monitoring",
       3, RULE_CRITICALITY,
       treatment_hint="Forward logs to the SIEM with use-cases, alerting thresholds and retention.",
       asset_kinds=_K_ANY),
    _s("RS-028", "Capacity of {asset} is exceeded",
       "Growth in volume outstrips capacity, degrading service before anyone notices.",
       "Operations", _IT, "Capacity exhaustion", "No capacity monitoring or forecasting",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Capacity thresholds with trend-based forecasting and a documented upgrade path.",
       asset_kinds=_K_HOSTED),
    _s("RS-029", "{asset} runs on unsupported or end-of-life technology",
       "The platform no longer receives security fixes from its vendor.",
       "Operations", _IT, "Unsupported technology", "End-of-life software or hardware",
       3, RULE_CRITICALITY,
       treatment_hint="Maintain a lifecycle register with funded upgrade plans ahead of end-of-support.",
       asset_kinds=_all_but(KIND_CLOUD)),
    # --- Third party & outsourcing ------------------------------------------
    _s("RS-030", "Third-party failure disrupts {asset}",
       "An outsourced provider or cloud service supporting the asset fails, and the contract provides no "
       "enforceable recovery commitment.",
       "Third Party", _BOTH, "Third-party service failure", "Inadequate contractual or exit arrangements",
       2, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Contractual RTOs with penalties, a tested exit plan and a named alternative provider.",
       asset_kinds=_K_MANAGED),
    _s("RS-031", "Third-party staff access {asset} without adequate control",
       "Vendor or contractor personnel hold standing access without supervision, screening or revocation.",
       "Third Party", _BOTH, "Third-party misuse", "Uncontrolled vendor access",
       3, RULE_PROPERTY, impact_property="confidentiality",
       treatment_hint="Time-bound, supervised and recorded vendor access, revoked at contract close.",
       asset_kinds=_K_MANAGED),
    _s("RS-032", "Concentration risk on the provider supporting {asset}",
       "A single provider supports several critical services, so one failure has systemic impact.",
       "Third Party", _BOTH, "Provider concentration", "No alternative provider or exit capability",
       2, RULE_CRITICALITY,
       treatment_hint="Assess concentration at portfolio level and maintain a viable substitution path.",
       asset_kinds=_K_MANAGED),
    # --- Physical -----------------------------------------------------------
    _s("RS-033", "Theft or loss of {asset}",
       "The asset — or the device holding it — is stolen or lost outside the premises.",
       "Physical Security", _IT, "Theft", "Inadequate physical protection or device encryption",
       2, RULE_CRITICALITY,
       treatment_hint="Full-disk encryption, asset tagging, remote wipe and a loss-reporting procedure.",
       asset_kinds=_K_PORTABLE),
    _s("RS-034", "Unauthorised physical access to {asset}",
       "Someone reaches the asset's location without an authorised, logged entry.",
       "Physical Security", _IT, "Unauthorised physical access", "Weak physical access control",
       2, RULE_CRITICALITY,
       treatment_hint="Badge control with anti-passback, visitor escort and periodic access reviews.",
       asset_kinds=_K_PHYSICAL),
    _s("RS-035", "Fire, flood or natural hazard affecting {asset}",
       "An environmental event damages the asset or its hosting location.",
       "Physical Security", _IT, "Natural hazard", "Insufficient environmental protection",
       1, RULE_PROPERTY, impact_property="availability",
       treatment_hint="Detection and suppression systems, geographically separated DR, tested evacuation.",
       asset_kinds=_K_PHYSICAL),
    # --- Compliance & regulatory ---------------------------------------------
    _s("RS-036", "Regulatory non-compliance involving {asset}",
       "The asset is handled in a way that breaches a regulatory obligation, attracting censure or penalty.",
       "Compliance", _BOTH, "Regulatory breach", "Obligations not mapped to controls",
       2, RULE_BUSINESS_VALUE,
       treatment_hint="Map obligations to controls with named owners and evidence of operation.",
       asset_kinds=_K_MANAGED),
    _s("RS-037", "Cross-border transfer of {asset} without a lawful basis",
       "Data leaves the jurisdiction — often via a cloud service — without the approvals data-sovereignty "
       "rules require.",
       "Compliance", _INFO, "Unlawful data transfer", "No data-residency control",
       2, RULE_BUSINESS_VALUE,
       treatment_hint="Pin data residency contractually and technically; obtain approval before any transfer.",
       asset_kinds=_DATA),
    _s("RS-038", "Customer data in {asset} is processed without a lawful basis or consent",
       "Personal data is used for a purpose the customer never agreed to.",
       "Compliance", _INFO, "Privacy breach", "No consent or purpose-limitation control",
       2, RULE_BUSINESS_VALUE,
       treatment_hint="Record purpose and lawful basis in the RoPA; enforce purpose limitation in systems.",
       asset_kinds=(KIND_CUSTOMER_DATA,)),
    _s("RS-039", "Records supporting {asset} cannot be produced for an audit or inspection",
       "Evidence of control operation is missing, incomplete or not retrievable within the time allowed.",
       "Compliance", _BOTH, "Inability to evidence compliance", "No evidence retention",
       2, RULE_CRITICALITY,
       treatment_hint="Attach evidence to controls as they operate rather than reconstructing at audit time.",
       asset_kinds=_K_MANAGED),
    # --- Fraud ---------------------------------------------------------------
    _s("RS-040", "Internal fraud committed through {asset}",
       "An employee manipulates the asset for personal gain, exploiting weak monitoring or SoD.",
       "Financial Crime", _BOTH, "Internal fraud", "Insufficient monitoring of sensitive transactions",
       2, RULE_CRITICALITY,
       treatment_hint="Behavioural analytics on sensitive transactions with independent investigation.",
       asset_kinds=_K_FRAUD_INTERNAL),
    _s("RS-041", "External fraud against customers via {asset}",
       "Attackers use the channel to defraud customers through social engineering or account takeover.",
       "Financial Crime", _BOTH, "External fraud", "Weak transaction authentication or anomaly detection",
       3, RULE_CRITICALITY,
       treatment_hint="Step-up authentication on risk signals plus real-time anomaly scoring.",
       asset_kinds=_K_FRAUD_EXTERNAL),
    _s("RS-042", "{asset} is used to move funds linked to money laundering",
       "The channel processes transactions that should have been detected and reported.",
       "Financial Crime", _BOTH, "Money laundering", "Inadequate transaction monitoring rules",
       2, RULE_CRITICALITY,
       treatment_hint="Tune monitoring scenarios, test coverage annually and escalate to the FMU on time.",
       asset_kinds=_K_FRAUD_EXTERNAL),
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
    #: The asset's kinds (:func:`classify_asset`). Empty = not classified: only the class
    #: decides, as before kinds existed.
    kinds: frozenset[str] = frozenset()


#: Why a scenario is not proposed for an asset (:func:`scenario_fit`).
FITS, WRONG_CLASS, WRONG_KIND = "fits", "class", "kind"


def scenario_fit(spec: ScenarioSpec, facts: AssetFacts) -> str:
    """:data:`FITS`, or why not: :data:`WRONG_CLASS` (information vs IT) or
    :data:`WRONG_KIND` (the scenario names kinds and the asset is none of them).

    The preview counts kind mismatches separately, so "no fraud scenario for the
    firewall" reads as a decision rather than a gap.
    """
    if spec.asset_classes and facts.asset_class not in spec.asset_classes:
        return WRONG_CLASS
    if spec.asset_kinds and facts.kinds and not (facts.kinds & set(spec.asset_kinds)):
        return WRONG_KIND
    return FITS


def applies_to_asset(spec: ScenarioSpec, facts: AssetFacts) -> bool:
    """True when the scenario is relevant to this asset.

    An empty ``asset_classes`` means "any class" and empty ``asset_kinds`` "any kind" —
    most scenarios are narrower (a DR failover scenario is meaningless against a data
    record, internal fraud against a firewall), and proposing an irrelevant risk is the
    fastest way to make a generated register untrustworthy.
    """
    return scenario_fit(spec, facts) == FITS


def library_kinds_for(row, spec: ScenarioSpec) -> str | None:
    """The ``asset_kinds`` to write on a tenant's installed template, or None to leave it.

    Only a row that has no kinds yet and still *is* the library scenario — same title,
    category, asset classes, threat and vulnerability — takes the library's kinds.
    Retuned likelihood, description, treatment or control references do not change what
    the scenario is about, so they do not block it; a retitled or re-scoped row is the
    tenant's own and is left alone.
    """
    if (getattr(row, "asset_kinds", "") or "").strip() or not spec.asset_kinds:
        return None

    def same(a, b) -> bool:
        return " ".join((a or "").split()).lower() == " ".join((b or "").split()).lower()

    classes = ",".join(sorted(c.strip() for c in (row.asset_classes or "").split(",") if c.strip()))
    if not (
        same(row.title, spec.title) and same(row.category, spec.category)
        and classes == ",".join(sorted(spec.asset_classes))
        and same(row.threat, spec.threat) and same(row.vulnerability, spec.vulnerability)
    ):
        return None
    return ",".join(sorted(spec.asset_kinds))


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


# ---------------------------------------------------------------------------
# Phase 3 (F-04): the candidate queue.
#
# Generation used to write one register risk per asset × scenario pair, which is how a
# reviewed register reached 1,700 near-duplicates. Pairs now become *candidates*
# (``RiskProposal`` rows) grouped by a de-duplication key, and only a candidate a person
# accepts becomes a register risk. Everything below is pure so the grouping, the skip
# rules and the titles are unit-tested without a database; the API layer loads the
# facts and applies the plan.
#
# The key — scenario + process + business unit — is the unit a bank assesses: "ransomware
# against the assets that run Payments in Retail Banking" is one risk with forty servers
# behind it, not forty risks.
# ---------------------------------------------------------------------------
#: A candidate's lifecycle. Only ``pending`` can be accepted, rejected or merged.
PROPOSAL_STATUSES: tuple[str, ...] = ("pending", "accepted", "rejected", "merged")
PENDING, ACCEPTED, REJECTED, MERGED = PROPOSAL_STATUSES

_CLASS_NOUN = {
    AssetClass.information_asset.value: "information assets",
    AssetClass.it_asset.value: "IT assets",
}


@dataclass(frozen=True)
class Placement:
    """Where an asset sits for de-duplication: the process and business unit whose
    risk it is part of. Names are for titles and labels only; the key uses ids."""

    asset_class: str
    process_id: uuid.UUID | None = None
    process_name: str = ""
    business_unit_id: uuid.UUID | None = None
    business_unit_name: str = ""


def place_asset(
    *,
    asset_class: str,
    owner_unit: tuple[uuid.UUID, str] | None,
    processes: Iterable[tuple[uuid.UUID, str, uuid.UUID | None]],
    unit_names: Mapping[uuid.UUID, str],
) -> Placement:
    """Decide an asset's process and business unit. The exact rule (documented in the
    user guide, pinned by tests):

    * **Process** — the asset's live linked processes; with several, the first by name
      (case-insensitive, then id), so the choice is stable between runs.
    * **Business unit** — the asset's owning unit (the asset form's *Owner*) when it is
      live; otherwise the unit that runs the chosen process.

    ``owner_unit`` is ``(id, name)`` of a *live* owning unit, or None. ``processes`` are
    ``(id, name, business_unit_id)`` of *live* processes. ``unit_names`` names live units.
    """
    ordered = sorted(processes, key=lambda p: ((p[1] or "").strip().lower(), str(p[0])))
    process = ordered[0] if ordered else None
    unit_id, unit_name = owner_unit if owner_unit else (None, "")
    if unit_id is None and process is not None and process[2] in unit_names:
        unit_id, unit_name = process[2], unit_names[process[2]]
    return Placement(
        asset_class=asset_class,
        process_id=process[0] if process else None,
        process_name=(process[1] or "").strip() if process else "",
        business_unit_id=unit_id,
        business_unit_name=(unit_name or "").strip(),
    )


def dedupe_key(
    reference: str,
    process_id: uuid.UUID | None,
    business_unit_id: uuid.UUID | None,
    asset_class: str = "",
) -> str:
    """``<SCENARIO>|<process id or ->|<business unit id or ->``.

    Two pairs with the same key are one risk. When an asset has neither a process nor a
    business unit, the asset class is appended (``RS-011|-|-|it_asset``) so unplaced
    IT assets and unplaced information assets are not folded into one candidate.
    """
    ref = (reference or "").strip().upper()
    if process_id is None and business_unit_id is None:
        return f"{ref}|-|-|{(asset_class or '-').strip()}"
    return f"{ref}|{process_id or '-'}|{business_unit_id or '-'}"


def scope_label(placement: Placement) -> str:
    """How a candidate's scope reads in lists: *Payments · Retail Banking*."""
    parts = [p for p in (placement.process_name, placement.business_unit_name) if p]
    return " · ".join(parts) if parts else _CLASS_NOUN.get(placement.asset_class, "assets").capitalize()


def group_subject(placement: Placement) -> str:
    """What stands in for ``{asset}`` when one candidate covers several assets."""
    if placement.process_name and placement.business_unit_name:
        return f"{placement.process_name} assets in {placement.business_unit_name}"
    if placement.process_name:
        return f"{placement.process_name} assets"
    if placement.business_unit_name:
        return f"{placement.business_unit_name} assets"
    return _CLASS_NOUN.get(placement.asset_class, "assets")


def _fit_title(title: str) -> str:
    title = " ".join(title.split())
    if title:
        title = title[0].upper() + title[1:]
    return title if len(title) <= 255 else title[:254] + "…"


def group_title(template_title: str, subject: str) -> str:
    """A scenario title rendered for a group of assets (``subject``), e.g. *Ransomware
    encrypts Payments assets in Retail Banking*. Mirrors :func:`title_for`."""
    if "{asset}" in template_title:
        return _fit_title(template_title.replace("{asset}", subject))
    return _fit_title(f"{template_title} — {subject}")


def candidate_title(titles: Sequence[str], *, group: str, asset_count: int, single_asset_titles: set[str]) -> str:
    """The title a candidate carries.

    ``titles`` are the titles offered for it (the stored title first when merging into
    an existing candidate). One asset: the offered title stands (the reviewer may have
    edited it). Several assets: a shared title is kept — the preview sends the group's
    title, edited or not — unless it names only one of the assets (a per-asset generated
    title, lower-cased in ``single_asset_titles``), in which case the group title is used.
    """
    offered = [t.strip() for t in titles if t and t.strip()]
    if asset_count <= 1 and offered:
        return _fit_title(offered[0])
    distinct = list(dict.fromkeys(offered))
    if len(distinct) == 1 and not _names_one_asset(distinct[0], single_asset_titles):
        return _fit_title(distinct[0])
    return group


def _names_one_asset(title: str, single_asset_titles: set[str]) -> bool:
    """A per-asset generated title, possibly with the preview's `` (hostname)`` suffix."""
    low = title.strip().lower()
    return low in single_asset_titles or any(low.startswith(t + " (") for t in single_asset_titles if t)


def worst_scores(scores: Iterable[tuple[int | None, int | None]]) -> tuple[int | None, int | None]:
    """The most exposed (likelihood, impact) of several: highest score, then the higher
    impact, then the higher likelihood. A candidate is scored at its worst asset."""
    best: tuple[tuple[int, int, int], tuple[int, int]] | None = None
    for likelihood, impact in scores:
        if not likelihood or not impact:
            continue
        rank = (likelihood * impact, impact, likelihood)
        if best is None or rank > best[0]:
            best = (rank, (likelihood, impact))
    return best[1] if best else (None, None)


def split_refs(value: str | None) -> list[str]:
    """``"A.8.5, CIS 6.3"`` -> ``["A.8.5", "CIS 6.3"]`` (blank entries dropped)."""
    return [r.strip() for r in (value or "").split(",") if r.strip()]


def merge_refs(*groups: Iterable[str]) -> list[str]:
    """Control references from several sources, first spelling kept, no repeats
    (compared case-insensitively), order preserved."""
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for ref in group:
            ref = (ref or "").strip()
            if ref and ref.lower() not in seen:
                seen.add(ref.lower())
                out.append(ref)
    return out


# ----------------------------------------------------- legacy generated titles ---
@dataclass(frozen=True)
class TitlePattern:
    reference: str
    regex: re.Pattern


def title_patterns(templates: Iterable[tuple[str, str]]) -> list[TitlePattern]:
    """Recognisers for titles written by the pre-queue generator, one risk per asset:
    ``(reference, title template)`` -> a regex capturing the asset name. A trailing
    `` (hostname)`` added to tell same-named assets apart is tolerated."""
    out: list[TitlePattern] = []
    suffix = r"(?: \((?P<tag>[^()]+)\))?$"
    for reference, template in templates:
        template = (template or "").strip()
        if not template:
            continue
        if "{asset}" in template:
            before, _, after = template.partition("{asset}")
            body = re.escape(before) + r"(?P<asset>.+?)" + re.escape(after.replace("{asset}", ""))
        else:
            body = re.escape(template) + r" — (?P<asset>.+?)"
        out.append(TitlePattern(reference, re.compile("^" + body + suffix, re.IGNORECASE)))
    return out


def match_generated_title(title: str, patterns: Sequence[TitlePattern]) -> list[tuple[str, list[str]]]:
    """Every ``(scenario reference, possible asset names)`` a register title could have
    been generated from. An asset whose own name ends in brackets (``Payments DB
    (Primary)``) is ambiguous with the disambiguating suffix, so both readings are
    offered; the caller keeps the one naming an asset the risk actually links."""
    out: list[tuple[str, list[str]]] = []
    text = (title or "").strip()
    for pattern in patterns:
        found = pattern.regex.match(text)
        if not found:
            continue
        asset = found.group("asset").strip()
        tag = found.group("tag")
        names = [f"{asset} ({tag})", asset] if tag else [asset]
        out.append((pattern.reference, names))
    return out


# --------------------------------------------------------------- key ownership ---
@dataclass(frozen=True)
class ProposalFacts:
    """What the queue needs to know about a stored candidate."""

    id: uuid.UUID
    dedupe_key: str
    status: str
    title: str = ""
    merged_into_id: uuid.UUID | None = None
    promoted_risk_id: uuid.UUID | None = None
    decision_note: str = ""
    decided_at: datetime | None = None


@dataclass(frozen=True)
class KeyOwner:
    """What a de-duplication key already has. ``status``:

    * ``accepted`` — a candidate with this key became a risk that is still live
      (``risk_reference``): new pairs are skipped as already in the register;
    * ``pending`` — a candidate is waiting (``proposal_id``): new pairs join it;
    * ``rejected`` — the last candidate was rejected (``note``): the preview says so and
      leaves the pair unticked, but a person may still send it.
    """

    status: str
    proposal_id: uuid.UUID
    title: str = ""
    risk_id: uuid.UUID | None = None
    risk_reference: str = ""
    note: str = ""
    decided_at: datetime | None = None


def survivor_of(proposal: ProposalFacts, by_id: Mapping[uuid.UUID, ProposalFacts]) -> ProposalFacts:
    """Follow ``merged_into_id`` to the candidate that absorbed this one (itself when it
    was never merged). A broken or circular chain stops at the last candidate reached."""
    current = proposal
    seen = {current.id}
    while current.status == MERGED and current.merged_into_id is not None:
        nxt = by_id.get(current.merged_into_id)
        if nxt is None or nxt.id in seen:
            break
        seen.add(nxt.id)
        current = nxt
    return current


def key_owners(
    proposals: Iterable[ProposalFacts],
    by_id: Mapping[uuid.UUID, ProposalFacts],
    live_risks: Mapping[uuid.UUID, str],
) -> dict[str, KeyOwner]:
    """The owner of each key among ``proposals`` (oldest first).

    A merged candidate counts as its survivor, so pairs whose candidate was folded into
    another follow it. Precedence: an accepted candidate whose risk is live (``live_risks``
    maps live risk ids to references) > the oldest pending candidate > the latest
    rejection. An accepted candidate whose risk was archived owns nothing: the key is no
    longer in the register.
    """
    rank = {ACCEPTED: 3, PENDING: 2, REJECTED: 1}
    out: dict[str, KeyOwner] = {}
    for proposal in proposals:
        final = survivor_of(proposal, by_id)
        if final.status == ACCEPTED:
            if final.promoted_risk_id not in live_risks:
                continue
            owner = KeyOwner(
                ACCEPTED, final.id, final.title, final.promoted_risk_id,
                live_risks[final.promoted_risk_id],
            )
        elif final.status == PENDING:
            owner = KeyOwner(PENDING, final.id, final.title)
        elif final.status == REJECTED:
            owner = KeyOwner(REJECTED, final.id, final.title, note=final.decision_note, decided_at=final.decided_at)
        else:
            continue
        held = out.get(proposal.dedupe_key)
        if held is None or rank[owner.status] > rank[held.status]:
            out[proposal.dedupe_key] = owner
        elif owner.status == REJECTED == held.status and _later(owner.decided_at, held.decided_at):
            out[proposal.dedupe_key] = owner
    return out


def _later(a: datetime | None, b: datetime | None) -> bool:
    if a is None:
        return False
    return b is None or a > b


# ------------------------------------------------------------------ the commit plan ---
@dataclass(frozen=True)
class PairIn:
    """One asset × scenario pair sent to the queue, with everything the plan needs."""

    index: int
    asset_id: uuid.UUID
    key: str
    title: str
    likelihood: int
    impact: int
    scenario_reference: str = ""
    asset_name: str = ""
    #: The title this pair's asset would get on its own (``title_for``) — never kept on
    #: a candidate that covers several assets.
    auto_title: str = ""
    #: The candidate's title when it covers several assets.
    group_title: str = ""
    refs: tuple[str, ...] = ()
    description: str = ""
    business_unit_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None


@dataclass
class NewCandidate:
    key: str
    pairs: list[PairIn] = field(default_factory=list)

    @property
    def asset_ids(self) -> list[uuid.UUID]:
        return list(dict.fromkeys(p.asset_id for p in self.pairs))

    @property
    def scores(self) -> tuple[int | None, int | None]:
        return worst_scores((p.likelihood, p.impact) for p in self.pairs)

    @property
    def refs(self) -> list[str]:
        return merge_refs(*(p.refs for p in self.pairs))

    @property
    def title(self) -> str:
        first = self.pairs[0]
        return candidate_title(
            [p.title for p in self.pairs],
            group=first.group_title or first.title,
            asset_count=len(self.asset_ids),
            single_asset_titles={p.auto_title.lower() for p in self.pairs if p.auto_title},
        )


@dataclass
class CommitPlan:
    new: list[NewCandidate] = field(default_factory=list)
    #: Pending candidates from earlier runs -> the pairs joining them.
    merges: dict[uuid.UUID, list[PairIn]] = field(default_factory=dict)
    #: Pairs already in the register, with the reference of the risk that covers them.
    skipped: list[tuple[PairIn, str]] = field(default_factory=list)

    @property
    def created(self) -> int:
        return len(self.new)

    @property
    def merged_into_existing(self) -> int:
        return sum(len(v) for v in self.merges.values())

    @property
    def merged(self) -> int:
        """Pairs that joined a candidate instead of creating one: those folded into a
        candidate created earlier in the same run, plus those joining the queue's."""
        return sum(len(c.pairs) - 1 for c in self.new) + self.merged_into_existing


def plan_commit(
    pairs: Sequence[PairIn],
    *,
    owners: Mapping[str, KeyOwner],
    legacy_keys: Mapping[str, str] | None = None,
    register_titles: Mapping[str, str] | None = None,
) -> CommitPlan:
    """Decide, pair by pair in order, what sending ``pairs`` to the queue does.

    1. **Already in the register** — skipped, never queued: the key's candidate was
       accepted and its risk is live; or a live risk written by the old one-risk-per-asset
       generator covers the key (``legacy_keys``); or a live risk carries the pair's title
       (``register_titles``, lower-cased title -> reference).
    2. **Joins the queue** — the key has a pending candidate: the pair's asset is added
       to it (``merges``).
    3. **Duplicate within the run** — the key was already started in this run: the pair
       joins that new candidate.
    4. Otherwise it starts a new candidate.

    Invariant: ``created + merged + len(skipped) == len(pairs)``.
    """
    legacy_keys = legacy_keys or {}
    register_titles = register_titles or {}
    plan = CommitPlan()
    started: dict[str, NewCandidate] = {}
    for pair in pairs:
        owner = owners.get(pair.key)
        covered = None
        if owner is not None and owner.status == ACCEPTED:
            covered = owner.risk_reference or "an accepted candidate"
        elif pair.key in legacy_keys:
            covered = legacy_keys[pair.key]
        else:
            for title in (pair.title, pair.auto_title):
                hit = register_titles.get((title or "").strip().lower())
                if hit:
                    covered = hit
                    break
        if covered is not None:
            plan.skipped.append((pair, covered))
        elif owner is not None and owner.status == PENDING:
            plan.merges.setdefault(owner.proposal_id, []).append(pair)
        elif pair.key in started:
            started[pair.key].pairs.append(pair)
        else:
            candidate = NewCandidate(pair.key, [pair])
            started[pair.key] = candidate
            plan.new.append(candidate)
    return plan


# ------------------------------------------------------------------- queue merge ---
@dataclass(frozen=True)
class MergeOutcome:
    likelihood: int | None
    impact: int | None
    control_references: str
    asset_ids: list[uuid.UUID]


def merge_candidates(
    survivor_scores: tuple[int | None, int | None],
    survivor_refs: str,
    survivor_assets: Sequence[uuid.UUID],
    others: Sequence[tuple[tuple[int | None, int | None], str, Sequence[uuid.UUID]]],
) -> MergeOutcome:
    """What the surviving candidate holds after others are merged into it: every asset
    (no repeats, survivor's first), every control reference, and the worst scores."""
    likelihood, impact = worst_scores([survivor_scores, *(o[0] for o in others)])
    refs = merge_refs(split_refs(survivor_refs), *(split_refs(o[1]) for o in others))
    assets = list(dict.fromkeys([*survivor_assets, *(a for o in others for a in o[2])]))
    return MergeOutcome(likelihood, impact, ", ".join(refs), assets)
