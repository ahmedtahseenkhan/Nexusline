"""What a control test means for the control — and what a control means for a clause.

Two small rules, kept pure so they are testable and so the register, the residual
engine and the compliance gap analysis all read the same answer:

* **A recorded test sets effectiveness.** Recording *passed* and then separately
  editing the control to say *effective* is two steps where one is the record; in
  practice the second step was skipped and every control stayed *not assessed*
  forever, which starved the residual suggestion. The result drives effectiveness —
  *passed* → effective, *failed* → ineffective — and the tester may say
  *partially effective* explicitly when a pass came with findings.
* **A clause is assured by a working control, not by a mapped one.** Installing a
  framework now maps a control to every clause; if mapping alone counted as
  coverage, a freshly installed framework would look covered with nothing behind it.
  Coverage therefore has states — unmapped, unassessed, failing, assured — and only
  the last one is coverage.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from app.models.control import UNTESTABLE_CONTROL_STATUSES
from app.models.enums import ControlEffectiveness, ControlStatus, ReviewFrequency, TestResult
from app.services.risk_scoring import next_review_date

#: Coverage states, weakest to strongest. A clause takes the strongest its controls reach.
UNMAPPED = "unmapped"
UNASSESSED = "unassessed"
FAILING = "failing"
ASSURED = "assured"

_ASSURED = {ControlEffectiveness.effective, ControlEffectiveness.partially_effective}


def effectiveness_after_test(
    result: TestResult,
    override: ControlEffectiveness | None,
    current: ControlEffectiveness,
) -> ControlEffectiveness:
    """The effectiveness a control should carry after a test with this result.

    An explicit ``override`` from the tester wins — "it passed, but only partially".
    Otherwise the result decides. A test recorded as *not assessed* is a placeholder
    (scheduled, not yet performed) and changes nothing.
    """
    if override is not None:
        return override
    if result == TestResult.passed:
        return ControlEffectiveness.effective
    if result == TestResult.failed:
        return ControlEffectiveness.ineffective
    return current


def control_state(effectiveness: ControlEffectiveness | None) -> str:
    """One control's contribution to a clause."""
    if effectiveness in _ASSURED:
        return ASSURED
    if effectiveness == ControlEffectiveness.ineffective:
        return FAILING
    return UNASSESSED


_RANK = {UNMAPPED: 0, UNASSESSED: 1, FAILING: 2, ASSURED: 3}


def coverage_state(effectivenesses: Iterable[ControlEffectiveness | None]) -> str:
    """A clause's coverage from the controls mapped to it: the strongest state any of
    them reaches, or unmapped when there are none."""
    best = UNMAPPED
    for e in effectivenesses:
        state = control_state(e)
        if _RANK[state] > _RANK[best]:
            best = state
    return best


def is_assured(effectivenesses: Iterable[ControlEffectiveness | None]) -> bool:
    return coverage_state(effectivenesses) == ASSURED


#: Effectiveness values that count as assurance, for the SQL side of the gap filter.
ASSURED_EFFECTIVENESS: tuple[ControlEffectiveness, ...] = tuple(_ASSURED)


# ---------------------------------------------------------------------------
# The test clock
# ---------------------------------------------------------------------------
# A planned control has nothing to test: scheduling its first test from the day it was
# written down made every freshly created (or pack-installed) control "due" on day one,
# and flooded the alerts with controls nobody could test yet. The clock starts when the
# control goes live (implemented / operational) and stops when it is retired. The same
# rule drives both cycles — audits (``audit_frequency``) and maintenance
# (``maintenance_frequency``).
def carries_test_clock(status: ControlStatus | None) -> bool:
    """Only an implemented or operational control has a next test / maintenance date."""
    return status not in UNTESTABLE_CONTROL_STATUSES


def next_cycle_date(
    status: ControlStatus,
    frequency: ReviewFrequency,
    *,
    current: date | None = None,
    explicit: date | None = None,
    explicit_given: bool = False,
    frequency_changed: bool = False,
    became_testable: bool = False,
    last_done: date | None = None,
    today: date | None = None,
) -> date | None:
    """The next due date for one cycle of a control after a create or an edit.

    * Planned / retired → ``None``, whatever was sent: an explicit date is ignored.
    * An explicit date wins.
    * A control that has just gone live (new, or planned/retired → implemented /
      operational) is scheduled a cycle from today — not from a test run years ago,
      which would make it overdue the moment it went live, and not from a stale date
      it carried while it had no clock.
    * An explicit *blank* or a changed frequency re-derives from the last time the
      cycle ran (or today).
    * Otherwise the current date stands.
    """
    if not carries_test_clock(status):
        return None
    today = today or date.today()
    if explicit_given and explicit is not None:
        return explicit
    if became_testable:
        return next_review_date(frequency, today)
    if explicit_given or frequency_changed:
        return next_review_date(frequency, last_done or today)
    return current


def after_test_date(status: ControlStatus, frequency: ReviewFrequency, conducted: date) -> date | None:
    """The next due date once a test (or maintenance) has been recorded."""
    if not carries_test_clock(status):
        return None
    return next_review_date(frequency, conducted)


def is_cycle_overdue(status: ControlStatus, due: date | None, today: date | None = None) -> bool:
    """Past its due date — and only for a control that carries a clock at all."""
    return carries_test_clock(status) and due is not None and due < (today or date.today())
