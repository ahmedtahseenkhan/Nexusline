"""Suggested crosswalks between installed frameworks (phase 3, plan §3.4).

A crosswalk says two clauses of different frameworks ask for the same thing, so it has
to be right: these pin that suggestions are conservative (only a topic's primary clause
on at least one side; never two secondary clauses), that every suggested reference is a
live clause of the installed framework, that a control shared by two clauses counts in
proportion to how specific it is, that existing crosswalks are not suggested again, and
that the accept/remove helpers refuse a pair within one framework. Pure — no database.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import clause_suggestions as cs
from app.services.framework_library import TEMPLATES

ISO, PCI, CSF, ETGRM, SBP_CS = "iso-27001-2022", "pci-dss-4.0", "nist-csf-2.0", "sbp-etgrm", "sbp-cybersecurity"


def _clauses(key: str, *, drop: tuple[str, ...] = ()) -> list[cs.CrosswalkClause]:
    fid = uuid.uuid5(uuid.NAMESPACE_URL, key)
    return [
        cs.CrosswalkClause(uuid.uuid5(uuid.NAMESPACE_URL, f"{key}/{r['reference']}"), fid, r["reference"], r["title"])
        for r in TEMPLATES[key]["requirements"] if r["reference"] not in drop
    ]


def _rid(key: str, ref: str):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{key}/{ref}")


def _pairs(suggestions) -> dict:
    return {(s.reference, s.related_reference): s for s in suggestions}


def _suggest(a: str, b: str, **kw):
    return cs.suggest_crosswalks(_clauses(a), _clauses(b), from_template=a, to_template=b, **kw)


# --------------------------------------------------------------- the topic table ---
def test_topic_pairs_never_join_two_secondary_clauses():
    for a, b in ((ISO, PCI), (ISO, CSF), (PCI, SBP_CS), (ISO, ETGRM)):
        pairs = cs.topic_crosswalk_pairs(a, b)
        assert pairs
        for (x, y), hits in pairs.items():
            assert all(rank in (1, 2) for rank in hits.values())
            # rank 1 or 2 means at least one of the two is the topic's first-listed clause
            assert any(
                (t.refs.get(a, ())[:1] == (x,) or t.refs.get(b, ())[:1] == (y,))
                for t in cs.TOPICS if t.label in hits
            )


def test_a_framework_is_not_crosswalked_to_itself_by_topic():
    assert cs.topic_crosswalk_pairs(ISO, ISO) == {}
    assert cs.topic_crosswalk_pairs(ISO, None) == {}


def test_incident_secondary_clauses_are_not_paired():
    """ISO lists A.5.24 first and A.5.25 after it for incidents; PCI lists 12.10 then
    12.10.1. A.5.25 ≡ 12.10.1 would be two secondary clauses — never proposed."""
    pairs = cs.topic_crosswalk_pairs(ISO, PCI)
    assert pairs[("A.5.24", "12.10")]["Incident response"] == 2
    assert pairs[("A.5.25", "12.10")]["Incident response"] == 1
    assert ("A.5.25", "12.10.1") not in pairs


# ------------------------------------------------------------------ suggestions ---
def test_mfa_is_a_strong_crosswalk_between_iso_and_pci():
    found = _pairs(_suggest(ISO, PCI))
    mfa = found[("A.8.5", "8.4")]
    assert mfa.strength == "high" and mfa.confidence == cs.CW_BOTH_PRIMARY
    assert mfa.sources == ["topic"]
    assert mfa.reasons == ["Same topic: Multi-factor authentication (the primary clause in both frameworks)"]
    secondary = found[("A.8.5", "8.4.2")]
    assert secondary.strength == "medium" and secondary.confidence == cs.CW_ONE_PRIMARY


@pytest.mark.parametrize("a,b", [(ISO, PCI), (ISO, CSF), (ISO, ETGRM), (PCI, SBP_CS), (CSF, ETGRM)])
def test_every_suggested_reference_is_a_clause_of_its_framework(a, b):
    found = _suggest(a, b)
    assert len(found) >= 15
    a_refs = {r["reference"] for r in TEMPLATES[a]["requirements"]}
    b_refs = {r["reference"] for r in TEMPLATES[b]["requirements"]}
    for s in found:
        assert s.reference in a_refs and s.related_reference in b_refs
        assert 0 < s.confidence <= cs.CW_MAX
        assert s.strength in ("high", "medium")


def test_a_clause_missing_from_the_installed_framework_is_not_suggested():
    """A tenant on an older, shallower copy of PCI gets fewer candidates, not invented ones."""
    found = cs.suggest_crosswalks(_clauses(ISO), _clauses(PCI, drop=("8.4",)), from_template=ISO, to_template=PCI)
    refs = {s.related_reference for s in found}
    assert "8.4" not in refs
    assert ("A.8.5", "8.5") in _pairs(found)


def test_existing_crosswalks_are_not_suggested_again():
    existing = [frozenset((_rid(ISO, "A.8.5"), _rid(PCI, "8.4")))]
    found = _pairs(_suggest(ISO, PCI, existing=existing))
    assert ("A.8.5", "8.4") not in found
    assert ("A.8.5", "8.5") in found


def test_suggestions_are_deterministic_and_strongest_first():
    one, two = _suggest(ISO, PCI), _suggest(ISO, PCI)
    assert [(s.reference, s.related_reference, s.confidence) for s in one] == \
           [(s.reference, s.related_reference, s.confidence) for s in two]
    scores = [s.confidence for s in one]
    assert scores == sorted(scores, reverse=True)


def test_two_topics_agreeing_raise_the_confidence():
    """PCI 7.2 and NIST CSF PR.AA-05 are each framework's primary clause for both
    privileged access and access review."""
    pair = _pairs(_suggest(PCI, CSF))[("7.2", "PR.AA-05")]
    assert len([r for r in pair.reasons if r.startswith("Same topic")]) == 2
    assert pair.confidence == pytest.approx(cs.CW_BOTH_PRIMARY + cs.CW_EXTRA_TOPIC)


def test_a_topic_where_both_clauses_are_secondary_adds_nothing():
    """ISO A.5.18 and PCI 7.2 are both secondary under access control, so only the
    access-review topic (primary in both) pairs them."""
    pair = _pairs(_suggest(ISO, PCI))[("A.5.18", "7.2")]
    assert pair.reasons == ["Same topic: Access review (the primary clause in both frameworks)"]


# --------------------------------------------------------------- shared controls ---
def _custom(name: str, *refs: str) -> list[cs.CrosswalkClause]:
    fid = uuid.uuid5(uuid.NAMESPACE_URL, name)
    return [cs.CrosswalkClause(uuid.uuid5(uuid.NAMESPACE_URL, f"{name}/{r}"), fid, r, f"{name} {r}") for r in refs]


def test_a_specific_shared_control_proposes_a_pair_between_custom_frameworks():
    a, b = _custom("Bank policy", "P-1", "P-2"), _custom("Group standard", "G-1", "G-2")
    links = {uuid.uuid4(): ("CTL-7 Encrypt laptops", {a[0].requirement_id, b[0].requirement_id})}
    found = cs.suggest_crosswalks(a, b, from_template=None, to_template=None, control_links=links)
    assert len(found) == 1
    s = found[0]
    assert (s.reference, s.related_reference, s.sources) == ("P-1", "G-1", ["control"])
    assert s.confidence == pytest.approx(cs.CW_CONTROL_BASE + cs.CW_CONTROL_SPAN)
    assert s.reasons == ["Implemented by the same control: CTL-7 Encrypt laptops"]


def test_a_broad_control_alone_proposes_nothing():
    a, b = _custom("A", "1", "2", "3"), _custom("B", "1", "2", "3")
    everything = {c.requirement_id for c in a + b}
    found = cs.suggest_crosswalks(a, b, from_template=None, to_template=None,
                                  control_links={uuid.uuid4(): ("CTL-1 Information security policy", everything)})
    assert found == []  # 1 / (3 x 3) support per pair is below the threshold


def test_controls_linked_to_one_side_only_propose_nothing():
    a, b = _custom("A", "1"), _custom("B", "1")
    found = cs.suggest_crosswalks(a, b, from_template=None, to_template=None,
                                  control_links={uuid.uuid4(): ("CTL-1", {a[0].requirement_id})})
    assert found == []


def test_a_shared_control_confirms_a_topic_match():
    links = {uuid.uuid4(): ("A.8.5 Secure authentication", {_rid(ISO, "A.8.5"), _rid(PCI, "8.5")})}
    pair = _pairs(_suggest(ISO, PCI, control_links=links))[("A.8.5", "8.5")]
    assert pair.sources == ["topic", "control"]
    assert pair.strength == "high"
    assert pair.confidence == pytest.approx(cs.CW_CONTROL_BASE + cs.CW_CONTROL_SPAN + cs.CW_BOTH_SIGNALS_BONUS)
    assert "Implemented by the same control: A.8.5 Secure authentication" in pair.reasons


def test_a_library_and_a_custom_framework_meet_only_through_controls():
    custom = _custom("Bank standard", "BS-1")
    assert cs.suggest_crosswalks(_clauses(ISO), custom, from_template=ISO, to_template=None) == []
    links = {uuid.uuid4(): ("MFA", {_rid(ISO, "A.8.5"), custom[0].requirement_id})}
    found = cs.suggest_crosswalks(_clauses(ISO), custom, from_template=ISO, to_template=None, control_links=links)
    assert [(s.reference, s.related_reference) for s in found] == [("A.8.5", "BS-1")]


def test_many_controls_are_named_briefly():
    a, b = _custom("A", "1"), _custom("B", "1")
    both = {a[0].requirement_id, b[0].requirement_id}
    links = {uuid.uuid4(): (f"CTL-{i}", both) for i in range(5)}
    s = cs.suggest_crosswalks(a, b, from_template=None, to_template=None, control_links=links)[0]
    assert s.reasons == ["Implemented by the same control: CTL-0, CTL-1, CTL-2 and 2 more"]
    assert s.confidence == pytest.approx(cs.CW_CONTROL_BASE + cs.CW_CONTROL_SPAN)  # support capped at 1


# ------------------------------------------------------------ accept / remove ---
class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, stmt):
        return SimpleNamespace(all=lambda: self.rows)


def _req(fid, ref):
    return SimpleNamespace(id=uuid.uuid4(), framework_id=fid, reference=ref, title=ref,
                           framework=SimpleNamespace(name=str(fid)[:4]))


async def test_accepting_a_pair_within_one_framework_is_refused():
    from app.api.v1.compliance import CrosswalkPair, _crosswalk_pairs

    fid = uuid.uuid4()
    a, b = _req(fid, "A.1"), _req(fid, "A.2")
    with pytest.raises(HTTPException) as exc:
        await _crosswalk_pairs(FakeDB([a, b]), [CrosswalkPair(requirement_id=a.id, related_requirement_id=b.id)])
    assert exc.value.status_code == 422 and "same framework" in exc.value.detail


async def test_accepting_an_unknown_clause_is_refused():
    from app.api.v1.compliance import CrosswalkPair, _crosswalk_pairs

    a = _req(uuid.uuid4(), "A.1")
    with pytest.raises(HTTPException) as exc:
        await _crosswalk_pairs(FakeDB([a]), [CrosswalkPair(requirement_id=a.id, related_requirement_id=uuid.uuid4())])
    assert exc.value.status_code == 400


async def test_a_pair_sent_twice_or_reversed_is_written_once():
    from app.api.v1.compliance import CrosswalkPair, _crosswalk_pairs

    a, b = _req(uuid.uuid4(), "A.8.5"), _req(uuid.uuid4(), "8.4")
    _, pairs = await _crosswalk_pairs(FakeDB([a, b]), [
        CrosswalkPair(requirement_id=a.id, related_requirement_id=b.id),
        CrosswalkPair(requirement_id=b.id, related_requirement_id=a.id),
    ])
    assert pairs == [(a.id, b.id)]


def test_the_accept_body_is_bounded():
    from pydantic import ValidationError

    from app.api.v1.compliance import CrosswalkPairsBody

    with pytest.raises(ValidationError):
        CrosswalkPairsBody(pairs=[])


# --------------------------------------------------- loaders build valid PostgreSQL ---
class CompilingDB:
    def __init__(self, frameworks=()):
        self.sql: list[str] = []
        self.frameworks = list(frameworks)

    def _compile(self, stmt):
        from sqlalchemy.dialects import postgresql

        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))

    async def execute(self, stmt):
        self._compile(stmt)
        return SimpleNamespace(all=lambda: [])

    async def scalars(self, stmt):
        self._compile(stmt)
        rows = self.frameworks if "FROM frameworks" in self.sql[-1] else []
        return SimpleNamespace(all=lambda: rows)


async def test_the_crosswalk_loaders_compile_and_refuse_bad_frameworks():
    same = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await cs.load_crosswalk_context(CompilingDB(), same, same)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await cs.load_crosswalk_context(CompilingDB(), uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404

    a = SimpleNamespace(id=uuid.uuid4(), name="ISO/IEC 27001:2022")
    b = SimpleNamespace(id=uuid.uuid4(), name="Bank standard")
    db = CompilingDB([a, b])
    ctx, found = await cs.crosswalk_suggestions_for(db, a.id, b.id)
    assert (ctx.from_template, ctx.to_template) == (ISO, None)
    assert found == [] and ctx.existing == set()
    assert any("FROM requirements" in q for q in db.sql)
    links = await cs.crosswalk_control_links(db, [uuid.uuid4()])
    assert links == {} and "requirement_controls" in db.sql[-1]
