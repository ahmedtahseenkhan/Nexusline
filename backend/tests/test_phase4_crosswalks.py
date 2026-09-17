"""Phase 4C: typed crosswalks, shipped crosswalk content and the common control set.

Pins that the shipped content is well-formed (every reference is a real clause of a
library template, no clause is mapped to itself, the vocabulary is closed and reading a
row the other way round inverts it); that materialising it respects a tenant's
rejections and its own typed rows; that "covered via crosswalk" only flows in the
direction the relationship allows and never counts as a direct mapping; and that a pack
install reuses a control through an equivalent crosswalk and asks for the rest. Pure,
except the loaders, which are compiled against PostgreSQL.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from app.models.enums import ComplianceStatus
from app.services import clause_suggestions as cs
from app.services import compliance_posture as cp
from app.services import crosswalk_content as cc
from app.services import crosswalks as cw
from app.services import framework_library as fl
from app.services import soa_export as soa

ISO, CSF, N53, CIS, PCI, SOC, ETGRM, SBP = (
    "iso-27001-2022", "nist-csf-2.0", "nist-800-53-r5", "cis-controls-v8", "pci-dss-4.0",
    "soc-2-2017", "sbp-etgrm", "sbp-cybersecurity",
)


# ============================================================ content integrity ===
def test_every_referenced_clause_exists_in_its_template():
    refs = {k: {r["reference"] for r in t["requirements"]} for k, t in fl.TEMPLATES.items()}
    missing = [
        (r.from_template, r.from_ref) for r in cc.all_rows() if r.from_ref not in refs[r.from_template]
    ] + [
        (r.to_template, r.to_ref) for r in cc.all_rows() if r.to_ref not in refs[r.to_template]
    ]
    assert missing == []


def test_the_required_framework_pairs_are_shipped():
    shipped = {frozenset((p.from_template, p.to_template)) for p in cc.pairs()}
    for a, b in ((ISO, CSF), (ISO, N53), (CSF, N53), (ISO, CIS), (ISO, PCI), (ISO, SOC),
                 (ISO, ETGRM), (ISO, SBP), (ETGRM, SBP), (PCI, CIS)):
        assert frozenset((a, b)) in shipped
    assert all(p.rows for p in cc.pairs())


def test_no_self_maps_no_duplicates_closed_vocabulary():
    seen = set()
    for r in cc.all_rows():
        assert r.from_template != r.to_template
        assert r.relationship in cc.RELATIONSHIPS
        assert 0 < r.confidence <= 1
        assert r.source
        key = cc.pair_key(*r.key)
        assert key not in seen, r.key
        seen.add(key)


def test_rationale_is_short_and_our_own():
    assert all(len(r.rationale) <= 160 for r in cc.all_rows())


def test_inverse_is_consistent():
    for rel, inv in cc.INVERSE.items():
        assert cc.INVERSE[inv] == rel
    row = cc.lookup(ISO, "A.5.9", CSF, "ID.AM-01")
    assert row.relationship == cc.SUPERSET
    back = cc.lookup(CSF, "ID.AM-01", ISO, "A.5.9")
    assert (back.from_template, back.from_ref, back.relationship) == (CSF, "ID.AM-01", cc.SUBSET)
    for r in cc.all_rows():
        o = r.oriented(r.to_template, r.to_ref)
        assert o.relationship == cc.INVERSE[r.relationship]
        assert o.oriented(r.from_template, r.from_ref) == r


def test_annex_a_is_substantively_covered_by_the_hubs():
    annex = {r["reference"] for r in fl.TEMPLATES[ISO]["requirements"] if r["reference"].startswith("A.")}
    for other, floor in ((CSF, 0.8), (N53, 0.9)):
        mapped = {r.from_ref for r in cc.all_rows() if r.from_template == ISO and r.to_template == other}
        assert len(mapped & annex) / len(annex) >= floor, other


def test_a_malformed_row_is_refused():
    with pytest.raises(cc.ContentError):
        cc.parse_rows("A.5.1 GV.PO-01 same 0.9", from_template=ISO, to_template=CSF, source="x")
    with pytest.raises(cc.ContentError):
        cc.parse_rows("A.5.1 GV.PO-01 equivalent 1.5", from_template=ISO, to_template=CSF, source="x")
    rows = cc.parse_rows("# c\n\nA.5.1 GV.PO-01 equivalent 0.9 Policy", from_template=ISO, to_template=CSF, source="x")
    assert rows[0].rationale == "Policy"


# ============================================================ materialisation ===
def _ids(*clauses):
    return {c: uuid.uuid5(uuid.NAMESPACE_URL, "/".join(c)) for c in clauses}


ROW_EQ = cc.ShippedRow(ISO, "A.8.5", CSF, "PR.AA-03", cc.EQUIVALENT, 0.85, "Auth", "src")
ROW_SUP = cc.ShippedRow(ISO, "A.5.9", CSF, "ID.AM-01", cc.SUPERSET, 0.75, "Inventory", "src")


def test_sync_inserts_shipped_rows_between_installed_clauses_only():
    ids = _ids((ISO, "A.8.5"), (CSF, "PR.AA-03"), (ISO, "A.5.9"))  # ID.AM-01 not installed
    plan = cw.plan_sync(ids, [], set(), rows=[ROW_EQ, ROW_SUP])
    assert len(plan.inserts) == 1
    ins = plan.inserts[0]
    assert (ins["requirement_id"], ins["related_requirement_id"]) == (ids[(ISO, "A.8.5")], ids[(CSF, "PR.AA-03")])
    assert (ins["relationship"], ins["origin"], ins["content_version"]) == ("equivalent", "shipped", cc.CONTENT_VERSION)


def test_sync_respects_rejections_and_is_idempotent():
    ids = _ids((ISO, "A.8.5"), (CSF, "PR.AA-03"))
    plan = cw.plan_sync(ids, [], {ROW_EQ.key}, rows=[ROW_EQ])
    assert plan.inserts == [] and plan.skipped_rejected == 1
    first = cw.plan_sync(ids, [], set(), rows=[ROW_EQ]).inserts[0]
    again = cw.plan_sync(ids, [cw.Link(**first)], set(), rows=[ROW_EQ])
    assert (again.inserts, again.updates, again.deletes) == ([], [], [])


def test_a_retyped_content_row_updates_and_needs_review_again():
    ids = _ids((ISO, "A.5.9"), (CSF, "ID.AM-01"))
    a, b = ids[(ISO, "A.5.9")], ids[(CSF, "ID.AM-01")]
    old = cw.Link(a, b, "intersects", "Inventory", "src", "2026.01", 0.75, "shipped", "Ayesha", uuid.uuid4(),
                  datetime.now(timezone.utc))
    plan = cw.plan_sync(ids, [old], set(), rows=[ROW_SUP])
    (_, _, changes), = plan.updates
    assert changes["relationship"] == "superset" and changes["approved_at"] is None


def test_a_row_stored_the_other_way_round_is_typed_inversely():
    ids = _ids((ISO, "A.5.9"), (CSF, "ID.AM-01"))
    a, b = ids[(ISO, "A.5.9")], ids[(CSF, "ID.AM-01")]
    legacy = cw.Link(b, a)  # manual, related, no source: written before typing
    (_, _, changes), = cw.plan_sync(ids, [legacy], set(), rows=[ROW_SUP]).updates
    assert changes["relationship"] == "subset" and changes["origin"] == "shipped"


def test_an_organisations_own_typed_row_is_never_overwritten():
    ids = _ids((ISO, "A.8.5"), (CSF, "PR.AA-03"))
    mine = cw.Link(ids[(ISO, "A.8.5")], ids[(CSF, "PR.AA-03")], "intersects", "Our call", origin="manual",
                   approved_at=datetime.now(timezone.utc))
    plan = cw.plan_sync(ids, [mine], set(), rows=[ROW_EQ])
    assert (plan.inserts, plan.updates) == ([], [])


def test_a_shipped_row_the_content_drops_is_removed_unless_approved():
    ids = _ids((ISO, "A.8.5"), (CSF, "PR.AA-03"))
    a, b = ids[(ISO, "A.8.5")], ids[(CSF, "PR.AA-03")]
    back = {v: k for k, v in ids.items()}
    stale = cw.Link(a, b, "equivalent", origin="shipped")
    assert cw.plan_sync(ids, [stale], set(), rows=[], clause_of=back).deletes == [(a, b)]
    stale.approved_at = datetime.now(timezone.utc)
    assert cw.plan_sync(ids, [stale], set(), rows=[], clause_of=back).deletes == []


# ============================================================ coverage via crosswalk ===
FW_ISO, FW_CSF = uuid.uuid4(), uuid.uuid4()


def _via(relationship, *, own="unmapped", assured=True, same_framework=False):
    r, s = uuid.uuid4(), uuid.uuid4()
    link = cw.Link(r, s, relationship)
    controls = {s: [cw.ViaControl(uuid.uuid4(), "A.8.5", "Secure authentication", "effective")]} if assured else {}
    clauses = {s: (FW_CSF if same_framework else FW_ISO, "A.8.5", "Secure authentication", "ISO/IEC 27001:2022")}
    return r, cw.resolve_via({r: (FW_CSF, own)}, [link], controls, clauses)


def test_equivalent_and_contained_clauses_are_covered_via_crosswalk():
    r, found = _via("equivalent")
    assert found[r].label == "mapped via ISO/IEC 27001:2022 A.8.5"
    r, found = _via("subset")  # the clause is wholly contained in A.8.5
    assert r in found and found[r].relationship == "subset"


def test_containing_overlapping_and_related_clauses_are_not():
    for rel in ("superset", "intersects", "related"):
        r, found = _via(rel)
        assert r not in found, rel


def test_direction_is_read_from_the_covered_clause():
    r, s = uuid.uuid4(), uuid.uuid4()
    link = cw.Link(s, r, "superset")  # stored from s: s contains r, so r is covered
    controls = {s: [cw.ViaControl(uuid.uuid4(), "A.5.9", "Inventory", "effective")]}
    found = cw.resolve_via({r: (FW_CSF, "unmapped"), s: (FW_ISO, "unmapped")}, [link], controls,
                           {s: (FW_ISO, "A.5.9", "Inventory", "ISO"), r: (FW_CSF, "ID.AM-01", "Hardware", "CSF")})
    assert r in found and s not in found


def test_no_tested_control_failing_direct_control_or_same_framework_means_no_coverage():
    assert not _via("equivalent", assured=False)[1]
    assert not _via("equivalent", own="failing")[1]
    assert not _via("equivalent", own="assured")[1]
    assert not _via("equivalent", same_framework=True)[1]
    r, found = _via("equivalent", own="unassessed")
    assert r in found


def _clause(rid, coverage="unmapped"):
    return NS(id=rid, status=ComplianceStatus.not_assessed, coverage=coverage, deleted=False)


def test_posture_reports_via_crosswalk_separately():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    reqs = [_clause(a), _clause(b, "assured"), _clause(c, "failing")]
    p = cp.posture(reqs, {a: object(), b: object(), c: object()})
    assert (p.mapped, p.assured, p.via_crosswalk) == (2, 1, 1)
    assert p.via_crosswalk_pct == pytest.approx(33.3)
    assert p.line.endswith("· 33.3% covered via crosswalk")
    assert cp.posture(reqs).line == "0% assessed compliant · 66.7% mapped · 33.3% tested"
    assert cp.combine([p, p]).via_crosswalk == 2


def test_the_soa_shows_crosswalk_coverage_apart_from_implementing_controls():
    rid = uuid.uuid4()
    req = NS(id=rid, reference="PR.AA-03", title="Authentication performed", domain="Protect", treatment=None,
             status=ComplianceStatus.not_assessed, controls=[], applicability_justification="",
             coverage="unmapped", deleted=False)
    via = cw.ViaCrosswalk(rid, uuid.uuid4(), "A.8.5", "Secure authentication", "ISO/IEC 27001:2022", "equivalent",
                          controls=[cw.ViaControl(uuid.uuid4(), "A.8.5", "Secure authentication", "effective")])
    rows = soa.build_rows([req], {rid: via})
    assert rows[0].controls == [] and rows[0].via_crosswalk is via
    assert "not a direct mapping" in rows[0].via_text and "A.8.5" in rows[0].via_text
    counts = soa.summarize(rows)
    assert (counts["no_control"], counts["mapped"], counts["via_crosswalk"]) == (1, 0, 1)
    assert "1 covered via crosswalk" in soa.coverage_text(counts)
    assert "not a direct mapping" in soa.table_rows(rows)[0][5]


# ============================================================ common control set ===
def _catalogue():
    mfa = fl.ControlFacts(uuid.uuid4(), "CTL-7", "NTP clock synchronisation")
    log = fl.ControlFacts(uuid.uuid4(), "A.8.15", "Logging")
    return mfa, log


def _mapped(mfa, log):
    return [
        (ISO, "A.8.17", mfa.id, mfa.reference, mfa.name, "ISO/IEC 27001:2022"),
        (ISO, "A.8.15", log.id, log.reference, log.name, "ISO/IEC 27001:2022"),
    ]


def test_reuse_candidates_follow_content_and_respect_rejections():
    mfa, log = _catalogue()
    cands = cw.reuse_candidates(PCI, _mapped(mfa, log))
    assert cands["10.6"][0].relationship == "equivalent" and cands["10.6"][0].control_id == mfa.id
    assert cands["10.2"][0].relationship == "intersects" and cands["10.2"][0].control_id == log.id
    rejected = {cc.lookup(ISO, "A.8.17", PCI, "10.6").key}
    assert "10.6" not in cw.reuse_candidates(PCI, _mapped(mfa, log), rejected)


def test_plan_pack_reuses_for_equivalent_and_asks_for_the_rest():
    mfa, log = _catalogue()
    wanted = [r for r in fl.TEMPLATES[PCI]["requirements"] if r["reference"] in ("10.6", "10.2")]
    matches = cw.reuse_candidates(PCI, _mapped(mfa, log))
    steps = {s.requirement_ref: s for s in fl.plan_pack(wanted, PCI, [mfa, log], None, matches)}
    assert steps["10.6"].action == fl.MATCH_CROSSWALK and steps["10.6"].control.id == mfa.id
    assert steps["10.2"].action == fl.CREATE and steps["10.2"].crosswalk_match.control_id == log.id
    decided = {s.requirement_ref: s for s in fl.plan_pack(
        wanted, PCI, [mfa, log], {"10.2": str(log.id), "10.6": "create"}, matches)}
    assert decided["10.2"].action == fl.MAP_EXISTING and decided["10.6"].action == fl.CREATE


def test_a_reference_match_still_wins_and_own_controls_are_never_crosswalk_reused():
    mfa, log = _catalogue()
    own = fl.ControlFacts(uuid.uuid4(), "PCI 10.6", "Time synchronisation")
    wanted = [r for r in fl.TEMPLATES[PCI]["requirements"] if r["reference"] == "10.6"]
    steps = fl.plan_pack(wanted, PCI, [mfa, log, own], None, cw.reuse_candidates(PCI, _mapped(mfa, log)))
    assert steps[0].action == fl.MATCH_REFERENCE
    theirs = [(ISO, "A.8.17", own.id, own.reference, own.name, "ISO")]
    steps = fl.plan_pack(wanted, PCI, [own], None, cw.reuse_candidates(PCI, theirs))
    assert steps[0].crosswalk_match is None or steps[0].action == fl.MATCH_REFERENCE


# ============================================================ suggestions ===
def test_typed_crosswalks_weight_propagation_by_relationship():
    assert cs.crosswalk_factor(None) == cs.CROSSWALK_FACTOR
    assert cs.crosswalk_factor("equivalent") > cs.crosswalk_factor("superset") > cs.crosswalk_factor("subset")
    assert cs.crosswalk_factor("subset") > cs.crosswalk_factor("related")
    fid = uuid.uuid4()
    iso = [cs.Candidate(uuid.uuid5(uuid.NAMESPACE_URL, r["reference"]), "ISO", r["reference"], r["title"],
                        r["description"], uuid.uuid4(), ISO) for r in fl.TEMPLATES[ISO]["requirements"]]
    a85 = next(c.requirement_id for c in iso if c.reference == "A.8.5")
    custom = cs.Candidate(uuid.uuid4(), "Internal", "IS-9", "Login hardening", "", fid, None)
    index = cs.CandidateIndex(iso + [custom], {a85: {custom.requirement_id: "equivalent"},
                                               custom.requirement_id: {a85: "equivalent"}})
    got = {s.reference: s for s in cs.score_candidates(cs.ControlText("MFA"), index, limit=None)}
    assert got["IS-9"].score == pytest.approx(got["A.8.5"].score * 0.8, abs=1e-3)
    assert any("(equivalent)" in r for r in got["IS-9"].reasons)


# ============================================================ loaders compile ===
class CompilingDB:
    def __init__(self):
        self.sql: list[str] = []

    def _compile(self, stmt):
        from sqlalchemy.dialects import postgresql

        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))

    async def execute(self, stmt):
        self._compile(stmt)
        return NS(all=lambda: [])

    async def scalars(self, stmt):
        self._compile(stmt)
        return NS(all=lambda: [])

    async def scalar(self, stmt):
        self._compile(stmt)
        return None


async def test_the_loaders_build_valid_postgresql():
    db = CompilingDB()
    assert await cw.sync_shipped(db) == cw.SyncResult()
    assert await cw.load_links(db, [uuid.uuid4()], both=False) == []
    assert "requirement_crosswalks" in db.sql[-1]
    assert await cw.reuse_candidates_for(db, PCI) == {}
    assert "requirement_controls" in db.sql[-1]
    req = NS(id=uuid.uuid4(), framework_id=uuid.uuid4(), status=ComplianceStatus.not_assessed,
             coverage="unmapped", deleted=False)
    assert await cw.via_crosswalk_for(db, [req]) == {}
    assert await cw.rejected_keys(db) == set()
    assert "crosswalk_rejections" in db.sql[-1]


async def test_gap_analysis_carries_crosswalk_coverage(monkeypatch):
    from app.api.v1 import compliance as api

    rid = uuid.uuid4()
    fw = NS(id=uuid.uuid4(), name="NIST Cybersecurity Framework 2.0", kind="compliance", requirements=[
        NS(id=rid, reference="PR.AA-03", title="Authentication performed", status=ComplianceStatus.not_assessed,
           coverage="unmapped", is_covered=False, deleted=False),
    ])
    via = cw.ViaCrosswalk(rid, uuid.uuid4(), "A.8.5", "Secure authentication", "ISO/IEC 27001:2022", "equivalent")

    async def load(db, _id):
        return fw

    async def fake_via(db, reqs):
        return {rid: via}

    monkeypatch.setattr(api, "_load_framework", load)
    monkeypatch.setattr(api, "_via_crosswalks", fake_via)
    out = await api.gap_analysis(fw.id, None)
    assert out.posture.via_crosswalk == 1 and out.posture.mapped == 0
    assert out.gaps[0].via_crosswalk == "mapped via ISO/IEC 27001:2022 A.8.5"


def test_the_schema_module_is_idempotent_and_protected():
    import app.models  # noqa: F401
    from app.db.phase4 import crosswalks as schema
    from app.db.rls import TENANT_SCOPED_TABLES

    ddl = schema.ddl_statements()
    assert all("IF NOT EXISTS" in s for s in ddl if s.startswith("ALTER TABLE requirement_crosswalks ADD"))
    assert "crosswalk_rejections" in schema.TABLES and "crosswalk_rejections" in TENANT_SCOPED_TABLES
    assert any("FORCE ROW LEVEL SECURITY" in s for s in ddl)
