"""Phase 2 §2.1 — control attributes and derived effectiveness (finding F-13).

Pure rules: attribute vocabularies, the ISO 27002:2022 attribute table the ISO 27001
pack installs, the design / operating / combined effectiveness derivation (reviewed
tests only, legacy tests kept, open issues cap the operating rating, overrides need a
reason), and the permission/import plumbing. No database: fakes stand in for it."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import controls as controls_api
from app.core.permissions import DEFAULT_ROLES, PERMISSION_CATALOG
from app.models.enums import ControlEffectiveness as E
from app.models.enums import TestResult as R
from app.schemas import control as cs
from app.services import control_assurance as ca
from app.services import framework_library as fl
from app.services.import_registry import REGISTRY

TODAY = date(2026, 9, 12)


# ====================================================== attribute vocabularies ===
@pytest.mark.parametrize("field, good", [
    ("nature", "detective"), ("automation", "it_dependent_manual"), ("operating_frequency", "per_event"),
])
def test_attributes_accept_their_vocabulary(field, good):
    assert getattr(cs.ControlCreate(name="MFA", **{field: good}), field) == good
    assert getattr(cs.ControlUpdate(**{field: good}), field) == good


@pytest.mark.parametrize("field", ["nature", "automation", "operating_frequency"])
def test_attributes_refuse_anything_else(field):
    with pytest.raises(ValidationError):
        cs.ControlCreate(name="MFA", **{field: "sometimes"})
    with pytest.raises(ValidationError):
        cs.ControlUpdate(**{field: "sometimes"})


def test_attributes_are_optional_and_the_key_flag_defaults_off():
    c = cs.ControlCreate(name="MFA")
    assert (c.nature, c.automation, c.operating_frequency, c.is_key) == (None, None, None, False)
    assert c.iso27002_attributes == {} and c.business_unit_ids == [] and c.process_ids == []


def test_iso_attributes_accept_the_standards_hashtag_spelling_and_normalise():
    got = cs.normalize_iso27002({
        "#Control_type": ["#Detective", "#Preventive", "preventive"],
        "security_properties": "#Integrity, #Confidentiality",
        "operational_capabilities": ["Identity and access management"],
        "security_domains": [],
    })
    # standard order, de-duplicated, lower case, empty attributes dropped
    assert got == {
        "control_type": ["preventive", "detective"],
        "security_properties": ["confidentiality", "integrity"],
        "operational_capabilities": ["identity_and_access_management"],
    }


@pytest.mark.parametrize("attrs, fragment", [
    ({"control_kind": ["preventive"]}, "unknown attribute"),
    ({"control_type": ["directive"]}, "'directive' is not an ISO 27002 value"),
    ({"security_domains": ["defense"]}, "'defense'"),
    ({"cybersecurity_concepts": ["govern"]}, "'govern'"),
])
def test_iso_attributes_refuse_what_the_standard_does_not_define(attrs, fragment):
    with pytest.raises(ValueError, match=fragment):
        cs.normalize_iso27002(attrs)
    with pytest.raises(ValidationError):
        cs.ControlCreate(name="MFA", iso27002_attributes=attrs)


def test_iso_attributes_on_update_are_optional_and_validated():
    assert cs.ControlUpdate().iso27002_attributes is None
    assert cs.ControlUpdate(iso27002_attributes={"control_type": ["#Corrective"]}).iso27002_attributes == {
        "control_type": ["corrective"]
    }
    with pytest.raises(ValidationError):
        cs.ControlUpdate(iso27002_attributes={"colour": ["red"]})


def test_the_vocabulary_is_the_2022_standards():
    v = cs.ISO27002_VOCABULARY
    assert set(v) == {"control_type", "security_properties", "cybersecurity_concepts",
                      "operational_capabilities", "security_domains"}
    assert len(v["operational_capabilities"]) == 15
    assert v["security_domains"] == ("governance_and_ecosystem", "protection", "defence", "resilience")


def test_the_read_model_shows_the_new_fields():
    fields = set(cs.ControlRead.model_fields)
    assert {
        "nature", "automation", "is_key", "operating_frequency", "iso27002_attributes",
        "test_procedure", "evidence_expected", "design_effectiveness", "operating_effectiveness",
        "effectiveness_override_reason", "effectiveness_basis", "open_issues",
        "pending_review_count", "business_units", "processes",
    } <= fields


# ============================================================ ISO 27002 table ===
def test_every_annex_a_control_carries_its_attributes():
    rows = [r for r in fl.TEMPLATES["iso-27001-2022"]["requirements"] if r["reference"].startswith("A.")]
    assert len(rows) == 93
    assert all(r.get("iso27002_attributes") for r in rows)
    assert set(fl.ISO27002_ATTRIBUTES) == {r["reference"] for r in rows}


def test_the_table_uses_only_the_standards_vocabulary():
    for ref, attrs in fl.ISO27002_ATTRIBUTES.items():
        assert cs.normalize_iso27002(attrs) == attrs, ref
        assert set(attrs) == set(cs.ISO27002_VOCABULARY), ref


@pytest.mark.parametrize("ref, control_type, props", [
    ("A.8.5", ["preventive"], ["confidentiality", "integrity", "availability"]),
    ("A.8.13", ["corrective"], ["integrity", "availability"]),
    ("A.5.25", ["detective"], ["confidentiality", "integrity", "availability"]),
    ("A.8.7", ["preventive", "detective", "corrective"], ["confidentiality", "integrity", "availability"]),
    ("A.7.7", ["preventive"], ["confidentiality"]),
    ("A.5.30", ["corrective"], ["availability"]),
])
def test_spot_checks_against_the_standard(ref, control_type, props):
    attrs = fl.ISO27002_ATTRIBUTES[ref]
    assert attrs["control_type"] == control_type
    assert attrs["security_properties"] == props


def test_only_the_iso_27001_template_carries_attributes_and_they_are_copies():
    assert fl.iso27002_attributes_for("cis-controls-v8", "A.8.5") == {}
    a = fl.iso27002_attributes_for("iso-27001-2022", "A.8.5")
    a["control_type"].append("detective")
    assert fl.ISO27002_ATTRIBUTES["A.8.5"]["control_type"] == ["preventive"]


class _PackDB:
    """Enough of a session for install_controls_pack: the catalogue facts query, the
    matched controls, the framework's requirements, add and flush."""

    def __init__(self, controls, requirements):
        self.controls = controls
        self.requirements = requirements
        self.added = []

    async def execute(self, stmt):
        rows = [(c.id, c.reference, c.name) for c in self.controls]
        return SimpleNamespace(all=lambda: rows)

    async def scalars(self, stmt):
        entity = stmt.column_descriptions[0]["entity"].__name__
        rows = self.controls if entity == "Control" else self.requirements
        return SimpleNamespace(all=lambda: list(rows))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


async def test_a_pack_install_copies_attributes_onto_new_controls_but_never_over_a_tenants():
    own = SimpleNamespace(id=uuid.uuid4(), reference="A.8.5", name="Secure authentication",
                          iso27002_attributes={"control_type": ["detective"]})  # the tenant's call
    bare = SimpleNamespace(id=uuid.uuid4(), reference="A.8.13", name="Information backup",
                           iso27002_attributes={})
    reqs = [SimpleNamespace(reference=r["reference"], controls=[])
            for r in fl.TEMPLATES["iso-27001-2022"]["requirements"] if r["reference"].startswith("A.")]
    db = _PackDB([own, bare], reqs)
    user = SimpleNamespace(tenant_id=uuid.uuid4())
    created, linked, _ = await fl.install_controls_pack(db, user, SimpleNamespace(id=uuid.uuid4()), "iso-27001-2022")
    assert (created, linked) == (91, 2)
    assert own.iso27002_attributes == {"control_type": ["detective"]}
    assert bare.iso27002_attributes == fl.ISO27002_ATTRIBUTES["A.8.13"]
    mfa_like = next(c for c in db.added if c.reference == "A.8.2")
    assert mfa_like.iso27002_attributes == fl.ISO27002_ATTRIBUTES["A.8.2"]


# ================================================== derived effectiveness ===
def _t(result, test_type="operating", review="reviewed", days_ago=0, created=None):
    when = TODAY - timedelta(days=days_ago)
    return SimpleNamespace(
        result=result, test_type=test_type, review_status=review, conducted_date=when,
        created_at=created or datetime(when.year, when.month, when.day, 9, 0),
    )


def test_no_tests_and_no_rating_is_not_assessed():
    d = ca.derive_effectiveness([])
    assert (d.design, d.operating, d.combined, d.basis) == (E.not_assessed, E.not_assessed, E.not_assessed, "none")


def test_a_hand_rating_from_before_derivation_is_kept_until_the_first_reviewed_test():
    d = ca.derive_effectiveness([], current=E.effective)
    assert (d.combined, d.basis) == (E.effective, "manual")
    d = ca.derive_effectiveness([_t(R.failed)], current=E.effective)
    assert (d.combined, d.basis) == (E.ineffective, "tests")


@pytest.mark.parametrize("review", ["pending", "returned"])
def test_an_unreviewed_test_changes_nothing(review):
    d = ca.derive_effectiveness([_t(R.passed, review=review)], current=E.not_assessed)
    assert d.combined == E.not_assessed and d.basis == "none"


def test_legacy_tests_keep_their_effect_as_operating_tests():
    d = ca.derive_effectiveness([_t(R.failed, test_type=None, review="legacy")])
    assert (d.operating, d.design, d.combined) == (E.ineffective, E.not_assessed, E.ineffective)


def test_design_and_operating_come_from_their_own_latest_reviewed_test():
    tests = [
        _t(R.failed, "design", days_ago=200),
        _t(R.passed, "design", days_ago=100),          # latest design
        _t(R.passed, "operating", days_ago=50),
        _t(R.passed_with_exceptions, "operating", days_ago=10),  # latest operating
        _t(R.failed, "operating", review="pending", days_ago=1),  # not reviewed: ignored
    ]
    d = ca.derive_effectiveness(tests)
    assert (d.design, d.operating) == (E.effective, E.partially_effective)
    assert d.combined == E.partially_effective  # the worse of the two


def test_the_combined_rating_is_the_worst_of_those_assessed():
    assert ca.combine(E.effective, E.not_assessed) == E.effective
    assert ca.combine(E.not_assessed, E.not_assessed) == E.not_assessed
    assert ca.combine(E.effective, E.ineffective) == E.ineffective
    assert ca.combine(E.partially_effective, E.effective) == E.partially_effective


def test_a_design_pass_alone_rates_the_control():
    d = ca.derive_effectiveness([_t(R.passed, "design")])
    assert (d.design, d.operating, d.combined) == (E.effective, E.not_assessed, E.effective)


def test_same_day_tests_are_ordered_by_when_they_were_recorded():
    first = _t(R.failed, created=datetime(2026, 9, 12, 9))
    later = _t(R.passed, created=datetime(2026, 9, 12, 15))
    assert ca.derive_effectiveness([later, first]).operating == E.effective


def test_an_open_issue_caps_the_operating_rating_until_it_closes():
    tests = [_t(R.passed)]
    capped = ca.derive_effectiveness(tests, has_open_issue=True)
    assert (capped.operating, capped.combined, capped.capped) == (E.partially_effective, E.partially_effective, True)
    assert ca.derive_effectiveness(tests, has_open_issue=False).operating == E.effective


def test_an_open_issue_never_raises_a_rating():
    assert ca.cap_for_open_issue(E.ineffective, True) == E.ineffective
    assert ca.cap_for_open_issue(E.not_assessed, True) == E.not_assessed
    d = ca.derive_effectiveness([_t(R.failed)], has_open_issue=True)
    assert d.operating == E.ineffective and not d.capped


def test_an_override_holds_the_combined_rating_but_the_derived_ones_stay_visible():
    d = ca.derive_effectiveness([_t(R.failed)], override_reason="Compensating control CC-4", current=E.partially_effective)
    assert (d.combined, d.basis, d.operating) == (E.partially_effective, "override", E.ineffective)


def test_passed_with_exceptions_means_partially_effective():
    assert ca.rating_for(R.passed_with_exceptions) == E.partially_effective
    assert ca.rating_for(R.not_assessed) is None
    assert ca.effectiveness_after_test(R.passed_with_exceptions, None, E.effective) == E.partially_effective


def test_apply_derived_writes_and_reports_only_what_moved():
    control = SimpleNamespace(design_effectiveness=E.not_assessed, operating_effectiveness=E.effective,
                              effectiveness=E.effective)
    changes = ca.apply_derived(control, ca.DerivedEffectiveness(E.effective, E.effective, E.effective, "tests"))
    assert changes == {"design_effectiveness": {"from": "not_assessed", "to": "effective"}}
    assert ca.apply_derived(control, ca.DerivedEffectiveness(E.effective, E.effective, E.effective, "tests")) == {}


class _RecomputeDB:
    def __init__(self, tests, open_issue):
        self.tests, self.open_issue = tests, open_issue

    async def scalars(self, stmt):
        return SimpleNamespace(all=lambda: list(self.tests))

    async def scalar(self, stmt):
        return uuid.uuid4() if self.open_issue else None


async def test_recompute_effectiveness_is_the_hook_the_issues_module_calls(monkeypatch):
    logged = []

    async def record_system(db, **kw):
        logged.append(kw)

    monkeypatch.setattr("app.services.audit.record_system", record_system)
    control = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), reference="A.8.5", name="MFA",
                              effectiveness=E.effective, design_effectiveness=E.not_assessed,
                              operating_effectiveness=E.effective, effectiveness_override_reason="")
    # an issue opened: the operating rating drops to partial, and the trail says why
    await ca.recompute_effectiveness(_RecomputeDB([_t(R.passed)], True), control, reason="ISS-004 opened")
    assert (control.operating_effectiveness, control.effectiveness) == (E.partially_effective, E.partially_effective)
    assert logged and "ISS-004 opened" in logged[-1]["summary"] and logged[-1]["entity_type"] == "control"
    # closed: back to what the test said
    await ca.recompute_effectiveness(_RecomputeDB([_t(R.passed)], False), control, reason="ISS-004 closed")
    assert control.effectiveness == E.effective
    # nothing moved: nothing logged
    n = len(logged)
    await ca.recompute_effectiveness(_RecomputeDB([_t(R.passed)], False), control)
    assert len(logged) == n


async def test_dropping_an_override_goes_back_to_the_tests_not_to_the_override():
    control = SimpleNamespace(id=uuid.uuid4(), effectiveness=E.effective, design_effectiveness=E.not_assessed,
                              operating_effectiveness=E.not_assessed, effectiveness_override_reason="")
    await ca.recompute(_RecomputeDB([], False), control, forget_manual=True)
    assert control.effectiveness == E.not_assessed


# ============================================================ override edits ===
def _ctl(eff=E.effective, reason=""):
    return SimpleNamespace(effectiveness=eff, effectiveness_override_reason=reason)


def test_resending_the_same_rating_is_not_an_override():
    data = {"effectiveness": E.effective, "name": "MFA"}
    assert controls_api._override_edit(_ctl(), data) is None
    assert data == {"name": "MFA"}  # taken out of the plain update either way


def test_changing_the_rating_without_a_reason_is_refused():
    with pytest.raises(HTTPException) as exc:
        controls_api._override_edit(_ctl(), {"effectiveness": E.ineffective})
    assert exc.value.status_code == 422 and "reason" in exc.value.detail


def test_changing_the_rating_with_a_reason_is_an_override():
    got = controls_api._override_edit(_ctl(), {"effectiveness": E.ineffective, "effectiveness_override_reason": " Bypass found "})
    assert got == (E.ineffective, "Bypass found")


def test_an_existing_override_reason_covers_a_new_value():
    assert controls_api._override_edit(_ctl(reason="Known gap"), {"effectiveness": E.ineffective}) == (E.ineffective, "Known gap")


def test_a_blank_reason_drops_an_override_and_is_ignored_when_there_is_none():
    assert controls_api._override_edit(_ctl(reason="Known gap"), {"effectiveness_override_reason": ""}) == (None, "")
    assert controls_api._override_edit(_ctl(), {"effectiveness_override_reason": ""}) is None


def test_a_create_with_a_rating_needs_a_reason():
    with pytest.raises(ValidationError, match="effectiveness_override_reason"):
        cs.ControlCreate(name="MFA", effectiveness=E.effective)
    ok = cs.ControlCreate(name="MFA", effectiveness=E.effective, effectiveness_override_reason="Rated in the 2025 RCSA")
    assert ok.effectiveness == E.effective
    assert cs.ControlCreate(name="MFA").effectiveness == E.not_assessed


def test_an_override_needs_a_real_reason():
    with pytest.raises(ValidationError):
        cs.EffectivenessOverride(effectiveness=E.effective, reason="   ")
    assert cs.EffectivenessOverride(effectiveness=E.effective, reason=" CC-4 ").reason == "CC-4"


def test_the_basis_tells_the_register_where_the_rating_came_from():
    assert ca.effectiveness_basis([], "", E.not_assessed) == "none"
    assert ca.effectiveness_basis([], "", E.effective) == "manual"
    assert ca.effectiveness_basis([_t(R.passed)], "", E.effective) == "tests"
    assert ca.effectiveness_basis([_t(R.passed)], "Known gap", E.partially_effective) == "override"


# ================================================================ plumbing ===
def test_control_test_is_a_permission_every_control_writer_holds():
    assert "control:test" in PERMISSION_CATALOG
    for role, (_desc, codes) in DEFAULT_ROLES.items():
        if "control:write" in codes:
            assert "control:test" in codes, role


def test_the_import_takes_the_attributes_and_the_override_reason():
    columns = {c.field for c in REGISTRY["controls"].columns}
    wanted = {"nature", "automation", "is_key", "operating_frequency", "test_procedure",
              "evidence_expected", "effectiveness_override_reason", "business_unit_ids", "process_ids"}
    assert wanted <= columns
    assert wanted <= set(cs.ControlCreate.model_fields)
    enum_values = {c.field: c.enum_values for c in REGISTRY["controls"].columns if c.kind == "enum"}
    assert tuple(enum_values["nature"]) == cs.NATURES
    assert tuple(enum_values["automation"]) == cs.AUTOMATIONS
    assert tuple(enum_values["operating_frequency"]) == cs.OPERATING_FREQUENCIES


def test_scope_links_are_on_the_control():
    rels = controls_api.Control.__mapper__.relationships
    assert rels["business_units"].secondary.name == "control_business_units"
    assert rels["processes"].secondary.name == "control_processes"
