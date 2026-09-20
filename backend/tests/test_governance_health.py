"""The dashboard's headline number, and that it explains itself."""
import pytest

from app.services import governance_health as gh


def _parts(**kw):
    base = dict(
        risks_total=100, risks_within_tolerance=90,
        controls_total=50, controls_assured=25,
        clauses_applicable=80, clauses_assured=40,
        deadlines_total=40, deadlines_overdue=4,
    )
    return gh.components(**{**base, **kw})


def test_the_score_is_a_weighted_mean_of_named_components():
    parts = _parts()
    assert [c.key for c in parts] == ["tolerance", "assurance", "compliance", "discipline"]
    assert [c.value for c in parts] == [90.0, 50.0, 50.0, 90.0]
    # 0.35*90 + 0.30*50 + 0.20*50 + 0.15*90 = 31.5 + 15 + 10 + 13.5 = 70
    assert gh.score(parts) == 70


def test_every_component_carries_the_counts_behind_it():
    for c in _parts():
        assert " of " in c.detail, c.key


def test_weights_sum_to_one():
    assert abs(sum(c.weight for c in _parts()) - 1.0) < 1e-9


_EMPTY = dict(risks_total=0, risks_within_tolerance=0, controls_total=0, controls_assured=0,
              clauses_applicable=0, clauses_assured=0, deadlines_total=0, deadlines_overdue=0)


def test_an_empty_measure_has_no_value_rather_than_a_free_hundred_or_zero():
    """No risks is not "100 % within tolerance" and no controls is not "0 % assured":
    both are unknown. Each empty component carries no value and a population of 0."""
    parts = _parts(**_EMPTY)
    assert all(c.value is None for c in parts)
    assert all(c.population == 0 for c in parts)
    assert gh.pct(0, 0) is None


def test_every_component_reports_its_population_and_formula():
    by = {c.key: c for c in _parts()}
    assert by["tolerance"].population == 100
    assert by["assurance"].population == 50
    assert by["compliance"].population == 80
    assert by["discipline"].population == 40
    assert all(c.formula for c in by.values())


def test_mapped_but_untested_controls_do_not_lift_the_score():
    """The endpoint counts only effective/partially effective as assured; a fresh
    framework install (93 not-assessed controls) must not read as healthy."""
    installed = _parts(controls_total=93, controls_assured=0, clauses_applicable=93, clauses_assured=0)
    assert {c.key: c.value for c in installed}["assurance"] == 0.0
    assert gh.score(installed) < gh.score(_parts())


@pytest.mark.parametrize("value,expected", [(95, "healthy"), (80, "healthy"), (79, "elevated"), (60, "elevated"), (59, "critical"), (0, "critical")])
def test_bands(value, expected):
    assert gh.band(value) == expected


# ------------------------------------------------------------------- KRIs ---
def test_a_kri_with_no_reading_is_no_data_not_green():
    assert gh.kri_status(None, 5, 10, "above") == "no_data"


def test_kri_rag_when_higher_is_worse():
    assert gh.kri_status(3, 5, 10, "above") == "green"
    assert gh.kri_status(5, 5, 10, "above") == "amber"
    assert gh.kri_status(12, 5, 10, "above") == "red"


def test_kri_rag_when_lower_is_worse():
    """Liquidity cover, staffing levels: the breach is a fall, not a rise."""
    assert gh.kri_status(120, 110, 100, "below") == "green"
    assert gh.kri_status(105, 110, 100, "below") == "amber"
    assert gh.kri_status(90, 110, 100, "below") == "red"


def test_kri_with_only_a_limit_threshold():
    assert gh.kri_status(4, None, 10, "above") == "green"
    assert gh.kri_status(11, None, 10, "above") == "red"


# ------------------------------------------------------- an empty organisation ---
def test_an_empty_tenant_has_no_score_at_all():
    """A wiped system once read 70/100: no risks scored full marks for tolerance and
    for "nothing critical", and the empty catalogue was simply not asked about. There
    is nothing to judge here, and the page must say so rather than print a number."""
    empty = _parts(risks_total=0, risks_within_tolerance=0, controls_total=0, controls_assured=0,
                   clauses_applicable=0, clauses_assured=0, deadlines_total=0, deadlines_overdue=0)
    assert gh.has_data(empty) is False
    assert gh.band(gh.score(empty), data=False) == gh.NO_DATA


def test_one_populated_component_is_enough_to_score():
    """Import a control catalogue and nothing else: that is a real, judgeable state."""
    seeded = _parts(risks_total=0, risks_within_tolerance=0, clauses_applicable=0, clauses_assured=0,
                    deadlines_total=0, deadlines_overdue=0, controls_total=93, controls_assured=0)
    assert gh.has_data(seeded) is True
    assert gh.band(gh.score(seeded), data=True) == "critical"


def test_an_empty_tenant_scores_on_nothing():
    empty = _parts(**_EMPTY)
    assert gh.score(empty) == 0
    cov = gh.coverage(empty)
    assert (cov.scored, cov.total, cov.weight_pct) == (0, 4, 0.0)


def test_a_controls_only_tenant_gets_no_free_tolerance_or_discipline_credit():
    """The F-01 bug: controls but no risks and no deadlines used to collect 100 % for
    tolerance (0.35) and discipline (0.15), lifting 50 %-assured controls to a score of
    65. Only the measure with data behind it may count."""
    controls_only = _parts(risks_total=0, risks_within_tolerance=0, clauses_applicable=0, clauses_assured=0,
                           deadlines_total=0, deadlines_overdue=0, controls_total=40, controls_assured=20)
    by = {c.key: c for c in controls_only}
    assert by["tolerance"].value is None and by["tolerance"].population == 0
    assert by["discipline"].value is None and by["discipline"].population == 0
    # Only assurance is scored, so the score is exactly its value, not inflated.
    assert gh.score(controls_only) == 50
    cov = gh.coverage(controls_only)
    assert cov.scored == 1 and cov.total == 4 and cov.weight_pct == 30.0


def test_weights_are_renormalised_over_the_scored_measures():
    """Two measures with data: their weights (0.35 + 0.20) are rescaled to sum to one."""
    parts = _parts(controls_total=0, controls_assured=0, deadlines_total=0, deadlines_overdue=0,
                   risks_total=10, risks_within_tolerance=10, clauses_applicable=10, clauses_assured=0)
    # (0.35*100 + 0.20*0) / 0.55 = 63.6 -> 64
    assert gh.score(parts) == 64
    assert gh.coverage(parts).weight_pct == 55.0


def test_a_full_tenant_is_unchanged():
    parts = _parts()
    assert gh.score(parts) == 70
    cov = gh.coverage(parts)
    assert (cov.scored, cov.total, cov.weight_pct) == (4, 4, 100.0)
