"""Where the framework → controls → risks loop closes: a test moves effectiveness, and
only a working control assures a clause.

The two defects these pin were silent. Recording a passed test left the control
*not assessed* unless someone also edited it, so every residual suggestion starved.
And a clause counted as covered the moment a control was mapped, so a freshly
installed framework — 93 planned, untested controls — looked covered with nothing
behind it.
"""
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.models.enums import ComplianceStatus, ControlEffectiveness, TestResult
from app.services import control_assurance as ca

E = ControlEffectiveness


# ---------------------------------------------------- a test sets effectiveness ---
@pytest.mark.parametrize(
    "result,current,expected",
    [
        (TestResult.passed, E.not_assessed, E.effective),
        (TestResult.passed, E.ineffective, E.effective),
        (TestResult.failed, E.effective, E.ineffective),
        (TestResult.failed, E.not_assessed, E.ineffective),
        # Scheduled but not performed: a placeholder, changes nothing.
        (TestResult.not_assessed, E.effective, E.effective),
        (TestResult.not_assessed, E.not_assessed, E.not_assessed),
    ],
)
def test_the_result_drives_effectiveness(result, current, expected):
    assert ca.effectiveness_after_test(result, None, current) is expected


def test_the_tester_can_say_it_passed_only_partially():
    assert ca.effectiveness_after_test(TestResult.passed, E.partially_effective, E.not_assessed) is E.partially_effective


def test_an_explicit_override_wins_even_over_a_failure():
    """"Failed the metric but the control is partially working" is a legitimate verdict;
    the tester's word is the record."""
    assert ca.effectiveness_after_test(TestResult.failed, E.partially_effective, E.effective) is E.partially_effective


# ---------------------------------------------------------- coverage of a clause ---
def test_no_controls_is_unmapped():
    assert ca.coverage_state([]) == ca.UNMAPPED


def test_mapped_but_untested_is_not_coverage():
    """The whole point: installing a framework maps a control to every clause."""
    assert ca.coverage_state([E.not_assessed, E.not_assessed]) == ca.UNASSESSED
    assert not ca.is_assured([E.not_assessed])


def test_an_ineffective_control_is_failing_not_unassessed():
    assert ca.coverage_state([E.ineffective]) == ca.FAILING


def test_one_working_control_assures_the_clause():
    """The strongest state wins: one effective control among failing and untested ones
    is still assurance — that is what "at least one control in the way" means."""
    assert ca.coverage_state([E.not_assessed, E.ineffective, E.partially_effective]) == ca.ASSURED
    assert ca.is_assured([E.ineffective, E.effective])


def test_partially_effective_counts_as_assurance():
    assert ca.control_state(E.partially_effective) == ca.ASSURED


# ------------------------------------------------------- the gap rule in the API ---
def _req(status, *effectivenesses):
    controls = [SimpleNamespace(effectiveness=e) for e in effectivenesses]
    return SimpleNamespace(
        status=status, controls=controls,
        is_covered=bool(controls), coverage=ca.coverage_state(effectivenesses),
    )


def test_gap_reasons_name_the_actual_problem():
    from app.api.v1.compliance import _gap_reason

    assert _gap_reason(_req(ComplianceStatus.compliant)) == "No controls mapped"
    assert _gap_reason(_req(ComplianceStatus.compliant, E.not_assessed)) == "Controls mapped but none assessed yet"
    assert _gap_reason(_req(ComplianceStatus.compliant, E.ineffective)) == "Mapped controls are ineffective"
    assert _gap_reason(_req(ComplianceStatus.non_compliant, E.effective)) == "Status is non compliant"
    assert _gap_reason(_req(ComplianceStatus.not_assessed, E.not_assessed)) == (
        "Controls mapped but none assessed yet; status is not assessed"
    )


def test_an_assured_settled_clause_is_not_a_gap():
    from app.api.v1.compliance import _gap_reason

    assert _gap_reason(_req(ComplianceStatus.compliant, E.effective)) == ""
    assert _gap_reason(_req(ComplianceStatus.not_applicable)) == ""


def test_the_sql_filter_agrees_with_the_python_rule():
    """The list page filters in SQL; the roll-up counts in Python. They must not drift:
    the SQL must demand a mapped control that is effective or partially effective, not
    merely a mapped control."""
    from app.api.v1.compliance import _gap_predicate

    text = str(_gap_predicate().compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "NOT (EXISTS" in text
    assert "controls.effectiveness IN" in text
    assert "'effective'" in text and "'partially_effective'" in text
    assert "'not_assessed'" not in text


# --------------------------------------------- generated risks link to clauses ---
def test_clauses_are_derived_from_the_linked_controls():
    from app.api.v1.risk_scenarios import _clauses_for_controls_stmt

    ids = [uuid.uuid4(), uuid.uuid4()]
    text = str(_clauses_for_controls_stmt(ids).compile(dialect=postgresql.dialect()))
    assert "requirement_controls" in text and "requirement_id" in text and "control_id IN" in text
