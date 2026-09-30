"""Asset tier, PCI DSS scope and the asset-based risk rating (no DB required).

The asset-based method (ISO/IEC 27005) rates a risk by what it threatens: likelihood x
impact times the value of the asset at risk. These pin the arithmetic, the banding, the
read model and the import of the two new asset fields.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.enums import Criticality, PciScope, Severity
from app.schemas.asset import MAX_ASSET_TIER, AssetCreate, AssetUpdate
from app.schemas.risk import RiskRead
from app.services import import_registry as ir
from app.services.import_mapping import suggest_mapping
from app.services.import_registry import REGISTRY
from app.services.risk_scoring import (
    MAX_ASSET_VALUE,
    AssetFacts,
    BusinessImpactScale,
    asset_value_of,
    business_impact,
)
from app.services.risk_settings import business_scale_for


# ------------------------------------------------------------------ arithmetic
@pytest.mark.parametrize(
    "criticality,value",
    [(Criticality.low, 1), (Criticality.medium, 2), (Criticality.high, 3), (Criticality.critical, 4),
     ("critical", 4), (None, None), ("", None)],
)
def test_an_assets_value_is_the_criticality_its_register_shows(criticality, value):
    assert asset_value_of(criticality) == value


def test_business_impact_is_the_score_times_the_asset_value():
    assert business_impact(20, 4) == 80
    assert business_impact(6, 1) == 6


def test_no_business_impact_without_a_score_or_an_asset():
    assert business_impact(None, 4) is None
    assert business_impact(20, None) is None


def test_the_default_scale_bands_like_the_matrix_does():
    scale = BusinessImpactScale()  # 5x5 matrix x asset value 4
    assert scale.max_value == 25 * MAX_ASSET_VALUE == 100
    assert [(low, high, sev.value) for low, high, sev in scale.ranges()] == [
        (1, 16, "low"), (17, 36, "medium"), (37, 56, "high"), (57, 100, "critical"),
    ]
    assert scale.for_value(16) == Severity.low
    assert scale.for_value(17) == Severity.medium
    assert scale.for_value(80) == Severity.critical
    assert scale.for_value(None) is None


def test_configured_thresholds_replace_the_derived_bands():
    scale = BusinessImpactScale(max_value=100, bands=(20, 40, 70))
    assert scale.for_value(20) == Severity.low
    assert scale.for_value(41) == Severity.high
    assert scale.for_value(71) == Severity.critical


# ------------------------------------------------------------------ the setting
def _settings(**over):
    base = dict(scoring_method="asset_based", matrix_size=5, business_impact_bands={})
    return SimpleNamespace(**{**base, **over})


def test_the_matrix_method_reports_no_business_impact():
    assert business_scale_for(_settings(scoring_method="matrix")) is None


def test_the_scale_follows_the_matrix_size():
    assert business_scale_for(_settings(matrix_size=4)).max_value == 16 * MAX_ASSET_VALUE


def test_thresholds_that_no_longer_fit_a_shrunk_matrix_are_ignored():
    scale = business_scale_for(
        _settings(matrix_size=3, business_impact_bands={"low_max": 20, "medium_max": 40, "high_max": 70})
    )
    assert scale.max_value == 36 and scale.bands is None


# ------------------------------------------------------------------ the risk read
def _risk(**over):
    now = datetime.now(timezone.utc)
    base = dict(
        id=uuid.uuid4(), reference="R-001", title="Ransomware", description="", category="",
        status="assessed", owner_id=None, inherent_likelihood=4, inherent_impact=5, inherent_score=20,
        residual_likelihood=2, residual_impact=3, residual_score=6, target_likelihood=None,
        target_impact=None, last_assessed_at=now, annual_loss_frequency=None,
        single_loss_expectancy=None, annual_loss_expectancy=None, treatment_strategy=None,
        treatment_description="", treatment_owner="", treatment_deadline=None, treatment_cost=None,
        review_frequency="annual", last_review_date=None, next_review_date=None, expired_reviews=0,
        workflow_status="draft", workflow_owner="", created_at=now, updated_at=now,
    )
    return SimpleNamespace(**{**base, **over})


def _read(risk, *, facts=None, scale=None):
    context = {"asset_facts": {risk.id: facts} if facts else {}, "business_scale": scale}
    return RiskRead.model_validate(risk, context=context)


def test_a_risk_reports_its_assets_value_and_tier_under_either_method():
    read = _read(_risk(), facts=AssetFacts(asset_value=4, tier=1))
    assert (read.asset_value, read.asset_tier) == (4, 1)
    assert read.inherent_business_impact is None and read.inherent_business_rating is None


def test_the_asset_based_method_rates_each_score_by_the_asset_value():
    read = _read(_risk(), facts=AssetFacts(asset_value=4, tier=2), scale=BusinessImpactScale())
    assert (read.inherent_business_impact, read.inherent_business_rating) == (80, Severity.critical)
    assert (read.residual_business_impact, read.residual_business_rating) == (24, Severity.medium)
    assert read.target_business_impact is None
    # The matrix rating is untouched: the heat map stays likelihood x impact.
    assert read.inherent_severity == Severity.critical and read.residual_severity == Severity.medium


def test_a_risk_with_no_asset_has_no_business_impact():
    read = _read(_risk(), scale=BusinessImpactScale())
    assert read.asset_value is None and read.inherent_business_impact is None


def test_an_unscored_draft_is_not_rated_by_its_placeholder():
    draft = _risk(status="draft", last_assessed_at=None, inherent_likelihood=1, inherent_impact=1,
                  inherent_score=1, residual_likelihood=None, residual_impact=None, residual_score=None)
    read = _read(draft, facts=AssetFacts(asset_value=4, tier=1), scale=BusinessImpactScale())
    assert read.asset_value == 4
    assert read.inherent_business_impact is None and read.inherent_business_rating is None


def test_the_response_pass_does_not_wipe_the_business_impact():
    """FastAPI validates the handler's return value again, with no context."""
    read = _read(_risk(), facts=AssetFacts(asset_value=3, tier=1), scale=BusinessImpactScale())
    again = RiskRead.model_validate(read)
    assert (again.asset_value, again.asset_tier, again.inherent_business_impact) == (3, 1, 60)
    assert again.inherent_business_rating == Severity.critical


# ------------------------------------------------------------------ the asset fields
def test_an_asset_takes_a_tier_and_a_pci_scope_and_neither_is_assumed():
    asset = AssetCreate(name="Core banking DB")
    assert asset.tier is None and asset.pci_scope is None
    asset = AssetCreate(name="Card switch", tier=1, pci_scope="in_scope")
    assert asset.tier == 1 and asset.pci_scope == PciScope.in_scope


@pytest.mark.parametrize("tier", [0, MAX_ASSET_TIER + 1])
def test_a_tier_outside_the_range_is_refused(tier):
    with pytest.raises(ValidationError):
        AssetCreate(name="x", tier=tier)
    with pytest.raises(ValidationError):
        AssetUpdate(tier=tier)


@pytest.mark.parametrize("cell,tier", [("1", 1), ("Tier 2", 2), ("T3", 3), (" tier-1 ", 1)])
def test_a_tier_cell_is_read_the_way_registers_write_it(cell, tier):
    assert ir._parse_tier(cell) == tier


@pytest.mark.parametrize("cell", ["Gold", "Tier 9", "0"])
def test_a_tier_cell_that_names_no_tier_fails_the_row(cell):
    with pytest.raises(ValueError, match="tier"):
        ir._parse_tier(cell)


@pytest.mark.parametrize(
    "cell,scope",
    [("in_scope", PciScope.in_scope), ("In Scope", PciScope.in_scope), ("Yes", PciScope.in_scope),
     ("CDE", PciScope.in_scope), ("Connected", PciScope.connected), ("connected-to", PciScope.connected),
     ("No", PciScope.out_of_scope), ("Out of scope", PciScope.out_of_scope), ("N/A", None)],
)
def test_a_pci_scope_cell_takes_the_value_or_a_trackers_yes_and_no(cell, scope):
    assert ir._parse_pci_scope(cell) == scope


def test_an_unknown_pci_scope_fails_the_row():
    with pytest.raises(ValueError, match="pci_scope"):
        ir._parse_pci_scope("maybe")


@pytest.mark.parametrize("resource", ["it-assets", "information-assets"])
def test_both_asset_registers_import_and_export_tier_and_pci_scope(resource):
    cols = {c.header: c for c in REGISTRY[resource].all_columns}
    assert cols["tier"].parse is ir._parse_tier
    assert cols["pci_scope"].enum_values == [s.value for s in PciScope]


def test_a_banks_headings_map_to_the_new_columns():
    res = REGISTRY["it-assets"]
    suggestions, _unmapped, _unfilled = suggest_mapping(
        ["Asset Name", "TIER", "PCI DSS - SCOPE", "ENVIRONMENT TYPE"], res.all_columns, resource="it-assets"
    )
    by_heading = {m.source: m.target for m in suggestions}
    assert by_heading["TIER"] == "tier"
    assert by_heading["PCI DSS - SCOPE"] == "pci_scope"
    assert by_heading["ENVIRONMENT TYPE"] == "environment"


def test_the_risk_export_carries_the_asset_columns_and_an_import_ignores_them():
    res = REGISTRY["risks"]
    headers = {c.header for c in res.all_columns}
    assert set(ir._RISK_ASSET_COLUMNS) <= headers
    payload = {"title": "x", "asset_value": "4", "asset_tier": "1", "inherent_business_impact": "80",
               "inherent_business_rating": "critical"}
    assert res.prepare(payload) == []
    assert payload == {"title": "x"}


# ------------------------------------------------------------------ the bank's own risk IDs
def test_a_risk_may_carry_the_organisations_own_reference():
    from app.schemas.risk import RiskCreate

    assert RiskCreate(title="x").reference == ""
    assert RiskCreate(title="x", reference="ISR-014").reference == "ISR-014"
    with pytest.raises(ValidationError):
        RiskCreate(title="x", reference="R" * 33)


def test_the_risk_register_imports_and_exports_its_reference():
    cols = {c.header: c for c in REGISTRY["risks"].columns}
    assert cols["reference"].field == "reference"


_BANK_RISK_SHEET = [
    "S.No", "Risk ID", "Asset", "Threat", "Vulnerabilities", "Existing Controls", "Probability",
    "Severity", "Risk Value", "Asset Value", "Business Impact", "Risk Rating", "Proposed Controls",
    "Risk Owner", "Tier",
]


def test_a_banks_risk_id_becomes_the_reference_and_its_row_number_does_not():
    suggestions, unmapped, _ = suggest_mapping(_BANK_RISK_SHEET, REGISTRY["risks"].all_columns, resource="risks")
    by_heading = {m.source: m.target for m in suggestions}
    assert by_heading["Risk ID"] == "reference"
    assert "S.No" in unmapped
    assert by_heading["Asset"] == "assets" and by_heading["Risk Owner"] == "risk_owner"
    assert by_heading["Proposed Controls"] == "treatment_description"
    # Their computed columns are ours to compute: read-only here, or left unmapped.
    assert by_heading["Asset Value"] == "asset_value"
    assert {"Risk Value", "Risk Rating"} <= set(unmapped)


@pytest.mark.parametrize("resource,heading", [("risks", "Sr#"), ("controls", "S.No"), ("risks", "Serial No")])
def test_a_row_counter_is_never_taken_for_the_record_id(resource, heading):
    suggestions, _, _ = suggest_mapping([heading, "Title"], REGISTRY[resource].all_columns, resource=resource)
    assert all(m.target != "reference" for m in suggestions)


# ------------------------------------------------------------------ a register with no title column
def test_an_asset_based_row_is_titled_by_its_threat_and_asset():
    from app.services.risk_integrity import compose_asset_title

    assert compose_asset_title(["Ransomware"], [], ["Core banking DB"]) == "Ransomware affecting Core banking DB"
    assert compose_asset_title(["ransomware", "Phishing"], [], []) == "Ransomware and Phishing"
    assert compose_asset_title([], ["Unpatched OS"], ["ATM switch"]) == "Unpatched OS affecting ATM switch"
    assert compose_asset_title(["A", "B", "C", "D"], [], ["X"]) == "A, B and 2 more affecting X"


def test_an_asset_alone_names_no_risk():
    from app.services.risk_integrity import compose_asset_title

    assert compose_asset_title([], [], ["Core banking DB"]) == ""


def test_a_composed_asset_title_fits_the_column():
    from app.services.risk_integrity import compose_asset_title

    assert len(compose_asset_title(["T" * 200], [], ["A" * 200])) <= 255
