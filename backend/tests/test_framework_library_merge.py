"""One framework per standard (D-04, §0.1, §0.7).

The same standard existed twice — SBP ETGRM as the retired 33-row pack *and* the
71-row template — so every gap counted twice; the demo seeder's five-row ISO 27001
carried the template's name, so the full one showed "installed" and 409'd forever.
These pin the pure rules behind the fix: which names are one standard, which copy
survives a merge, what a merge hands over, and when installing upgrades instead of
refusing.
"""
from datetime import datetime, timezone

import pytest

from app.models.compliance import FRAMEWORK_KINDS
from app.models.enums import ComplianceStatus, ComplianceTreatment
from app.services import control_mapping
from app.services import framework_library as fl
from app.services.framework_library import FrameworkFacts as F


def at(day: int) -> datetime:
    return datetime(2026, 8, day, tzinfo=timezone.utc)


ETGRM = fl.TEMPLATES["sbp-etgrm"]["name"]


# ------------------------------------------------------------------ PCI DSS 4.0.1 ---
def test_pci_is_named_and_versioned_4_0_1_under_the_old_key():
    tpl = fl.TEMPLATES["pci-dss-4.0"]
    assert tpl["name"] == "PCI DSS v4.0.1"
    assert tpl["version"] == "4.0.1"
    # The key is referenced by control mapping and saved catalogue references.
    assert control_mapping.is_control_framework("pci-dss-4.0")


def test_existing_pci_v4_0_installs_are_recognised():
    assert "PCI DSS v4.0" in fl.LEGACY_ALIASES["pci-dss-4.0"]
    assert fl.template_key_for_name("PCI DSS v4.0") == "pci-dss-4.0"
    assert fl.template_key_for_name("  pci dss v4.0.1 ") == "pci-dss-4.0"


def test_no_name_belongs_to_two_templates():
    seen: dict[str, str] = {}
    for key in fl.TEMPLATES:
        for name in fl.template_names(key):
            norm = fl.normalize_name(name)
            assert seen.setdefault(norm, key) == key, f"{name} is claimed by {seen[norm]} and {key}"


# ------------------------------------------------------------------ framework kind ---
@pytest.mark.parametrize("key", ["iso-27005-2022", "iso-31000-2018", "basel-operational-risk"])
def test_guidance_standards_are_maturity_self_assessments(key):
    assert fl.template_kind(key) == "maturity"


@pytest.mark.parametrize("key", [
    "iso-27001-2022", "pci-dss-4.0", "nist-csf-2.0", "nist-800-53-r5", "soc-2-2017", "gdpr",
    "hipaa-security-privacy", "cis-controls-v8", "sbp-etgrm", "sbp-cybersecurity",
    "sbp-outsourcing", "sbp-bcp", "shariah-governance", "iso-42001-2023",
])
def test_obligations_stay_compliance(key):
    assert fl.template_kind(key) == "compliance"


def test_every_template_kind_is_a_valid_kind():
    assert {fl.template_kind(k) for k in fl.TEMPLATES} <= set(FRAMEWORK_KINDS)


# --------------------------------------------------------------- merge grouping ---
def test_a_legacy_pack_and_its_template_are_one_standard():
    assert fl.merge_group_key("SBP ETGRM Framework") == fl.merge_group_key(ETGRM)
    assert fl.merge_group_key("ISO/IEC 27001:2022 Annex A") == fl.merge_group_key("iso/iec 27001:2022")


def test_other_names_group_by_case_insensitive_name():
    assert fl.merge_group_key("Internal Policy Set") == fl.merge_group_key("  internal policy set ")
    assert fl.merge_group_key("Internal Policy Set") != fl.merge_group_key("Internal Policy Set 2")


def test_a_clean_tenant_plans_nothing():
    frameworks = [F(1, ETGRM, 71, at(1)), F(2, "PCI DSS v4.0.1", 93, at(2)), F(3, "Mine", 4, at(3))]
    assert fl.plan_merges(frameworks) == []


def test_the_etgrm_duplicate_merges_into_the_deep_template():
    plans = fl.plan_merges([F("old", "SBP ETGRM Framework", 33, at(1)), F("new", ETGRM, 71, at(5))])
    assert len(plans) == 1
    plan = plans[0]
    assert plan.keeper.id == "new"
    assert [f.id for f in plan.losers] == ["old"]
    assert plan.template_key == "sbp-etgrm"
    assert plan.rename_to is None  # the keeper already carries the canonical name


def test_a_deeper_legacy_copy_survives_and_takes_the_canonical_name():
    # The seeder's 5-row stub under the template name vs a full 93-row Annex A pack.
    plans = fl.plan_merges([
        F("stub", "ISO/IEC 27001:2022", 5, at(1)),
        F("annex", "ISO/IEC 27001:2022 Annex A", 93, at(2)),
    ])
    (plan,) = plans
    assert plan.keeper.id == "annex"
    assert plan.rename_to == "ISO/IEC 27001:2022"


def test_a_tie_goes_to_the_oldest_then_the_id():
    keeper = fl.pick_keeper([F("b", "X", 10, at(3)), F("a", "x", 10, at(2)), F("c", "X ", 10, at(2))])
    assert keeper.id == "a"
    assert fl.pick_keeper([F("z", "X", 3, None), F("y", "X", 3, at(9))]).id == "y"


def test_same_name_copies_of_a_custom_framework_merge_without_rename():
    (plan,) = fl.plan_merges([F(1, "Board Charter", 2, at(1)), F(2, "board charter", 8, at(4)), F(3, "Other", 1, at(1))])
    assert plan.keeper.id == 2
    assert [f.id for f in plan.losers] == [1]
    assert plan.rename_to is None and plan.template_key is None


def test_three_copies_leave_one():
    (plan,) = fl.plan_merges([
        F(1, "SBP ETGRM Framework", 33, at(1)), F(2, ETGRM, 71, at(2)), F(3, "sbp etgrm framework", 0, at(3)),
    ])
    assert plan.keeper.id == 2
    assert sorted(f.id for f in plan.losers) == [1, 3]


# ------------------------------------------------------------------ carry over ---
def test_carry_over_fills_only_what_the_keeper_left_at_default():
    keeper = {"status": ComplianceStatus.not_assessed, "treatment": None, "implementation": "",
              "owner": "CISO", "efficacy": None, "legal_id": None}
    loser = {"status": ComplianceStatus.compliant, "treatment": ComplianceTreatment.implement,
             "implementation": "MFA on all admin accounts", "owner": "IT Ops", "efficacy": 80,
             "legal_id": None}
    out = fl.carry_over(keeper, loser)
    assert out == {"status": ComplianceStatus.compliant, "treatment": ComplianceTreatment.implement,
                   "implementation": "MFA on all admin accounts", "efficacy": 80}


def test_carry_over_never_overwrites_the_keepers_answer():
    keeper = {"status": ComplianceStatus.non_compliant, "treatment": ComplianceTreatment.accept,
              "implementation": "x", "owner": "a", "efficacy": 10, "legal_id": "L1"}
    loser = {"status": ComplianceStatus.compliant, "treatment": ComplianceTreatment.implement,
             "implementation": "y", "owner": "b", "efficacy": 90, "legal_id": "L2"}
    assert fl.carry_over(keeper, loser) == {}


def test_carry_over_of_two_untouched_rows_is_nothing():
    blank = dict(fl.REQUIREMENT_DEFAULTS)
    assert fl.carry_over(blank, dict(blank)) == {}


# -------------------------------------------------------- upgrade instead of 409 ---
def refs(key: str) -> list[str]:
    return [r["reference"] for r in fl.TEMPLATES[key]["requirements"]]


def test_nothing_installed_installs_everything():
    action, add = fl.install_action("sbp-etgrm", None, [])
    assert action == fl.INSTALL
    assert len(add) == len(fl.TEMPLATES["sbp-etgrm"]["requirements"])


def test_the_seeder_stub_under_the_canonical_name_is_upgraded():
    stub = refs("iso-27001-2022")[:5]
    action, add = fl.install_action("iso-27001-2022", "ISO/IEC 27001:2022", stub)
    assert action == fl.UPGRADE
    assert len(add) == len(refs("iso-27001-2022")) - 5
    assert not {r["reference"] for r in add} & set(stub)


def test_a_legacy_named_copy_is_upgraded_even_when_complete():
    # A full 93-row "PCI DSS v4.0" only needs the rename and the 4.0.1 metadata.
    action, add = fl.install_action("pci-dss-4.0", "PCI DSS v4.0", refs("pci-dss-4.0"))
    assert (action, add) == (fl.UPGRADE, [])


def test_references_match_ignoring_case_and_spaces():
    messy = [f"  {r.lower()} " for r in refs("pci-dss-4.0")]
    action, add = fl.install_action("pci-dss-4.0", "PCI DSS v4.0.1", messy)
    assert (action, add) == (fl.CONFLICT, [])


def test_a_complete_canonical_install_is_a_conflict():
    action, add = fl.install_action("sbp-etgrm", ETGRM.upper(), refs("sbp-etgrm"))
    assert (action, add) == (fl.CONFLICT, [])


def test_customer_added_clauses_do_not_block_the_conflict_rule():
    action, _ = fl.install_action("sbp-etgrm", ETGRM, refs("sbp-etgrm") + ["BANK-1", "BANK-2"])
    assert action == fl.CONFLICT


def test_template_installs_reports_upgrade_available():
    ok = fl.TemplateInstall(framework_id=None, name=ETGRM, legacy=False, missing=0)
    assert ok.upgrade_available is False
    assert fl.TemplateInstall(framework_id=None, name="x", legacy=True).upgrade_available
    assert fl.TemplateInstall(framework_id=None, name="x", missing=3).upgrade_available


def test_pack_result_unpacks_and_names_its_counts():
    res = fl.PackResult(93, 0, 93)
    created, linked, requirement_links = res
    assert (created, linked, requirement_links) == (93, 0, 93)
    assert res.requirements_linked == 93


# ------------------------------------------------------------ merge link tables ---
def test_the_merge_finds_every_requirement_link_table():
    tables = {t.name for t, _ in fl._requirement_fk_columns()}
    assert {
        "requirement_controls", "requirement_risks", "requirement_policies", "requirement_crosswalks",
        "assets_requirements", "exception_requirements", "vendor_requirements",
        "obligation_requirements", "audit_finding_requirements", "compliance_findings",
        "audit_program_steps",
    } <= tables
    assert "audit_programs" in {t.name for t, _ in fl._framework_fk_columns()}


# ------------------------------------------------- controls pack: dedupe by name ---
from app.services.framework_library import ControlFacts as C  # noqa: E402

_ISO_WANTED = [
    {"reference": "A.5.15", "title": "Access control", "description": ""},
    {"reference": "A.8.32", "title": "Change management", "description": ""},
    {"reference": "A.8.5", "title": "Secure authentication", "description": ""},
]


@pytest.mark.parametrize("a,b", [
    ("Access Control Policy", "access-control policy"),
    ("Review of access rights", "review access rights"),
    ("  Change   Management ", "change management"),
    ("Backup & Restore", "backup restore"),
])
def test_control_names_normalise_to_the_same_key(a, b):
    assert fl.normalize_control_name(a) == fl.normalize_control_name(b)


def test_name_normalisation_is_not_fuzzy():
    assert fl.normalize_control_name("Access control") != fl.normalize_control_name("Access control policy")
    assert fl.normalize_control_name("Backup") != fl.normalize_control_name("Backups")


def test_pack_plan_prefers_reference_then_name_then_create():
    own = C("c1", "CTL-014", "Change Management")
    by_ref = C("c2", "A.5.15", "Something else entirely")
    steps = {s.requirement_ref: s for s in fl.plan_pack(_ISO_WANTED, "iso-27001-2022", [own, by_ref])}
    assert steps["A.5.15"].action == fl.MATCH_REFERENCE and steps["A.5.15"].control is by_ref
    assert steps["A.8.32"].action == fl.MATCH_NAME and steps["A.8.32"].control is own
    assert steps["A.8.5"].action == fl.CREATE and steps["A.8.5"].control is None


def test_decisions_override_name_matches_but_never_a_reference_match():
    own = C("c1", "CTL-014", "Change management")
    by_ref = C("c2", "A.5.15", "Access control")
    other = C("c3", "CTL-099", "Login controls")
    steps = {s.requirement_ref: s for s in fl.plan_pack(
        _ISO_WANTED, "iso-27001-2022", [own, by_ref, other],
        {"A.8.32": fl.CREATE, "A.8.5": "c3", "A.5.15": fl.CREATE},
    )}
    assert steps["A.8.32"].action == fl.CREATE and steps["A.8.32"].name_match is own
    assert steps["A.8.5"].action == fl.MAP_EXISTING and steps["A.8.5"].control is other
    assert steps["A.5.15"].action == fl.MATCH_REFERENCE


def test_bad_decisions_are_refused():
    with pytest.raises(fl.PackDecisionError):
        fl.plan_pack(_ISO_WANTED, "iso-27001-2022", [], {"A.9.9": fl.CREATE})
    with pytest.raises(fl.PackDecisionError):
        fl.plan_pack(_ISO_WANTED, "iso-27001-2022", [], {"A.8.5": "no-such-control"})


def test_the_organisations_own_control_wins_a_name_tie():
    library = C("c1", "ETGRM-4.2", "Change management")
    own = C("c2", "CTL-014", "Change management")
    step = fl.plan_pack(_ISO_WANTED, "iso-27001-2022", [library, own])[1]
    assert step.control is own


def test_a_frameworks_own_controls_are_never_name_matches_for_its_other_clauses():
    """PCI 6.3 and 11.3 share a title; 11.3 must not be folded into 6.3's control."""
    wanted = [r for r in fl.TEMPLATES["pci-dss-4.0"]["requirements"] if r["reference"] in ("6.3", "11.3")]
    assert wanted[0]["title"] == wanted[1]["title"]
    existing = [C("c1", "PCI 6.3", wanted[0]["title"])]
    steps = {s.requirement_ref: s for s in fl.plan_pack(wanted, "pci-dss-4.0", existing)}
    assert steps["6.3"].action == fl.MATCH_REFERENCE
    assert steps["11.3"].action == fl.CREATE


def test_a_rerun_of_an_installed_pack_matches_everything_by_reference():
    key = "sbp-etgrm"
    wanted = control_mapping.control_requirements(fl.TEMPLATES[key], key)
    existing = [C(f"c{i}", control_mapping.catalogue_reference(key, r["reference"]), r["title"])
                for i, r in enumerate(wanted)]
    assert {s.action for s in fl.plan_pack(wanted, key, existing)} == {fl.MATCH_REFERENCE}
