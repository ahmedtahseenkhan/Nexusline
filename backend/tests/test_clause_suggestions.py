"""Suggest clauses for existing controls (D-03).

A control named "MFA" was never linked to ISO A.8.5 because mapping was manual and the
scenario mapping resolves exact references only. These pin the engine's promises: every
reference it can suggest is a real clause, the ranking is deterministic and puts the
obvious clause first, propagation is one hop and weaker than the source, and nothing
already linked is suggested again. Pure — no database.
"""
import uuid

import pytest

from app.api.v1.ai_assist import _ISO_KEYWORDS, _heuristic_control_mapping, iso_controls_for_text
from app.services import clause_suggestions as cs
from app.services.framework_library import TEMPLATES


def _candidates(*keys: str) -> list[cs.Candidate]:
    out = []
    for key in keys:
        fid = uuid.UUID(int=len(out) + 10_000)
        for i, r in enumerate(TEMPLATES[key]["requirements"]):
            out.append(cs.Candidate(
                requirement_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{key}/{r['reference']}"),
                framework=TEMPLATES[key]["name"], reference=r["reference"], title=r["title"],
                description=r["description"], framework_id=uuid.uuid5(uuid.NAMESPACE_URL, key),
                template_key=key,
            ))
    return out


def _rid(key: str, ref: str):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{key}/{ref}")


def _refs(suggestions) -> list[str]:
    return [s.reference for s in suggestions]


# ------------------------------------------------------------- the synonym table ---
@pytest.mark.parametrize("topic,key,ref", cs.topic_references())
def test_every_synonym_reference_exists_in_its_template(topic, key, ref):
    assert key in TEMPLATES, f"{topic}: unknown template {key}"
    refs = {r["reference"] for r in TEMPLATES[key]["requirements"]}
    assert ref in refs, f"{topic}: {ref!r} is not a clause of {key}"


def test_the_topics_the_finding_names_are_covered():
    """D-03 lists MFA, PAM, encryption, logging and backup; the plan adds the rest."""
    wanted = {
        "mfa": ("iso-27001-2022", "A.8.5"), "pam": ("iso-27001-2022", "A.8.2"),
        "encryption": ("iso-27001-2022", "A.8.24"), "logging": ("iso-27001-2022", "A.8.15"),
        "monitoring": ("iso-27001-2022", "A.8.16"), "backup": ("iso-27001-2022", "A.8.13"),
        "vulnerability": ("iso-27001-2022", "A.8.8"), "access_review": ("iso-27001-2022", "A.5.18"),
        "incident": ("iso-27001-2022", "A.5.24"), "awareness": ("iso-27001-2022", "A.6.3"),
        "change": ("iso-27001-2022", "A.8.32"), "network": ("iso-27001-2022", "A.8.20"),
        "asset_inventory": ("iso-27001-2022", "A.5.9"), "supplier": ("iso-27001-2022", "A.5.19"),
        "continuity": ("iso-27001-2022", "A.5.30"), "classification": ("iso-27001-2022", "A.5.12"),
    }
    topics = {t.key: t for t in cs.TOPICS}
    for key, (tpl, ref) in wanted.items():
        assert ref in topics[key].refs[tpl], key
    assert "8.4" in topics["mfa"].refs["pci-dss-4.0"]
    assert "PR.AA-03" in topics["mfa"].refs["nist-csf-2.0"]
    assert "ETGRM-3.5" in topics["mfa"].refs["sbp-etgrm"]


def test_ai_assist_keywords_use_2022_annex_a_numbering():
    iso = {r["reference"] for r in TEMPLATES["iso-27001-2022"]["requirements"]}
    for kw, ref in _ISO_KEYWORDS.items():
        assert ref in iso, f"{kw}: {ref} is not an ISO 27001:2022 clause"
    text = _heuristic_control_mapping("Enforce MFA and encrypt data; keep backups.")
    assert "A.8.5 Secure authentication" in text
    assert "A.9" not in text and "A.10" not in text  # the retired 2013 domains


def test_iso_controls_come_in_order_of_mention():
    pairs = iso_controls_for_text("Backups must be encrypted")
    assert pairs[0][0] == "A.8.13"
    assert ("A.8.24", "Use of cryptography") in pairs


# ------------------------------------------------------------------ text handling ---
def test_stemming_meets_plurals_and_gerunds():
    assert cs.stem("backups") == cs.stem("backup")
    assert cs.stem("logging") == "log"
    assert cs.stem("encrypted") == "encrypt"
    assert cs.stem("access") == "access"


def test_topics_are_found_as_whole_words_and_ordered_by_mention():
    found = [t.key for t, _ in cs.topics_in("MFA for privileged access")]
    assert found[:2] == ["mfa", "pam"]
    # "otp" inside another word is not a mention.
    assert "mfa" not in [t.key for t, _ in cs.topics_in("Hotpatching of servers")]


# ---------------------------------------------------------------------- ranking ---
def test_mfa_for_privileged_access_ranks_a_8_5_first():
    index = cs.CandidateIndex(_candidates("iso-27001-2022"))
    result = cs.score_candidates(cs.ControlText("MFA for privileged access"), index)
    assert result[0].reference == "A.8.5"
    assert "A.8.2" in _refs(result)  # the qualifier is still suggested, lower
    assert _refs(result).index("A.8.5") < _refs(result).index("A.8.2")
    assert any("Multi-factor authentication" in r for r in result[0].reasons)


def test_a_8_5_is_the_top_iso_clause_among_several_frameworks():
    index = cs.CandidateIndex(_candidates("iso-27001-2022", "pci-dss-4.0", "nist-csf-2.0"))
    result = cs.score_candidates(cs.ControlText("MFA for privileged access"), index, limit=None)
    iso = [s for s in result if s.framework == TEMPLATES["iso-27001-2022"]["name"]]
    assert iso[0].reference == "A.8.5"
    top = _refs(result[:6])
    assert "8.4" in top and "PR.AA-03" in top


def test_scoring_is_deterministic():
    index = cs.CandidateIndex(_candidates("iso-27001-2022", "pci-dss-4.0", "cis-controls-v8"))
    control = cs.ControlText("Daily backups", "Restores are tested quarterly", "Recover data")
    first = [(s.requirement_id, s.score, tuple(s.reasons)) for s in cs.score_candidates(control, index, limit=None)]
    again = cs.CandidateIndex(list(reversed(_candidates("iso-27001-2022", "pci-dss-4.0", "cis-controls-v8"))))
    second = [(s.requirement_id, s.score, tuple(s.reasons)) for s in cs.score_candidates(control, again, limit=None)]
    assert first == second


@pytest.mark.parametrize("name,expected", [
    ("Privileged access management", "A.8.2"),
    ("Database encryption at rest", "A.8.24"),
    ("SIEM log collection", "A.8.15"),
    ("Daily backups", "A.8.13"),
    ("Monthly patching of servers", "A.8.8"),
    ("Quarterly user access review", "A.5.18"),
    ("Security awareness training", "A.6.3"),
    ("Change advisory board approval", "A.8.32"),
    ("Perimeter firewall rule review", "A.8.20"),
    ("Vendor due diligence", "A.5.19"),
    ("Annual DR test", "A.5.30"),
    ("Data classification scheme", "A.5.12"),
])
def test_named_controls_land_on_their_iso_clause(name, expected):
    index = cs.CandidateIndex(_candidates("iso-27001-2022"))
    result = cs.score_candidates(cs.ControlText(name), index, limit=3)
    assert expected in _refs(result), (name, _refs(result))


def test_keywords_alone_suggest_when_the_overlap_is_real():
    index = cs.CandidateIndex(_candidates("iso-27001-2022"))
    result = cs.score_candidates(cs.ControlText("Clear desk policy"), index)
    assert result and result[0].reference == "A.7.7"
    assert result[0].score < cs.SYN_NAME  # weaker than any synonym hit in the name


def test_nothing_is_invented_for_an_unrelated_control():
    index = cs.CandidateIndex(_candidates("iso-27001-2022"))
    assert cs.score_candidates(cs.ControlText("Customer complaint handling"), index, min_score=0.2) == []


def test_the_controls_own_reference_is_the_strongest_signal():
    index = cs.CandidateIndex(_candidates("iso-27001-2022", "cis-controls-v8"))
    result = cs.score_candidates(cs.ControlText("Our control", reference="CIS 6.3"), index)
    assert result[0].reference == "6.3" and result[0].score >= cs.OWN_REFERENCE


def test_already_linked_requirements_are_not_suggested():
    index = cs.CandidateIndex(_candidates("iso-27001-2022"))
    linked = _rid("iso-27001-2022", "A.8.5")
    result = cs.score_candidates(cs.ControlText("MFA"), index, exclude={linked})
    assert "A.8.5" not in _refs(result)


def test_min_score_and_limit_are_honoured():
    index = cs.CandidateIndex(_candidates("iso-27001-2022", "pci-dss-4.0"))
    result = cs.score_candidates(cs.ControlText("Logging and monitoring"), index, limit=3, min_score=0.5)
    assert len(result) <= 3 and all(s.score >= 0.5 for s in result)


def test_a_custom_framework_is_scored_on_keywords():
    fid = uuid.uuid4()
    custom = cs.Candidate(uuid.uuid4(), "Bank IT Standard", "ITS-7", "Clear desk and screen lock",
                          "Desks are cleared and screens locked when unattended.", fid, None)
    result = cs.score_candidates(cs.ControlText("Clear desk policy"), cs.CandidateIndex([custom]))
    assert _refs(result) == ["ITS-7"]


# ------------------------------------------------------------------ propagation ---
def test_crosswalked_requirements_follow_at_a_lower_score():
    iso = _candidates("iso-27001-2022")
    fid = uuid.uuid4()
    custom = cs.Candidate(uuid.uuid4(), "Internal Standard", "IS-9", "Login hardening", "", fid, None)
    a85 = _rid("iso-27001-2022", "A.8.5")
    index = cs.CandidateIndex(iso + [custom], {a85: {custom.requirement_id}, custom.requirement_id: {a85}})
    result = {s.reference: s for s in cs.score_candidates(cs.ControlText("MFA"), index, limit=None)}
    assert "IS-9" in result
    assert result["IS-9"].score == pytest.approx(result["A.8.5"].score * cs.CROSSWALK_FACTOR, abs=1e-3)
    assert any("Crosswalked to A.8.5" in r for r in result["IS-9"].reasons)


def test_crosswalks_do_not_chain():
    """One hop: a clause reached only by crosswalk does not pull in its own crosswalks."""
    fid1, fid2 = uuid.uuid4(), uuid.uuid4()
    b = cs.Candidate(uuid.uuid4(), "Std B", "B-1", "Unrelated clause", "", fid1, None)
    c = cs.Candidate(uuid.uuid4(), "Std C", "C-1", "Another unrelated clause", "", fid2, None)
    a85 = _rid("iso-27001-2022", "A.8.5")
    index = cs.CandidateIndex(
        _candidates("iso-27001-2022") + [b, c],
        {a85: {b.requirement_id}, b.requirement_id: {a85, c.requirement_id}, c.requirement_id: {b.requirement_id}},
    )
    refs = _refs(cs.score_candidates(cs.ControlText("MFA"), index, limit=None))
    assert "B-1" in refs and "C-1" not in refs


def test_shared_risk_scenarios_propagate_across_frameworks():
    """Keyword-free: an ISO control reference pulls in the CIS clauses the scenario
    library lists with it for the same scenarios."""
    index = cs.CandidateIndex(_candidates("iso-27001-2022", "cis-controls-v8"))
    result = cs.score_candidates(cs.ControlText("Our own control", reference="A.8.13"), index, limit=None)
    cis = {s.reference: s for s in result if s.framework == TEMPLATES["cis-controls-v8"]["name"]}
    assert "11.2" in cis
    assert any("same risk scenarios" in r for r in cis["11.2"].reasons)
    assert cis["11.2"].score < result[0].score
