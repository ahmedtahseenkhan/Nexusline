"""A control's test clock runs only while the control is live (D-02).

A planned control was given a next-test date a year from the day it was written down,
so a freshly created catalogue (and every pack install) went "due" and then "overdue"
before anything existed to test — 36 planned controls due on day one, 72 of 80 alerts.
The rule: only implemented / operational controls carry a clock; planned and retired
never do, and are never overdue whatever date an older row still holds.
"""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.models.control import UNTESTABLE_CONTROL_STATUSES, Control
from app.models.enums import ControlStatus, ReviewFrequency
from app.models.enums import TestResult as Result
from app.schemas.control import ControlAuditCreate, control_test_problems
from app.services import control_assurance as ca
from app.services import metrics
from app.services import report_builder as rb
from app.services.risk_scoring import next_review_date

S = ControlStatus
F = ReviewFrequency
TODAY = date(2026, 9, 11)
PAST = date(2026, 1, 1)


def test_untestable_statuses_match_the_startup_repair():
    from app.db import data_repairs

    assert set(UNTESTABLE_CONTROL_STATUSES) == {S.planned, S.retired}
    assert set(data_repairs.UNTESTABLE_CONTROL_STATUSES) == set(UNTESTABLE_CONTROL_STATUSES)


@pytest.mark.parametrize("status,live", [
    (S.planned, False), (S.retired, False), (S.implemented, True), (S.operational, True),
])
def test_only_live_controls_carry_a_clock(status, live):
    assert ca.carries_test_clock(status) is live


# ------------------------------------------------------------------ on create ---
@pytest.mark.parametrize("status", [S.planned, S.retired])
def test_a_new_planned_or_retired_control_gets_no_date(status):
    assert ca.next_cycle_date(status, F.annual, became_testable=True, today=TODAY) is None


@pytest.mark.parametrize("status", [S.planned, S.retired])
def test_an_explicit_date_for_a_planned_control_is_ignored(status):
    got = ca.next_cycle_date(
        status, F.annual, explicit=date(2026, 10, 1), explicit_given=True,
        became_testable=True, today=TODAY,
    )
    assert got is None


@pytest.mark.parametrize("status", [S.implemented, S.operational])
def test_a_new_live_control_is_scheduled_from_its_frequency(status):
    got = ca.next_cycle_date(status, F.quarterly, became_testable=True, today=TODAY)
    assert got == next_review_date(F.quarterly, TODAY)


def test_an_explicit_date_wins_for_a_live_control():
    got = ca.next_cycle_date(
        S.operational, F.annual, explicit=date(2026, 12, 31), explicit_given=True,
        became_testable=True, today=TODAY,
    )
    assert got == date(2026, 12, 31)


def test_no_frequency_means_no_date():
    assert ca.next_cycle_date(S.operational, F.none, became_testable=True, today=TODAY) is None


# ------------------------------------------------------------------ on update ---
def test_going_live_starts_the_clock_from_today():
    # planned -> implemented, no date: one cycle from today — not from a test run long
    # ago, which would make it overdue the moment it went live.
    got = ca.next_cycle_date(
        S.implemented, F.annual, current=None, became_testable=True,
        last_done=date(2020, 1, 1), today=TODAY,
    )
    assert got == next_review_date(F.annual, TODAY)


def test_going_live_with_a_blank_date_from_the_form_also_starts_from_today():
    got = ca.next_cycle_date(
        S.operational, F.monthly, current=None, explicit=None, explicit_given=True,
        became_testable=True, last_done=date(2020, 1, 1), today=TODAY,
    )
    assert got == next_review_date(F.monthly, TODAY)


def test_going_live_ignores_a_stale_date_left_from_the_planned_period():
    got = ca.next_cycle_date(
        S.operational, F.quarterly, current=date(2025, 1, 1), became_testable=True, today=TODAY,
    )
    assert got == next_review_date(F.quarterly, TODAY)


@pytest.mark.parametrize("status", [S.planned, S.retired])
def test_moving_back_to_planned_or_retired_clears_the_date(status):
    got = ca.next_cycle_date(
        status, F.annual, current=date(2026, 12, 1), explicit=date(2026, 12, 1),
        explicit_given=True, today=TODAY,
    )
    assert got is None


def test_an_untouched_live_control_keeps_its_date():
    assert ca.next_cycle_date(S.operational, F.annual, current=date(2027, 1, 5), today=TODAY) == date(2027, 1, 5)


def test_a_frequency_change_re_derives_from_the_last_test():
    last = date(2026, 6, 1)
    got = ca.next_cycle_date(
        S.operational, F.quarterly, current=date(2027, 6, 1), frequency_changed=True,
        last_done=last, today=TODAY,
    )
    assert got == next_review_date(F.quarterly, last)


def test_a_blank_explicit_date_re_derives_from_the_last_test():
    last = date(2026, 6, 1)
    got = ca.next_cycle_date(
        S.implemented, F.annual, current=date(2027, 6, 1), explicit=None, explicit_given=True,
        last_done=last, today=TODAY,
    )
    assert got == next_review_date(F.annual, last)


def test_recording_a_test_reschedules_only_a_live_control():
    assert ca.after_test_date(S.operational, F.annual, TODAY) == next_review_date(F.annual, TODAY)
    assert ca.after_test_date(S.planned, F.annual, TODAY) is None
    assert ca.after_test_date(S.retired, F.annual, TODAY) is None


# ------------------------------------------------------------ overdue predicates ---
@pytest.mark.parametrize("status,expected", [
    (S.planned, False), (S.retired, False), (S.implemented, True), (S.operational, True),
])
def test_pure_overdue_rule(status, expected):
    assert ca.is_cycle_overdue(status, PAST, TODAY) is expected
    assert ca.is_cycle_overdue(status, None, TODAY) is False
    assert ca.is_cycle_overdue(status, date(2027, 1, 1), TODAY) is False


def _control(status, next_audit=PAST, next_maint=PAST):
    return Control(
        name="c", status=status, next_audit_date=next_audit, next_maintenance_date=next_maint,
    )


@pytest.mark.parametrize("status", [S.planned, S.retired])
def test_model_never_calls_a_planned_or_retired_control_overdue(status):
    c = _control(status)
    assert c.is_audit_overdue is False
    assert c.is_maintenance_overdue is False


@pytest.mark.parametrize("status", [S.implemented, S.operational])
def test_model_flags_a_live_control_past_its_date(status):
    c = _control(status)
    assert c.is_audit_overdue is True
    assert c.is_maintenance_overdue is True


def test_requirement_control_health_ignores_a_planned_controls_old_date():
    # Requirement.control_health reads Control.is_audit_overdue: a planned control with a
    # stale date must not flip every clause it is mapped to into "issues".
    from app.models.compliance import Requirement

    planned = _control(S.planned)
    live = _control(S.operational)
    assert Requirement.control_health.fget(SimpleNamespace(controls=[planned])) == "ok"
    assert Requirement.control_health.fget(SimpleNamespace(controls=[live])) == "issues"


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_report_builder_overdue_filter_excludes_planned_and_retired():
    ctx = rb.ReportContext(today=TODAY)
    yes = _sql(rb.build_statement(rb.CONTROLS, {"audit_overdue": "true"}, ctx))
    assert "next_audit_date < '2026-09-11'" in yes
    assert "controls.status NOT IN ('planned', 'retired')" in yes
    no = _sql(rb.build_statement(rb.CONTROLS, {"audit_overdue": "false"}, ctx))
    assert "controls.status IN ('planned', 'retired')" in no


def test_metric_overdue_audit_excludes_planned_and_retired():
    import asyncio

    seen = []

    class FakeDb:
        async def scalar(self, stmt):
            seen.append(stmt)
            return 0

    asyncio.run(metrics.compute(FakeDb(), "controls_overdue_audit", tenant_id=None))
    text = _sql(seen[0])
    assert "controls.next_audit_date <" in text
    assert "controls.status NOT IN ('planned', 'retired')" in text


# --------------------------------------------------------- a test needs evidence ---
def test_a_placeholder_test_needs_nothing():
    assert control_test_problems(Result.not_assessed, None, "") == []
    assert ControlAuditCreate().result is Result.not_assessed


@pytest.mark.parametrize("result", [Result.passed, Result.failed])
def test_a_pass_or_fail_needs_a_date_and_a_conclusion(result):
    problems = control_test_problems(result, None, "   ")
    assert len(problems) == 2
    assert any("conducted_date" in p for p in problems)
    assert any("result_description" in p for p in problems)
    with pytest.raises(ValueError, match="conducted_date"):
        ControlAuditCreate(result=result, result_description="Sampled 25 logins, all MFA")
    with pytest.raises(ValueError, match="result_description"):
        ControlAuditCreate(result=result, conducted_date=TODAY, result_description=" ")
    ok = ControlAuditCreate(result=result, conducted_date=TODAY, result_description="Sampled 25 logins")
    assert ok.conducted_date == TODAY
