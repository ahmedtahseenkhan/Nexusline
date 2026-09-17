"""Statement of Applicability (§1.6).

ISO/IEC 27001 6.1.3 d) requires every exclusion to be justified. These pin that rule,
how applicability maps onto the existing treatment/status fields (so the SoA and the gap
analysis can never disagree), the rows and counts, and that both exports render. Pure —
no database.
"""
import io
import uuid
from datetime import date
from types import SimpleNamespace as NS

import pytest

from app.models.enums import ComplianceStatus, ComplianceTreatment, ControlEffectiveness, ControlStatus
from app.models.enums import TestResult as Result
from app.services import soa_export as soa


def control(ref, name, eff=ControlEffectiveness.effective, tested=None, result=None):
    return NS(id=uuid.uuid4(), reference=ref, name=name, effectiveness=eff, status=ControlStatus.operational,
              last_audit_date=tested, last_audit_result=result, deleted=False)


def req(ref, title="Clause", *, treatment=None, status=ComplianceStatus.not_assessed, controls=(),
        justification="", deleted=False):
    return NS(id=uuid.uuid4(), reference=ref, title=title, domain="Annex A", treatment=treatment,
              status=status, controls=list(controls), applicability_justification=justification,
              coverage="unmapped" if not controls else "assured", deleted=deleted)


# --------------------------------------------------------------------- the rule ---
def test_excluding_a_clause_needs_a_justification():
    assert soa.applicability_error(False, None)
    assert soa.applicability_error(False, "   ")
    assert soa.applicability_error(False, "No cardholder data in scope") is None


def test_including_a_clause_does_not_need_one():
    assert soa.applicability_error(True, None) is None
    assert soa.applicability_error(True, "") is None


def test_either_not_applicable_field_excludes_the_clause():
    assert soa.is_applicable(None, ComplianceStatus.compliant)
    assert not soa.is_applicable(ComplianceTreatment.not_applicable, ComplianceStatus.not_assessed)
    assert not soa.is_applicable(None, ComplianceStatus.not_applicable)
    assert not soa.is_applicable("not_applicable", "compliant")


def test_excluding_sets_both_fields_so_the_gap_analysis_agrees():
    assert soa.applicability_changes(False, None, ComplianceStatus.partially_compliant) == {
        "treatment": "not_applicable", "status": "not_applicable",
    }


def test_including_resets_only_what_said_not_applicable():
    assert soa.applicability_changes(True, ComplianceTreatment.not_applicable, ComplianceStatus.not_applicable) == {
        "treatment": None, "status": "not_assessed",
    }
    # A real assessment is never touched by toggling a clause in.
    assert soa.applicability_changes(True, ComplianceTreatment.implement, ComplianceStatus.compliant) == {}
    assert soa.applicability_changes(True, ComplianceTreatment.not_applicable, ComplianceStatus.compliant) == {
        "treatment": None,
    }


def test_reincluding_without_text_clears_the_exclusion_reason():
    assert soa.justification_after(True, False, "No card data", None) == ""
    assert soa.justification_after(True, True, "Core to operations", None) == "Core to operations"
    assert soa.justification_after(False, True, "", "  Out of scope  ") == "Out of scope"
    assert soa.justification_after(True, False, "old", "Now in scope") == "Now in scope"


# ------------------------------------------------------------------------ rows ---
def test_rows_are_in_clause_order_and_skip_archived():
    rows = soa.build_rows([req("A.5.10"), req("A.5.9"), req("4.1"), req("A.8.1", deleted=True)])
    assert [r.reference for r in rows] == ["4.1", "A.5.9", "A.5.10"]


def test_a_row_carries_controls_and_the_latest_test():
    old = control("CTL-2", "Token MFA", tested=date(2026, 3, 1), result=Result.failed)
    new = control("A.8.5", "Secure authentication", tested=date(2026, 8, 1), result=Result.passed)
    row = soa.build_row(req("A.8.5", "Secure authentication", controls=[old, new], justification="Remote access"))
    assert row.applicable and row.justification == "Remote access"
    assert [c.reference for c in row.controls] == ["A.8.5", "CTL-2"]
    assert row.last_test_date == date(2026, 8, 1) and row.last_test_result == "passed"
    assert row.controls[0].effectiveness == "effective"
    assert "last tested 2026-08-01 (passed)" in row.controls[0].label()


def test_summary_and_filters():
    rows = soa.build_rows([
        req("A.5.1", controls=[control("A.5.1", "Policy")]),
        req("A.5.2"),
        req("A.5.23", treatment=ComplianceTreatment.not_applicable, justification="No cloud services"),
        req("A.7.4", status=ComplianceStatus.not_applicable),  # excluded before the rule
    ])
    assert soa.summarize(rows) == {
        "total": 4, "applicable": 2, "excluded": 2, "no_control": 1, "missing_justification": 1,
        "mapped": 1, "assured": 1,
    }
    assert [r.reference for r in soa.filter_rows(rows, "applicable")] == ["A.5.1", "A.5.2"]
    assert [r.reference for r in soa.filter_rows(rows, "excluded")] == ["A.5.23", "A.7.4"]
    assert [r.reference for r in soa.filter_rows(rows, "no_control")] == ["A.5.2"]
    assert len(soa.filter_rows(rows, "all")) == 4


# --------------------------------------------------------------------- exports ---
def _doc(view="all"):
    rows = soa.build_rows([
        req("A.5.1", "Policies & <rules>", controls=[control("A.5.1", "Policy set", tested=date(2026, 7, 1),
                                                          result=Result.passed)]),
        req("A.5.23", "Cloud services", treatment=ComplianceTreatment.not_applicable,
            justification="No cloud services in use"),
    ])
    return soa.SoaDocument(
        org_name="Example Bank & Co", framework_name="ISO/IEC 27001:2022", version="2022",
        rows=soa.filter_rows(rows, view), summary=soa.summarize(rows), view=view,
    )


def test_xlsx_export_has_the_header_block_and_one_row_per_clause():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(soa.to_xlsx(_doc())))
    ws = wb.active
    values = [[c.value for c in row] for row in ws.iter_rows()]
    flat = [v for row in values for v in row if v]
    assert "Example Bank & Co" in flat and "ISO/IEC 27001:2022" in flat and "2022" in flat
    header_row = next(i for i, row in enumerate(values) if row[0] == "Reference")
    body = [row for row in values[header_row + 1:] if row[0]]
    assert [row[0] for row in body] == ["A.5.1", "A.5.23"]
    assert body[1][3] == "No" and body[1][4] == "No cloud services in use"


def test_a_filtered_export_says_so_and_keeps_whole_framework_counts():
    openpyxl = pytest.importorskip("openpyxl")
    ws = openpyxl.load_workbook(io.BytesIO(soa.to_xlsx(_doc("excluded")))).active
    flat = [c.value for row in ws.iter_rows() for c in row if c.value]
    assert "Excluded clauses only" in flat
    assert any(isinstance(v, str) and v.startswith("2 — 1 applicable, 1 excluded") for v in flat)


def test_pdf_export_renders_and_escapes_markup():
    pytest.importorskip("reportlab")
    data = soa.to_pdf(_doc())
    assert data.startswith(b"%PDF")
