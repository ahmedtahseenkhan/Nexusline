"""The turnaround-time clock: when a record is on track, at risk, or breached.

The point of this feature is that a missed remediation deadline is noticed *before* an
auditor counts. Two things therefore have to hold: the early warning must fire while
there is still time to act, and the fall-back targets must be real numbers — a fresh
installation with nothing configured has to measure something, or the clock silently
does not exist.
"""
from datetime import date, timedelta

import pytest

from app.core.permissions import ALL_PERMISSIONS
from app.models.enums import Severity
from app.services.sla import (
    AT_RISK,
    BREACHED,
    DEFAULT_TARGETS,
    DEFAULT_WARN_PERCENT,
    ENTITIES,
    ON_TRACK,
    due_from,
    state_of,
    target_for,
)

TODAY = date(2026, 8, 12)


def _started(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


# ------------------------------------------------------------------ windows ---
def test_due_date_is_the_start_plus_the_target():
    assert due_from(date(2026, 1, 1), 15) == date(2026, 1, 16)


def test_a_record_with_no_window_is_never_late():
    """No policy and no default (a severity nobody targets) means no clock, not a breach."""
    result = state_of(_started(400), None, today=TODAY)
    assert result.state == ON_TRACK
    assert result.due is None


def test_fresh_record_is_on_track():
    started = _started(1)
    assert state_of(started, due_from(started, 30), today=TODAY).state == ON_TRACK


def test_early_warning_fires_before_the_deadline_not_on_it():
    """An alert that only arrives on the day of breach is a report, not a control."""
    started = _started(24)  # 24 of 30 days elapsed = 80%
    result = state_of(started, due_from(started, 30), today=TODAY)
    assert result.state == AT_RISK
    assert result.days_remaining == 6


def test_just_below_the_warning_threshold_is_still_on_track():
    started = _started(23)  # 76.7%
    assert state_of(started, due_from(started, 30), today=TODAY).state == ON_TRACK


def test_the_warning_threshold_is_configurable():
    started = _started(15)  # 50%
    assert state_of(started, due_from(started, 30), today=TODAY).state == ON_TRACK
    assert state_of(started, due_from(started, 30), today=TODAY, warn_at_percent=50).state == AT_RISK


def test_the_day_it_falls_due_is_not_yet_a_breach():
    started = _started(30)
    result = state_of(started, due_from(started, 30), today=TODAY)
    assert result.state == AT_RISK
    assert result.days_remaining == 0


def test_the_day_after_is_a_breach():
    started = _started(31)
    result = state_of(started, due_from(started, 30), today=TODAY)
    assert result.state == BREACHED
    assert result.days_remaining == -1


def test_days_overdue_keeps_counting():
    started = _started(45)
    assert state_of(started, due_from(started, 30), today=TODAY).days_remaining == -15


def test_a_same_day_window_is_at_risk_on_the_day():
    """A one-day incident TAT has no room for a percentage warning; flag it immediately."""
    started = TODAY
    result = state_of(started, due_from(started, 0), today=TODAY)
    assert result.state == AT_RISK


def test_state_without_a_start_date_still_detects_a_breach():
    """A missing start only costs the early warning, never the breach itself."""
    assert state_of(None, TODAY - timedelta(days=1), today=TODAY).state == BREACHED
    assert state_of(None, TODAY + timedelta(days=5), today=TODAY).state == ON_TRACK


# ------------------------------------------------------------------ targets ---
def test_an_unconfigured_scope_uses_the_shipped_default():
    target, warn, role = target_for({}, "risk", Severity.critical)
    assert target == DEFAULT_TARGETS["risk"][Severity.critical]
    assert warn == DEFAULT_WARN_PERCENT
    assert role == ""


def test_a_configured_scope_wins():
    class _Policy:
        target_days, warn_at_percent, escalate_to_role, enabled = 5, 60, "CRO", True

    target, warn, role = target_for({("risk", Severity.high): _Policy()}, "risk", Severity.high)
    assert (target, warn, role) == (5, 60, "CRO")


def test_a_disabled_policy_switches_the_clock_off_for_that_scope():
    """Disabling must mean 'no clock', not 'fall back to the default' — otherwise a bank
    that deliberately excludes low-severity findings still gets chased about them."""
    class _Policy:
        target_days, warn_at_percent, escalate_to_role, enabled = 90, 80, "", False

    target, _warn, _role = target_for({("risk", Severity.low): _Policy()}, "risk", Severity.low)
    assert target is None


@pytest.mark.parametrize("entity_type", list(ENTITIES))
def test_every_record_type_has_a_default_for_every_severity(entity_type):
    """A severity with no default is a record type the clock silently ignores."""
    targets = DEFAULT_TARGETS[entity_type]
    for severity in (Severity.critical, Severity.high, Severity.medium, Severity.low):
        assert targets.get(severity), f"{entity_type}/{severity.value} has no default"


@pytest.mark.parametrize("entity_type", list(ENTITIES))
def test_defaults_get_looser_as_severity_falls(entity_type):
    targets = DEFAULT_TARGETS[entity_type]
    assert (
        targets[Severity.critical]
        <= targets[Severity.high]
        <= targets[Severity.medium]
        <= targets[Severity.low]
    ), f"{entity_type} targets are not ordered by severity"


def test_incidents_are_measured_in_days_not_months():
    """Incident TAT is response time; borrowing the remediation defaults would make the
    clock meaningless there."""
    assert DEFAULT_TARGETS["incident"][Severity.critical] <= 2
    assert DEFAULT_TARGETS["incident"][Severity.low] < DEFAULT_TARGETS["risk"][Severity.low]


# ------------------------------------------------------------------ registry ---
def test_every_entity_declares_a_complete_spec():
    for key, spec in ENTITIES.items():
        assert spec.key == key
        assert spec.label.strip()
        assert spec.link.startswith("/")
        assert hasattr(spec.model, "tat_due_date"), f"{key} has no TAT column"
        assert hasattr(spec.model, "tat_breached_at"), f"{key} has no breach column"


def test_the_sla_permission_exists():
    assert "sla:manage" in ALL_PERMISSIONS
