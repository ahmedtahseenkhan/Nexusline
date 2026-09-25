"""Decisions 6, 7 and 8 (2026-09-17), and the Phase-0 follow-up on `review_risk()`.

* **6 — attestation needs approval.** Only a record whose approval is complete can be
  attested: draft and in review are refused ("Approve this <type> before attesting it"),
  retired is final, and a type with no approval lifecycle keeps the old rule. The same
  gate decides what My Work asks for and which overdue-attestation alerts are raised.
* **Phase 0 follow-up.** `POST /risks/{id}/review` *is* the risk's attestation: it runs
  the attest call's gates and writes one attestation, which alone moves the review dates
  (one clock, D-05b), audited once as ``review``.
* **7 — test counts are reviewed-only.** "Tested" means a test a reviewer signed off;
  tests awaiting review are counted and named apart, everywhere a rating, a count or an
  examiner's export is shown (the control read, the SoA, a clause's control health).
* **8 — control classification defaults** are the four ISO/IEC 27002:2022 themes, seeded
  for new and existing organisations; a control that says which theme it belongs to is
  classified by the start-up repair, once, and never against an admin's decision.

No database: pure rules are called directly and the endpoints with fake sessions, the
pattern of ``test_attestations`` / ``test_record_page_backend_a``.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import attestations as att
from app.api.v1 import risks as risks_api
from app.core.config import settings
from app.db import data_repairs as dr
from app.db.lookup_seed import DEFAULT_LOOKUPS, missing_defaults
from app.models.attestation import Attestation
from app.models.base import WorkflowState
from app.models.compliance import Requirement
from app.models.control import Control, ControlAudit
from app.models.enums import (
    AuditFindingStatus,
    ControlEffectiveness,
    ControlStatus,
    ReviewFrequency,
    RiskStatus,
    TestResult,
)
from app.models.risk import Risk
from app.schemas.control import REVIEW_PENDING, REVIEW_REVIEWED, ControlRead
from app.services import audit, record_workflow
from app.services import notifications, soa_export

ME = uuid.uuid4()
OTHER = uuid.uuid4()
TENANT = uuid.uuid4()
TODAY = date.today()


def _user(*perms, uid=ME):
    return SimpleNamespace(id=uid, tenant_id=TENANT, email="me@bank.pk", permission_codes=list(perms))


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeDB:
    """Answers the attestation endpoints: the record, its history and the maker."""

    def __init__(self, record=None, maker=None, history=()):
        self.record = record
        self.maker = maker
        self.history = list(history)
        self.added: list = []

    async def get(self, model, _id):
        return self.record if isinstance(self.record, model) else None

    async def scalar(self, stmt, *a, **k):
        return self.maker if "audit_logs" in str(stmt) else None

    async def scalars(self, stmt, *a, **k):
        return _Rows(self.history if "FROM attestations" in str(stmt) else [])

    def add(self, obj):
        if isinstance(obj, Attestation):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)
            self.history.insert(0, obj)
        self.added.append(obj)

    async def flush(self):
        return None


@pytest.fixture
def sod_off(monkeypatch):
    """Four eyes is a separate gate with its own tests; these pin the approval one."""
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", False)


@pytest.fixture
def audited(monkeypatch):
    calls: list[dict] = []

    async def _record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit, "record", _record)
    return calls


def _risk(**kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, title="Ransomware", reference="R-002",
        status=RiskStatus.assessed, workflow_status=WorkflowState.approved, owner_id=OTHER,
        review_frequency=ReviewFrequency.quarterly, next_review_date=TODAY - timedelta(days=5),
    )
    base.update(kw)
    return Risk(**base)


# ======================================================================= decision 6 ===
def test_only_a_complete_approval_lets_a_record_be_attested():
    assert att.approval_refusal("approved", "control") is None
    #: A type with no approval lifecycle is judged on the older rules alone.
    assert att.approval_refusal(None, "control") is None
    code, text = att.approval_refusal("draft", "control")
    assert (code, text) == (409, "Approve this control before attesting it — its approval is draft.")
    assert att.approval_refusal("in_review", "risk")[1] == (
        "Approve this risk before attesting it — its approval is in review."
    )
    assert att.approval_refusal("retired", "policy") == (
        409, "This policy is retired, so it can't be attested.",
    )


def test_the_approval_state_comes_from_the_lifecycle_registry():
    """Only a record whose table carries ``workflow_status`` has an approval to complete."""
    assert att.approval_state(_risk()) == "approved"
    assert att.approval_state(_risk(workflow_status=WorkflowState.in_review)) == "in_review"
    assert att.approval_state(None) is None
    # A plain object is not a mapped record: no approval, so no new refusal.
    assert att.approval_state(SimpleNamespace(workflow_status="draft")) is None


def test_a_type_with_an_approval_workflow_is_judged_on_its_approval():
    """2026-09-25: for a type registered for approval the approval state is the gate — a
    risk's business Draft (not yet assessed) is not an approval stage, so it no longer
    answers first with "submit it for review"."""
    refusal = att.attest_refusal(
        attester_id=ME, owner_id=OTHER, workflow_status=RiskStatus.draft, approval="draft", label="risk",
    )
    assert refusal == (409, "Approve this risk before attesting it — its approval is draft.")
    assert att.attest_refusal(
        attester_id=ME, owner_id=OTHER, workflow_status=RiskStatus.draft, approval="approved", label="risk",
    ) is None
    # Without an approval workflow, the record's own draft status still decides.
    assert att.attest_refusal(workflow_status=RiskStatus.draft, approval=None) == (409, att.DRAFT_REFUSAL)


def test_the_owner_hears_the_approval_rule_like_anyone_else():
    """Decision 9 removed the owner refusal, so the owner of an assessed risk awaiting
    approval is told what actually stands in the way."""
    assert att.attest_refusal(
        attester_id=ME, owner_id=ME, workflow_status=RiskStatus.assessed, approval="draft", label="risk",
    ) == (409, "Approve this risk before attesting it — its approval is draft.")


async def test_an_assessed_risk_awaiting_approval_cannot_be_attested(sod_off):
    risk = _risk(workflow_status=WorkflowState.in_review)
    ok, why = await att.attest_eligibility(FakeDB(), _user("risk:write"), "risk", risk.id, risk)
    assert (ok, why) == (False, "Approve this risk before attesting it — its approval is in review.")


async def test_the_attest_call_refuses_it_with_the_same_words(sod_off, audited):
    from app.schemas.attestation import AttestationCreate

    risk = _risk(workflow_status=WorkflowState.draft, status=RiskStatus.assessed)
    with pytest.raises(HTTPException) as exc:
        await att.attest(
            "risk", risk.id, AttestationCreate(), FakeDB(record=risk), _user("risk:read", "risk:write"),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "Approve this risk before attesting it — its approval is draft."
    assert audited == []


async def test_an_approved_record_is_still_attestable(sod_off, audited):
    from app.schemas.attestation import AttestationCreate

    risk = _risk()
    db = FakeDB(record=risk)
    body = await att.attest("risk", risk.id, AttestationCreate(), db, _user("risk:read", "risk:write"))
    assert body.status == "current"
    assert any(isinstance(o, Attestation) for o in db.added)


def test_the_work_list_asks_for_the_approval_instead_of_the_attestation():
    assert record_workflow.approval_complete(WorkflowState.approved) is True
    assert record_workflow.approval_complete(None) is True
    assert record_workflow.attest_work_note(WorkflowState.approved) is None
    assert record_workflow.attest_work_note(WorkflowState.draft) == (
        "Submit it for approval: it can't be attested until approved"
    )
    assert record_workflow.attest_work_note("in_review") == (
        "Awaiting approval: it can't be attested until approved"
    )
    # A retired record owes nothing at all; callers drop it rather than word it.
    assert record_workflow.attest_work_note(WorkflowState.retired) is None


async def test_my_work_names_the_approval_step_on_an_unapproved_review():
    from app.services import my_work

    policy_id, vendor_id = uuid.uuid4(), uuid.uuid4()
    due = TODAY - timedelta(days=3)
    answers = [
        [(policy_id, "POL-001", "Access control", due, WorkflowState.draft)],
        [(vendor_id, "AWS", due, WorkflowState.approved)],
        [],  # assets
        [],  # attestations of the other record types
        [],  # decision 9: none of them is awaiting a second signature
    ]

    class DB:
        def __init__(self, scripted):
            self.answers = list(scripted)

        async def execute(self, _stmt):
            return _Rows(self.answers.pop(0))

    ctx = my_work.Ctx(
        user_id=ME, email="me@bank.pk", permissions=set(), role_names=set(), role_ids=set(),
        today=TODAY, horizon=TODAY + timedelta(days=30),
    )
    items = await my_work.my_attestations(DB(answers), ctx)
    assert [i.subtitle for i in items] == [
        "Submit it for approval: it can't be attested until approved", "Third-party review",
    ]


async def test_no_overdue_attestation_alert_for_a_record_awaiting_approval():
    """The scan drops what the attest call would refuse; the record page asks for the
    approval instead."""
    good, blocked = uuid.uuid4(), uuid.uuid4()

    class DB:
        async def execute(self, _stmt):
            return _Rows([(good, WorkflowState.approved), (blocked, WorkflowState.draft)])

    out = await notifications.attestation_blocked_records(DB(), [("control", good), ("control", blocked)])
    assert out == {("control", blocked)}


async def test_a_type_without_an_approval_workflow_is_never_blocked():
    class DB:
        async def execute(self, _stmt):  # pragma: no cover - never reached
            raise AssertionError("no query for a type with no lifecycle")

    assert await notifications.attestation_blocked_records(DB(), [("nonsense_type", uuid.uuid4())]) == set()


# ============================================== Phase 0 follow-up: review_risk() ===
async def test_recording_a_risk_review_records_the_attestation(sod_off, audited, monkeypatch):
    risk = _risk()
    db = FakeDB(record=risk)
    monkeypatch.setattr(risks_api, "_load_risk", lambda _db, _id: _wrap(risk))
    monkeypatch.setattr(risks_api, "_read", lambda _db, _id, _user: _wrap("read"))
    monkeypatch.setattr(att, "_native_frequency", lambda *a, **k: _wrap(ReviewFrequency.quarterly))

    assert await risks_api.review_risk(risk.id, db, _user("risk:read", "risk:write")) == "read"
    [row] = [o for o in db.added if isinstance(o, Attestation)]
    assert row.entity_type == "risk" and row.attested_by_id == ME
    assert row.statement == att.DEFAULT_STATEMENTS["risk"]
    # One clock: the attestation moved the risk's dates, and only once.
    assert risk.last_review_date == TODAY
    assert risk.next_review_date == row.next_due
    # One audit row, the review's own verb, carrying the attestation it wrote.
    assert [c["action"] for c in audited] == ["review"]
    assert audited[0]["changes"]["attestation_id"] == str(row.id)


async def test_a_risk_awaiting_approval_cannot_be_reviewed(sod_off, audited, monkeypatch):
    risk = _risk(workflow_status=WorkflowState.draft)
    db = FakeDB(record=risk)
    monkeypatch.setattr(risks_api, "_load_risk", lambda _db, _id: _wrap(risk))
    with pytest.raises(HTTPException) as exc:
        await risks_api.review_risk(risk.id, db, _user("risk:read", "risk:write"))
    assert exc.value.detail == "Approve this risk before attesting it — its approval is draft."
    assert risk.last_review_date is None and audited == []


async def _wrap(value):
    return value


# ======================================================================= decision 7 ===
def _test_row(result, review_status, when):
    return ControlAudit(
        id=uuid.uuid4(), result=result, review_status=review_status, conducted_date=when,
        test_type="operating",
    )


def _control(*tests, **kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, name="MFA on remote access", reference="A.8.13",
        status=ControlStatus.operational, effectiveness=ControlEffectiveness.effective,
    )
    base.update(kw)
    control = Control(**base)
    control.audits = list(tests)
    return control


def test_tested_means_reviewed_and_waiting_tests_are_counted_apart():
    control = _control(
        _test_row(TestResult.passed, REVIEW_REVIEWED, TODAY - timedelta(days=190)),
        _test_row(TestResult.failed, REVIEW_PENDING, TODAY - timedelta(days=2)),
    )
    assert control.audit_count == 2  # the test log, for the Tests tab
    assert control.tested_count == 1
    assert control.pending_review_count == 1
    assert control.last_reviewed_result == TestResult.passed
    # The read exposes it, so every page, list column and export reads the same number.
    assert "tested_count" in ControlRead.model_fields
    assert ControlRead.model_fields["tested_count"].default == 0


def test_a_control_whose_only_test_awaits_review_has_never_been_tested():
    control = _control(_test_row(TestResult.passed, REVIEW_PENDING, TODAY))
    assert (control.tested_count, control.pending_review_count) == (0, 1)
    assert control.last_reviewed_result is None


def test_the_statement_of_applicability_shows_the_last_reviewed_test():
    control = _control(
        _test_row(TestResult.passed, REVIEW_REVIEWED, TODAY - timedelta(days=30)),
        _test_row(TestResult.failed, REVIEW_PENDING, TODAY),
    )
    row = soa_export.control_row(control)
    assert (row.last_test_date, row.last_test_result) == (TODAY - timedelta(days=30), "passed")
    assert row.pending_review_count == 1
    assert "last reviewed test" in row.label() and "1 test awaiting review" in row.label()


def test_the_soa_row_and_export_carry_the_waiting_tests():
    control = _control(_test_row(TestResult.passed, REVIEW_PENDING, TODAY))
    requirement = SimpleNamespace(
        id=uuid.uuid4(), reference="A.8.13", title="Access control", domain="Annex A",
        treatment=None, status=None, applicability_justification="", coverage="unassessed",
        controls=[control], deleted=False,
    )
    row = soa_export.build_row(requirement)
    assert (row.last_test_date, row.last_test_result) == (None, None)
    assert row.pending_review_count == 1
    assert soa_export.HEADERS[-3:] == [
        "Last reviewed test date", "Last reviewed test result", "Tests awaiting review",
    ]
    assert soa_export.table_rows([row])[0][-1] == 1


def test_a_clause_s_control_health_counts_open_findings_like_the_risk_rollup():
    """Decided 2026-09-17 (spec "Not done" 6): an open finding is a reason not to rely on
    the control, so the clause it backs is not healthy either."""
    tested = _control(_test_row(TestResult.passed, REVIEW_REVIEWED, TODAY - timedelta(days=10)))
    tested.audit_findings = []
    assert Requirement.control_health.fget(SimpleNamespace(controls=[tested])) == "ok"
    tested.audit_findings = [SimpleNamespace(status=AuditFindingStatus.open)]
    assert Requirement.control_health.fget(SimpleNamespace(controls=[tested])) == "issues"
    tested.audit_findings = [SimpleNamespace(status=AuditFindingStatus.closed)]
    assert Requirement.control_health.fget(SimpleNamespace(controls=[tested])) == "ok"
    # A finding raised against the clause itself counts too.
    assert Requirement.control_health.fget(
        SimpleNamespace(controls=[tested], audit_findings=[SimpleNamespace(status=AuditFindingStatus.open)])
    ) == "issues"


def test_a_test_awaiting_review_does_not_make_a_clause_unhealthy():
    control = _control(
        _test_row(TestResult.passed, REVIEW_REVIEWED, TODAY - timedelta(days=10)),
        _test_row(TestResult.failed, REVIEW_PENDING, TODAY),
    )
    control.audit_findings = []
    assert Requirement.control_health.fget(SimpleNamespace(controls=[control])) == "ok"


# ======================================================================= decision 8 ===
def test_the_shipped_classifications_are_the_iso_27002_themes():
    assert [(v.value, v.label) for v in DEFAULT_LOOKUPS["control_classification"]] == [
        ("organizational", "Organizational"), ("people", "People"),
        ("physical", "Physical"), ("technological", "Technological"),
    ]
    assert all(v.description for v in DEFAULT_LOOKUPS["control_classification"])


def test_a_tenant_that_already_has_them_gets_nothing_added():
    existing = [(v.value, v.label) for v in DEFAULT_LOOKUPS["control_classification"]]
    assert missing_defaults("control_classification", existing) == []
    # Typed differently but meaning the same thing still matches.
    assert missing_defaults("control_classification", [("", "organizational"), ("people", "People"),
                                                       ("physical", ""), ("", "Technological")]) == []


async def test_a_value_an_admin_deleted_is_not_re_seeded():
    """A deactivated default keeps its row, so it is never re-added; a *deleted* one is
    remembered from the audit trail (``deleted_values``) and skipped."""
    from app.db.lookup_seed import deleted_values

    class DB:
        async def execute(self, _stmt):
            return _Rows([
                ({"key": "control_classification", "value": "physical"},),
                ({"key": "control_classification", "value": ""},),
                (None,),
            ])

    deleted = await deleted_values(DB())
    assert deleted == {"control_classification": {"physical"}}
    kept = [v.value for v in missing_defaults(
        "control_classification", [(v, "") for v in sorted(deleted["control_classification"])]
    )]
    assert kept == ["organizational", "people", "technological"]


def test_a_control_is_classified_by_the_theme_it_already_states():
    assert dr.theme_of_reference("A.5.1") == "organizational"
    assert dr.theme_of_reference("a 6.3") == "people"
    assert dr.theme_of_reference("A.7.2") == "physical"
    assert dr.theme_of_reference("A.8.13") == "technological"
    # The 2013 edition's clauses and a bank's own references say nothing.
    assert dr.theme_of_reference("A.9.1") is None
    assert dr.theme_of_reference("CTL-2") is None
    # An attribute wins over the reference; conflicting values decide nothing.
    assert dr.theme_for_control(reference="A.8.13", attributes={"theme": ["#Physical"]}) == "physical"
    assert dr.theme_for_control(reference="CTL-2", attributes={"themes": ["People", "Physical"]}) is None
    # Otherwise the clauses it implements, but only when they agree.
    assert dr.theme_for_control(
        reference="CTL-2", attributes=None, clause_references=["A.8.1", "A.8.9"]
    ) == "technological"
    assert dr.theme_for_control(
        reference="CTL-2", attributes=None, clause_references=["A.8.1", "A.5.9"]
    ) is None
    assert dr.theme_for_control(reference="CTL-2", attributes={}, clause_references=[]) is None
