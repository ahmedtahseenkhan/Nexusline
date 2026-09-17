"""Product review re-check, 17 September 2026 — workstream C (F-16, F-19, F-11).

No database: the pure rules are tested directly and the endpoints are driven with a
fake session and stubbed loaders.

Pinned here:

1. **F-16 natural sort** — one shared helper; the stored ``reference_sort_key`` sorts
   in SQL exactly as the tuple key sorts in Python (A.5.2 < A.5.10, 4.1 < 10.1,
   PCI 1.2.1 < 1.10, ETGRM-3.5, CC6.1, blank first); every ORM write fills it; the boot
   repair backfills stale rows; lists order by it.
2. **F-19 mapping counts** — compliance is never faked: posture shows assessed
   compliant, mapped and tested side by side; the register-wide review pages through
   every control in scope, filters by framework and counts strong suggestions; the SoA
   export says mapped and tested.
3. **F-11 third parties** — substitutability / concentration vocabularies; a material
   arrangement can't go live without rationale, exit plan and substitutability (plain
   422); vendor facts carry the new fields and a derived concentration indicator that
   also says when an arrangement is expected; the summary counts them.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.v1 import clause_suggestions as suggestions_api
from app.api.v1 import compliance as compliance_api
from app.api.v1 import outsourcing as outsourcing_api
from app.api.v1 import vendors as vendors_api
from app.db import data_repairs
from app.models.compliance import Framework, Requirement, _fill_reference_sort_key
from app.models.enums import ComplianceStatus, ControlEffectiveness
from app.models.outsourcing import (
    CONCENTRATION_LEVELS,
    SUBSTITUTABILITY,
    OutsourcingMateriality,
    OutsourcingStatus,
    missing_for_activation,
)
from app.schemas import outsourcing as outsourcing_s
from app.services import clause_suggestions as engine
from app.services import compliance_posture as cp
from app.services import soa_export
from app.services.reference_sort import natural_key, reference_sort_key


# ============================================================ F-16: natural sort ===
CASES = [
    ["A.5.10", "A.5.2", "A.5.1"],
    ["10.1", "4.1"],
    ["1.10", "1.2.1", "1.2"],
    ["ETGRM-3.5", "ETGRM-3.10", "ETGRM-10.1"],
    ["CC6.1", "cc10.1", "CC6.10", "CC6.2"],
    ["", "A.5.1", "1"],
]
EXPECTED = [
    ["A.5.1", "A.5.2", "A.5.10"],
    ["4.1", "10.1"],
    ["1.2", "1.2.1", "1.10"],
    ["ETGRM-3.5", "ETGRM-3.10", "ETGRM-10.1"],
    ["CC6.1", "CC6.2", "CC6.10", "cc10.1"],
    ["", "1", "A.5.1"],
]


@pytest.mark.parametrize("refs, expected", list(zip(CASES, EXPECTED)))
def test_references_sort_naturally_in_python_and_in_the_stored_key(refs, expected):
    assert sorted(refs, key=natural_key) == expected
    assert sorted(refs, key=reference_sort_key) == expected


def test_the_stored_key_agrees_with_the_tuple_on_every_pair():
    refs = sorted({r for case in CASES for r in case} | {"A.5", "A.5.1a", "A.5.1b", "PCI 12.3.4", "6.4.3", "Z", "a1"})
    for a in refs:
        for b in refs:
            if natural_key(a) != natural_key(b):
                assert (natural_key(a) < natural_key(b)) == (reference_sort_key(a) < reference_sort_key(b)), (a, b)


def test_the_stored_key_is_collation_safe_and_fits_the_column():
    for ref in ("A.5.10", "ETGRM-3.5", "CC6.1", "PCI DSS 1.2.1", "Clause (a)"):
        key = reference_sort_key(ref)
        # Only digits and lower-case letters: en_US / ICU collations ignore punctuation.
        assert key and set(key) <= set("0123456789abcdefghijklmnopqrstuvwxyz")
    assert reference_sort_key("") == "" and reference_sort_key(None) == ""
    assert reference_sort_key("A.5.10") == "1a" + "0" + "5".rjust(10, "0") + "0" + "10".rjust(10, "0")
    assert len(reference_sort_key("1." * 400)) <= 255
    assert reference_sort_key("A.05.1") == reference_sort_key("A.5.1")


def test_one_helper_serves_every_surface():
    assert soa_export.natural_key is natural_key
    assert engine.natural_key is natural_key


def test_every_orm_write_fills_the_key():
    req = Requirement(reference="A.5.10", title="Clause")
    _fill_reference_sort_key(None, None, req)
    assert req.reference_sort_key == reference_sort_key("A.5.10")
    req.reference = "A.5.2"
    _fill_reference_sort_key(None, None, req)
    assert req.reference_sort_key == reference_sort_key("A.5.2")


def test_lists_order_by_the_key():
    assert compliance_api._REQUIREMENT_SORTABLE["reference"] is Requirement.reference_sort_key
    order_by = Framework.requirements.property.order_by
    assert [c.key for c in order_by] == ["reference_sort_key"]


class RepairDB:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    async def execute(self, stmt, *_a, **_k):
        if stmt.is_select:
            return NS(all=lambda: self.rows)
        self.updates.append(stmt.compile(dialect=postgresql.dialect()).params)
        return NS()


async def test_the_boot_repair_fills_only_stale_keys():
    good = (uuid.uuid4(), "A.5.1", reference_sort_key("A.5.1"))
    stale = (uuid.uuid4(), "A.5.10", "")
    blank = (uuid.uuid4(), "", "")
    db = RepairDB([good, stale, blank])
    assert await data_repairs.fill_requirement_sort_keys(db) == 1
    assert db.updates[0]["reference_sort_key"] == reference_sort_key("A.5.10")
    # Idempotent: once filled, a second run writes nothing.
    db2 = RepairDB([good, (stale[0], stale[1], reference_sort_key("A.5.10")), blank])
    assert await data_repairs.fill_requirement_sort_keys(db2) == 0


# ============================================================ F-19: posture ===
def clause(status=ComplianceStatus.not_assessed, coverage="unmapped", deleted=False):
    return NS(status=status, coverage=coverage, deleted=deleted)


def test_a_mapped_but_unassessed_framework_reads_honestly():
    reqs = (
        [clause(coverage="assured") for _ in range(4)]
        + [clause(coverage="unassessed") for _ in range(26)]
        + [clause(coverage="failing")]
        + [clause() for _ in range(19)]
        + [clause(status=ComplianceStatus.not_applicable, coverage="assured")]
        + [clause(coverage="assured", deleted=True)]
    )
    p = cp.posture(reqs)
    assert (p.total, p.applicable, p.compliant, p.mapped, p.assured, p.unassessed, p.failing) == (51, 50, 0, 31, 4, 26, 1)
    assert p.line == "0% assessed compliant · 62% mapped · 8% tested"


def test_only_an_assessment_moves_compliant():
    p = cp.posture([clause(ComplianceStatus.compliant, "unmapped"), clause(coverage="assured")])
    assert (p.compliant_pct, p.mapped_pct, p.assured_pct) == (50.0, 50.0, 50.0)
    assert cp.posture([]).line == "No applicable clauses"


def test_posture_reads_controls_when_coverage_is_not_precomputed():
    eff = NS(effectiveness=ControlEffectiveness.effective, deleted=False)
    untested = NS(effectiveness=ControlEffectiveness.not_assessed, deleted=False)
    reqs = [NS(status=ComplianceStatus.not_assessed, controls=[eff]),
            NS(status=ComplianceStatus.not_assessed, controls=[untested]),
            NS(status=ComplianceStatus.not_assessed, controls=[])]
    p = cp.posture(reqs)
    assert (p.mapped, p.assured) == (2, 1)


def test_combine_weighs_clauses_not_frameworks():
    a = cp.posture([clause(coverage="assured")])
    b = cp.posture([clause() for _ in range(3)])
    total = cp.combine([a, b])
    assert (total.applicable, total.mapped_pct, total.assured_pct) == (4, 25.0, 25.0)


async def test_gap_analysis_carries_the_posture(monkeypatch):
    fw = NS(id=uuid.uuid4(), name="ISO/IEC 27001:2022", kind="compliance", requirements=[
        NS(id=uuid.uuid4(), reference="A.5.1", title="Policies", status=ComplianceStatus.not_assessed,
           coverage="unassessed", is_covered=True, deleted=False),
        NS(id=uuid.uuid4(), reference="A.5.2", title="Roles", status=ComplianceStatus.not_assessed,
           coverage="unmapped", is_covered=False, deleted=False),
    ])

    async def load(db, _id):
        return fw

    monkeypatch.setattr(compliance_api, "_load_framework", load)
    out = await compliance_api.gap_analysis(fw.id, None)
    assert out.compliant_pct == 0.0
    assert out.posture.line == "0% assessed compliant · 50% mapped · 0% tested"
    assert (out.posture.mapped, out.posture.assured) == (1, 0)


def test_the_soa_export_says_mapped_and_tested():
    assert soa_export.coverage_text({"applicable": 93, "mapped": 40, "assured": 6, "no_control": 53}) == (
        "40 of 93 applicable clauses mapped to a control; 6 backed by a tested control"
    )
    assert soa_export.coverage_text({"applicable": 0}) == "No applicable clauses"


# ============================================================ F-19: review all ===
def sug(fw, ref, score):
    return engine.Suggestion(uuid.uuid4(), fw, f"FW-{fw}", ref, "Clause", score, [])


def test_framework_filter_and_counts():
    a, b = uuid.uuid4(), uuid.uuid4()
    found = [sug(a, "A.5.1", 0.9), sug(b, "1.2", 0.8), sug(a, "A.5.2", 0.5)]
    assert [s.reference for s in engine.for_framework(found, a, None)] == ["A.5.1", "A.5.2"]
    assert [s.reference for s in engine.for_framework(found, None, 2)] == ["A.5.1", "1.2"]
    counts = {r["framework_id"]: (r["suggestions"], r["strong"]) for r in engine.framework_counts([found])}
    assert counts == {a: (2, 1), b: (1, 1)}


def test_unmapped_scope_means_no_live_clause_linked_of_the_framework():
    fw = uuid.uuid4()
    sql = str(engine.scope_statement("unmapped", fw).compile(dialect=postgresql.dialect()))
    assert "NOT (EXISTS" in sql and "requirements.framework_id" in sql and "requirements.deleted" in sql
    assert "ORDER BY controls.reference" in sql
    assert "EXISTS" not in str(engine.scope_statement("all").compile(dialect=postgresql.dialect()))


class ReviewDB:
    def __init__(self, total, controls):
        self.total, self.controls, self.offsets = total, controls, []

    async def scalar(self, *_a, **_k):
        return self.total

    async def scalars(self, stmt, *_a, **_k):
        compiled = stmt.compile(dialect=postgresql.dialect())
        offset = compiled.params.get("param_1", 0)
        self.offsets.append(offset)
        return NS(all=lambda: self.controls)


async def test_review_pages_through_the_register(monkeypatch):
    fw_a, fw_b = uuid.uuid4(), uuid.uuid4()
    c1 = NS(id=uuid.uuid4(), reference="C-1", name="Access control policy")
    c2 = NS(id=uuid.uuid4(), reference="C-2", name="Nothing matches")

    async def fake_suggest(db, controls, *, limit=None, min_score=0.0, index=None):
        return {c1.id: [sug(fw_a, "A.5.15", 0.9), sug(fw_b, "7.2", 0.6)], c2.id: []}

    monkeypatch.setattr(engine, "suggest_for_controls", fake_suggest)
    page = await engine.review_page(ReviewDB(250, [c1, c2]), offset=0, page_size=100)
    assert (page["total_controls"], page["scanned"], page["next_offset"]) == (250, 2, 2)
    assert [c.reference for c, _ in page["groups"]] == ["C-1"]
    assert (page["suggestion_count"], page["strong_count"]) == (2, 1)

    only_a = await engine.review_page(ReviewDB(2, [c1, c2]), framework_id=fw_a)
    assert only_a["next_offset"] is None
    assert [s.reference for _, kept in only_a["groups"] for s in kept] == ["A.5.15"]

    async def fake_strong(db, controls, *, limit=None, min_score=0.0, index=None):
        assert min_score == engine.STRONG
        return {c1.id: [sug(fw_a, "A.5.15", 0.9), sug(fw_a, "A.5.16", 0.8)], c2.id: []}

    monkeypatch.setattr(engine, "suggest_for_controls", fake_strong)
    pending = await engine.pending_strong(ReviewDB(5000, [c1, c2]), cap=2)
    assert pending == {"framework_id": None, "unmapped_controls": 5000, "scanned": 2, "capped": True,
                       "controls_with_strong": 1, "strong_suggestions": 2}


async def test_review_endpoint_shapes_the_page(monkeypatch):
    c1 = NS(id=uuid.uuid4(), reference="C-1", name="Backups")
    fw = uuid.uuid4()

    async def fake_page(db, **kw):
        assert kw["scope"] == "all" and kw["page_size"] == 50
        return {"scope": "all", "framework_id": None, "total_controls": 1, "offset": 0, "page_size": 50,
                "scanned": 1, "next_offset": None, "groups": [(c1, [sug(fw, "A.8.13", 0.8)])],
                "suggestion_count": 1, "strong_count": 1,
                "frameworks": [{"framework_id": fw, "framework": "ISO", "suggestions": 1, "strong": 1}]}

    monkeypatch.setattr(engine, "review_page", fake_page)
    out = await suggestions_api.review_all_suggestions(None, scope="all", framework_id=None, offset=0,
                                                       page_size=50, min_score=0.5, limit=5)
    assert out.groups[0].reference == "C-1" and out.groups[0].suggestions[0].reference == "A.8.13"
    assert out.frameworks[0].strong == 1


# ============================================================ F-11: outsourcing ===
def test_the_vocabularies():
    assert SUBSTITUTABILITY == ("easy", "moderate", "difficult", "none")
    assert CONCENTRATION_LEVELS == ("low", "medium", "high")
    ok = outsourcing_s.OutsourcingArrangementCreate(title="Core banking", substitutability=" Difficult ",
                                                   concentration_level="HIGH")
    assert (ok.substitutability, ok.concentration_level) == ("difficult", "high")
    assert outsourcing_s.OutsourcingArrangementUpdate(substitutability="").substitutability == ""
    with pytest.raises(ValidationError, match="substitutability must be one of"):
        outsourcing_s.OutsourcingArrangementCreate(title="x", substitutability="hard")
    with pytest.raises(ValidationError, match="concentration_level must be one of"):
        outsourcing_s.OutsourcingArrangementUpdate(concentration_level="extreme")


def facts(status="proposed", materiality="material", **kw):
    base = {"status": OutsourcingStatus(status), "materiality": OutsourcingMateriality(materiality),
            "materiality_assessment": "Core ledger; customers can't transact if it fails.",
            "exit_plan": "Move to the DR vendor within 90 days.", "substitutability": "difficult"}
    base.update(kw)
    return base


def test_what_a_material_arrangement_needs():
    assert missing_for_activation("material", {}) == ["materiality rationale", "exit plan", "substitutability"]
    assert missing_for_activation("non_material", {}) == []
    assert missing_for_activation("material", facts()) == []


def test_a_material_arrangement_cannot_go_live_without_the_facts():
    err = outsourcing_api.activation_error
    bare = facts(materiality_assessment="", exit_plan=" ", substitutability="")
    msg = err(None, {**bare, "status": OutsourcingStatus.active})
    assert msg.startswith("A material outsourcing arrangement can't be active until its materiality rationale, "
                          "exit plan and substitutability are recorded.")
    assert err(None, bare) is None  # proposed is fine
    assert err(None, {**bare, "materiality": OutsourcingMateriality.non_material, "status": OutsourcingStatus.active}) is None
    assert err(None, {**bare, "status": OutsourcingStatus.terminated}) is None
    assert err(None, facts(status="active")) is None
    # proposed -> under review with one fact missing
    assert "until its substitutability is recorded" in err(facts(substitutability=""), facts(status="under_review", substitutability=""))


def test_legacy_live_arrangements_keep_editing_but_cannot_lose_facts():
    err = outsourcing_api.activation_error
    legacy = facts(status="active", substitutability="")
    assert err(legacy, {**legacy, "exit_plan": "Updated plan"}) is None
    assert "exit plan and substitutability" in err(legacy, {**legacy, "exit_plan": ""})
    non_material = facts(status="active", materiality="non_material", substitutability="")
    assert "substitutability" in err(non_material, {**non_material, "materiality": OutsourcingMateriality.material})


async def test_create_and_update_refuse_with_a_plain_422(monkeypatch):
    body = outsourcing_s.OutsourcingArrangementCreate(title="Card switch", status=OutsourcingStatus.active)
    with pytest.raises(HTTPException) as exc:
        await outsourcing_api.create_arrangement(body, None, None)
    assert exc.value.status_code == 422 and "materiality rationale" in exc.value.detail

    arr = NS(id=uuid.uuid4(), reference="OUT-1", title="Card switch", vendor_id=None, owner_id=None, owner="",
             country_id=None, country="", **facts(substitutability=""))

    async def load(db, _id):
        return arr

    monkeypatch.setattr(outsourcing_api, "_load_arrangement", load)
    with pytest.raises(HTTPException) as exc:
        await outsourcing_api.update_arrangement(
            arr.id, outsourcing_s.OutsourcingArrangementUpdate(status=OutsourcingStatus.active), None, None,
        )
    assert exc.value.status_code == 422 and "until its substitutability is recorded" in exc.value.detail
    assert arr.status == OutsourcingStatus.proposed


class RowsDB:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, *_a, **_k):
        return NS(all=lambda: self.rows)


def arrangement(**kw):
    base = dict(id=uuid.uuid4(), reference="OUT-1", title="Core banking", status=OutsourcingStatus.active,
                materiality=OutsourcingMateriality.material, is_cloud=False, data_offshored=False, country="",
                country_id=None, sbp_approval_status=outsourcing_api.SbpApprovalStatus.not_required,
                contract_end=None, exit_plan="Plan", exit_plan_tested=False, materiality_assessment="Why",
                substitutability="none", concentration_level="high", concentration_note="Sole core vendor",
                is_contract_expiring=False, deleted=False)
    base.update(kw)
    arr = NS(**base)
    arr.missing_for_activation = missing_for_activation(
        arr.materiality, {"materiality_assessment": arr.materiality_assessment, "exit_plan": arr.exit_plan,
                          "substitutability": arr.substitutability})
    return arr


async def test_the_summary_counts_substitutability_and_concentration():
    rows = [
        arrangement(),
        arrangement(substitutability="easy", concentration_level="low", exit_plan_tested=True),
        arrangement(substitutability="", concentration_level=""),
        arrangement(materiality=OutsourcingMateriality.non_material, substitutability="none"),
        arrangement(status=OutsourcingStatus.terminated),
    ]
    out = await outsourcing_api.outsourcing_summary(RowsDB(rows))
    assert (out.hard_to_substitute, out.hard_to_substitute_untested, out.substitutability_unassessed) == (1, 1, 1)
    assert out.high_concentration == 2  # the live material and non-material ones; terminated is not counted
    assert out.live_missing_facts == 1


# ============================================================ F-11: vendor facts ===
def test_vendor_facts_carry_rationale_substitutability_and_concentration():
    [fact] = vendors_api.outsourcing_facts([arrangement()], {})
    assert (fact.materiality_assessment, fact.substitutability, fact.concentration_level, fact.concentration_note) == (
        "Why", "none", "high", "Sole core vendor")


def vendor(criticality="medium", tier=None, arrangements=(), processes=()):
    return NS(criticality=criticality, inherent_tier=tier, outsourcing_arrangements=list(arrangements),
              processes=list(processes))


def process(criticality):
    return NS(criticality=criticality, deleted=False)


def test_concentration_is_high_on_a_recorded_level_two_material_or_three_critical_processes():
    recorded = vendors_api.concentration_view(vendor(arrangements=[arrangement()]))
    assert recorded.level == "high" and recorded.flagged and recorded.recorded_level == "high"

    two = vendors_api.concentration_view(vendor(arrangements=[arrangement(concentration_level=""),
                                                              arrangement(concentration_level="")]))
    assert two.level == "high" and "2 material outsourcing arrangements rely on this provider." in two.reasons

    procs = vendors_api.concentration_view(vendor(processes=[process("critical"), process("high"), process("high"),
                                                             process("low")]))
    assert (procs.level, procs.critical_processes, procs.processes) == ("high", 3, 4)

    one = vendors_api.concentration_view(vendor(arrangements=[arrangement(concentration_level="")]))
    assert (one.level, one.flagged, one.material_arrangements) == ("medium", False, 1)

    ended = vendors_api.concentration_view(vendor(arrangements=[arrangement(status=OutsourcingStatus.terminated)]))
    assert (ended.level, ended.arrangements, ended.arrangement_expected) == ("low", 0, False)


def test_an_arrangement_is_expected_for_a_critical_third_party_with_none():
    assert vendors_api.concentration_view(vendor("critical")).arrangement_expected
    assert vendors_api.concentration_view(vendor("low", tier="high")).arrangement_expected
    assert vendors_api.concentration_view(vendor("low", processes=[process("critical")])).arrangement_expected
    assert not vendors_api.concentration_view(vendor("low")).arrangement_expected
    assert not vendors_api.concentration_view(vendor("critical", arrangements=[arrangement()])).arrangement_expected
