"""Record-page round 2 integration fixes (reviewer findings on B2, B3).

Pure / fake-session, no database:

* **One reliance rule.** The residual engine (``_control_inputs``), the risk page's
  assurance fields (B2), the control read and the health rollups all judge a linked
  control by ``control_assurance.reliance_note``: a test awaiting review neither
  withholds nor restores reliance until a reviewer decides it, and open audit findings
  are reported wherever they withhold credit.
* **B2 is gated.** Test results and dates reach only a viewer with ``control:read``, the
  open-issue count only one who also holds ``issue:read``.
* **B3 never shows an archived exception** on a risk, control, policy or requirement.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.api.v1 import risks as risks_api
from app.models.compliance import Requirement
from app.models.control import Control, ControlAudit
from app.models.enums import AuditFindingStatus, ControlEffectiveness as E, ControlStatus, TestResult as R
from app.models.policy import Policy
from app.models.risk import Risk
from app.schemas.control import ControlRead
from app.services import control_assurance as ca
from app.services.residual_engine import ResidualPolicySpec, suggest_residual

TODAY = date.today()


def _audit(result, review, when: date, test_type="operating"):
    return ControlAudit(
        id=uuid.uuid4(), result=result, review_status=review, test_type=test_type,
        conducted_date=when, created_at=datetime(when.year, when.month, when.day, 9, tzinfo=timezone.utc),
    )


def _a813(*audits, findings=()):
    """Control A.8.13 as the reviewer set it up: operational, rated effective."""
    c = Control(
        id=uuid.uuid4(), name="Backup & Recovery", reference="A.8.13", status=ControlStatus.operational,
        effectiveness=E.effective, effectiveness_override_reason="", next_audit_date=TODAY + timedelta(days=90),
    )
    c.audits = list(audits)
    c.audit_findings = list(findings)
    return c


def _reviewed_pass_then_pending_fail():
    # Newest first, as ``Control.audits`` loads them (ordered by created_at desc).
    return _a813(
        _audit(R.failed, "pending", TODAY - timedelta(days=10)),
        _audit(R.passed, "reviewed", TODAY - timedelta(days=190)),
    )


# ------------------------------------------------------------- one reliance rule ---
def test_the_engine_and_the_risk_page_read_the_same_last_test():
    control = _reviewed_pass_then_pending_fail()
    risk = SimpleNamespace(controls=[control])
    [engine] = risks_api._control_inputs(risk)
    ref = risks_api.control_assurance_ref(control, control.audits, open_issue_count=0, today=TODAY)
    # A failed test awaiting review is the tester's claim: it withholds nothing yet...
    assert engine.healthy is True and engine.health_note == ""
    assert (ref.last_audit_result, ref.audit_count, ref.pending_review_count) == (R.passed, 1, 1)
    # ...and the page says so rather than "no failed test" beside a withheld credit.
    assert ref.last_audit_date == TODAY - timedelta(days=190)
    # The control's own read carries the same counted view beside its test log.
    assert (control.reviewed_audit_count, control.last_reviewed_result, control.last_reviewed_date) == (
        1, R.passed, TODAY - timedelta(days=190))
    assert (control.audit_count, control.last_audit_result) == (2, R.failed)  # the log: every test
    for name in ("reviewed_audit_count", "last_reviewed_result", "last_reviewed_date", "pending_review_count"):
        assert name in ControlRead.model_fields, name


def test_once_reviewed_the_failure_withholds_credit_everywhere():
    control = _a813(
        _audit(R.passed, "reviewed", TODAY - timedelta(days=190)),
        _audit(R.failed, "reviewed", TODAY - timedelta(days=10)),
    )
    [engine] = risks_api._control_inputs(SimpleNamespace(controls=[control]))
    ref = risks_api.control_assurance_ref(control, control.audits, today=TODAY)
    assert engine.health_note == ca.NOTE_TEST_FAILED
    assert (ref.last_audit_result, ref.pending_review_count) == (R.failed, 0)
    assert Risk.control_health.fget(SimpleNamespace(controls=[control])) == "issues"
    assert Requirement.control_health.fget(SimpleNamespace(controls=[control])) == "issues"
    s = suggest_residual(
        inherent_likelihood=4, inherent_impact=4, controls=risks_api._control_inputs(SimpleNamespace(controls=[control])),
        policy=ResidualPolicySpec(),
    )
    assert any("its last reviewed test failed" in line for line in s.rationale)


def test_a_pending_fail_leaves_the_rollups_as_the_page_shows_them():
    control = _reviewed_pass_then_pending_fail()
    assert Risk.control_health.fget(SimpleNamespace(controls=[control])) == "ok"
    assert Requirement.control_health.fget(SimpleNamespace(controls=[control])) == "ok"


def test_an_open_audit_finding_is_on_the_page_when_it_withholds_credit():
    finding = SimpleNamespace(status=AuditFindingStatus.open)
    closed = SimpleNamespace(status=AuditFindingStatus.closed)
    control = _a813(_audit(R.passed, "reviewed", TODAY - timedelta(days=30)), findings=[finding, closed])
    [engine] = risks_api._control_inputs(SimpleNamespace(controls=[control]))
    ref = risks_api.control_assurance_ref(control, control.audits, today=TODAY)
    assert engine.health_note == ca.NOTE_OPEN_FINDING
    assert ref.open_finding_count == 1


def test_an_overdue_test_is_judged_on_the_same_clock():
    control = _a813(_audit(R.passed, "reviewed", TODAY - timedelta(days=400)))
    control.next_audit_date = TODAY - timedelta(days=5)
    [engine] = risks_api._control_inputs(SimpleNamespace(controls=[control]))
    assert engine.health_note == ca.NOTE_TEST_OVERDUE
    assert risks_api.control_assurance_ref(control, control.audits, today=TODAY).is_audit_overdue is True


# ------------------------------------------------------------------- B2 gating ---
class _FakeDB:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.statements = []

    async def execute(self, stmt, *_a, **_k):
        self.statements.append(stmt)
        rows = self.answers.pop(0) if self.answers else []
        return SimpleNamespace(all=lambda: rows)


def _user(*perms):
    return SimpleNamespace(id=uuid.uuid4(), permission_codes=list(perms))


async def test_a_risk_reader_without_control_read_sees_identity_only():
    control = _reviewed_pass_then_pending_fail()
    db = _FakeDB()
    [ref] = await risks_api._assured_controls(db, [control], _user("risk:read"))
    assert db.statements == []  # no test or issue query at all
    assert (ref.reference, ref.name) == ("A.8.13", "Backup & Recovery")
    assert (ref.effectiveness_basis, ref.audit_count, ref.last_audit_result, ref.open_issue_count) == (
        None, None, None, None)


async def test_the_open_issue_count_needs_issue_read():
    control = _reviewed_pass_then_pending_fail()
    tests = [SimpleNamespace(control_id=control.id, **{k: getattr(a, k) for k in (
        "result", "review_status", "test_type", "conducted_date", "created_at")}) for a in control.audits]
    db = _FakeDB(tests)
    [ref] = await risks_api._assured_controls(db, [control], _user("risk:read", "control:read"))
    assert len(db.statements) == 1  # the tests only: no issue query
    assert (ref.audit_count, ref.last_audit_result, ref.open_issue_count) == (1, R.passed, None)

    db = _FakeDB(tests, [(control.id, 2)])
    [ref] = await risks_api._assured_controls(db, [control], _user("risk:read", "control:read", "issue:read"))
    assert (len(db.statements), ref.open_issue_count) == (2, 2)


# ------------------------------------------------------ B3: archived exceptions ---
def test_archived_exceptions_never_ride_on_a_record():
    for model in (Risk, Control, Policy, Requirement):
        join = str(model.exceptions.property.secondaryjoin)
        assert "exceptions.deleted = false" in join, model.__name__
