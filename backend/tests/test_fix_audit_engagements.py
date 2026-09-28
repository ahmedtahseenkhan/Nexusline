"""Internal audit — universe cycle, engagement links, findings consistency, the report.

Regressions from live verification: "next audit due" was never derived although the
form said so; a risk-accepted finding counted as open on the engagement but not in the
follow-up view; an engagement whose unit was archived could not be saved; the audit
frequency picker lacked values the API accepts; the engagement PDF left out who
performed the audit and what management agreed to do.
"""
from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 - populate mappers
from app.api.v1.internal_audit import (
    _OPEN_STATES,
    audited_on,
    field_changes,
    next_due_after_edit,
)
from app.models.enums import (
    AuditEngagementStatus,
    AuditFindingStatus,
    AuditProcedureResult,
    AuditType,
    ReviewFrequency,
    Severity,
)
from app.models.internal_audit import (
    RESOLVED_FINDING_STATES,
    AuditableUnit,
    AuditEngagement,
    AuditFinding,
    audit_finding_controls,
    derive_next_audit_due,
    live_finding_secondaryjoin,
)
from app.schemas.internal_audit import EngagementRead
from app.services import pdf_report

F = ReviewFrequency


# ------------------------------------------------------------ next audit due ---
def test_next_due_is_one_cycle_after_the_last_audit():
    assert derive_next_audit_due(F.annual, date(2025, 3, 1)) == date(2026, 3, 1)
    assert derive_next_audit_due(F.quarterly, date(2026, 1, 10)) == date(2026, 4, 10)
    assert derive_next_audit_due(F.fortnightly, date(2026, 1, 10)) == date(2026, 1, 24)


def test_never_audited_or_no_cycle_has_no_derived_date():
    assert derive_next_audit_due(F.annual, None) is None
    assert derive_next_audit_due(F.none, date(2026, 1, 1)) is None


def _unit(**kw) -> AuditableUnit:
    base = dict(name="Payroll", audit_frequency=F.annual,
                last_audited_date=date(2025, 3, 1), next_audit_due=date(2026, 3, 1))
    base.update(kw)
    return AuditableUnit(**base)


def test_changing_last_audited_rederives_when_the_form_echoes_the_old_due_date():
    unit = _unit()
    out = next_due_after_edit(unit, {"last_audited_date": date(2026, 2, 1), "next_audit_due": date(2026, 3, 1)})
    assert out["next_audit_due"] == date(2027, 2, 1)


def test_changing_frequency_rederives():
    out = next_due_after_edit(_unit(), {"audit_frequency": F.semiannual})
    assert out["next_audit_due"] == date(2025, 9, 1)


def test_a_due_date_typed_by_hand_is_kept():
    out = next_due_after_edit(_unit(), {"last_audited_date": date(2026, 2, 1), "next_audit_due": date(2026, 12, 31)})
    assert out["next_audit_due"] == date(2026, 12, 31)


def test_blanking_the_due_date_derives_it():
    out = next_due_after_edit(_unit(next_audit_due=date(2030, 1, 1)), {"next_audit_due": None})
    assert out["next_audit_due"] == date(2026, 3, 1)


def test_an_unrelated_edit_leaves_the_due_date_alone():
    out = next_due_after_edit(_unit(next_audit_due=date(2030, 1, 1)), {"name": "Payroll v2"})
    assert "next_audit_due" not in out


def test_a_closed_audit_counts_from_the_end_of_fieldwork():
    today = date(2026, 9, 25)
    e = AuditEngagement(title="x", actual_end=date(2026, 9, 1), report_date=date(2026, 9, 10))
    assert audited_on(e, today) == date(2026, 9, 1)
    assert audited_on(AuditEngagement(title="x", report_date=date(2026, 9, 10)), today) == date(2026, 9, 10)
    assert audited_on(AuditEngagement(title="x"), today) == today


# --------------------------------------------------------- open findings ---
def _engagement(*statuses) -> AuditEngagement:
    e = AuditEngagement(title="Payroll", status=AuditEngagementStatus.fieldwork)
    e.findings = [AuditFinding(title=f"F{i}", status=s) for i, s in enumerate(statuses)]
    return e


def test_a_risk_accepted_finding_is_not_open_on_the_engagement():
    e = _engagement(AuditFindingStatus.open, AuditFindingStatus.in_progress,
                    AuditFindingStatus.closed, AuditFindingStatus.risk_accepted)
    assert e.finding_count == 4
    assert e.open_finding_count == 2


def test_every_open_count_uses_one_definition():
    assert set(_OPEN_STATES) == set(RESOLVED_FINDING_STATES)
    assert set(RESOLVED_FINDING_STATES) == {AuditFindingStatus.closed, AuditFindingStatus.risk_accepted}


def test_findings_of_an_archived_audit_can_be_filtered_from_linked_records():
    sql = str(live_finding_secondaryjoin(audit_finding_controls).compile(dialect=postgresql.dialect()))
    assert "audit_engagements.deleted IS false" in sql
    assert "audit_finding_controls.audit_finding_id = audit_findings.id" in sql


# ----------------------------------------------------- archived unit link ---
def test_the_engagement_says_when_its_unit_was_archived():
    e = AuditEngagement(title="x")
    e.auditable_unit = AuditableUnit(name="Old branch", deleted=True)
    assert e.auditable_unit_name == "Old branch"
    assert e.auditable_unit_archived is True
    e.auditable_unit = None
    assert e.auditable_unit_name == "" and e.auditable_unit_archived is False
    assert {"auditable_unit_name", "auditable_unit_archived"} <= set(EngagementRead.model_fields)


# ------------------------------------------------------------ audit trail ---
def test_changes_record_before_and_after_for_changed_fields_only():
    f = AuditFinding(title="x", status=AuditFindingStatus.open, due_date=date(2026, 10, 1), action_owner="CFO")
    out = field_changes(f, {"status": AuditFindingStatus.in_progress, "due_date": date(2026, 11, 1), "action_owner": "CFO"})
    assert out == {
        "status": {"from": "open", "to": "in_progress"},
        "due_date": {"from": "2026-10-01", "to": "2026-11-01"},
    }


def test_the_module_logs_updates_and_deletes_not_only_creates():
    source = (Path(__file__).resolve().parents[1] / "app/api/v1/internal_audit.py").read_text()
    for fn in ("update_unit", "delete_unit", "update_engagement", "delete_engagement",
               "update_procedure", "delete_procedure", "update_finding", "delete_finding"):
        body = source.split(f"def {fn}(", 1)[1].split("\n@router", 1)[0]
        assert "audit_log.record(" in body, fn
    plan_source = (Path(__file__).resolve().parents[1] / "app/api/v1/audit_plan.py").read_text()
    for fn in ("add_plan_item", "update_plan_item", "delete_plan_item", "update_program",
               "add_step", "update_step", "delete_step"):
        body = plan_source.split(f"def {fn}(", 1)[1].split("\n@router", 1)[0]
        assert "audit_log.record(" in body, fn


# ------------------------------------------------------------- frontend enum ---
def test_the_frequency_picker_offers_every_frequency_the_api_accepts():
    page = Path(__file__).resolve().parents[2] / "frontend/app/(app)/internal-audit/page.tsx"
    if not page.exists():
        pytest.skip("frontend not present")
    match = re.search(r"const AUDIT_FREQ = opts\(\[([^\]]*)\]\)", page.read_text())
    assert match
    offered = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert offered == {f.value for f in ReviewFrequency}


# ------------------------------------------------------------------ report ---
def test_user_text_is_printed_not_parsed():
    assert pdf_report._esc("BID/1 <x> & y") == "BID/1 &lt;x&gt; &amp; y"
    assert pdf_report._esc("") == "—"
    assert pdf_report._plain_text("<p>Weak</p><ul><li>one</li></ul>") == "Weak<br/>• one"


def _pdf_engagement():
    finding = SimpleNamespace(
        reference="IAF-001", title="Dormant accounts <reactivated>", rating=Severity.high,
        description="obs", risk_implication="fraud", recommendation="Dual control & review",
        management_response="Agreed; CRO to implement", action_owner="CRO",
        due_date=date(2026, 12, 31), status=AuditFindingStatus.open, closed_date=None,
    )
    procedure = SimpleNamespace(title="Sample 25 reactivations", result=AuditProcedureResult.failed,
                                workpaper_ref="WP-1", performed_by="A. Auditor")
    return SimpleNamespace(
        id=uuid.uuid4(), reference="IA-001", title="Deposits inspection",
        audit_type=AuditType.regulatory, auditor_firm="State Bank of Pakistan",
        report_reference="BID/2026/114", report_date=date(2026, 9, 10),
        auditable_unit=SimpleNamespace(name="Branch banking"), lead_auditor="", audit_team="",
        status=AuditEngagementStatus.reporting, period_start=None, period_end=None,
        planned_start=date(2026, 8, 1), planned_end=date(2026, 8, 31),
        actual_start=date(2026, 8, 3), actual_end=date(2026, 9, 2),
        rating=Severity.high, scope="Deposits & KYC", objectives="", conclusion="<p>Weak</p>",
        finding_count=1, open_finding_count=1, findings=[finding], procedures=[procedure],
    )


def test_the_engagement_report_renders_with_provenance_and_responses(monkeypatch):
    pytest.importorskip("reportlab")
    seen = []
    real_kv = pdf_report._kv

    def spy_kv(ss, pairs):
        seen.extend(pairs)
        return real_kv(ss, pairs)

    monkeypatch.setattr(pdf_report, "_kv", spy_kv)
    data = pdf_report.audit_engagement_pdf(_pdf_engagement(), "Bank & Co")
    assert data.startswith(b"%PDF")
    labels = dict(seen)
    assert labels["Audit type"] == "Regulatory inspection"
    assert labels["Audit firm / regulator"] == "State Bank of Pakistan"
    assert labels["Report reference"] == "BID/2026/114"
    assert labels["Actual fieldwork"] == "2026-08-03 – 2026-09-02"
    assert labels["Recommendation"] == "Dual control &amp; review"
    assert labels["Management response"] == "Agreed; CRO to implement"
