"""Asset-driven risk generation: applicability and score derivation.

The failure mode this guards against is a *plausible but wrong* register. Generating
risks that don't apply to an asset, or scoring every important asset into the top-right
corner of the heat map, produces something worse than an empty register — a full one
nobody trusts. So the applicability rule, the derivation rules and the scale mapping are
all pinned, along with the catalogue's own internal consistency.
"""
import pytest

from app.models.enums import AssetClass, Criticality
from app.services.risk_scenarios import (
    CATALOGUE,
    IMPACT_RULES,
    RULE_BUSINESS_VALUE,
    RULE_CIA_MAX,
    RULE_CRITICALITY,
    RULE_FIXED,
    RULE_PROPERTY,
    AssetFacts,
    ScenarioSpec,
    applies_to_asset,
    impact_for,
    likelihood_for,
    scale,
    title_for,
)
from app.services.risk_scoring import MAX_MATRIX_SIZE, MIN_MATRIX_SIZE


def _asset(
    name="Core Banking System",
    asset_class=AssetClass.it_asset,
    criticality=Criticality.high,
    business_value=Criticality.medium,
    confidentiality=Criticality.medium,
    integrity=Criticality.medium,
    availability=Criticality.medium,
) -> AssetFacts:
    return AssetFacts(
        name=name, asset_class=asset_class.value, criticality=criticality,
        business_value=business_value, confidentiality=confidentiality,
        integrity=integrity, availability=availability,
    )


def _spec(**kwargs) -> ScenarioSpec:
    base = dict(
        reference="RS-X", title="Something happens to {asset}", description="", category="Test",
        asset_classes=(), threat="T", vulnerability="V", likelihood=3,
        impact_rule=RULE_CRITICALITY,
    )
    base.update(kwargs)
    return ScenarioSpec(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------- applicability ---
def test_a_scenario_with_no_classes_applies_to_everything():
    spec = _spec(asset_classes=())
    assert applies_to_asset(spec, _asset(asset_class=AssetClass.it_asset))
    assert applies_to_asset(spec, _asset(asset_class=AssetClass.information_asset))


def test_a_class_specific_scenario_skips_the_wrong_asset_kind():
    """A DR-failover scenario against a data record is noise that discredits the register."""
    it_only = _spec(asset_classes=(AssetClass.it_asset.value,))
    assert applies_to_asset(it_only, _asset(asset_class=AssetClass.it_asset))
    assert not applies_to_asset(it_only, _asset(asset_class=AssetClass.information_asset))


# ------------------------------------------------------------------- scaling ---
@pytest.mark.parametrize(
    "value,size,expected",
    [
        (1, 5, 1), (3, 5, 3), (5, 5, 5),          # same scale is a pass-through
        (5, 3, 3), (3, 3, 2), (1, 3, 1),          # down to 3x3
        (5, 6, 6), (3, 6, 4), (1, 6, 2),          # up to 6x6
    ],
)
def test_scale_maps_the_top_of_one_scale_to_the_top_of_another(value, size, expected):
    assert scale(value, size) == expected


@pytest.mark.parametrize("size", range(MIN_MATRIX_SIZE, MAX_MATRIX_SIZE + 1))
def test_scaling_never_leaves_the_matrix(size):
    for value in range(1, 6):
        assert 1 <= scale(value, size) <= size


# -------------------------------------------------------- impact derivation ---
def test_criticality_rule_follows_the_asset_rating():
    spec = _spec(impact_rule=RULE_CRITICALITY)
    assert impact_for(spec, _asset(criticality=Criticality.low), 5) == 2
    assert impact_for(spec, _asset(criticality=Criticality.critical), 5) == 5


def test_business_value_rule_follows_the_data_owner_rating():
    spec = _spec(impact_rule=RULE_BUSINESS_VALUE)
    asset = _asset(criticality=Criticality.low, business_value=Criticality.critical)
    assert impact_for(spec, asset, 5) == 5


def test_cia_max_rule_takes_the_worst_property():
    spec = _spec(impact_rule=RULE_CIA_MAX)
    asset = _asset(
        confidentiality=Criticality.low, integrity=Criticality.critical, availability=Criticality.medium
    )
    assert impact_for(spec, asset, 5) == 5


def test_property_rule_targets_the_named_property():
    """An availability scenario must not be scored on confidentiality."""
    availability = _spec(impact_rule=RULE_PROPERTY, impact_property="availability")
    asset = _asset(confidentiality=Criticality.critical, availability=Criticality.low)
    assert impact_for(availability, asset, 5) == 2

    confidentiality = _spec(impact_rule=RULE_PROPERTY, impact_property="confidentiality")
    assert impact_for(confidentiality, asset, 5) == 5


def test_property_rule_falls_back_to_criticality_when_unset():
    spec = _spec(impact_rule=RULE_PROPERTY, impact_property="")
    assert impact_for(spec, _asset(criticality=Criticality.critical), 5) == 5


def test_fixed_rule_ignores_the_asset():
    spec = _spec(impact_rule=RULE_FIXED, fixed_impact=2)
    assert impact_for(spec, _asset(criticality=Criticality.critical), 5) == 2


@pytest.mark.parametrize("size", range(MIN_MATRIX_SIZE, MAX_MATRIX_SIZE + 1))
@pytest.mark.parametrize("rule", IMPACT_RULES)
def test_every_rule_stays_inside_every_matrix(rule, size):
    spec = _spec(impact_rule=rule, impact_property="integrity", fixed_impact=4)
    for level in Criticality:
        asset = _asset(
            criticality=level, business_value=level,
            confidentiality=level, integrity=level, availability=level,
        )
        assert 1 <= impact_for(spec, asset, size) <= size


# ---------------------------------------------------------------- likelihood ---
def test_likelihood_comes_from_the_threat_not_the_asset():
    """Deriving likelihood from asset value would double-count criticality and push
    every important asset into the top-right corner of the heat map."""
    spec = _spec(likelihood=2)
    cheap = _asset(criticality=Criticality.low, business_value=Criticality.low)
    precious = _asset(criticality=Criticality.critical, business_value=Criticality.critical)
    assert likelihood_for(spec, cheap, 5) == likelihood_for(spec, precious, 5) == 2


# --------------------------------------------------------------------- title ---
def test_title_substitutes_the_asset_name():
    spec = _spec(title="Ransomware encrypts {asset}")
    assert title_for(spec, _asset(name="Core Banking")) == "Ransomware encrypts Core Banking"


def test_title_appends_the_asset_when_there_is_no_placeholder():
    spec = _spec(title="Ransomware")
    assert title_for(spec, _asset(name="Core Banking")) == "Ransomware — Core Banking"


def test_titles_are_unique_per_asset_and_scenario():
    """The title is the de-duplication key, so a collision would silently swallow a risk."""
    assets = [_asset(name=n) for n in ("Core Banking", "ATM Switch", "Card Management")]
    titles = {
        title_for(spec, asset)
        for spec in CATALOGUE
        for asset in assets
        if applies_to_asset(spec, asset)
    }
    expected = sum(1 for spec in CATALOGUE for a in assets if applies_to_asset(spec, a))
    assert len(titles) == expected


def test_colliding_titles_are_disambiguated_by_the_asset():
    """Asset registers really do hold two distinct records with the same name — a pair of
    identically-named servers, one app in two environments. Because the title is the
    de-duplication key, an un-disambiguated collision produces two risks nobody can tell
    apart *and* makes the next run treat both as already present."""
    import uuid as _uuid

    from app.api.v1.risk_scenarios import _disambiguate
    from app.schemas.risk_scenario import RiskProposal

    class _StubAsset:  # only the attributes the discriminator reads
        def __init__(self, asset_id, hostname=""):
            self.id = asset_id
            self.hostname = hostname
            self.serial_number = ""
            self.external_id = ""
            self.ip_address = ""
            self.location = ""

    first, second, third = _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4()

    def _proposal(asset_id, title):
        return RiskProposal(
            scenario_id=_uuid.uuid4(), scenario_reference="RS-001", asset_id=asset_id,
            asset_name="Payments DB", title=title, description="", category="Test",
            inherent_likelihood=3, inherent_impact=3, inherent_score=9,
            threat="T", vulnerability="V", treatment_description="",
        )

    proposals = [
        _proposal(first, "Unauthorised access to Payments DB"),
        _proposal(second, "Unauthorised access to Payments DB"),
        _proposal(third, "Ransomware encrypts Payments DB"),
    ]
    assets = {
        first: _StubAsset(first, hostname="pay-db-01"),
        second: _StubAsset(second),  # no hostname -> falls back to a short id
        third: _StubAsset(third, hostname="pay-db-03"),
    }
    _disambiguate(proposals, assets)

    titles = [p.title for p in proposals]
    assert len(set(titles)) == 3, titles
    assert titles[0] == "Unauthorised access to Payments DB (pay-db-01)"
    assert titles[1].endswith(f"({str(second)[:8]})")
    # A title that never collided is left exactly as it was.
    assert titles[2] == "Ransomware encrypts Payments DB"


# ----------------------------------------------------------- the catalogue ---
def test_catalogue_references_are_unique():
    references = [s.reference for s in CATALOGUE]
    assert len(references) == len(set(references))


def test_catalogue_entries_are_complete():
    for spec in CATALOGUE:
        assert spec.title.strip(), spec.reference
        assert spec.description.strip(), spec.reference
        assert spec.category.strip(), spec.reference
        assert spec.threat.strip(), spec.reference
        assert spec.vulnerability.strip(), spec.reference
        assert spec.treatment_hint.strip(), f"{spec.reference} proposes no treatment"


def test_catalogue_rules_and_ranges_are_valid():
    valid_classes = {c.value for c in AssetClass}
    for spec in CATALOGUE:
        assert spec.impact_rule in IMPACT_RULES, spec.reference
        assert 1 <= spec.likelihood <= 5, spec.reference
        assert set(spec.asset_classes) <= valid_classes, spec.reference
        if spec.impact_rule == RULE_PROPERTY:
            assert spec.impact_property in ("confidentiality", "integrity", "availability"), spec.reference
        if spec.impact_rule == RULE_FIXED:
            assert 1 <= spec.fixed_impact <= 5, spec.reference


def test_catalogue_titles_carry_the_asset_placeholder():
    """Without it every generated risk for a scenario would read identically."""
    missing = [s.reference for s in CATALOGUE if "{asset}" not in s.title]
    assert missing == []


def test_catalogue_covers_both_asset_classes_and_the_main_domains():
    assert any(AssetClass.information_asset.value in s.asset_classes for s in CATALOGUE)
    assert any(AssetClass.it_asset.value in s.asset_classes for s in CATALOGUE)
    assert any(not s.asset_classes for s in CATALOGUE)
    categories = {s.category for s in CATALOGUE}
    for expected in (
        "Access Control", "Data Protection", "Cyber Security", "Business Continuity",
        "Third Party", "Compliance", "Financial Crime", "Physical Security", "Operations",
    ):
        assert expected in categories, f"no scenario covers {expected}"


def test_every_asset_kind_gets_a_usable_number_of_scenarios():
    """A register generated from three applicable scenarios is not worth the button."""
    for asset_class in AssetClass:
        facts = _asset(asset_class=asset_class)
        applicable = [s for s in CATALOGUE if applies_to_asset(s, facts)]
        assert len(applicable) >= 15, f"{asset_class.value} only matches {len(applicable)}"
