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

from typing import Iterable

from app.models.enums import ControlEffectiveness, TestResult

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
