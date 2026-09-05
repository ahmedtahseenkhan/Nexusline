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


def test_an_empty_register_is_not_out_of_tolerance_but_an_empty_catalogue_is_not_assured():
    """No risks means nothing exceeds tolerance; no controls means nothing is working."""
    parts = _parts(risks_total=0, risks_within_tolerance=0, controls_total=0, controls_assured=0,
                   clauses_applicable=0, clauses_assured=0, deadlines_total=0, deadlines_overdue=0)
    by = {c.key: c.value for c in parts}
    assert by["tolerance"] == 100.0 and by["discipline"] == 100.0
    assert by["assurance"] == 0.0 and by["compliance"] == 0.0


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
