"""Which controls answer which risk scenario — the knowledge that closes the loop.

Install a framework and you get its clauses. Generate risks and you get a register. The
gap between them is the question every bank's risk function answers by hand: *for this
threat, which of our controls are supposed to be in the way?* This module holds that
answer as content, the way the scenario library holds threats and vulnerabilities:

* **Control frameworks.** Which library templates are catalogues of controls (as
  opposed to management clauses), and how each one's references are spelled once they
  land in the Control Catalogue — ``A.8.5`` for ISO, ``CIS 6.3`` for CIS, ``CS-3.3``
  for the SBP framework — so two frameworks numbering their controls ``6.3`` never
  collide.
* **Scenario mapping.** For each of the 42 scenarios, the controls that address it, in
  every control framework the library ships. Authored against ISO 27001 Annex A first
  (the vocabulary everything else cross-walks to), then CIS v8 and the SBP
  Cybersecurity framework, which is what the client's regulator examines against —
  and then the rest of the SBP set a Pakistani bank is examined on: ETGRM (technology
  governance), the Outsourcing framework and the BCP guidelines, so a generated risk
  in a bank that installed only the SBP frameworks still lands on controls.

Two rules keep this honest. The mapping says *"meant to address"*, never *"working"*:
a generated risk gets its controls linked, and its residual stays equal to inherent
until somebody assesses those controls — the system maps, a person judges. And nothing
here guesses: if the organisation has not installed a framework the mapping knows, the
scenario's references simply do not resolve and the proposal says which ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# ---------------------------------------------------------------------------
# Control-type frameworks and their catalogue spelling
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ControlFramework:
    template_key: str
    #: Prepended to the requirement reference in the Control Catalogue, so ``6.3`` from
    #: CIS and ``6.3`` from PCI DSS are two controls, not one.
    prefix: str
    #: Only requirements whose reference starts with one of these are controls; the
    #: rest are management-system clauses (ISO 27001's 4-10) and stay requirements only.
    control_ref_prefixes: tuple[str, ...] = ()
    #: Individual references that are controls although their section is not (ETGRM's
    #: "1.6 Segregation of duties" sits in the governance pillar). Exact match — a
    #: prefix would make ``OS-1.5`` swallow ``OS-1.50``.
    control_refs: tuple[str, ...] = ()
    #: For a framework whose catalogue spelling adds no prefix: the namespace its own
    #: references already carry (``A.``, ``CS-``, ``ETGRM-``), which is how a catalogue
    #: reference is traced back to its framework.
    namespace: str = ""


#: The SBP frameworks are split the way ISO 27001 is. Governance, risk-management and
#: assurance clauses (board oversight, the IT risk framework, the audit function) are
#: the management system and stay requirements; the operational ones — something a
#: bank does, and could test, on a schedule — are controls:
#:
#: * **ETGRM** — pillars 3 Information Security, 4 IT Operations, 5 Project Management
#:   & Acquisition, 6 BCP/DR and 7 IT Outsourcing, plus 1.6 Segregation of duties and
#:   1.9 Regulatory compliance (ISO's A.5.3 and A.5.31 are Annex A controls too).
#:   Pillars 1 (governance), 2 (IT risk management) and 8 (IT audit) are clauses.
#: * **Outsourcing** — sections 3-10 (due diligence, contracts, monitoring, data
#:   security, continuity, cloud/offshore, exit, regulatory notification) plus the
#:   outsourcing register (1.5) and the per-arrangement risk assessment, oversight and
#:   reassessment (2.3-2.5). Policy, accountability and the materiality method are
#:   governance.
#: * **BCP** — BIA (2), recovery strategy (4), plans (5), crisis management (6),
#:   testing (7), DR site and backup (9), plus periodic plan review (8.1) and training
#:   (8.3). Governance (1), the risk assessment (3), change-driven updates (8.2) and
#:   independent audit (8.4) are clauses.
#:
#: Their references are already namespaced (``ETGRM-3.4``, ``OS-6.2``, ``BCP-9.4``), so
#: the catalogue spells them as the framework does, like ``CS-3.3``: no two frameworks
#: can collide, and a control a bank already keyed as ``ETGRM-3.4`` is matched, not
#: duplicated.
CONTROL_FRAMEWORKS: dict[str, ControlFramework] = {
    "iso-27001-2022": ControlFramework("iso-27001-2022", "", ("A.",), namespace="A."),
    "cis-controls-v8": ControlFramework("cis-controls-v8", "CIS "),
    "sbp-cybersecurity": ControlFramework("sbp-cybersecurity", "", namespace="CS-"),
    "nist-800-53-r5": ControlFramework("nist-800-53-r5", ""),
    "pci-dss-4.0": ControlFramework("pci-dss-4.0", "PCI "),
    "sbp-etgrm": ControlFramework(
        "sbp-etgrm", "",
        ("ETGRM-3.", "ETGRM-4.", "ETGRM-5.", "ETGRM-6.", "ETGRM-7."),
        ("ETGRM-1.6", "ETGRM-1.9"),
        namespace="ETGRM-",
    ),
    "sbp-outsourcing": ControlFramework(
        "sbp-outsourcing", "",
        ("OS-3.", "OS-4.", "OS-5.", "OS-6.", "OS-7.", "OS-8.", "OS-9.", "OS-10."),
        ("OS-1.5", "OS-2.3", "OS-2.4", "OS-2.5"),
        namespace="OS-",
    ),
    "sbp-bcp": ControlFramework(
        "sbp-bcp", "",
        ("BCP-2.", "BCP-4.", "BCP-5.", "BCP-6.", "BCP-7.", "BCP-9."),
        ("BCP-8.1", "BCP-8.3"),
        namespace="BCP-",
    ),
}


def is_control_framework(template_key: str) -> bool:
    return template_key in CONTROL_FRAMEWORKS


def is_control_requirement(template_key: str, reference: str) -> bool:
    """Whether this requirement of this framework is a control (and so gets a
    Control Catalogue entry) rather than a management clause."""
    fw = CONTROL_FRAMEWORKS.get(template_key)
    if fw is None:
        return False
    if not fw.control_ref_prefixes and not fw.control_refs:
        return True
    return reference in fw.control_refs or (
        bool(fw.control_ref_prefixes) and reference.startswith(fw.control_ref_prefixes)
    )


def catalogue_reference(template_key: str, reference: str) -> str:
    """How the requirement's reference is spelled in the Control Catalogue."""
    fw = CONTROL_FRAMEWORKS.get(template_key)
    return f"{fw.prefix}{reference}" if fw else reference


def control_requirements(template: dict, template_key: str) -> list[dict]:
    """The requirements of a template that become controls, in template order."""
    return [r for r in template["requirements"] if is_control_requirement(template_key, r["reference"])]


# ---------------------------------------------------------------------------
# Scenario → controls
# ---------------------------------------------------------------------------
#: Scenario reference -> catalogue-spelled control references, ISO first, then CIS,
#: then SBP Cybersecurity. Order is presentation order in the proposal. The ETGRM,
#: Outsourcing and BCP references are kept in ``_SBP_SCENARIO_CONTROLS`` below and
#: appended, so the original mapping reads as it did and the addition can be told
#: apart (see ``upgraded_references``).
SCENARIO_CONTROLS: dict[str, tuple[str, ...]] = {
    # --- access control -------------------------------------------------------------
    "RS-001": ("A.5.15", "A.5.18", "A.8.3", "CIS 6.1", "CIS 6.2", "CIS 6.8", "CS-3.1", "CS-3.2"),
    "RS-002": ("A.8.2", "A.8.18", "A.8.15", "CIS 5.4", "CIS 6.5", "CIS 8.2", "CS-3.4", "CS-4.2"),
    "RS-003": ("A.5.17", "A.8.5", "A.5.16", "CIS 6.3", "CIS 6.4", "CIS 5.2", "CS-3.3", "CS-3.2"),
    "RS-004": ("A.5.16", "A.5.18", "A.8.15", "CIS 5.1", "CIS 5.3", "CIS 6.6", "CS-3.2", "CS-4.5"),
    # --- data protection -----------------------------------------------------------
    "RS-005": ("A.8.12", "A.5.12", "A.5.13", "A.8.11", "CIS 3.13", "CIS 3.7", "CIS 3.3", "CS-3.12", "CS-3.11"),
    "RS-006": ("A.5.14", "A.6.6", "A.5.19", "A.5.20", "CIS 3.3", "CIS 15.4", "CS-7.3", "CS-3.11"),
    "RS-007": ("A.8.24", "A.8.10", "CIS 3.11", "CIS 3.6", "CS-3.10", "CS-3.11"),
    "RS-008": ("A.8.24", "A.8.20", "A.5.14", "CIS 3.10", "CIS 12.6", "CS-3.10", "CS-3.6"),
    "RS-009": ("A.5.33", "A.8.10", "A.5.34", "CIS 3.4", "CIS 3.5", "CS-3.11"),
    "RS-010": ("A.7.14", "A.7.10", "A.8.10", "CIS 3.5", "CS-3.11"),
    # --- cyber security ------------------------------------------------------------
    "RS-011": ("A.8.7", "A.8.13", "A.8.16", "A.8.8", "CIS 10.1", "CIS 11.2", "CIS 11.4", "CIS 7.4", "CS-3.7", "CS-6.3", "CS-4.4"),
    "RS-012": ("A.8.7", "A.8.19", "A.8.23", "CIS 10.1", "CIS 10.2", "CIS 10.6", "CIS 9.2", "CS-3.7", "CS-3.13"),
    "RS-013": ("A.8.8", "A.8.9", "CIS 7.1", "CIS 7.3", "CIS 7.4", "CIS 7.5", "CS-3.8", "CS-2.5"),
    "RS-014": ("A.8.6", "A.8.14", "A.8.20", "A.8.21", "CIS 12.2", "CIS 13.3", "CS-3.5", "CS-3.6", "CS-6.1"),
    "RS-015": ("A.8.26", "A.8.28", "A.8.29", "A.8.25", "CIS 16.1", "CIS 16.10", "CIS 16.12", "CIS 16.13", "CS-3.14", "CS-4.9"),
    "RS-016": ("A.8.9", "A.8.19", "A.8.18", "CIS 4.1", "CIS 4.2", "CIS 4.7", "CIS 4.8", "CS-3.9", "CS-3.7"),
    "RS-017": ("A.5.21", "A.8.19", "A.8.32", "CIS 2.5", "CIS 16.5", "CIS 15.5", "CS-7.1", "CS-7.4", "CS-7.6"),
    # --- business continuity --------------------------------------------------------
    "RS-018": ("A.5.30", "A.8.14", "A.5.29", "CIS 11.1", "CS-6.1", "CS-6.2", "CS-6.5"),
    "RS-019": ("A.8.13", "CIS 11.2", "CIS 11.3", "CIS 11.5", "CS-6.3", "CS-6.4"),
    "RS-020": ("A.5.30", "A.8.14", "CIS 11.5", "CS-6.2", "CS-6.4"),
    "RS-021": ("A.5.2", "A.5.37", "A.6.5", "CIS 17.5", "CS-1.4"),
    "RS-022": ("A.7.11", "A.7.5", "A.7.8", "CS-3.15", "CS-6.1"),
    # --- change / operations --------------------------------------------------------
    "RS-023": ("A.8.32", "A.8.31", "A.8.9", "CIS 4.1", "CIS 16.8", "CS-3.9"),
    "RS-024": ("A.8.32", "A.8.29", "A.8.15", "CIS 3.1", "CIS 16.1", "CS-3.11", "CS-4.3"),
    "RS-025": ("A.8.16", "A.8.15", "A.5.37", "CIS 8.11", "CIS 8.2", "CS-4.3", "CS-4.7"),
    "RS-026": ("A.5.3", "A.5.18", "A.8.2", "CIS 6.8", "CIS 5.4", "CS-3.4", "CS-1.4"),
    "RS-027": ("A.8.15", "A.8.16", "A.8.17", "CIS 8.1", "CIS 8.2", "CIS 8.9", "CIS 8.11", "CIS 13.1", "CS-4.2", "CS-4.3", "CS-4.5"),
    "RS-028": ("A.8.6", "A.8.14", "CIS 12.1", "CS-6.1"),
    "RS-029": ("A.8.8", "A.8.9", "A.5.9", "CIS 2.2", "CIS 9.1", "CIS 12.1", "CS-3.8", "CS-2.1"),
    # --- third party ----------------------------------------------------------------
    "RS-030": ("A.5.19", "A.5.22", "A.5.30", "CIS 15.2", "CIS 15.6", "CS-7.1", "CS-7.4"),
    "RS-031": ("A.5.19", "A.5.20", "A.5.15", "A.6.6", "CIS 15.4", "CIS 6.1", "CS-7.5", "CS-7.3"),
    "RS-032": ("A.5.19", "A.5.21", "A.5.30", "CIS 15.3", "CS-7.6", "CS-2.8"),
    # --- physical -------------------------------------------------------------------
    "RS-033": ("A.7.9", "A.8.1", "A.7.10", "A.8.24", "CIS 4.10", "CIS 4.11", "CIS 3.6", "CS-3.7", "CS-3.15"),
    "RS-034": ("A.7.1", "A.7.2", "A.7.3", "A.7.4", "CS-3.15"),
    "RS-035": ("A.7.5", "A.7.8", "A.5.30", "CIS 11.4", "CS-3.15", "CS-6.1"),
    # --- compliance -----------------------------------------------------------------
    "RS-036": ("A.5.31", "A.5.36", "A.5.35", "CS-1.6", "CS-1.8"),
    "RS-037": ("A.5.31", "A.5.34", "A.5.14", "CIS 3.8", "CS-1.6", "CS-3.11"),
    "RS-038": ("A.5.34", "A.5.31", "A.5.12", "CIS 3.1", "CIS 3.7", "CS-1.6"),
    "RS-039": ("A.5.33", "A.8.15", "A.5.37", "CIS 8.10", "CIS 3.4", "CS-4.5", "CS-1.8"),
    # --- financial crime ------------------------------------------------------------
    "RS-040": ("A.5.3", "A.8.2", "A.8.15", "A.6.1", "CIS 6.8", "CIS 8.11", "CS-4.7", "CS-3.4"),
    "RS-041": ("A.8.5", "A.8.16", "A.5.7", "CIS 6.3", "CIS 13.1", "CIS 9.5", "CS-4.7", "CS-3.16", "CS-8.5"),
    "RS-042": ("A.8.16", "A.5.31", "A.8.15", "CIS 8.11", "CS-4.7", "CS-1.6"),
}


#: The rest of the SBP set, per scenario: ETGRM technology controls, then Outsourcing
#: (where a third party is in the chain), then BCP (where the scenario is a disruption).
#: Chosen from each clause's title and text; every reference is a control of its
#: framework (pinned by ``tests/test_control_mapping.py``).
_SBP_SCENARIO_CONTROLS: dict[str, tuple[str, ...]] = {
    # --- access control
    "RS-001": ("ETGRM-3.4", "ETGRM-3.5"),
    "RS-002": ("ETGRM-3.5", "ETGRM-3.10", "ETGRM-1.6"),
    "RS-003": ("ETGRM-3.5", "ETGRM-3.4"),
    "RS-004": ("ETGRM-3.4", "ETGRM-3.10"),
    # --- data protection
    "RS-005": ("ETGRM-3.11", "ETGRM-3.3"),
    "RS-006": ("ETGRM-7.6", "ETGRM-3.3", "OS-6.1", "OS-4.3"),
    "RS-007": ("ETGRM-3.8",),
    "RS-008": ("ETGRM-3.8", "ETGRM-3.6"),
    "RS-009": ("ETGRM-3.3", "ETGRM-3.11"),
    "RS-010": ("ETGRM-3.11", "ETGRM-4.3", "OS-6.5"),
    # --- cyber security
    "RS-011": ("ETGRM-3.7", "ETGRM-4.6", "ETGRM-3.9", "ETGRM-6.5", "BCP-9.3", "BCP-9.4"),
    "RS-012": ("ETGRM-3.7", "ETGRM-3.6"),
    "RS-013": ("ETGRM-3.9", "ETGRM-4.9"),
    "RS-014": ("ETGRM-3.6", "ETGRM-4.4", "ETGRM-6.5", "BCP-9.5"),
    "RS-015": ("ETGRM-5.4", "ETGRM-5.5", "ETGRM-3.6"),
    "RS-016": ("ETGRM-4.3", "ETGRM-3.7"),
    "RS-017": ("ETGRM-7.5", "ETGRM-4.9", "ETGRM-5.6", "OS-3.3", "OS-5.2"),
    # --- business continuity
    "RS-018": ("ETGRM-6.5", "ETGRM-6.3", "ETGRM-6.4", "BCP-4.1", "BCP-5.1", "BCP-9.5"),
    "RS-019": ("ETGRM-4.6", "ETGRM-6.6", "BCP-9.3", "BCP-9.4"),
    "RS-020": ("ETGRM-6.6", "ETGRM-6.4", "BCP-9.2", "BCP-7.1"),
    "RS-021": ("BCP-4.4", "BCP-5.2"),
    "RS-022": ("ETGRM-4.7", "BCP-9.5", "BCP-4.5"),
    # --- change / operations
    "RS-023": ("ETGRM-4.2", "ETGRM-1.6", "ETGRM-5.7"),
    "RS-024": ("ETGRM-4.2", "ETGRM-5.5", "ETGRM-4.8"),
    "RS-025": ("ETGRM-4.8", "ETGRM-3.10", "ETGRM-4.5"),
    "RS-026": ("ETGRM-1.6", "ETGRM-3.4"),
    "RS-027": ("ETGRM-3.10",),
    "RS-028": ("ETGRM-4.4", "ETGRM-4.10"),
    "RS-029": ("ETGRM-4.3", "ETGRM-3.9"),
    # --- third party
    "RS-030": ("ETGRM-7.5", "ETGRM-7.8", "OS-7.1", "OS-7.3", "OS-5.1"),
    "RS-031": ("ETGRM-7.6", "OS-6.2", "OS-4.3"),
    "RS-032": ("ETGRM-7.8", "OS-7.4", "OS-9.1"),
    # --- physical
    "RS-033": ("ETGRM-3.7", "ETGRM-3.8", "ETGRM-4.3"),
    "RS-034": ("ETGRM-4.7",),
    "RS-035": ("ETGRM-4.7", "ETGRM-6.4", "BCP-9.1", "BCP-4.3"),
    # --- compliance
    "RS-036": ("ETGRM-1.9", "OS-10.1"),
    "RS-037": ("OS-8.3", "OS-8.4", "OS-8.2", "ETGRM-7.7"),
    "RS-038": ("ETGRM-3.3", "ETGRM-1.9", "OS-6.1"),
    "RS-039": ("ETGRM-1.9", "OS-4.4", "OS-10.3"),
    # --- financial crime
    "RS-040": ("ETGRM-1.6", "ETGRM-3.5", "ETGRM-3.10"),
    "RS-041": ("ETGRM-3.5", "ETGRM-3.10"),
    "RS-042": ("ETGRM-1.9", "ETGRM-3.10"),
}

#: The mapping as shipped before the SBP additions — what a tenant's scenario row holds
#: if it was installed then and never edited.
_PREVIOUS_SCENARIO_CONTROLS: dict[str, tuple[str, ...]] = dict(SCENARIO_CONTROLS)

for _scenario, _refs in _SBP_SCENARIO_CONTROLS.items():
    SCENARIO_CONTROLS[_scenario] = SCENARIO_CONTROLS.get(_scenario, ()) + tuple(
        r for r in _refs if r not in SCENARIO_CONTROLS.get(_scenario, ())
    )
del _scenario, _refs


def references_for(scenario_reference: str) -> tuple[str, ...]:
    return SCENARIO_CONTROLS.get(scenario_reference, ())


def upgraded_references(scenario_reference: str, stored: Iterable[str]) -> tuple[str, ...] | None:
    """The current mapping for a tenant scenario row that still holds an earlier
    shipped mapping verbatim, or None when the row should be left alone.

    ``install-library`` never overwrites a row: a tenant may have retuned it. But a row
    whose references are exactly what an earlier release shipped is not retuned — it is
    just old — so it can take the SBP additions. Anything else (edited, cleared,
    re-ordered) is the tenant's decision and returns None.
    """
    have = tuple(r.strip() for r in stored if r and r.strip())
    current = references_for(scenario_reference)
    if not have or have == current:
        return None
    if have == _PREVIOUS_SCENARIO_CONTROLS.get(scenario_reference):
        return current
    return None


def template_for_reference(reference: str) -> tuple[str, str] | None:
    """(template key, the reference as the template spells it) for a catalogue
    reference, or None when it belongs to no library framework — a control the
    organisation wrote itself."""
    for key, fw in CONTROL_FRAMEWORKS.items():
        if fw.prefix and reference.startswith(fw.prefix):
            return key, reference[len(fw.prefix):]
    for key, fw in CONTROL_FRAMEWORKS.items():
        if fw.namespace and reference.startswith(fw.namespace):
            return key, reference
    # NIST SP 800-53 families (AC-2, SC-7): two letters and a dash. Checked after the
    # namespaced frameworks so ``OS-6.2`` is SBP Outsourcing, not a NIST family.
    if len(reference) > 3 and reference[:2].isalpha() and reference[2] == "-":
        return "nist-800-53-r5", reference
    return None


def resolve_controls(references: Iterable[str], catalogue: dict[str, object]) -> tuple[list, list[str]]:
    """Split the scenario's references into (ids found in this organisation's
    catalogue, references it does not have). ``catalogue`` maps lower-cased
    references to control ids. Order is preserved; duplicates are dropped."""
    found: list = []
    missing: list[str] = []
    seen: set = set()
    for ref in references:
        ident = catalogue.get(ref.strip().lower())
        if ident is None:
            missing.append(ref)
        elif ident not in seen:
            seen.add(ident)
            found.append(ident)
    return found, missing


def merge_controls(primary: list, secondary: list) -> list:
    """Asset-protecting controls first (the more specific signal), then the scenario's,
    without repeats."""
    out = list(primary)
    for item in secondary:
        if item not in out:
            out.append(item)
    return out
