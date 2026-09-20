"""Phase 2 §2.2 — the control test workpaper and its four-eyes review (finding F-05).

A conclusive test needs a type, a period (operating tests), a conclusion and evidence;
it starts pending and changes nothing until someone other than its tester, recorder or
editor approves it; approving a failure (or exceptions) opens an issue in the same
transaction. No database: fakes stand in for the session."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import controls as controls_api
from app.api.v1 import evidence as evidence_api
from app.models.control import ControlAudit
from app.models.enums import ControlEffectiveness as E
from app.models.enums import Severity
from app.models.enums import TestResult as R
from app.models.evidence import Evidence
from app.models.identity import User
from app.models.issue import Issue, IssueSource
from app.schemas import control as cs
from app.services import control_assurance as ca
from app.services import dual_control

TODAY = date(2026, 9, 12)
Q3 = dict(period_start=date(2026, 7, 1), period_end=date(2026, 9, 30))


def _body(**kw):
    base = dict(result=R.passed, test_type="operating", conducted_date=TODAY, conclusion="25 of 25 had MFA",
                new_evidence=[{"title": "IAM export"}], **Q3)
    base.update(kw)
    return cs.ControlAuditCreate(**base)


# ================================================================ the schema ===
def test_conclusion_and_the_legacy_result_description_are_one_field():
    a = cs.ControlAuditCreate(result=R.passed, conducted_date=TODAY, result_description="Sampled 25")
    assert a.conclusion == a.result_description == "Sampled 25"
    b = cs.ControlAuditCreate(result=R.passed, conducted_date=TODAY, conclusion="Sampled 30")
    assert b.result_description == "Sampled 30"


def test_a_conclusive_test_needs_a_date_and_a_conclusion():
    with pytest.raises(ValidationError, match="conducted_date"):
        cs.ControlAuditCreate(result=R.failed, conclusion="x")
    with pytest.raises(ValidationError, match="conclusion"):
        cs.ControlAuditCreate(result=R.passed_with_exceptions, conducted_date=TODAY, exceptions_count=1)


def test_the_period_runs_forwards():
    with pytest.raises(ValidationError, match="period_start"):
        _body(period_start=date(2026, 9, 30), period_end=date(2026, 7, 1))


def test_the_sample_is_drawn_from_the_population():
    with pytest.raises(ValidationError, match="sample_size"):
        _body(population_size=10, sample_size=25)
    assert _body(population_size=250, sample_size=25).sample_size == 25
    with pytest.raises(ValidationError):
        _body(sample_size=-1)


def test_passed_with_exceptions_records_at_least_one_exception():
    with pytest.raises(ValidationError, match="exceptions_count"):
        _body(result=R.passed_with_exceptions)
    assert _body(result=R.passed_with_exceptions, exceptions_count=2).exceptions_count == 2


def test_the_sample_method_is_one_of_the_known_methods():
    assert _body(sample_method="random").sample_method == "random"
    with pytest.raises(ValidationError):
        _body(sample_method="eyeballed")


def _problems(**kw):
    base = dict(test_type="operating", period_start=Q3["period_start"], period_end=Q3["period_end"], evidence_count=1)
    base.update(kw)
    return cs.workpaper_problems(kw.pop("result", R.passed), **{k: v for k, v in base.items() if k != "result"})


def test_a_complete_workpaper_has_no_problems():
    assert _problems() == []


def test_a_conclusive_result_says_what_kind_of_test_it_was():
    assert any("test_type" in p for p in _problems(test_type=None))


def test_an_operating_test_covers_a_period_and_a_design_test_need_not():
    assert any("period" in p for p in _problems(period_start=None))
    assert _problems(test_type="design", period_start=None, period_end=None) == []


def test_a_conclusive_result_needs_evidence():
    assert any("evidence" in p for p in _problems(evidence_count=0))


def test_a_placeholder_needs_nothing():
    assert cs.workpaper_problems(R.not_assessed, test_type=None, period_start=None, period_end=None,
                                 evidence_count=0) == []


def test_a_return_says_why():
    with pytest.raises(ValidationError, match="note"):
        cs.ControlTestReview(decision="return", note=" ")
    assert cs.ControlTestReview(decision="approve").note == ""


# =========================================================== review eligibility ===
ME, TESTER = uuid.uuid4(), uuid.uuid4()


def _pending(result=R.passed):
    return SimpleNamespace(review_status="pending", result=result)


def test_an_independent_holder_of_control_test_may_review():
    assert controls_api.review_eligibility(_pending(), holds=True, sod_required=True, makers={TESTER}, user_id=ME) == (True, "")


def test_the_tester_recorder_or_editor_may_not_review_their_own_test():
    ok, why = controls_api.review_eligibility(_pending(), holds=True, sod_required=True, makers={ME}, user_id=ME)
    assert not ok and "independent reviewer" in why


def test_with_segregation_of_duties_off_the_maker_may_review():
    assert controls_api.review_eligibility(_pending(), holds=True, sod_required=False, makers={ME}, user_id=ME)[0]


def test_only_a_pending_test_with_a_result_and_a_permission_holder():
    assert controls_api.review_eligibility(SimpleNamespace(review_status="reviewed", result=R.passed),
                                           holds=True, sod_required=True, makers=set(), user_id=ME) == (False, "")
    assert "no result" in controls_api.review_eligibility(_pending(R.not_assessed), holds=True, sod_required=True,
                                                          makers=set(), user_id=ME)[1]
    assert "control:test" in controls_api.review_eligibility(_pending(), holds=False, sod_required=True,
                                                             makers=set(), user_id=ME)[1]


# ============================================================ issue raised ===
@pytest.mark.parametrize("result, is_key, severity", [
    (R.failed, True, Severity.high),
    (R.failed, False, Severity.medium),
    (R.passed_with_exceptions, True, Severity.medium),
    (R.passed_with_exceptions, False, Severity.low),
])
def test_the_issue_is_as_serious_as_the_control_that_failed(result, is_key, severity):
    assert ca.issue_severity(result, is_key) == severity


def test_the_issue_title_names_the_control():
    assert ca.issue_title(R.failed, "A.8.5", "Secure authentication") == "Control test failed: A.8.5 Secure authentication"
    assert ca.issue_title(R.passed_with_exceptions, "", "MFA").startswith("Control test found exceptions: MFA")


# ======================================================= endpoints, faked ===
class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeDB:
    """The slice of AsyncSession the control-test endpoints use."""

    def __init__(self, users=(), tests=(), evidence=(), open_issue=False):
        self.users = {u.id: u for u in users}
        self.tests = list(tests)
        self.evidence = list(evidence)
        self.open_issue = open_issue
        self.added: list = []
        self.executed: list = []

    async def get(self, model, key):
        if model is User:
            return self.users.get(key)
        return None

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, ControlAudit):
            obj.created_at = datetime(2026, 9, 12, 12)
            self.tests.append(obj)
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def scalars(self, stmt, *_a, **_k):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is ControlAudit:
            return _Result(self.tests)
        if entity is Evidence:
            return _Result(self.evidence)
        if entity is User:
            return _Result(self.users.values())
        return _Result([])

    async def scalar(self, stmt):  # has_open_issue
        return uuid.uuid4() if self.open_issue else None

    async def execute(self, stmt, *a, **k):
        self.executed.append(stmt)
        return _Result([])


def _user(uid=None):
    return SimpleNamespace(id=uid or uuid.uuid4(), tenant_id=uuid.uuid4(), email="t@bank.pk",
                           full_name="Tess Tester", is_active=True, permission_codes=["control:test"])


def _control(**kw):
    base = dict(id=uuid.uuid4(), tenant_id=uuid.uuid4(), reference="A.8.5", name="Secure authentication",
                status=None, audit_frequency=None, last_audit_date=None, next_audit_date=None,
                effectiveness=E.effective, design_effectiveness=E.not_assessed,
                operating_effectiveness=E.not_assessed, effectiveness_override_reason="",
                is_key=False, owner_id=None, owner="", audits=[])
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def wired(monkeypatch):
    """Route the endpoint's collaborators to fakes; returns the audit calls."""
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    async def fresh(db, control_id):
        return state["control"]

    async def read(db, control):
        return control

    async def no_sod(*a, **k):
        return None

    async def not_required(db, module, action, amount=None):
        return False, None

    state: dict = {}
    monkeypatch.setattr(controls_api.audit_log, "record", record)
    monkeypatch.setattr(controls_api, "_fresh", fresh)
    monkeypatch.setattr(controls_api, "_read", read)
    monkeypatch.setattr(dual_control, "enforce_record_maker_checker", no_sod)
    monkeypatch.setattr(dual_control, "dual_control_required", not_required)

    def use(control):
        state["control"] = control

        async def get(db, control_id):
            return control

        monkeypatch.setattr(controls_api, "_get_or_404", get)
        return control

    return SimpleNamespace(calls=calls, use=use)


async def test_a_conclusive_test_without_evidence_is_refused_before_anything_is_written(wired):
    control = wired.use(_control())
    db = FakeDB()
    body = cs.ControlAuditCreate(result=R.passed, test_type="operating", conducted_date=TODAY,
                                 conclusion="All good", **Q3)
    with pytest.raises(HTTPException) as exc:
        await controls_api.record_control_audit(control.id, body, db, _user())
    assert exc.value.status_code == 422 and "evidence" in exc.value.detail
    assert db.added == [] and wired.calls == []


async def test_a_recorded_test_waits_for_review_and_changes_no_rating(wired):
    control = wired.use(_control(effectiveness=E.not_assessed))
    me = _user()
    db = FakeDB(users=[me])
    await controls_api.record_control_audit(control.id, _body(), db, me)
    test = next(o for o in db.added if isinstance(o, ControlAudit))
    ev = next(o for o in db.added if isinstance(o, Evidence))
    assert test.review_status == "pending" and test.tested_by_id == me.id  # the recorder tested it
    assert test.conclusion == test.result_description == "25 of 25 had MFA"
    assert ev.control_audit_id == test.id and ev.control_id == control.id and ev.collected_at == TODAY
    assert control.effectiveness == E.not_assessed  # nothing moves until review
    assert control.last_audit_date == TODAY  # the test clock does
    kinds = {(c["entity_type"], c["action"]) for c in wired.calls}
    assert ("control_audit", "create") in kinds and ("control", "audit") in kinds


async def test_existing_evidence_is_cited_only_from_the_same_control_and_once(wired):
    control = wired.use(_control())
    me = _user()
    other_control = Evidence(id=uuid.uuid4(), control_id=uuid.uuid4(), title="Someone else's", control_audit_id=None)
    body = _body(new_evidence=[], evidence_ids=[other_control.id])
    with pytest.raises(HTTPException, match="another control"):
        await controls_api.record_control_audit(control.id, body, FakeDB(users=[me], evidence=[other_control]), me)
    taken = Evidence(id=uuid.uuid4(), control_id=control.id, title="Q2 export", control_audit_id=uuid.uuid4())
    body = _body(new_evidence=[], evidence_ids=[taken.id])
    with pytest.raises(HTTPException, match="already supports another test"):
        await controls_api.record_control_audit(control.id, body, FakeDB(users=[me], evidence=[taken]), me)
    free = Evidence(id=uuid.uuid4(), control_id=control.id, title="Q3 export", control_audit_id=None)
    body = _body(new_evidence=[], evidence_ids=[free.id])
    db = FakeDB(users=[me], evidence=[free])
    await controls_api.record_control_audit(control.id, body, db, me)
    assert free.control_audit_id == next(o for o in db.added if isinstance(o, ControlAudit)).id


def _stored_test(control, result=R.failed, review="pending", tester=None, **kw):
    base = dict(id=uuid.uuid4(), control_id=control.id, result=result, test_type="operating",
                review_status=review, tested_by_id=tester or TESTER, conducted_date=TODAY,
                created_at=datetime(2026, 9, 12, 9), raised_issue_id=None, reviewed_by_id=None,
                reviewed_at=None, review_note="", conclusion="3 of 25 lacked MFA",
                result_description="3 of 25 lacked MFA", exceptions_count=3, exceptions_detail="",
                period_start=Q3["period_start"], period_end=Q3["period_end"], sample_size=25,
                population_size=400)
    base.update(kw)
    return SimpleNamespace(**base)


def _use_test(monkeypatch, test, makers=None):
    async def get_test(db, control_id, audit_id):
        return test

    async def makers_by_test(db, tests):
        return {t.id: set(makers if makers is not None else {t.tested_by_id}) for t in tests}

    monkeypatch.setattr(controls_api, "_test_or_404", get_test)
    monkeypatch.setattr(controls_api, "_makers_by_test", makers_by_test)


async def test_the_tester_cannot_approve_their_own_test(wired, monkeypatch):
    control = wired.use(_control())
    me = _user()
    test = _stored_test(control, tester=me.id)
    _use_test(monkeypatch, test)

    async def required(db, module, action, amount=None):
        assert (module, action) == ("control", "review_test")
        return True, None

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    with pytest.raises(HTTPException) as exc:
        await controls_api.review_control_audit(control.id, test.id, cs.ControlTestReview(decision="approve"), FakeDB(), me)
    assert exc.value.status_code == 403
    assert test.review_status == "pending"


async def test_whoever_recorded_or_edited_it_cannot_approve_it_either(wired, monkeypatch):
    control = wired.use(_control())
    me = _user()
    test = _stored_test(control)  # someone else tested it; I recorded it
    _use_test(monkeypatch, test, makers={TESTER, me.id})

    async def required(db, module, action, amount=None):
        return True, None

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    with pytest.raises(HTTPException):
        await controls_api.review_control_audit(control.id, test.id, cs.ControlTestReview(decision="approve"), FakeDB(), me)


async def test_approving_a_failed_key_control_test_opens_a_high_issue_and_rates_the_control(wired, monkeypatch):
    owner = _user()
    control = wired.use(_control(is_key=True, owner_id=owner.id, effectiveness=E.effective,
                                 effectiveness_override_reason="Rated by hand last year"))
    test = _stored_test(control)
    _use_test(monkeypatch, test)

    async def next_ref(db, model, prefix, width=3):
        assert model is Issue and prefix == "ISS"
        return "ISS-042"

    monkeypatch.setattr(controls_api, "next_reference", next_ref)
    db = FakeDB(users=[owner], tests=[test])
    reviewer = _user()
    await controls_api.review_control_audit(control.id, test.id, cs.ControlTestReview(decision="approve", note="Agreed"), db, reviewer)

    assert test.review_status == "reviewed" and test.reviewed_by_id == reviewer.id and test.reviewed_at
    issue = next(o for o in db.added if isinstance(o, Issue))
    assert issue.reference == "ISS-042" and test.raised_issue_id == issue.id
    assert issue.title == "Control test failed: A.8.5 Secure authentication"
    assert issue.severity == Severity.high and issue.owner_id == owner.id and issue.owner == "Tess Tester"
    assert issue.source_type == IssueSource.assessment and issue.source_id == control.id
    assert any("issue_controls" in str(s) for s in db.executed)  # linked to the control
    # the reviewed failure rates the control, and replaces the hand rating
    assert (control.operating_effectiveness, control.effectiveness) == (E.ineffective, E.ineffective)
    assert control.effectiveness_override_reason == ""
    assert {("issue", "create"), ("control_audit", "review"), ("control", "review_test")} <= {
        (c["entity_type"], c["action"]) for c in wired.calls
    }


async def test_approving_a_pass_rates_the_control_and_opens_nothing(wired, monkeypatch):
    control = wired.use(_control(effectiveness=E.not_assessed))
    test = _stored_test(control, result=R.passed, exceptions_count=0)
    _use_test(monkeypatch, test)
    db = FakeDB(tests=[test])
    await controls_api.review_control_audit(control.id, test.id, cs.ControlTestReview(decision="approve"), db, _user())
    assert control.effectiveness == E.effective and test.raised_issue_id is None
    assert not any(isinstance(o, Issue) for o in db.added)


async def test_approving_a_pass_while_an_issue_is_open_rates_it_partially(wired, monkeypatch):
    control = wired.use(_control(effectiveness=E.not_assessed))
    test = _stored_test(control, result=R.passed, exceptions_count=0)
    _use_test(monkeypatch, test)
    await controls_api.review_control_audit(control.id, test.id, cs.ControlTestReview(decision="approve"),
                                            FakeDB(tests=[test], open_issue=True), _user())
    assert control.operating_effectiveness == E.partially_effective


async def test_returning_a_test_sends_it_back_with_the_note_and_changes_nothing(wired, monkeypatch):
    control = wired.use(_control(effectiveness=E.effective))
    test = _stored_test(control)
    _use_test(monkeypatch, test)
    db = FakeDB(tests=[test])
    await controls_api.review_control_audit(control.id, test.id,
                                            cs.ControlTestReview(decision="return", note="Attach the sample list"), db, _user())
    assert test.review_status == "returned" and test.review_note == "Attach the sample list"
    assert control.effectiveness == E.effective and not db.added


async def test_only_a_pending_test_can_be_decided(wired, monkeypatch):
    control = wired.use(_control())
    test = _stored_test(control, review="reviewed")
    _use_test(monkeypatch, test)
    with pytest.raises(HTTPException) as exc:
        await controls_api.review_control_audit(control.id, test.id, cs.ControlTestReview(decision="approve"), FakeDB(), _user())
    assert exc.value.status_code == 409


async def test_a_placeholder_cannot_be_approved(wired, monkeypatch):
    control = wired.use(_control())
    test = _stored_test(control, result=R.not_assessed)
    _use_test(monkeypatch, test)
    with pytest.raises(HTTPException) as exc:
        await controls_api.review_control_audit(control.id, test.id, cs.ControlTestReview(decision="approve"), FakeDB(), _user())
    assert exc.value.status_code == 422


async def test_a_reviewed_test_is_signed_off_and_cannot_be_edited(wired, monkeypatch):
    control = wired.use(_control())
    test = _stored_test(control, review="reviewed")
    _use_test(monkeypatch, test)
    with pytest.raises(HTTPException) as exc:
        await controls_api.update_control_audit(control.id, test.id, _body(), FakeDB(), _user())
    assert exc.value.status_code == 409


async def test_a_returned_test_is_edited_and_resubmitted(wired, monkeypatch):
    control = wired.use(_control())
    me = _user()
    test = _stored_test(control, review="returned", tester=me.id, reviewed_by_id=uuid.uuid4())
    _use_test(monkeypatch, test)
    db = FakeDB(users=[me])
    await controls_api.update_control_audit(control.id, test.id, _body(result=R.failed, conclusion="Now with the list"), db, me)
    assert test.review_status == "pending" and test.reviewed_by_id is None
    assert test.conclusion == "Now with the list" and test.result == R.failed
    assert any(c["entity_type"] == "control_audit" and c["action"] == "update" for c in wired.calls)


# ============================================================ evidence side ===
async def test_evidence_of_a_signed_off_test_cannot_be_deleted(monkeypatch):
    ev = SimpleNamespace(id=uuid.uuid4(), title="IAM export", control_audit_id=uuid.uuid4())

    async def get_ev(db, evidence_id):
        return ev

    async def signed_off(db, audit_id):
        return True

    monkeypatch.setattr(evidence_api, "_evidence_or_404", get_ev)
    monkeypatch.setattr(evidence_api, "_is_signed_off", signed_off)
    with pytest.raises(HTTPException) as exc:
        await evidence_api.delete_evidence(ev.id, FakeDB(), _user())
    assert exc.value.status_code == 409


async def test_evidence_may_only_support_a_test_of_its_own_control():
    control_id = uuid.uuid4()
    other = SimpleNamespace(control_id=uuid.uuid4())

    class DB:
        async def get(self, model, key):
            return other

    with pytest.raises(HTTPException) as exc:
        await evidence_api._test_of(DB(), control_id, uuid.uuid4())
    assert exc.value.status_code == 422
    assert await evidence_api._test_of(DB(), control_id, None) is None


def test_evidence_shows_the_test_it_supports():
    from app.schemas.evidence import EvidenceCreate, EvidenceRead, EvidenceUpdate

    assert "control_audit_id" in EvidenceCreate.model_fields and "control_audit_id" in EvidenceUpdate.model_fields
    assert {"control_audit_id", "control_audit"} <= set(EvidenceRead.model_fields)
    assert {"id", "result", "test_type", "conducted_date", "review_status"} <= set(cs.ControlTestRef.model_fields)


def test_the_test_read_shows_the_workpaper_and_its_review():
    fields = set(cs.ControlAuditRead.model_fields)
    assert {"test_type", "period_start", "period_end", "population_size", "sample_size", "sample_method",
            "exceptions_count", "exceptions_detail", "conclusion", "review_status", "reviewed_by_ref",
            "reviewed_at", "review_note", "raised_issue", "evidence", "can_review", "can_edit"} <= fields


def test_review_test_is_a_documented_dual_control_action():
    assert "review_test" in dual_control.__doc__
