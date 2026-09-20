"""Phase 4E: the questionnaire engine.

No database: the pure rules are tested directly, ORM rows are built transient, and the
endpoints that matter are driven with stubbed loaders.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.rate_limit import RateLimiter
from fastapi import HTTPException

import app.models  # noqa: F401 - registers every table
from app.api.v1 import assessments as api
from app.core.database import Base
from app.db.phase4 import questionnaires as schema
from app.db.rls import TENANT_SCOPED_TABLES
from app.models.assessment import (
    Assessment,
    AssessmentFinding,
    Questionnaire,
)
from app.models.enums import FindingStatus, Severity, VendorAssessmentStatus
from app.schemas.assessment import AssessmentRead, QuestionnaireUpdate
from app.services import questionnaire_library as library
from app.services import questionnaire_logic as ql
from app.services import questionnaire_portal as portal
from app.services import questionnaire_versions as versions
from app.services import questionnaire_workflow as wf
from app.services import vendor_tiering as vt

TID = uuid.uuid4()
AV = ql.AnswerValue


def yn(key, *, weight=1, mandatory=False, flag=None, when=None):
    return library.yes_no(key, f"Question {key}?", weight=weight, mandatory=mandatory, flag=flag, when=when)


# ================================================================ conditions ===
def test_rules_cover_every_operator():
    sel = AV(option_values=("yes",))
    assert ql.rule_holds({"op": "in", "values": ["yes", "na"]}, sel)
    assert not ql.rule_holds({"op": "in", "values": ["no"]}, sel)
    assert ql.rule_holds({"op": "not_in", "values": ["no"]}, sel)
    assert ql.rule_holds({"op": "not_in", "values": ["no"]}, None)  # unanswered is "not in"
    assert ql.rule_holds({"op": "answered"}, AV(na=True))
    assert ql.rule_holds({"op": "not_answered"}, AV(text="   "))
    n = AV(number=5)
    for op, value, expected in [("eq", 5, True), ("neq", 5, False), ("gt", 4, True), ("gte", 5, True),
                                ("lt", 5, False), ("lte", 5, True)]:
        assert ql.rule_holds({"op": op, "value": value}, n) is expected, op
    assert not ql.rule_holds({"op": "neq", "value": 1}, None)  # no number: every comparison is false
    assert not ql.rule_holds({"op": "bogus"}, sel)


def test_conditions_match_all_or_any_and_empty_always_shows():
    answers = {"a": AV(option_values=("yes",)), "b": AV(number=2)}
    rules = [{"question": "a", "op": "in", "values": ["yes"]}, {"question": "b", "op": "gt", "value": 3}]
    assert not ql.condition_holds({"match": "all", "rules": rules}, answers)
    assert ql.condition_holds({"match": "any", "rules": rules}, answers)
    assert ql.condition_holds({}, answers) and ql.condition_holds(None, answers)


def test_hiding_cascades_and_sections_hide_their_questions():
    spec = [
        library.section("s1", "One", "", [
            yn("gate"),
            yn("child", when=library.when_in("gate", "yes")),
            yn("grandchild", when=library.when_in("child", "yes")),
        ]),
        library.section("s2", "Two", "", [yn("inside")], when=library.when_in("gate", "no")),
    ]
    answers = {"gate": AV(option_values=("no",)), "child": AV(option_values=("yes",)), "inside": AV(option_values=("yes",))}
    vis = ql.visibility(spec, answers)
    # child is hidden, so its stale "yes" can't show grandchild
    assert vis.questions == {"gate", "inside"} and vis.sections == {"s1", "s2"}
    vis = ql.visibility(spec, {"gate": AV(option_values=("yes",)), "child": AV(option_values=("yes",))})
    assert vis.questions == {"gate", "child", "grandchild"} and "s2" not in vis.sections


def test_structure_checks_refuse_forward_references_and_unknown_values():
    good = [library.section("s", "S", "", [yn("a"), yn("b", when=library.when_in("a", "yes"))])]
    assert ql.structure_problems(good) == []
    forward = [library.section("s", "S", "", [yn("b", when=library.when_in("a", "yes")), yn("a")])]
    assert any("earlier" in p for p in ql.structure_problems(forward))
    unknown = [library.section("s", "S", "", [yn("a"), yn("b", when=library.when_in("a", "maybe"))])]
    assert any("does not offer" in p for p in ql.structure_problems(unknown))
    dup = [library.section("s", "S", "", [yn("a"), yn("a")])]
    assert any("used by another question" in p for p in ql.structure_problems(dup))
    assert ql.structure_problems([], for_publish=True) == ["Add at least one question before publishing."]


def test_every_shipped_template_is_valid_and_in_our_own_words():
    keys = {t["key"] for t in library.TEMPLATES}
    assert keys == {"sbp-outsourcing-due-diligence", "cloud-service-security",
                    "third-party-information-security-baseline", "business-continuity-readiness",
                    "rcsa-control-self-assessment"}
    for t in library.TEMPLATES:
        assert ql.structure_problems(t["sections"], for_publish=True) == [], t["key"]
        assert ql.band_problems(t["bands"]) == [], t["key"]
        text = " ".join(q["text"] for s in t["sections"] for q in s["questions"]).lower()
        assert "sig " not in text and "caiq" not in text
    sbp = " ".join(q["text"] for s in library.get("sbp-outsourcing-due-diligence")["sections"] for q in s["questions"]).lower()
    for theme in ("materiality", "outside pakistan", "sub-contractor", "audit", "continuity", "exit", "state bank", "confidential"):
        assert theme in sbp or theme in str(library.get("sbp-outsourcing-due-diligence")).lower(), theme
    cloud = str(library.get("cloud-service-security")).lower()
    for theme in ("multi-factor", "encrypt", "keys", "logs", "region", "incident", "iso/iec 27001"):
        assert theme in cloud, theme


# ================================================================== scoring ===
def test_weights_na_and_hidden_questions_score_as_documented():
    spec = [library.section("s", "S", "", [
        yn("a", weight=2),                                  # max 2
        yn("b"),                                            # max 1, answered N/A: drops out
        yn("c", when=library.when_in("a", "no")),           # hidden: drops out
        library.choice("d", "Pick", [library._opt("x", "X", 2), library._opt("y", "Y", 3), library._opt("z", "Z", 0)],
                       multiple=True),                      # max 5
        library.field("e", "Notes", "long_text", mandatory=True),  # unscored
    ])]
    answers = {"a": AV(option_values=("yes",)), "b": AV(option_values=("na",)),
               "c": AV(option_values=("yes",)), "d": AV(option_values=("x", "y"))}
    r = ql.score(spec, answers)
    assert (r.earned, r.maximum) == (7.0, 7.0) and r.pct == 100.0
    assert r.not_applicable == 1 and r.missing_mandatory == ("e",)
    assert r.visible_questions == 4 and r.answered_questions == 3 and r.progress_pct == 75
    blank = ql.score(spec, {})
    assert blank.earned == 0 and blank.maximum == 8.0 and blank.pct == 0.0  # blanks keep their maximum
    assert ql.score([library.section("s", "S", "", [library.field("t", "T", "text")])], {}).pct is None


def test_bands_pick_the_highest_minimum_not_above_the_score():
    bands = library.DUE_DILIGENCE_BANDS
    assert ql.band_for(bands, 80)["label"] == "Strong"
    assert ql.band_for(bands, 79.9)["rating"] == "medium"
    assert ql.band_for(bands, 0)["rating"] == "critical"
    assert ql.band_for(bands, None) is None and ql.band_for([], 50) is None
    assert ql.band_problems([{"label": "Only", "min_pct": 10, "rating": "low"}]) == [
        "Add a band that starts at 0% so every score falls in a band."]
    assert any("same score" in p for p in ql.band_problems(
        [{"label": "A", "min_pct": 0, "rating": "low"}, {"label": "B", "min_pct": 0, "rating": "high"}]))


# ============================================================ ORM fixtures ===
def _version(template_key="sbp-outsourcing-due-diligence", status="published", purpose=None, tree=None, bands=None):
    t = library.get(template_key)
    qid = uuid.uuid4()
    v = Questionnaire(id=qid, tenant_id=TID, family_id=qid, version=1, status=status, name=t["name"], description="",
                      purpose=purpose or t["purpose"], bands=bands if bands is not None else t["bands"], origin="library")
    sections, questions = versions.build_rows(TID, qid, versions.normalise_tree(tree or t["sections"]))
    for q in questions:
        for o in q.options:
            o.id = uuid.uuid4()
    v.sections, v.questions = sections, questions
    return v


def _q(version, key):
    return next(q for q in version.questions if q.key == key)


def _opt(question, value):
    return next(o for o in question.options if o.value == value)


def _assessment(version, status=VendorAssessmentStatus.in_progress):
    a = Assessment(id=uuid.uuid4(), tenant_id=TID, title="1LINK due diligence", questionnaire=version,
                   questionnaire_id=version.id, status=status)
    a.answers, a.findings = [], []
    return a


def _answer(a, key, *values, **fields):
    q = _q(a.questionnaire, key)
    sent = SimpleNamespace(question_id=q.id, option_id=None, option_ids=[_opt(q, v).id for v in values],
                           value_text=fields.get("text"), value_number=fields.get("number"), value_date=None,
                           not_applicable=None, comment=fields.get("comment", ""))
    rows, _ = wf.upsert_answers(a, [sent], tenant_id=TID, answered_by="vendor@1link.net.pk")
    a.answers.extend(rows)
    return q


# ================================================================ versioning ===
async def test_a_published_version_cannot_be_edited(monkeypatch):
    v = _version()

    async def load(db, qid):
        return v

    monkeypatch.setattr(api, "_load_questionnaire", load)
    with pytest.raises(HTTPException) as exc:
        await api.update_questionnaire(v.id, QuestionnaireUpdate(name="Renamed"), SimpleNamespace(), SimpleNamespace(tenant_id=TID))
    assert exc.value.status_code == 409 and "new version" in exc.value.detail
    assert v.name == "SBP outsourcing due diligence"
    with pytest.raises(versions.VersionError) as err:
        await versions.replace_tree(SimpleNamespace(), v, [])
    assert err.value.status == 409


async def test_publishing_supersedes_the_previous_version_and_needs_a_valid_structure(monkeypatch):
    old = _version()
    draft = _version(status="draft")
    draft.family_id, draft.version = old.family_id, 2

    async def family(db, fid):
        return [draft, old]

    monkeypatch.setattr(versions, "family_versions", family)

    class DB:
        async def flush(self):
            pass

    user = SimpleNamespace(id=uuid.uuid4())
    await versions.publish(DB(), draft, user, "Adds cloud questions")
    assert (old.status, draft.status) == ("superseded", "published")
    assert draft.published_by_id == user.id and draft.change_note == "Adds cloud questions"
    with pytest.raises(versions.VersionError) as again:
        await versions.publish(DB(), draft, user)
    assert again.value.status == 409

    no_bands = _version(status="draft", bands=[])
    problems = versions.publish_problems(no_bands, ql.spec_from_version(no_bands))
    assert any("scoring bands" in p for p in problems)
    tiering = _version(status="draft", purpose="vendor_tiering")
    assert any("single-choice" in p for p in versions.publish_problems(tiering, ql.spec_from_version(tiering)))


def test_a_new_version_copies_keys_so_conditions_keep_working():
    v = _version()
    tree = versions._clone_tree(v)
    sections, questions = versions.build_rows(TID, uuid.uuid4(), tree)
    assert [q.key for q in questions] == [q.key for q in v.questions]
    assert all(q.id not in {x.id for x in v.questions} for q in questions)
    assert ql.structure_problems(ql.spec_from_version(SimpleNamespace(sections=sections, questions=questions)),
                                 for_publish=True) == []


def test_normalising_fills_blank_keys_uniquely():
    tree = versions.normalise_tree([{"title": "Access", "questions": [
        {"text": "Do you use MFA?", "type": "yes_no_na", "options": [{"label": "Yes"}, {"label": "Yes"}]},
        {"text": "Do you use MFA?", "type": "text", "options": []},
    ]}])
    qs = tree[0]["questions"]
    assert tree[0]["key"] == "access" and qs[0]["key"] != qs[1]["key"]
    assert [o["value"] for o in qs[0]["options"]] == ["yes", "yes_2"]


def test_existing_questionnaires_migrate_to_published_version_one():
    ddl = schema.ddl_statements()
    assert "UPDATE questionnaires SET family_id = id WHERE family_id IS NULL" in ddl
    assert any("status VARCHAR(16) NOT NULL DEFAULT 'published'" in s for s in ddl)
    assert "ALTER TABLE questionnaires ALTER COLUMN status SET DEFAULT 'draft'" in ddl
    assert any("purpose = 'vendor_tiering'" in s and "inherent risk tiering" in s for s in ddl)
    assert any(s.startswith("INSERT INTO questionnaire_sections") and "NOT EXISTS" in s for s in ddl)
    assert not any(s.lstrip().upper().startswith(("DELETE", "DROP TABLE", "TRUNCATE")) for s in ddl)
    for table, col, _ in schema.COLUMNS:
        assert col in Base.metadata.tables[table].c, (table, col)
    for table, col, target, _ in schema.FK_COLUMNS:
        assert {fk.column.table.name for fk in Base.metadata.tables[table].c[col].foreign_keys} == {target}
    for table in schema.TABLES:
        assert table in Base.metadata.tables and table in TENANT_SCOPED_TABLES


# ============================================================ tokens + portal ===
def test_links_store_only_a_hash_and_expire_or_revoke():
    now = datetime(2026, 9, 17, tzinfo=timezone.utc)
    link, token = portal.issue_link(tenant_id=TID, assessment_id=uuid.uuid4(), contact_name="Ayesha",
                                    contact_email="ayesha@vendor.pk", expires_in_days=500, now=now)
    assert portal.parse_token(token) == (TID, link.id)
    stored = " ".join(str(getattr(link, c.key)) for c in link.__table__.columns)
    assert token.split(".")[2] not in stored and link.token_hash == portal.token_hash(token)
    assert portal.token_matches(token, link.token_hash) and not portal.token_matches(token + "x", link.token_hash)
    assert link.expires_at == now + timedelta(days=portal.MAX_EXPIRY_DAYS)  # capped at 90 days
    assert portal.link_state(link, now) == portal.ACTIVE
    assert portal.link_state(link, now + timedelta(days=91)) == portal.EXPIRED
    link.revoked_at = now
    assert portal.link_state(link, now) == portal.REVOKED
    assert portal.parse_token("abc.def.short") is None and portal.parse_token(None) is None


def test_rate_limit_and_upload_rules():
    limiter = RateLimiter("test-respond", capacity=3, per_second=3 / 60)
    assert [limiter.hit_memory("1.2.3.4", now=t).allowed for t in (0, 0, 0, 0)] == [True, True, True, False]
    assert limiter.hit_memory("1.2.3.4", now=61).allowed
    assert portal.upload_refusal("report.pdf", "application/pdf") is None
    assert "can't be uploaded" in portal.upload_refusal("run.exe", "application/octet-stream")
    assert "does not match" in portal.upload_refusal("report.pdf", "text/html")
    req = SimpleNamespace(headers={"x-forwarded-for": "10.0.0.9, 172.16.0.1", "user-agent": "Mozilla"}, client=None)
    log = portal.access_log(tenant_id=TID, assessment_id=None, link_id=None, action="view", request=req)
    assert (log.ip_address, log.user_agent) == ("10.0.0.9", "Mozilla")


async def test_a_bad_token_is_refused_before_touching_the_database():
    portal.ip_limiter.reset()
    with pytest.raises(HTTPException) as exc:
        await api._open(SimpleNamespace(), "not-a-token", SimpleNamespace(headers={}, client=None), "view")
    assert exc.value.status_code == 404


def test_the_read_schema_no_longer_exposes_the_access_hash():
    assert "access_hash" not in AssessmentRead.model_fields


# ======================================================= answers + review ===
def test_answers_are_typed_and_na_drops_out():
    a = _assessment(_version())
    _answer(a, "data_access", "customer")
    q = _q(a.questionnaire, "customer_data_segregated")
    sent = SimpleNamespace(question_id=q.id, option_id=None, option_ids=None, value_text=None, value_number=None,
                           value_date=None, not_applicable=True, comment="")
    rows, _ = wf.upsert_answers(a, [sent], tenant_id=TID, answered_by="x")
    assert rows[0].not_applicable and rows[0].option_id == _opt(q, "na").id
    single = _q(a.questionnaire, "financials")
    with pytest.raises(wf.WorkflowError):
        wf.upsert_answers(a, [SimpleNamespace(question_id=single.id, option_id=None,
                                              option_ids=[o.id for o in single.options], value_text=None,
                                              value_number=None, value_date=None, not_applicable=None, comment="")],
                          tenant_id=TID, answered_by="x")


def test_returned_answers_reopen_and_nothing_else_can_change():
    a = _assessment(_version())
    q = _answer(a, "financials", "no")
    other = _answer(a, "ownership_disclosed", "yes")
    answer = a.answers[0]
    with pytest.raises(wf.WorkflowError):
        wf.review_answer(answer, "return", "  ", uuid.uuid4())
    wf.review_answer(answer, "return", "Please attach last year's audited accounts.", uuid.uuid4())
    a.status, a.submitted_at = VendorAssessmentStatus.submitted, date.today()
    assert a.returned_count == 1 and "returned" in wf.review_refusal(a)
    reopened = api._reopened(a)
    assert reopened == {q.id}
    change_other = SimpleNamespace(question_id=other.id, option_id=None, option_ids=[_opt(other, "no").id],
                                   value_text=None, value_number=None, value_date=None, not_applicable=None, comment="")
    with pytest.raises(wf.WorkflowError) as exc:
        wf.upsert_answers(a, [change_other], tenant_id=TID, answered_by="x", only_questions=reopened)
    assert exc.value.status == 409
    fix = SimpleNamespace(question_id=q.id, option_id=None, option_ids=[_opt(q, "yes").id], value_text=None,
                          value_number=None, value_date=None, not_applicable=None, comment="Attached.")
    _rows, changed = wf.upsert_answers(a, [fix], tenant_id=TID, answered_by="x", only_questions=reopened)
    assert changed == 1 and answer.review_state == "pending"
    assert wf.review_refusal(a) is None


async def test_final_review_is_refused_to_the_sender(monkeypatch):
    from app.services import dual_control

    sender = uuid.uuid4()
    a = _assessment(_version(), status=VendorAssessmentStatus.submitted)
    a.sent_by_id = sender

    async def required(db, module, action, amount=None):
        assert (module, action) == ("assessment", "review")
        return True, None

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    assert await api._review_block(None, a, SimpleNamespace(id=sender)) == api.REVIEW_SOD_MESSAGE
    assert await api._review_block(None, a, SimpleNamespace(id=uuid.uuid4())) is None


def test_mandatory_questions_block_submission():
    a = _assessment(_version())
    spec, _values, result = wf.evaluate(a)
    refusal = wf.submit_refusal(result, spec)
    assert refusal is not None and refusal.problems and "required" in str(refusal)


# ================================================================== findings ===
def test_flagged_answers_raise_findings_once_and_close_when_changed():
    a = _assessment(_version())
    _answer(a, "data_access", "customer")
    _answer(a, "data_location", "abroad_unapproved", comment="Singapore DR site")
    _answer(a, "audit_rights", "no")
    spec, values, _ = wf.evaluate(a)
    created, closed = wf.sync_flag_findings(a, spec, values, tenant_id=TID)
    titles = {f.title: f for f in created}
    assert closed == 0 and len(created) == 2
    loc = titles["Bank data held outside Pakistan without the required approvals"]
    assert loc.severity == Severity.critical and loc.auto_raised and "Singapore DR site" in loc.description
    a.findings.extend(created)
    again, _ = wf.sync_flag_findings(a, spec, values, tenant_id=TID)
    assert again == []
    _answer(a, "audit_rights", "yes")
    spec, values, _ = wf.evaluate(a)
    _new, closed = wf.sync_flag_findings(a, spec, values, tenant_id=TID)
    assert closed == 1 and titles["No right for the bank to audit the provider"].status == FindingStatus.closed


def test_a_finding_shows_closed_once_its_issue_is_closed():
    f = AssessmentFinding(title="Gap", status=FindingStatus.open)
    f.issue = SimpleNamespace(id=uuid.uuid4(), reference="ISS-031", title="Gap", status=SimpleNamespace(value="in_progress"), deleted=False)
    assert f.effective_status == "open" and f.issue_ref["reference"] == "ISS-031"
    f.issue.status = SimpleNamespace(value="closed")
    assert f.effective_status == "closed"


# =================================================================== results ===
def test_tiering_is_recognised_by_purpose_not_name():
    assert vt.is_tiering_questionnaire(SimpleNamespace(name="Supplier risk profile", purpose="vendor_tiering"))
    assert not vt.is_tiering_questionnaire(SimpleNamespace(name="Inherent risk tiering", purpose="general"))
    assert vt.is_tiering_questionnaire(SimpleNamespace(name="Inherent risk tiering"))  # pre-4E object


async def test_the_tiering_seed_is_a_published_purpose_version():
    from app.db import reference_data

    class DB:
        def __init__(self):
            self.added = []

        async def scalars(self, *_a, **_k):
            return SimpleNamespace(all=lambda: [])

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            pass

    db = DB()
    assert await reference_data.ensure_tiering_questionnaire(db, TID) == 1
    (q,) = db.added
    assert (q.purpose, q.status, q.family_id, q.version) == ("vendor_tiering", "published", q.id, 1)
    assert [b["min_pct"] for b in q.bands] == [70.0, 45.0, 20.0, 0.0]
    assert all(x.mandatory and x.section_id == q.sections[0].id and x.key for x in q.questions)


def test_due_diligence_rating_follows_the_band_unless_overridden_with_a_reason():
    v = SimpleNamespace(risk_rating=None, risk_rating_override_reason="")
    assert wf.apply_rating(v, "high", Severity) == {"risk_rating": {"from": None, "to": "high"}}
    assert v.risk_rating == Severity.high
    kept = SimpleNamespace(risk_rating=Severity.medium, risk_rating_override_reason="Exit plan tested in June")
    assert wf.apply_rating(kept, "critical", Severity) == {} and kept.risk_rating == Severity.medium
    stale = SimpleNamespace(risk_rating=Severity.high, risk_rating_override_reason="old")
    assert wf.apply_rating(stale, "high") == {"risk_rating_override_reason": {"from": "old", "to": ""}}

    with pytest.raises(wf.WorkflowError) as exc:
        wf.resolve_rating(proposed="high", band="Weak", stored_rating="high", stored_reason="", sent={"risk_rating": "low"})
    assert "risk_rating_override_reason" in str(exc.value)
    assert wf.resolve_rating(proposed="high", band="Weak", stored_rating="high", stored_reason="",
                             sent={"risk_rating": "low", "risk_rating_override_reason": " Compensating controls "}) == "Compensating controls"
    assert wf.resolve_rating(proposed="high", band="Weak", stored_rating="low", stored_reason="x", sent={"risk_rating": "high"}) == ""
    assert wf.resolve_rating(proposed=None, band="", stored_rating=None, stored_reason="", sent={"risk_rating": "low"}) is None


def test_due_diligence_view_names_the_latest_reviewed_result():
    dd = SimpleNamespace(purpose="vendor_due_diligence", name="Cloud service security")
    old = SimpleNamespace(id=uuid.uuid4(), title="2025", questionnaire=dd, status=VendorAssessmentStatus.reviewed,
                          reviewed_at=datetime(2025, 9, 1, tzinfo=timezone.utc), created_at=None,
                          result_pct=90.0, result_band="Strong", result_rating="low", open_findings=0)
    new = SimpleNamespace(id=uuid.uuid4(), title="2026", questionnaire=dd, status=VendorAssessmentStatus.reviewed,
                          reviewed_at=datetime(2026, 9, 1, tzinfo=timezone.utc), created_at=None,
                          result_pct=55.0, result_band="Weak", result_rating="high", open_findings=2)
    vendor = SimpleNamespace(assessments=[old, new], risk_rating=Severity.medium, risk_rating_override_reason="Exit tested",
                             last_due_diligence_on=date(2026, 9, 1), next_due_diligence_on=date(2026, 9, 10),
                             status="active")
    view = wf.due_diligence_view(vendor, today=date(2026, 9, 17))
    assert view["title"] == "2026" and view["band"] == "Weak" and view["overridden"] and view["overdue"]
    assert view["open_findings"] == 2
    assert wf.due_diligence_view(SimpleNamespace(assessments=[])) is None


def test_rcsa_runs_repeat_the_blueprint_per_line_and_take_the_worse_rating():
    lines = [SimpleNamespace(id=uuid.uuid4(), title="Card fraud", control=None, control_description="Velocity checks"),
             SimpleNamespace(id=uuid.uuid4(), title="Branch cash", control=None, control_description="Dual custody")]
    blueprint = library.get("rcsa-control-self-assessment")["sections"]
    tree = wf.build_rcsa_tree(blueprint, lines)
    assert ql.structure_problems(tree, for_publish=True) == []
    assert [s["key"] for s in tree] == ["control_1", "control_2"]
    weakness = next(q for q in tree[1]["questions"] if q["key"] == "weakness_2")
    assert {r["question"] for r in weakness["conditions"]["rules"]} == {"design_2", "operation_2"}
    answers = {"design_1": AV(option_values=("effective",)), "operation_1": AV(option_values=("partially_effective",)),
               "design_2": AV(option_values=("not_assessed",))}
    ratings = wf.rcsa_ratings(tree, answers)
    assert ratings[str(lines[0].id)] == {"design": "effective", "operation": "partially_effective"}
    assert wf.worse_rating("effective", "partially_effective") == "partially_effective"
    assert wf.worse_rating("not_assessed", None) is None


# ================================================================= scheduler ===
def test_reminders_overdue_alerts_and_recurrence_are_due_on_the_right_days():
    today = date(2026, 9, 17)

    def a(**kw):
        base = dict(status=VendorAssessmentStatus.sent, due_date=today + timedelta(days=5), last_reminder_on=None,
                    overdue_alerted_on=None, recurrence_months=None, next_issue_on=None)
        base.update(kw)
        return SimpleNamespace(**base)

    assert wf.due_action(a(due_date=today + timedelta(days=10)), today) is None
    assert wf.due_action(a(), today).kind == "reminder"
    assert wf.due_action(a(last_reminder_on=today - timedelta(days=1)), today) is None
    assert wf.due_action(a(due_date=today - timedelta(days=1)), today).kind == "overdue_first"
    assert wf.due_action(a(due_date=today - timedelta(days=9), overdue_alerted_on=today - timedelta(days=8),
                           last_reminder_on=today - timedelta(days=8)), today).kind == "overdue_reminder"
    assert wf.due_action(a(status=VendorAssessmentStatus.submitted), today) is None
    assert wf.reissue_due(a(status=VendorAssessmentStatus.reviewed, recurrence_months=12, next_issue_on=today), today)
    assert not wf.reissue_due(a(status=VendorAssessmentStatus.reviewed, recurrence_months=None, next_issue_on=today), today)
    assert wf.next_due(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert wf._base_title("Cloud review (Sep 2026)") == "Cloud review"


def test_invitation_email_is_plain_and_names_the_bank():
    subject, html, text = wf.render_request(
        "invite", organisation="Bank Alfalah", assessment=SimpleNamespace(title="Cloud <security>", due_date=date(2026, 10, 1)),
        url="https://grc.bank.pk/respond/tok", expires_at=datetime(2026, 10, 17, tzinfo=timezone.utc), contact_name="Ayesha",
    )
    assert subject.startswith("Bank Alfalah") and "&lt;security&gt;" in html and "https://grc.bank.pk/respond/tok" in text
    assert "Do not forward it" in text
