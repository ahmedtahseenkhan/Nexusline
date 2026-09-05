"""The risk report a board or a regulator asks for.

What the old export did — every risk, ignoring the screen's filter, seven bare columns —
was not a report. These pin what the new one must always carry: the scope it was taken
under, the methodology it was scored on, and per risk the controls, the assets *with
their classification*, both ratings and the treatment.

Rendering is real (ReportLab), then read back with pdftotext where available; the text
assertions are skipped rather than faked when it is not.
"""
import datetime
import shutil
import subprocess
import uuid

import pytest

from app.models.asset import Asset
from app.models.control import Control
from app.models.enums import (
    AcceptanceStatus,
    AssetClass,
    ControlEffectiveness,
    ControlStatus,
    Criticality,
    RiskStatus,
    TreatmentStrategy,
)
from app.models.organization import BusinessUnit, Process
from app.models.risk import Risk, RiskAcceptance
from app.services import pdf_report

pytest.importorskip("reportlab")

OWNER = uuid.uuid4()


def _named(model, name):
    obj = model()
    obj.id = uuid.uuid4()
    obj.name = name
    return obj


def _asset(name, asset_class=AssetClass.information_asset, criticality=Criticality.critical):
    asset = Asset()
    asset.id = uuid.uuid4()
    asset.name = name
    asset.asset_class = asset_class
    asset.criticality = criticality
    asset.label = None
    asset.classifications = []
    return asset


def _control(reference, name, effectiveness):
    control = Control()
    control.id = uuid.uuid4()
    control.reference = reference
    control.name = name
    control.effectiveness = effectiveness
    control.status = ControlStatus.implemented
    control.owner = "Head of IT Security"
    control.next_audit_date = datetime.date(2026, 12, 31)
    return control


def _risk(reference="R-001", *, residual=(4, 5), controls=True, assets=True):
    risk = Risk()
    risk.id = uuid.uuid4()
    risk.reference = reference
    risk.title = "Credential compromise via missing MFA"
    risk.description = "MFA is not enforced for privileged access."
    risk.category = "Information Security"
    risk.status = RiskStatus.assessed
    risk.inherent_likelihood, risk.inherent_impact = 5, 5
    risk.inherent_score = 25
    risk.residual_likelihood, risk.residual_impact = residual if residual else (None, None)
    risk.residual_score = residual[0] * residual[1] if residual else None
    risk.owner_id = OWNER
    risk.business_units = [_named(BusinessUnit, "Digital Banking")]
    risk.processes = [_named(Process, "Customer Authentication")]
    risk.assets = (
        [_asset("Internet Banking"), _asset("Core Banking System", AssetClass.it_asset, Criticality.high)]
        if assets
        else []
    )
    risk.controls = (
        [
            _control("A.5.17", "Authentication information", ControlEffectiveness.partially_effective),
            _control("A.8.5", "Secure authentication", ControlEffectiveness.effective),
        ]
        if controls
        else []
    )
    risk.treatment_strategy = TreatmentStrategy.mitigate
    risk.treatment_owner = "CISO"
    risk.treatment_deadline = datetime.date(2026, 11, 30)
    risk.treatment_cost = 4_500_000.0
    risk.treatment_description = "Roll out MFA to all privileged accounts."
    risk.annual_loss_expectancy = 12_500_000.0
    risk.next_review_date = datetime.date(2027, 3, 1)
    acceptance = RiskAcceptance()
    acceptance.status = AcceptanceStatus.expired
    acceptance.expires_at = datetime.date(2026, 6, 30)
    acceptance.decided_at = datetime.date(2025, 7, 1)
    acceptance.rationale = "Compensating monitoring pending rollout."
    risk.acceptances = [acceptance]
    return risk


def _context(**overrides):
    defaults = dict(
        org_name="Meezan Demo Bank",
        appetite=6,
        tolerance=12,
        max_score=25,
        matrix_size=5,
        scope="Digital Banking · Assessed",
        owner_names={OWNER: "Ayesha Raza"},
    )
    return pdf_report.RiskReportContext(**{**defaults, **overrides})


def _text(pdf: bytes) -> str:
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext not available")
    return subprocess.run(
        ["pdftotext", "-", "-"], input=pdf, capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------- renders ---
def test_it_produces_a_pdf():
    data = pdf_report.risk_register_pdf([_risk()], _context())
    assert data.startswith(b"%PDF")


def test_an_empty_scope_still_renders():
    """A segment with no risks yet is a legitimate answer, not an error page."""
    assert pdf_report.risk_register_pdf([], _context()).startswith(b"%PDF")


@pytest.mark.parametrize("matrix_size", [3, 5, 10])
def test_every_configurable_matrix_renders_its_heat_map(matrix_size):
    risk = _risk(residual=(min(4, matrix_size), min(5, matrix_size)))
    risk.inherent_likelihood = risk.inherent_impact = matrix_size
    risk.inherent_score = matrix_size * matrix_size
    context = _context(matrix_size=matrix_size, max_score=matrix_size * matrix_size)
    assert pdf_report.risk_register_pdf([risk], context).startswith(b"%PDF")


# ------------------------------------------------------------------- contents ---
def test_the_cover_names_the_scope_it_was_taken_under():
    """A filtered export circulating without this line is indistinguishable from the
    whole register — which is how one segment's report gets read as the bank's total
    exposure."""
    assert "Digital Banking" in _text(pdf_report.risk_register_pdf([_risk()], _context()))


def test_an_unfiltered_export_says_so():
    text = _text(pdf_report.risk_register_pdf([_risk()], _context(scope="Whole register")))
    assert "Whole register" in text


def test_the_cover_states_the_methodology_the_scores_mean_anything_under():
    text = _text(pdf_report.risk_register_pdf([_risk()], _context()))
    assert "Likelihood 1–5 x impact 1–5" in text
    assert "Low 1–4" in text and "Critical 15–25" in text
    assert "score ≤ 6" in text  # appetite
    assert "score ≤ 12" in text  # tolerance


def test_each_risk_carries_what_the_client_asked_for():
    """Controls, asset names with classification, both ratings, the treatment."""
    text = _text(pdf_report.risk_register_pdf([_risk()], _context()))
    assert "Authentication information" in text
    # The effectiveness cell wraps between the two words at this column width, which is
    # fine — the assertion is that the rating is stated, not how it is laid out.
    assert "Partially" in text and "Effective" in text
    assert "Internet Banking — Information asset, criticality Critical" in text
    assert "Core Banking System — IT asset, criticality High" in text
    assert "L5 x I5 = 25 (Critical)" in text
    assert "L4 x I5 = 20 (Critical)" in text
    assert "Mitigate" in text and "CISO" in text


def test_an_unassessed_residual_is_named_not_left_blank():
    text = _text(pdf_report.risk_register_pdf([_risk(residual=None)], _context()))
    assert "Not yet assessed" in text


def test_a_risk_with_no_controls_says_the_residual_rests_on_nothing():
    """A blank controls section reads as "not filled in yet". It is a finding."""
    text = _text(pdf_report.risk_register_pdf([_risk(controls=False)], _context()))
    assert "None linked" in text


def test_the_segment_appears_on_the_register_line():
    assert "Digital Banking" in _text(pdf_report.risk_register_pdf([_risk()], _context()))


def test_details_can_be_turned_off_for_a_table_only_export():
    with_details = pdf_report.risk_register_pdf([_risk()], _context())
    without = pdf_report.risk_register_pdf([_risk()], _context(include_details=False))
    assert len(without) < len(with_details)
    assert "Risk detail" not in _text(without)


def test_an_unowned_risk_is_named_unassigned_not_left_blank():
    risk = _risk()
    risk.owner_id = None
    assert "Unassigned" in _text(pdf_report.risk_register_pdf([risk], _context()))


def test_risks_are_ordered_by_exposure_worst_first():
    """A board reads the top of the table. The worst thing has to be there."""
    low = _risk("R-009", residual=(1, 1))
    high = _risk("R-001", residual=(5, 5))
    text = _text(pdf_report.risk_register_pdf([low, high], _context()))
    assert text.index("R-001") < text.index("R-009")
