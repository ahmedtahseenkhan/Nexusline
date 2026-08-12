"""Column-mapping rules for the smart import wizard.

These are the rules that decide where a client's data lands. A regression here does not
crash anything — it silently loads the wrong column into the wrong field, which is the
worst possible failure mode for an import. So the matching tiers, the one-to-one
assignment guarantee and the banner-row detection are all pinned here.
"""
import io
from datetime import date

import pytest
from fastapi import HTTPException

from app.api.v1.dataio import _validated_mapping
from app.models.asset import Asset
from app.models.internal_audit import AuditEngagement
from app.models.operational_risk import KeyRiskIndicator
from app.models.risk import Risk
from app.services.import_mapping import (
    apply_mapping,
    custom_field_model_key,
    load_csv,
    load_xlsx,
    normalise,
    suggest_mapping,
)
from app.services.import_registry import REGISTRY

RISKS = REGISTRY["risks"]


def _mapping(headers: list[str], resource: str = "risks") -> dict[str, str]:
    """suggest_mapping reduced to ``{their header: our header}``."""
    suggestions, _, _ = suggest_mapping(headers, REGISTRY[resource].columns, resource=resource)
    return {s.source: s.target for s in suggestions}


# --------------------------------------------------------------- normalise ---
def test_normalise_folds_case_punctuation_and_numbering():
    assert normalise("Risk_Description") == "risk description"
    assert normalise("  RISK DESCRIPTION  ") == "risk description"
    assert normalise("2) Risk Description") == "risk description"
    assert normalise("Impact (1-5)") == "impact"
    assert normalise("Inherent Likelihood / Probability") == "inherent likelihood probability"


# ------------------------------------------------------- suggestion tiers ---
def test_exact_headers_map_to_themselves():
    headers = [c.header for c in RISKS.columns]
    mapping = _mapping(headers)
    assert mapping == {h: h for h in headers}


def test_case_and_punctuation_variants_map():
    mapping = _mapping(["Risk_Title", "DESCRIPTION", "  category  "])
    assert mapping["Risk_Title"] == "title"
    assert mapping["DESCRIPTION"] == "description"
    assert mapping["  category  "] == "category"


def test_domain_synonyms_map():
    """The phrasings that actually appear in bank risk registers."""
    mapping = _mapping(
        [
            "Risk Description",
            "Probability",
            "Consequence",
            "Existing Controls",
            "Mitigation Plan",
            "Target Date",
        ]
    )
    assert mapping["Risk Description"] == "description"
    assert mapping["Probability"] == "inherent_likelihood"
    assert mapping["Consequence"] == "inherent_impact"
    assert mapping["Existing Controls"] == "controls"
    assert mapping["Mitigation Plan"] == "treatment_description"
    assert mapping["Target Date"] == "treatment_deadline"


def test_residual_columns_do_not_collide_with_inherent():
    """'Likelihood' and 'Residual Likelihood' in one sheet must land in different fields."""
    mapping = _mapping(["Likelihood", "Impact", "Residual Likelihood", "Residual Impact"])
    assert mapping["Likelihood"] == "inherent_likelihood"
    assert mapping["Impact"] == "inherent_impact"
    assert mapping["Residual Likelihood"] == "residual_likelihood"
    assert mapping["Residual Impact"] == "residual_impact"


def test_register_noun_is_discounted():
    """In a risk sheet, 'Risk Category' means category — the word 'Risk' carries no signal."""
    mapping = _mapping(["Risk Category", "Risk Owner", "Risk Status"])
    assert mapping["Risk Category"] == "category"
    assert mapping["Risk Status"] == "status"


def test_longer_header_containing_the_field_name_maps():
    mapping = _mapping(["Inherent Likelihood Score", "Treatment Strategy Selected"])
    assert mapping["Inherent Likelihood Score"] == "inherent_likelihood"
    assert mapping["Treatment Strategy Selected"] == "treatment_strategy"


def test_unrecognised_columns_are_reported_not_guessed():
    """A wrong silent mapping is worse than none — these must come back unmapped."""
    suggestions, unmapped, _ = suggest_mapping(
        ["Title", "Branch Manager Signature", "Zone Code XR7"], RISKS.columns, resource="risks"
    )
    mapped = {s.source for s in suggestions}
    assert "Title" in mapped
    assert "Branch Manager Signature" in unmapped
    assert "Zone Code XR7" in unmapped


def test_assignment_is_one_to_one_in_both_directions():
    """Two similar client columns may not both claim one field, and one column may not
    feed two fields."""
    headers = ["Risk Title", "Title", "Name", "Description", "Desc"]
    suggestions, _, _ = suggest_mapping(headers, RISKS.columns, resource="risks")
    sources = [s.source for s in suggestions]
    targets = [s.target for s in suggestions]
    assert len(sources) == len(set(sources))
    assert len(targets) == len(set(targets))


def test_confidence_bands_reflect_match_quality():
    suggestions, _, _ = suggest_mapping(
        ["title", "Probability"], RISKS.columns, resource="risks"
    )
    by_source = {s.source: s for s in suggestions}
    assert by_source["title"].band == "high"
    assert by_source["title"].confidence >= 0.97
    # A synonym is confident enough to preselect but still worth a glance.
    assert by_source["Probability"].confidence >= 0.85


def test_suggestions_are_deterministic():
    headers = ["Probability", "Consequence", "Risk Description", "Existing Controls"]
    assert _mapping(headers) == _mapping(headers)


def test_unfilled_targets_are_reported():
    _, _, unfilled = suggest_mapping(["Title"], RISKS.columns, resource="risks")
    assert "description" in unfilled
    assert "title" not in unfilled


# ----------------------------------------------------- other registers ------
def test_asset_sheet_headers_map():
    mapping = _mapping(["Asset Name", "Host", "IP", "Serial", "Site", "Business Owner"], "it-assets")
    assert mapping["Asset Name"] == "name"
    assert mapping["Host"] == "hostname"
    assert mapping["IP"] == "ip_address"
    assert mapping["Serial"] == "serial_number"
    assert mapping["Site"] == "location"


def test_audit_engagement_headers_map():
    mapping = _mapping(["Audit Title", "Scope", "Auditor", "From Date", "To Date"], "audit-engagements")
    assert mapping["Audit Title"] == "title"
    assert mapping["Scope"] == "scope"
    assert mapping["Auditor"] == "lead_auditor"
    assert mapping["From Date"] == "period_start"
    assert mapping["To Date"] == "period_end"


# ------------------------------------------------------- apply_mapping ------
def test_apply_mapping_rewrites_into_canonical_headers():
    row = {"Risk Description": "Data leak", "Probability": "4", "Zone": "North"}
    mapping = {"Risk Description": "description", "Probability": "inherent_likelihood"}
    assert apply_mapping(row, mapping) == {"description": "Data leak", "inherent_likelihood": "4"}


def test_apply_mapping_drops_unmapped_columns():
    """An unmapped column must be ignored outright — never matched by name downstream."""
    row = {"title": "Kept", "description": "Dropped because it is not in the mapping"}
    assert apply_mapping(row, {"title": "title"}) == {"title": "Kept"}


def test_apply_mapping_ignores_blank_targets():
    row = {"A": "1", "B": "2"}
    assert apply_mapping(row, {"A": "title", "B": ""}) == {"title": "1"}


# ------------------------------------------------------------ load_csv ------
def test_load_csv_reads_a_plain_file():
    table = load_csv("title,description\nPhishing,Staff targeted\n")
    assert table.headers == ["title", "description"]
    assert table.rows == [["Phishing", "Staff targeted"]]
    assert table.header_row_index == 0
    assert table.row_count == 1


def test_load_csv_skips_a_banner_row():
    """Client exports routinely open with a report title above the real header."""
    table = load_csv("Annexure-A: Risk Register\n\ntitle,description\nPhishing,Staff targeted\n")
    assert table.headers == ["title", "description"]
    assert table.header_row_index == 2
    assert table.rows == [["Phishing", "Staff targeted"]]


def test_load_csv_drops_blank_rows_and_pads_short_ones():
    table = load_csv("title,description,category\nA,B,C\n\nD,E\n")
    assert table.rows == [["A", "B", "C"], ["D", "E", ""]]


def test_load_csv_makes_blank_and_duplicate_headers_unique():
    table = load_csv("title,,title\n1,2,3\n")
    assert table.headers == ["title", "Column 2", "title (2)"]


def test_load_csv_reemits_canonical_csv():
    """The re-emitted CSV is what preview and import consume, so it must round-trip."""
    table = load_csv("Report\n\nTitle,Impact\nPhishing,5\n")
    assert load_csv(table.csv).rows == table.rows


# ----------------------------------------------------------- load_xlsx ------
def _workbook(rows: list[list[object]], *, sheets: dict[str, list[list[object]]] | None = None) -> bytes:
    """Build an in-memory .xlsx so the Excel path is tested for real, not mocked."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    for row in rows:
        sheet.append(row)
    for name, extra_rows in (sheets or {}).items():
        other = book.create_sheet(name)
        for row in extra_rows:
            other.append(row)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def test_load_xlsx_reads_the_first_sheet():
    table = load_xlsx(_workbook([["title", "description"], ["Phishing", "Staff targeted"]]))
    assert table.headers == ["title", "description"]
    assert table.rows == [["Phishing", "Staff targeted"]]
    assert table.sheet == "Sheet1"


def test_load_xlsx_keeps_whole_numbers_integral():
    """Excel stores 3 as 3.0; passing '3.0' downstream fails integer coercion."""
    table = load_xlsx(_workbook([["inherent_likelihood"], [3]]))
    assert table.rows == [["3"]]


def test_load_xlsx_renders_dates_as_iso():
    table = load_xlsx(_workbook([["treatment_deadline"], [date(2026, 3, 31)]]))
    assert table.rows == [["2026-03-31"]]


def test_load_xlsx_skips_a_banner_row():
    table = load_xlsx(_workbook([["Risk Register FY26"], [], ["title", "category"], ["Phishing", "Cyber"]]))
    assert table.headers == ["title", "category"]
    assert table.rows == [["Phishing", "Cyber"]]


def test_load_xlsx_lists_sheets_and_honours_the_choice():
    data = _workbook(
        [["title"], ["From sheet one"]], sheets={"Register": [["title"], ["From register"]]}
    )
    default = load_xlsx(data)
    assert default.sheet_names == ["Sheet1", "Register"]
    assert default.rows == [["From sheet one"]]
    chosen = load_xlsx(data, sheet="Register")
    assert chosen.sheet == "Register"
    assert chosen.rows == [["From register"]]


def test_load_xlsx_falls_back_when_the_named_sheet_is_missing():
    table = load_xlsx(_workbook([["title"], ["A"]]), sheet="Nope")
    assert table.sheet == "Sheet1"


def test_load_xlsx_rejects_a_non_workbook_with_a_clean_message():
    with pytest.raises(ValueError, match="Could not read the Excel file"):
        load_xlsx(b"this is not a workbook")


def test_xlsx_and_csv_paths_agree():
    """Both loaders feed the same canonical CSV, so a mapping works either way."""
    rows = [["Risk Title", "Probability"], ["Phishing", 4]]
    from_xlsx = load_xlsx(_workbook(rows))
    from_csv = load_csv("Risk Title,Probability\nPhishing,4\n")
    assert from_xlsx.csv == from_csv.csv


# ------------------------------------------------ mapping validation --------
def test_validated_mapping_passes_a_clean_mapping():
    mapping = {"Risk Desc": "description", "Probability": "inherent_likelihood"}
    assert _validated_mapping(RISKS, mapping) == mapping


def test_validated_mapping_drops_blank_targets():
    assert _validated_mapping(RISKS, {"A": "title", "B": ""}) == {"A": "title"}


def test_validated_mapping_rejects_an_unknown_target_column():
    with pytest.raises(HTTPException) as exc:
        _validated_mapping(RISKS, {"A": "not_a_real_field"})
    assert exc.value.status_code == 422
    assert "not_a_real_field" in exc.value.detail


def test_validated_mapping_rejects_two_columns_feeding_one_field():
    """Silently letting the last one win would make an import non-deterministic."""
    with pytest.raises(HTTPException) as exc:
        _validated_mapping(RISKS, {"Desc": "description", "Details": "description"})
    assert exc.value.status_code == 422
    assert "description" in exc.value.detail


def test_validated_mapping_of_nothing_is_nothing():
    """No mapping means the legacy path: the file's own headers must be canonical."""
    assert _validated_mapping(RISKS, {}) == {}


# --------------------------------------------------- custom field key -------
def test_custom_field_model_key_matches_the_registry_names():
    from app.models.custom_field import CUSTOM_FIELD_MODELS

    assert custom_field_model_key(Risk) == "risk"
    assert custom_field_model_key(Asset) == "asset"
    assert custom_field_model_key(AuditEngagement) == "audit_engagement"
    assert custom_field_model_key(KeyRiskIndicator) == "key_risk_indicator"
    for model in (Risk, Asset, AuditEngagement, KeyRiskIndicator):
        assert custom_field_model_key(model) in CUSTOM_FIELD_MODELS


def test_exception_register_uses_its_overridden_key():
    """``ExceptionRecord`` is registered for custom fields as ``exception``. Deriving
    ``exception_record`` would reject custom-field mapping on a register that supports it."""
    from app.models.custom_field import CUSTOM_FIELD_MODELS
    from app.models.exception import ExceptionRecord

    assert custom_field_model_key(ExceptionRecord) == "exception"
    assert custom_field_model_key(ExceptionRecord) in CUSTOM_FIELD_MODELS


def test_importable_resources_derive_a_known_custom_field_model():
    """Custom-field mapping is offered per resource; a derived key missing from the
    registry means that register 422s on custom fields. Only registers that genuinely
    have no custom-field support may appear here — pinned so a new mismatch is caught at
    build time rather than by a client mid-import."""
    from app.models.custom_field import CUSTOM_FIELD_MODELS

    missing = sorted(
        {
            custom_field_model_key(res.model)
            for res in REGISTRY.values()
            if res.importable and custom_field_model_key(res.model) not in CUSTOM_FIELD_MODELS
        }
    )
    # ``risk_scenario_template`` is configuration rather than a record users annotate,
    # so it deliberately has no custom fields.
    assert missing == ["evidence", "obligation", "risk_scenario_template"]
