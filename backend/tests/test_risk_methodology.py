"""Configurable risk matrix and control-driven residual suggestion.

Two rules matter most here and both are pinned:

1. **An unconfigured installation must not change.** The severity bands are now derived
   from the matrix size rather than hard-coded, so the 5x5 default has to reproduce the
   original 1-4 / 5-9 / 10-14 / 15-25 bands exactly.
2. **The residual engine only ever proposes.** It must never invent credit for a control
   that is not currently working, and it must explain every number it produces — a
   residual score with no reasoning behind it is an audit finding.
"""
import pytest

from app.models.enums import ControlEffectiveness, Severity
from app.services.residual_engine import (
    APPLIES_BOTH,
    APPLIES_IMPACT,
    ControlInput,
    ResidualPolicySpec,
    suggest_residual,
)
from app.services.risk_scoring import (
    DEFAULT_MAX_SCORE,
    MAX_MATRIX_SIZE,
    MIN_MATRIX_SIZE,
    band_ranges,
    max_score_for,
    severity_for_score,
)


def _effective(label="CTL-1", healthy=True):
    return ControlInput(label=label, effectiveness=ControlEffectiveness.effective, healthy=healthy)


# ------------------------------------------------------------- backwards compat ---
def test_default_matrix_reproduces_the_original_bands():
    """The exact bands the platform shipped with, before the matrix was configurable."""
    assert band_ranges() == [
        (1, 4, Severity.low),
        (5, 9, Severity.medium),
        (10, 14, Severity.high),
        (15, 25, Severity.critical),
    ]


@pytest.mark.parametrize(
    "score,expected",
    [
        (1, Severity.low), (4, Severity.low),
        (5, Severity.medium), (9, Severity.medium),
        (10, Severity.high), (14, Severity.high),
        (15, Severity.critical), (25, Severity.critical),
    ],
)
def test_severity_for_score_unchanged_without_a_matrix_size(score, expected):
    """Every pre-existing caller passes no max_score and must be unaffected."""
    assert severity_for_score(score) is expected


def test_severity_of_nothing_is_nothing():
    assert severity_for_score(None) is None


# ---------------------------------------------------------------- other scales ---
@pytest.mark.parametrize("size", range(MIN_MATRIX_SIZE, MAX_MATRIX_SIZE + 1))
def test_every_supported_matrix_produces_four_usable_bands(size):
    """A band no score can land in would vanish from the heat-map legend."""
    bands = band_ranges(max_score_for(size))
    assert len(bands) == 4
    assert [b[2] for b in bands] == [Severity.low, Severity.medium, Severity.high, Severity.critical]
    for low, high, _ in bands:
        assert low <= high, f"empty band on a {size}x{size} matrix"


@pytest.mark.parametrize("size", range(MIN_MATRIX_SIZE, MAX_MATRIX_SIZE + 1))
def test_bands_are_contiguous_and_cover_the_whole_scale(size):
    max_score = max_score_for(size)
    bands = band_ranges(max_score)
    assert bands[0][0] == 1
    assert bands[-1][1] == max_score
    for (_, previous_high, _), (next_low, _, _) in zip(bands, bands[1:]):
        assert next_low == previous_high + 1


@pytest.mark.parametrize("size", range(MIN_MATRIX_SIZE, MAX_MATRIX_SIZE + 1))
def test_every_reachable_score_bands_somewhere(size):
    max_score = max_score_for(size)
    for likelihood in range(1, size + 1):
        for impact in range(1, size + 1):
            assert severity_for_score(likelihood * impact, max_score) is not None


def test_the_worst_cell_is_always_critical_and_the_best_is_always_low():
    for size in range(MIN_MATRIX_SIZE, MAX_MATRIX_SIZE + 1):
        max_score = max_score_for(size)
        assert severity_for_score(max_score, max_score) is Severity.critical
        assert severity_for_score(1, max_score) is Severity.low


def test_a_four_by_four_bands_differently_from_the_default():
    """Proof the scale actually travels: 9 is medium out of 25, critical out of 16."""
    assert severity_for_score(9, DEFAULT_MAX_SCORE) is Severity.medium
    assert severity_for_score(9, max_score_for(4)) is Severity.critical


# ------------------------------------------------------ the 1-10 scale (0024) ----
# Banks arrive with a board-approved matrix already in force and 1-10 is common in the
# local market, so the ceiling has to reach it. These pin the promise made to a client
# choosing that scale; everything above already covers 7..10 by parametrisation.
def test_the_ceiling_reaches_ten():
    assert MAX_MATRIX_SIZE == 10


def test_a_ten_by_ten_bands_as_documented():
    """1-16 low, 17-36 medium, 37-56 high, 57-100 critical."""
    assert band_ranges(max_score_for(10)) == [
        (1, 16, Severity.low),
        (17, 36, Severity.medium),
        (37, 56, Severity.high),
        (57, 100, Severity.critical),
    ]


def test_widening_the_matrix_leaves_the_default_untouched():
    """A tenant that never opens the setting must score identically to before 0024."""
    assert [severity_for_score(v) for v in (4, 5, 9, 10, 14, 15, 25)] == [
        Severity.low, Severity.medium, Severity.medium,
        Severity.high, Severity.high, Severity.critical, Severity.critical,
    ]


def test_default_scale_wording_covers_every_rung():
    """A bank on 1-10 that has not written its criteria must still see words, not bare
    numbers, on rungs 7-10 — otherwise the widened scale ships half-built."""
    from app.services.risk_settings import DEFAULT_IMPACT_LABELS, DEFAULT_LIKELIHOOD_LABELS

    for axis in (DEFAULT_LIKELIHOOD_LABELS, DEFAULT_IMPACT_LABELS):
        for level in range(1, MAX_MATRIX_SIZE + 1):
            assert axis.get(level), f"no default wording for level {level}"


def test_database_checks_track_the_ceiling():
    """The DDL, the ORM constraints and the validators all read one constant. If any of
    them is edited by hand this fails rather than letting the schema reject a score the
    API accepts."""
    from app.db.schema_patches import risk_scale_constraint_statements

    statements = risk_scale_constraint_statements()
    assert statements, "no scale constraints generated"
    for statement in statements:
        assert f"BETWEEN 1 AND {MAX_MATRIX_SIZE}" in statement
        # Migration 0017 applies these before risk_matrix_levels exists.
        assert "to_regclass" in statement
    assert any("risk_matrix_levels" in s for s in statements)


def test_the_ceiling_is_importable_without_dragging_in_the_models():
    """The DDL patches and the ORM constraints both need the ceiling, and the scoring
    service needs the models' enums. Putting the constant in the service closed that
    circle: ``python -m app.db.init_db`` imported the patches first and died on a
    partially-initialised module, while the test suite (which imports the models first)
    stayed green. It lives in a module that imports nothing, and this asserts that."""
    import subprocess
    import sys

    for first in ("app.db.schema_patches", "app.db.init_db", "app.models"):
        result = subprocess.run(
            [sys.executable, "-c", f"import {first}"], capture_output=True, text=True
        )
        assert result.returncode == 0, f"importing {first} first fails:\n{result.stderr}"


def test_score_validators_accept_the_whole_scale():
    from app.schemas.risk import RiskCreate

    risk = RiskCreate(
        title="Top of the scale",
        inherent_likelihood=MAX_MATRIX_SIZE,
        inherent_impact=MAX_MATRIX_SIZE,
    )
    assert risk.inherent_likelihood == MAX_MATRIX_SIZE
    with pytest.raises(ValueError):
        RiskCreate(
            title="Off the scale",
            inherent_likelihood=MAX_MATRIX_SIZE + 1,
            inherent_impact=1,
        )


# ------------------------------------------------------------ residual engine ----
def test_no_controls_means_residual_equals_inherent():
    s = suggest_residual(4, 5, [])
    assert (s.likelihood, s.impact, s.reduction) == (4, 5, 0)
    assert "No controls are linked" in s.rationale[0]


def test_a_disabled_policy_suggests_nothing():
    s = suggest_residual(4, 5, [_effective()], ResidualPolicySpec(enabled=False))
    assert (s.likelihood, s.impact) == (4, 5)
    assert "switched off" in s.rationale[0]


def test_an_effective_control_reduces_likelihood_only_by_default():
    """Controls change how often something happens, not how badly it hurts."""
    s = suggest_residual(4, 5, [_effective()])
    assert (s.likelihood, s.impact) == (2, 5)
    assert s.reduction == 2


def test_a_partially_effective_control_earns_less():
    control = ControlInput("CTL-2", ControlEffectiveness.partially_effective)
    assert suggest_residual(4, 5, [control]).likelihood == 3


def test_an_ineffective_control_earns_nothing_and_says_so():
    control = ControlInput("CTL-3", ControlEffectiveness.ineffective)
    s = suggest_residual(4, 5, [control])
    assert (s.likelihood, s.impact, s.reduction) == (4, 5, 0)
    assert any("CTL-3: no credit — rated ineffective" in line for line in s.rationale)


def test_a_failing_control_earns_nothing_however_it_is_rated():
    """This is what makes the suggestion rise again when assurance lapses."""
    broken = ControlInput(
        "CTL-4", ControlEffectiveness.effective, healthy=False, health_note="its last audit failed"
    )
    s = suggest_residual(4, 5, [broken])
    assert s.reduction == 0
    assert any("CTL-4: no credit — its last audit failed" in line for line in s.rationale)


def test_credit_accumulates_across_controls():
    s = suggest_residual(5, 5, [_effective("A"), ControlInput("B", ControlEffectiveness.partially_effective)])
    assert s.reduction == 3
    assert s.likelihood == 2


def test_total_credit_is_capped_by_policy():
    controls = [_effective(f"C{i}") for i in range(5)]  # 10 raw credit
    s = suggest_residual(5, 5, controls, ResidualPolicySpec(max_reduction=3))
    assert s.reduction == 3
    assert any("capped at the policy maximum of 3" in line for line in s.rationale)


def test_a_score_never_drops_below_one():
    controls = [_effective(f"C{i}") for i in range(5)]
    s = suggest_residual(2, 2, controls, ResidualPolicySpec(max_reduction=5))
    assert s.likelihood == 1
    assert s.score == 2


def test_impact_only_policy_moves_impact():
    s = suggest_residual(4, 5, [_effective()], ResidualPolicySpec(applies_to=APPLIES_IMPACT))
    assert (s.likelihood, s.impact) == (4, 3)


def test_both_policy_splits_the_odd_point_toward_likelihood():
    control = ControlInput("A", ControlEffectiveness.partially_effective)  # 1 point
    s = suggest_residual(4, 5, [control], ResidualPolicySpec(applies_to=APPLIES_BOTH))
    assert (s.likelihood, s.impact) == (3, 5)
    s3 = suggest_residual(5, 5, [_effective("A"), control], ResidualPolicySpec(applies_to=APPLIES_BOTH))
    assert (s3.likelihood, s3.impact) == (3, 4)  # 3 points -> 2 likelihood, 1 impact


def test_every_control_is_accounted_for_in_the_rationale():
    """A number with no reasoning behind it is exactly what this feature must not ship."""
    controls = [
        _effective("A"),
        ControlInput("B", ControlEffectiveness.ineffective),
        ControlInput("C", ControlEffectiveness.effective, healthy=False, health_note="overdue"),
    ]
    s = suggest_residual(4, 5, controls)
    for label in ("A", "B", "C"):
        assert any(line.startswith(f"{label}:") for line in s.rationale)


# ------------------------------------------------------- serialisation banding ---
def _risk_read_payload(inherent_score: int) -> dict:
    import datetime
    import uuid

    return dict(
        id=uuid.uuid4(), reference="R-1", title="t", description="", category="",
        status="draft", owner_id=None, inherent_likelihood=3, inherent_impact=4,
        inherent_score=inherent_score, residual_likelihood=None, residual_impact=None,
        residual_score=None, annual_loss_frequency=None, single_loss_expectancy=None,
        annual_loss_expectancy=None, treatment_strategy=None, treatment_description="",
        treatment_owner="", treatment_deadline=None, treatment_cost=None,
        review_frequency="annual", last_review_date=None, next_review_date=None,
        expired_reviews=0, workflow_status="draft", workflow_owner="",
        created_at=datetime.datetime.now(), updated_at=datetime.datetime.now(),
    )


def test_risk_read_bands_on_the_supplied_matrix():
    from app.schemas.risk import RiskRead

    payload = _risk_read_payload(12)
    assert RiskRead.model_validate(payload).inherent_severity is Severity.high  # 5x5 default
    assert RiskRead.model_validate(payload, context={"max_score": 36}).inherent_severity is Severity.medium
    assert RiskRead.model_validate(payload, context={"max_score": 16}).inherent_severity is Severity.critical


def test_revalidating_a_read_model_keeps_its_bands():
    """FastAPI validates a handler's return value a second time against response_model,
    and that pass carries no context. Recomputing there would silently reset a 6x6
    tenant's severities to the default 5x5 bands — which is exactly what happened before
    this guard existed."""
    from app.schemas.risk import RiskRead

    banded = RiskRead.model_validate(_risk_read_payload(12), context={"max_score": 36})
    assert banded.inherent_severity is Severity.medium
    # The response pass: same object, no context.
    assert RiskRead.model_validate(banded).inherent_severity is Severity.medium


def test_a_custom_weighting_changes_the_outcome():
    """The bank's methodology is configuration, not a code change."""
    aggressive = ResidualPolicySpec(weight_effective=4, max_reduction=4)
    assert suggest_residual(5, 5, [_effective()], aggressive).likelihood == 1


def test_suggestion_is_deterministic():
    controls = [_effective("A"), ControlInput("B", ControlEffectiveness.partially_effective)]
    first = suggest_residual(4, 5, controls)
    second = suggest_residual(4, 5, controls)
    assert (first.likelihood, first.impact, first.rationale) == (
        second.likelihood, second.impact, second.rationale,
    )
