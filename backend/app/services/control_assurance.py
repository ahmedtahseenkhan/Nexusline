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

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from app.models.control import UNTESTABLE_CONTROL_STATUSES
from app.models.enums import ControlEffectiveness, ControlStatus, ReviewFrequency, Severity, TestResult
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
    return rating_for(result) or current


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


# ---------------------------------------------------------------------------
# Derived effectiveness (Phase 2)
# ---------------------------------------------------------------------------
# A control has two ratings, one per kind of test: *design* (would it work as
# designed?) and *operating* (did it work, over a period, on a sample?). Each comes
# from the latest test of its kind that an independent reviewer has approved — a test
# nobody has reviewed is the tester's claim, not assurance. The combined rating the
# rest of the platform reads (``Control.effectiveness``) is the worse of the two that
# have been assessed. An open issue against the control caps the operating rating at
# partially effective until it is closed: a known, unremediated failure is not an
# effective control, whatever the last sample said.
#
# Tests recorded before reviews existed (review status "legacy") keep their effect:
# they were operating tests of "does the control work", and count as such. A control
# rated by hand before derivation, with no test behind it, keeps that rating ("manual")
# until its first reviewed test. A manual override — the rating set by hand with a
# reason — wins over the derivation until it is dropped or a reviewed test replaces it.

E = ControlEffectiveness

#: A conclusive result -> the rating it supports.
_TEST_RATING: dict[TestResult, ControlEffectiveness] = {
    TestResult.passed: E.effective,
    TestResult.passed_with_exceptions: E.partially_effective,
    TestResult.failed: E.ineffective,
}
#: Worst first.
_SEVERITY_ORDER = (E.ineffective, E.partially_effective, E.effective)
#: Review states whose tests count towards the rating.
COUNTING_REVIEW_STATES = ("reviewed", "legacy")
#: Issue states that are no longer open.
CLOSED_ISSUE_STATES = ("closed", "remediated", "risk_accepted")

BASIS_TESTS, BASIS_OVERRIDE, BASIS_MANUAL, BASIS_NONE = "tests", "override", "manual", "none"


def rating_for(result: TestResult | None) -> ControlEffectiveness | None:
    """The rating a conclusive result supports; None for a placeholder."""
    return _TEST_RATING.get(result) if result is not None else None


def _value(x: Any) -> Any:
    return getattr(x, "value", x)


def counts_towards_rating(test: Any) -> bool:
    """A test that decides a rating: conclusive, and reviewed (or legacy)."""
    return (
        _value(getattr(test, "review_status", "legacy") or "legacy") in COUNTING_REVIEW_STATES
        and rating_for(test.result) is not None
    )


def kind_of_test(test: Any) -> str:
    """design | operating. A test with no type (recorded before types existed) was a
    "does the control work" test — an operating test."""
    return "design" if getattr(test, "test_type", None) == "design" else "operating"


def _when(test: Any) -> tuple:
    created = getattr(test, "created_at", None) or datetime.min
    conducted = getattr(test, "conducted_date", None) or (
        created.date() if isinstance(created, datetime) else date.min
    )
    return (conducted, created if isinstance(created, datetime) else datetime.min)


def latest_counting(tests: Iterable[Any], kind: str) -> Any | None:
    """The most recent counting test of one kind (by date performed, then recorded)."""
    candidates = [t for t in tests if counts_towards_rating(t) and kind_of_test(t) == kind]
    if not candidates:
        return None
    return max(candidates, key=_when)


def combine(*ratings: ControlEffectiveness | None) -> ControlEffectiveness:
    """The worst of the ratings that have been assessed; not assessed when none has."""
    assessed = [r for r in ratings if r is not None and r != E.not_assessed]
    if not assessed:
        return E.not_assessed
    return min(assessed, key=_SEVERITY_ORDER.index)


def cap_for_open_issue(rating: ControlEffectiveness, has_open_issue: bool) -> ControlEffectiveness:
    """An open issue holds an operating rating at partially effective at best."""
    if has_open_issue and rating == E.effective:
        return E.partially_effective
    return rating


@dataclass(frozen=True)
class DerivedEffectiveness:
    design: ControlEffectiveness
    operating: ControlEffectiveness
    combined: ControlEffectiveness
    basis: str
    #: True when an open issue lowered the operating rating.
    capped: bool = False


def derive_effectiveness(
    tests: Iterable[Any],
    *,
    has_open_issue: bool = False,
    override_reason: str = "",
    current: ControlEffectiveness = E.not_assessed,
) -> DerivedEffectiveness:
    """The control's design, operating and combined ratings. Pure: see the section
    comment above for the rules."""
    tests = list(tests)
    design_test = latest_counting(tests, "design")
    operating_test = latest_counting(tests, "operating")
    design = rating_for(design_test.result) if design_test is not None else E.not_assessed
    raw_operating = rating_for(operating_test.result) if operating_test is not None else E.not_assessed
    operating = cap_for_open_issue(raw_operating, has_open_issue)
    capped = operating != raw_operating
    if (override_reason or "").strip():
        return DerivedEffectiveness(design, operating, current, BASIS_OVERRIDE, capped)
    if design_test is None and operating_test is None:
        basis = BASIS_MANUAL if current != E.not_assessed else BASIS_NONE
        return DerivedEffectiveness(design, operating, current, basis, capped)
    return DerivedEffectiveness(design, operating, combine(design, operating), BASIS_TESTS, capped)


def effectiveness_basis(tests: Iterable[Any], override_reason: str, current: ControlEffectiveness) -> str:
    """Where a control's combined rating comes from (for display)."""
    return derive_effectiveness(tests, override_reason=override_reason, current=current).basis


def apply_derived(control: Any, derived: DerivedEffectiveness) -> dict[str, dict[str, str]]:
    """Write the derived ratings onto the control; return what changed as
    ``{field: {"from": …, "to": …}}`` for the audit trail."""
    changes: dict[str, dict[str, str]] = {}
    for field, value in (
        ("design_effectiveness", derived.design),
        ("operating_effectiveness", derived.operating),
        ("effectiveness", derived.combined),
    ):
        before = getattr(control, field, None)
        if before != value:
            changes[field] = {"from": _value(before) if before is not None else None, "to": value.value}
            setattr(control, field, value)
    return changes


async def has_open_issue(db, control_id) -> bool:
    """Is any issue linked to the control (``issue_controls``) still open?"""
    from sqlalchemy import select

    from app.models.issue import Issue, IssueStatus2, issue_controls

    found = await db.scalar(
        select(Issue.id)
        .join(issue_controls, issue_controls.c.issue_id == Issue.id)
        .where(
            issue_controls.c.control_id == control_id,
            Issue.deleted.is_(False),
            Issue.status.notin_([IssueStatus2(s) for s in CLOSED_ISSUE_STATES]),
        )
        .limit(1)
    )
    return found is not None


async def recompute(db, control, *, forget_manual: bool = False) -> dict[str, dict[str, str]]:
    """Re-derive and write the control's ratings from its tests and open issues.
    Returns the changes (empty when nothing moved). Flushes nothing. ``forget_manual``
    drops a hand-set rating that no test supports (used when an override is removed:
    the rating goes back to what the tests say, not to what the override said)."""
    from sqlalchemy import select

    from app.models.control import ControlAudit

    tests = (
        await db.scalars(select(ControlAudit).where(ControlAudit.control_id == control.id))
    ).all()
    derived = derive_effectiveness(
        tests,
        has_open_issue=await has_open_issue(db, control.id),
        override_reason=control.effectiveness_override_reason or "",
        current=E.not_assessed if forget_manual else control.effectiveness,
    )
    return apply_derived(control, derived)


async def recompute_effectiveness(db, control, *, reason: str = "") -> None:
    """Bring a control's design / operating / combined effectiveness up to date.

    Call after anything that changes what the rating rests on — an issue linked to the
    control closed or reopened, a test reviewed. A change is recorded in the activity
    trail (attributed to the platform: the rule moved the rating, not a person);
    ``reason`` says what prompted it ("ISS-004 closed").
    """
    changes = await recompute(db, control)
    if not changes:
        return
    from app.services import audit

    moved = "; ".join(f"{k.replace('_', ' ')} {v['from']} → {v['to']}" for k, v in changes.items())
    await audit.record_system(
        db, tenant_id=control.tenant_id, action="update", entity_type="control",
        entity_id=control.id,
        summary=(f"Effectiveness re-derived for {control.reference or control.name}: {moved}"
                 + (f" ({reason})" if reason else ""))[:500],
        changes={"effectiveness": changes, **({"reason": reason} if reason else {})},
    )


# ---------------------------------------------------------------------------
# Issues raised by a test
# ---------------------------------------------------------------------------
#: Results that open an issue once the test is approved.
ISSUE_RAISING_RESULTS = (TestResult.failed, TestResult.passed_with_exceptions)


def issue_severity(result: TestResult, is_key: bool) -> Severity:
    """How serious the issue a test raises is: a key control failing is high; a failure
    of any other control, or exceptions in a key control, medium; exceptions in a
    non-key control, low."""
    if result == TestResult.failed:
        return Severity.high if is_key else Severity.medium
    return Severity.medium if is_key else Severity.low


def issue_title(result: TestResult, reference: str, name: str) -> str:
    label = "Control test failed" if result == TestResult.failed else "Control test found exceptions"
    return f"{label}: {' '.join(p for p in (reference or '', name or '') if p)}"[:255]
