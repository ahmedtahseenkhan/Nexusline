"""Regressions from the client's "the system is not working" verification of the asset,
continuity, privacy, evidence and respondent-portal modules.

* custom-field values are only written onto a record of the key's own register;
* the asset registers sort by what they show (effective criticality, owning unit);
* links written on a continuity plan, RoPA, BIA or scanner finding show on the asset
  (and a plan's BIA shows its plans); archived controls and vendors drop off an asset;
* the evidence register hides an archived control's evidence;
* a reviewer's returned answer reopens its follow-up questions, and a resubmission is
  refused while a returned answer is unchanged;
* archiving stamps a timestamp, like every other module.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 - registers every table
from app.api.v1 import assessments as assessments_api
from app.api.v1 import assets as assets_api
from app.api.v1 import bia as bia_api
from app.api.v1 import custom_fields as cf_api
from app.api.v1 import evidence as evidence_api
from app.models.asset import Asset, AssetDependency
from app.models.assessment import Assessment, Questionnaire
from app.models.bia import BiaAssessment
from app.models.enums import AssetClass, Criticality, VendorAssessmentStatus
from app.schemas.asset import AssetRead
from app.schemas.bia import BiaRead
from app.services import questionnaire_library as library
from app.services import questionnaire_versions as versions
from app.services import questionnaire_workflow as wf

TID = uuid.uuid4()


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class _CaptureDb:
    """Records the statements a handler runs; answers with ``found`` / empty pages."""

    def __init__(self, found=None):
        self.found, self.statements = found, []

    async def scalar(self, stmt):
        self.statements.append(stmt)
        return self.found

    async def scalars(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: [])

    async def flush(self):
        return None


# ============================================================ custom fields ===
def test_custom_field_values_target_the_keys_own_register():
    orm, clauses = cf_api.record_filter("information_asset", uuid.uuid4())
    assert orm is Asset
    sql = " ".join(_sql(c) for c in clauses)
    assert "assets.asset_class = 'information_asset'" in sql
    orm, clauses = cf_api.record_filter("dpia", uuid.uuid4())
    assert orm.__tablename__ == "dpias" and len(clauses) == 1


async def test_values_for_a_record_outside_the_register_are_refused():
    with pytest.raises(HTTPException) as exc:
        await cf_api._require_record(_CaptureDb(found=None), "it_asset", uuid.uuid4())
    assert exc.value.status_code == 404 and exc.value.detail == "No IT asset with this id"
    await cf_api._require_record(_CaptureDb(found=uuid.uuid4()), "it_asset", uuid.uuid4())


# ================================================================== sorting ===
def test_the_asset_list_sorts_by_what_the_registers_show():
    for key in ("effective_criticality", "owner", "business_value", "availability"):
        assert key in assets_api._ASSET_SORTABLE
    sql = _sql(assets_api._ASSET_SORTABLE["effective_criticality"])
    assert "greatest" in sql.lower() and "max(" in sql.lower() and "deleted IS false" in sql
    assert "business_units.name" in _sql(assets_api._ASSET_SORTABLE["owner"])


def test_an_archived_information_asset_no_longer_lifts_its_server():
    info = Asset(asset_class=AssetClass.information_asset, business_value=Criticality.critical, deleted=True)
    it = Asset(asset_class=AssetClass.it_asset, replacement_cost=0, availability=Criticality.low)
    it.hosted_dependencies = [AssetDependency(information_asset=info)]
    assert it.derived_criticality == Criticality.low
    info.deleted = False
    assert it.effective_criticality == Criticality.critical


# ==================================================================== links ===
def test_reverse_links_are_on_the_asset_and_the_bia():
    for field in ("continuity_plans", "processing_activities", "bia_assessments", "vuln_findings"):
        assert field in AssetRead.model_fields
        assert hasattr(Asset, field)
    assert "continuity_plans" in BiaRead.model_fields and hasattr(BiaAssessment, "continuity_plans")
    for rel in (Asset.controls, Asset.vendors, Asset.continuity_plans, Asset.processing_activities,
                Asset.bia_assessments, BiaAssessment.continuity_plans):
        joins = [rel.property.primaryjoin, rel.property.secondaryjoin]
        assert any("deleted" in str(j) for j in joins if j is not None), rel


def test_linked_records_carry_their_reference_and_name():
    legal = SimpleNamespace(id=uuid.uuid4(), reference="SBP-BPRD-05", name="Outsourcing framework")
    ref = assets_api._ref(legal)
    assert (ref.label, ref.reference, ref.name) == ("SBP-BPRD-05", "SBP-BPRD-05", "Outsourcing framework")
    plain = assets_api._ref(SimpleNamespace(id=uuid.uuid4(), name="Card switch"))
    assert (plain.label, plain.reference, plain.name) == ("Card switch", "", "Card switch")


# ================================================================= evidence ===
async def test_the_evidence_register_hides_archived_controls_evidence():
    db = _CaptureDb(found=0)
    await evidence_api.list_evidence(db, control_id=uuid.uuid4(), search=None, control_audit_id=None,
                                     unattached=None, sort_by=None, sort_dir="asc", limit=10, offset=0)
    assert all("controls.deleted IS false" in _sql(s) for s in db.statements)


async def test_evidence_cannot_be_collected_for_an_archived_control():
    class Db:
        async def get(self, model, oid):
            return SimpleNamespace(id=oid, deleted=True)

    with pytest.raises(HTTPException) as exc:
        await evidence_api._control_or_400(Db(), uuid.uuid4())
    assert exc.value.status_code == 400 and "archived" in exc.value.detail


# ============================================================ archive stamp ===
async def test_archiving_a_bia_stamps_the_moment_not_the_date(monkeypatch):
    obj = BiaAssessment(id=uuid.uuid4(), reference="BIA-001", process_name="Payments", deleted=False)

    async def load(db, bid):
        return obj

    async def record(*args, **kwargs):
        return None

    monkeypatch.setattr(bia_api, "_load_bia", load)
    monkeypatch.setattr(bia_api.audit_log, "record", record)
    await bia_api.delete_bia(obj.id, _CaptureDb(), SimpleNamespace())
    assert obj.deleted and isinstance(obj.deleted_date, datetime) and obj.deleted_date.tzinfo is not None


# ========================================================= respondent portal ===
def _conditional_version():
    tree = [library.section("s1", "Certification", "", [
        library.yes_no("iso", "Are you ISO 27001 certified?"),
        library.field("scope", "What is the certificate's scope?", "text", mandatory=True,
                      when=library.when_in("iso", "yes")),
        library.yes_no("bcp", "Do you test your continuity plan yearly?"),
    ])]
    qid = uuid.uuid4()
    v = Questionnaire(id=qid, tenant_id=TID, family_id=qid, version=1, status="published", name="Conditional",
                      description="", purpose="vendor_due_diligence", bands=[], origin="tenant")
    sections, questions = versions.build_rows(TID, qid, versions.normalise_tree(tree))
    for q in questions:
        q.id = uuid.uuid4()
        for o in q.options:
            o.id = uuid.uuid4()
    v.sections, v.questions = sections, questions
    return v


def _sent(question, *values, text=None, comment=""):
    return SimpleNamespace(question_id=question.id, option_id=None,
                           option_ids=[o.id for o in question.options if o.value in values],
                           value_text=text, value_number=None, value_date=None, not_applicable=None, comment=comment)


def _returned_round():
    """Submitted with ISO "no", the ISO answer returned and "bcp" accepted."""
    v = _conditional_version()
    q = {x.key: x for x in v.questions}
    a = Assessment(id=uuid.uuid4(), tenant_id=TID, title="1LINK", questionnaire=v, questionnaire_id=v.id,
                   status=VendorAssessmentStatus.in_progress)
    a.answers, a.findings = [], []
    rows, _ = wf.upsert_answers(a, [_sent(q["iso"], "no"), _sent(q["bcp"], "yes")], tenant_id=TID, answered_by="v")
    a.answers.extend(rows)
    earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
    for row in a.answers:
        row.answered_at = earlier
    by_q = {row.question_id: row for row in a.answers}
    wf.review_answer(by_q[q["iso"].id], "return", "Your certificate is on your website.", uuid.uuid4())
    wf.review_answer(by_q[q["bcp"].id], "accept", "", uuid.uuid4())
    a.submitted_at = date.today()
    return a, q, by_q


def test_a_returned_answer_reopens_the_follow_up_it_reveals_in_the_same_save():
    a, q, by_q = _returned_round()
    reopened = wf.reopened_questions(a)
    assert reopened == {q["iso"].id, q["scope"].id}
    rows, changed = wf.upsert_answers(a, [_sent(q["iso"], "yes"), _sent(q["scope"], text="All data centres")],
                                      tenant_id=TID, answered_by="v", only_questions=reopened)
    a.answers.extend(rows)
    assert changed == 2 and by_q[q["iso"].id].review_state == "pending"
    # The round stays open: the revised answer can be corrected again, the accepted one can't.
    again = wf.reopened_questions(a)
    assert again == {q["iso"].id, q["scope"].id}
    wf.upsert_answers(a, [_sent(q["iso"], "yes", comment="Certified 2025")], tenant_id=TID, answered_by="v",
                      only_questions=again)
    with pytest.raises(wf.WorkflowError) as exc:
        wf.upsert_answers(a, [_sent(q["bcp"], "no")], tenant_id=TID, answered_by="v", only_questions=again)
    assert exc.value.status == 409


def test_follow_ups_hang_on_sections_and_chains():
    tree = [
        library.section("s1", "One", "", [library.yes_no("a", "A?"), library.yes_no("b", "B?", when=library.when_in("a", "yes"))]),
        library.section("s2", "Two", "", [library.yes_no("c", "C?")], when=library.when_in("b", "yes")),
        library.section("s3", "Three", "", [library.yes_no("d", "D?")]),
    ]
    sections, questions = versions.build_rows(TID, uuid.uuid4(), versions.normalise_tree(tree))
    for x in questions:
        x.id = uuid.uuid4()
    ids = {x.key: x.id for x in questions}
    spec = [{"id": s.id, "key": s.key, "conditions": s.conditions,
             "questions": [{"id": x.id, "key": x.key, "conditions": x.conditions} for x in questions if x.section_id == s.id]}
            for s in sections]
    assert wf.dependent_questions(spec, [ids["a"]]) == {ids["b"], ids["c"]}


def test_a_resubmission_with_an_unchanged_returned_answer_is_refused():
    a, q, _by_q = _returned_round()
    refusal = wf.returned_refusal(a)
    assert refusal is not None and refusal.status == 409
    assert refusal.problems == [f"Returned: {q['iso'].text}"]
    detail = assessments_api._http(refusal).detail
    assert "not been updated" in detail["message"]
    wf.upsert_answers(a, [_sent(q["iso"], "no", comment="We are not certified; see our SOC 2 report.")],
                      tenant_id=TID, answered_by="v", only_questions=wf.reopened_questions(a))
    assert wf.returned_refusal(a) is None


def test_a_condition_in_another_shape_is_refused_not_ignored():
    from app.services import questionnaire_logic as ql

    tree = [library.section("s1", "One", "", [
        library.yes_no("iso", "ISO?"),
        library.field("bcp", "Describe", "long_text", when={"all": [{"question": "iso", "equals": "yes"}]}),
    ])]
    problems = ql.structure_problems(versions.normalise_tree(tree))
    assert any("'all' is not understood" in p for p in problems)
    tree[0]["questions"][1]["conditions"] = library.when_in("iso", "yes")
    assert ql.structure_problems(versions.normalise_tree(tree)) == []


def test_nothing_is_locked_before_the_first_submission():
    a, _q, _by_q = _returned_round()
    a.submitted_at = None
    assert wf.reopened_questions(a) is None
