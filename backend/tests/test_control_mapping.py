"""Framework → controls → risks: the mapping that closes the loop.

Two promises are pinned. Every scenario in the library names the controls that
address it, and every reference it names really exists in the framework library —
so the mapping can never point at a control the install would not have created. And
resolution is honest: what the organisation's catalogue has is linked, what it lacks
is reported, nothing is invented.
"""
import uuid

import pytest

import app.models  # noqa: F401 - the scenario service and its model import each other; models first
from app.services import control_mapping as cm
from app.services.framework_library import TEMPLATES
from app.services.risk_scenarios import CATALOGUE


# --------------------------------------------------------- control frameworks ---
def test_every_control_framework_is_a_real_template():
    for key in cm.CONTROL_FRAMEWORKS:
        assert key in TEMPLATES, key


def test_iso_27001_controls_are_annex_a_only():
    """Clauses 4-10 are the management system; only Annex A entries are controls."""
    assert cm.is_control_requirement("iso-27001-2022", "A.8.5")
    assert not cm.is_control_requirement("iso-27001-2022", "6.1")
    assert len(cm.control_requirements(TEMPLATES["iso-27001-2022"], "iso-27001-2022")) == 93


def test_management_frameworks_produce_no_controls():
    for key in ("iso-31000-2018", "gdpr", "basel-operational-risk"):
        assert not cm.is_control_framework(key)
        assert cm.control_requirements(TEMPLATES[key], key) == []


def test_catalogue_references_cannot_collide_across_frameworks():
    """CIS 6.3 and PCI DSS 6.3 are two controls. ISO's A.8.5 is distinctive as it is."""
    assert cm.catalogue_reference("cis-controls-v8", "6.3") == "CIS 6.3"
    assert cm.catalogue_reference("pci-dss-4.0", "6.3") == "PCI 6.3"
    assert cm.catalogue_reference("iso-27001-2022", "A.8.5") == "A.8.5"
    assert cm.catalogue_reference("sbp-cybersecurity", "CS-3.3") == "CS-3.3"


def test_a_catalogue_reference_maps_back_to_its_framework():
    assert cm.template_for_reference("CIS 6.3") == ("cis-controls-v8", "6.3")
    assert cm.template_for_reference("A.8.5") == ("iso-27001-2022", "A.8.5")
    assert cm.template_for_reference("CS-3.3") == ("sbp-cybersecurity", "CS-3.3")
    assert cm.template_for_reference("AC-2") == ("nist-800-53-r5", "AC-2")
    assert cm.template_for_reference("CTL-014") is None  # the organisation's own control


# ------------------------------------------------------------- the mapping ---
def test_every_scenario_has_controls_that_address_it():
    missing = [s.reference for s in CATALOGUE if not cm.references_for(s.reference)]
    assert not missing, f"scenarios with no control mapping: {missing}"


def test_every_scenario_is_covered_in_iso_cis_and_sbp():
    """A bank installs one of these three; the mapping must answer for each."""
    for s in CATALOGUE:
        refs = cm.references_for(s.reference)
        assert any(r.startswith("A.") for r in refs), f"{s.reference}: no ISO 27001 control"
        assert any(r.startswith("CS-") for r in refs), f"{s.reference}: no SBP control"


@pytest.mark.parametrize("scenario", [s.reference for s in CATALOGUE])
def test_every_mapped_reference_exists_in_the_library(scenario):
    """The mapping can never point at a control the framework install would not have
    created — which is the only way a generated risk's links could be wrong."""
    for ref in cm.references_for(scenario):
        located = cm.template_for_reference(ref)
        assert located, f"{scenario}: {ref!r} belongs to no library framework"
        key, native = located
        refs = {r["reference"] for r in cm.control_requirements(TEMPLATES[key], key)}
        assert native in refs, f"{scenario}: {ref!r} is not a control in {key}"


def test_no_mapping_points_at_a_retired_scenario():
    live = {s.reference for s in CATALOGUE}
    stale = sorted(set(cm.SCENARIO_CONTROLS) - live)
    assert not stale, f"mapping entries for scenarios that no longer exist: {stale}"


# --------------------------------------------------------------- resolution ---
def test_resolution_links_what_the_organisation_has_and_reports_the_rest():
    mfa, auth = uuid.uuid4(), uuid.uuid4()
    catalogue = {"a.8.5": mfa, "a.5.17": auth}
    found, missing = cm.resolve_controls(("A.8.5", "A.5.17", "CIS 6.3", "CS-3.3"), catalogue)
    assert found == [mfa, auth]
    assert missing == ["CIS 6.3", "CS-3.3"]


def test_resolution_is_case_insensitive_and_deduplicates():
    one = uuid.uuid4()
    catalogue = {"a.8.5": one}
    found, missing = cm.resolve_controls(("a.8.5", "A.8.5 ", "A.8.5"), catalogue)
    assert found == [one] and missing == []


def test_asset_controls_come_first_then_the_scenarios():
    """A control already recorded as protecting the asset is the more specific
    signal; it leads, and is not repeated if the scenario names it too."""
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert cm.merge_controls([a, b], [b, c]) == [a, b, c]


def test_the_catalogue_copies_the_mapping_into_scenario_specs():
    """The shipped catalogue is pure data; the tenant row carries the mapping as CSV so
    it can be edited. Round-trip through the same split the API uses."""
    from app.api.v1.risk_scenarios import _split_refs

    refs = cm.references_for("RS-003")
    assert _split_refs(", ".join(refs)) == refs
    assert _split_refs("") == ()
