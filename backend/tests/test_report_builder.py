"""The report builder: registry integrity, filters as SQL, and the exports.

The promise being pinned: a report definition — subject, filters, columns, sort — is
declarative, compiles to one SQL statement, and renders the same rows to the screen,
the PDF and the spreadsheet. Everything here is DB-free: statements are compiled and
their SQL read, exports are rendered into memory and read back.
"""
import datetime
import io
import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.models.enums import (
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    RiskStatus,
    TreatmentStrategy,
)
from app.models.organization import BusinessUnit
from app.models.risk import Risk
from app.services import report_builder as rb
from app.services import report_export

TODAY = datetime.date(2026, 9, 5)


def sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def ctx(**kw) -> rb.ReportContext:
    base = dict(org_name="Meezan Demo Bank", appetite=6, tolerance=12, max_score=25, matrix_size=5, today=TODAY)
    return rb.ReportContext(**{**base, **kw})


# ------------------------------------------------------------------ registry ---
@pytest.mark.parametrize("subject", list(rb.SUBJECTS.values()), ids=lambda s: s.key)
def test_every_subject_is_internally_consistent(subject):
    keys = [c.key for c in subject.columns]
    assert len(keys) == len(set(keys)), "duplicate column keys"
    assert subject.default_sort in subject.column_map
    assert subject.column_map[subject.default_sort].sort is not None, "default sort must be sortable"
    assert any(c.default for c in subject.columns), "no default column set"
    for f in subject.filters:
        assert f.kind in ("select", "multiselect", "typeahead", "date", "bool", "text"), f.key
        if f.kind == "typeahead":
            assert f.source, f"{f.key}: typeahead needs a source"
        if f.kind in ("select", "multiselect", "bool"):
            assert f.options, f"{f.key}: needs options"


def test_the_catalogue_is_what_the_ui_builds_from():
    cat = {s["key"]: s for s in rb.catalog()}
    assert set(cat) == {"risks", "controls", "incidents"}
    risks = cat["risks"]
    assert risks["has_detail"] is True
    assert {"key", "label", "default", "sortable"} <= set(risks["columns"][0])
    assert {"key", "label", "kind", "options", "source", "help"} <= set(risks["filters"][0])


def test_default_columns_are_used_when_none_are_chosen():
    chosen = rb.selected_columns(rb.RISKS, [])
    assert chosen == [c for c in rb.RISKS.columns if c.default]


def test_chosen_columns_keep_their_order_and_drop_unknowns():
    """A report saved before a column was retired must still run."""
    chosen = rb.selected_columns(rb.RISKS, ["title", "retired_column", "reference"])
    assert [c.key for c in chosen] == ["title", "reference"]


# ---------------------------------------------------------------- risk SQL ---
def test_no_filters_is_the_live_register():
    text = sql(rb.build_statement(rb.RISKS, {}, ctx()))
    assert "deleted" in text
    assert "BETWEEN" not in text and "EXISTS" not in text.upper()


def test_severity_bands_follow_the_tenants_matrix():
    """"Critical" is 15-25 on a 5x5 and 57-100 on a 10x10 — the same word the heat map
    uses, so a report and the register can never disagree about what critical means."""
    five = sql(rb.build_statement(rb.RISKS, {"inherent_severity": ["critical"]}, ctx(max_score=25)))
    assert "BETWEEN 15 AND 25" in five
    ten = sql(rb.build_statement(rb.RISKS, {"inherent_severity": ["critical"]}, ctx(max_score=100)))
    assert "BETWEEN 57 AND 100" in ten


def test_several_bands_or_together():
    text = sql(rb.build_statement(rb.RISKS, {"residual_severity": ["high", "critical"]}, ctx()))
    assert "BETWEEN 10 AND 14" in text and "BETWEEN 15 AND 25" in text
    assert " OR " in text


def test_appetite_breach_uses_the_effective_score():
    """Residual where assessed, otherwise inherent — the exposure the board is asked about."""
    text = sql(rb.build_statement(rb.RISKS, {"appetite_status": ["breach"]}, ctx(tolerance=12)))
    assert "coalesce(risks.residual_score, risks.inherent_score) > 12" in text


def test_elevated_is_between_appetite_and_tolerance():
    text = sql(rb.build_statement(rb.RISKS, {"appetite_status": ["elevated"]}, ctx(appetite=6, tolerance=12)))
    assert "> 6" in text and "<= 12" in text


def test_review_overdue_compares_to_today():
    text = sql(rb.build_statement(rb.RISKS, {"review_overdue": "true"}, ctx()))
    assert "next_review_date < '2026-09-05'" in text


def test_not_overdue_includes_risks_with_no_review_date():
    text = sql(rb.build_statement(rb.RISKS, {"review_overdue": "false"}, ctx()))
    assert "next_review_date IS NULL" in text and ">= '2026-09-05'" in text


def test_has_controls_is_an_exists_and_its_negation():
    with_ = sql(rb.build_statement(rb.RISKS, {"has_controls": True}, ctx()))
    without = sql(rb.build_statement(rb.RISKS, {"has_controls": False}, ctx()))
    assert "EXISTS" in with_ and "risk_controls" in with_ and "NOT (EXISTS" not in with_
    assert "NOT (EXISTS" in without


def test_segment_filters_reuse_the_registers_query_builder():
    """The screen and the report agree by construction, not by discipline."""
    bu = uuid.uuid4()
    text = sql(rb.build_statement(rb.RISKS, {"business_unit_id": str(bu)}, ctx()))
    assert "risk_business_units" in text and "EXISTS" in text and " JOIN " not in text.upper()


def test_multi_status_becomes_an_in_list():
    text = sql(rb.build_statement(rb.RISKS, {"status": ["assessed", "accepted"]}, ctx()))
    assert "risks.status IN" in text


def test_date_ranges_bound_created_and_review():
    text = sql(rb.build_statement(
        rb.RISKS,
        {"created_from": "2026-01-01", "created_to": "2026-06-30", "review_from": "2026-09-01"},
        ctx(),
    ))
    assert ">= '2026-01-01'" in text and "<= '2026-06-30'" in text and "next_review_date >= '2026-09-01'" in text


def test_empties_unknowns_and_garbage_are_ignored_not_fatal():
    """A saved report must survive a retired filter, a blank, and a bad uuid."""
    text = sql(rb.build_statement(
        rb.RISKS,
        {"status": [], "asset_id": "not-a-uuid", "retired_filter": "x", "category": "", "review_overdue": "any"},
        ctx(),
    ))
    assert "EXISTS" not in text.upper() and "status IN" not in text and "ILIKE" not in text
    assert "WHERE risks.deleted IS false" in text and "AND" not in text.split("WHERE")[1]


# ------------------------------------------------------------- control SQL ---
def test_controls_mitigating_a_risk_is_an_exists_on_the_join():
    text = sql(rb.build_statement(rb.CONTROLS, {"risk_id": str(uuid.uuid4())}, ctx()))
    assert "risk_controls" in text and "EXISTS" in text


def test_control_effectiveness_and_test_overdue():
    text = sql(rb.build_statement(
        rb.CONTROLS, {"effectiveness": ["ineffective", "not_assessed"], "audit_overdue": "true"}, ctx()
    ))
    assert "controls.effectiveness IN" in text and "next_audit_date < '2026-09-05'" in text


# ------------------------------------------------------------ incident SQL ---
def test_incident_filters_compile():
    text = sql(rb.build_statement(
        rb.INCIDENTS,
        {"is_reportable": "true", "resolved": "false", "occurred_from": "2026-07-01",
         "severity": ["high", "critical"], "asset_id": str(uuid.uuid4())},
        ctx(),
    ))
    assert "is_reportable IS true" in text
    assert "resolved_at IS NULL" in text
    assert "occurred_at >= '2026-07-01'" in text
    assert "incidents.severity IN" in text
    assert "assets_incidents" in text and "EXISTS" in text


# --------------------------------------------------------------------- sort ---
def test_sort_falls_back_to_the_default_rather_than_erroring():
    stmt = rb.build_statement(rb.RISKS, {}, ctx())
    text = sql(rb.apply_sort(rb.RISKS, stmt, "assets", "desc"))  # not sortable
    assert "ORDER BY risks.inherent_score DESC" in text


def test_sortable_columns_sort_in_the_direction_asked():
    stmt = rb.build_statement(rb.RISKS, {}, ctx())
    assert "ORDER BY risks.next_review_date ASC" in sql(rb.apply_sort(rb.RISKS, stmt, "next_review_date", "asc"))


# ------------------------------------------------------------- rendering ----
def _risk(**kw):
    r = Risk()
    r.id = uuid.uuid4()
    r.reference, r.title, r.category = "R-001", "Credential compromise", "InfoSec"
    r.status = RiskStatus.assessed
    r.inherent_likelihood, r.inherent_impact, r.inherent_score = 5, 5, 25
    r.residual_likelihood, r.residual_impact, r.residual_score = 4, 5, 20
    r.owner_id = kw.get("owner_id")
    r.treatment_strategy = TreatmentStrategy.mitigate
    r.business_units = [_named(BusinessUnit, "Digital Banking")]
    r.processes, r.assets, r.controls = [], [], []
    r.next_review_date = datetime.date(2027, 3, 1)
    r.created_at = datetime.datetime(2026, 1, 15, 9, 0)
    r.description = ""
    r.annual_loss_expectancy = None
    r.treatment_owner, r.treatment_deadline, r.last_review_date = "", None, None
    return r


def _named(model, name):
    o = model()
    o.id = uuid.uuid4()
    o.name = name
    return o


def test_risk_rows_render_the_same_values_the_screen_shows():
    owner = uuid.uuid4()
    c = ctx(names={str(owner): "Ayesha Raza"})
    cols = rb.selected_columns(rb.RISKS, ["reference", "inherent", "inherent_severity", "residual_severity",
                                          "appetite", "owner", "business_units"])
    [row] = rb.render_rows(rb.RISKS, cols, [_risk(owner_id=owner)], c)
    assert row["cells"] == {
        "reference": "R-001", "inherent": "5x5=25", "inherent_severity": "Critical",
        "residual_severity": "Critical", "appetite": "Breach", "owner": "Ayesha Raza",
        "business_units": "Digital Banking",
    }


def test_summary_counts_the_whole_set_by_severity_status_and_appetite():
    s = rb.RISKS.summarize([_risk(), _risk()], ctx())
    assert s["By severity"] == {"Critical": 2}
    assert s["By status"] == {"Assessed": 2}
    assert s["Against appetite"] == {"Breach": 2}


def test_filter_description_reads_like_a_person_wrote_it():
    bu = uuid.uuid4()
    c = ctx(names={str(bu): "Digital Banking"})
    described = rb.describe_filters(
        rb.RISKS,
        {"business_unit_id": str(bu), "status": ["assessed", "treatment_in_progress"],
         "review_overdue": "true", "created_from": "2026-01-01", "category": "", "search": None},
        c,
    )
    assert described == [
        ("Business unit", "Digital Banking"),
        ("Status", "Assessed, Treatment In Progress"),
        ("Review overdue", "Yes"),
        ("Created from", "2026-01-01"),
    ]


def test_id_filters_name_their_models_for_resolution():
    bu, asset = uuid.uuid4(), uuid.uuid4()
    found = rb.id_filter_models(rb.RISKS, {"business_unit_id": str(bu), "asset_id": str(asset), "owner_id": "junk"})
    assert {(k, m.__name__) for k, m, _ in found} == {("business_unit_id", "BusinessUnit"), ("asset_id", "Asset")}


# ------------------------------------------------------------------ exports ---
HEADERS = ["Ref", "Risk", "Inherent", "Ctrls"]
ROWS = [["R-001", "Credential compromise", "5x5=25", 2], ["R-002", "Outage", "3x5=15", 0]]
PARAMS = [("Business unit", "Digital Banking"), ("Status", "Assessed")]
SUMMARY = {"By severity": {"Critical": 1, "High": 1}}


def test_csv_has_the_header_row_and_every_row():
    text = report_export.to_csv(HEADERS, ROWS)
    lines = text.strip().splitlines()
    assert lines[0].startswith("Ref,Risk,Inherent,Ctrls")
    assert len(lines) == 3


def test_excel_carries_the_report_and_its_parameters():
    """A spreadsheet without its parameters becomes "the register" in someone's inbox."""
    openpyxl = pytest.importorskip("openpyxl")
    data = report_export.to_xlsx(
        title="Critical risks — Digital Banking", org_name="Meezan Demo Bank", subject_label="Risks",
        run_by="Ayesha Raza", params=PARAMS, summary=SUMMARY, headers=HEADERS, rows=ROWS,
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Report", "Parameters"]
    report = wb["Report"]
    assert [c.value for c in report[1]] == HEADERS
    assert report["A2"].value == "R-001"
    assert report["D2"].value == 2 and isinstance(report["D2"].value, int)  # numbers stay numeric
    assert report.freeze_panes == "A2"
    params = {row[0].value: row[1].value for row in wb["Parameters"].iter_rows() if row[0].value}
    assert params["Report"] == "Critical risks — Digital Banking"
    assert params["  Business unit"] == "Digital Banking"
    assert params["  Critical"] == 1


def test_pdf_renders_upright_and_landscape():
    pytest.importorskip("reportlab")
    from app.services import pdf_report

    for landscape in (False, True):
        data = pdf_report.tabular_report_pdf(
            title="Critical risks", org_name="Meezan Demo Bank", subject_label="Risks", run_by="Ayesha Raza",
            params=PARAMS, summary=SUMMARY, headers=HEADERS, rows=[[str(v) for v in r] for r in ROWS],
            widths=[8, 26, 9, 5], landscape=landscape,
        )
        assert data.startswith(b"%PDF")


def test_pdf_with_no_rows_says_so_rather_than_rendering_nothing():
    pytest.importorskip("reportlab")
    from app.services import pdf_report

    data = pdf_report.tabular_report_pdf(
        title="Nothing", org_name="Meezan Demo Bank", subject_label="Risks", run_by="x",
        params=[], summary={}, headers=HEADERS, rows=[], widths=[1, 1, 1, 1],
    )
    assert data.startswith(b"%PDF")
