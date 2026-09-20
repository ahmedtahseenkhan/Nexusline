"""Phase 0 of the product-review remediation: schema patch, start-up repairs, evidence.

Each rule here exists because a reviewer found the product contradicting itself once
real data was in it. The tests pin the rule, not the implementation.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.db import data_repairs
from app.db.reference_data import (
    AVAILABILITY_VALUES,
    CLASSIFICATION_VALUES_BY_AXIS,
    CONFIDENTIALITY_VALUES,
    INTEGRITY_VALUES,
)
from app.db.schema_patches import PHASE0_COLUMNS, phase0_ddl_statements
from app.models.enums import ControlStatus, EvidenceStatus
from app.models.risk import RESIDUAL_NOT_ABOVE_INHERENT
from app.schemas.evidence import (
    NOT_COLLECTED_MESSAGE,
    EvidenceCreate,
    EvidenceRead,
    evidence_status_problem,
)


# --- schema patch -------------------------------------------------------------------
def test_every_phase0_column_is_added_idempotently():
    ddl = phase0_ddl_statements()
    for table, col, _type, _default in PHASE0_COLUMNS:
        assert any(
            s.startswith(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} ") for s in ddl
        ), (table, col)


def test_residual_check_binds_new_writes_without_failing_the_upgrade():
    ddl = [s for s in phase0_ddl_statements() if "ck_risk_residual_le_inherent" in s]
    drop, add = ddl
    assert drop.startswith("ALTER TABLE risks DROP CONSTRAINT IF EXISTS")  # re-runnable
    assert add.endswith("NOT VALID")  # an existing bad row must not stop the migration
    assert RESIDUAL_NOT_ABOVE_INHERENT in add


def test_the_residual_rule_allows_an_override_with_a_reason():
    assert "residual_override_reason <> ''" in RESIDUAL_NOT_ABOVE_INHERENT


def test_the_residual_rule_lets_the_repair_flag_a_legacy_row():
    # PostgreSQL checks a NOT VALID constraint on later UPDATEs of old rows; the start-up
    # repair sets needs_review on exactly those rows, so the flag must satisfy the check.
    assert RESIDUAL_NOT_ABOVE_INHERENT.rstrip().endswith("OR needs_review")


# --- classification scales ------------------------------------------------------------
def test_each_cia_axis_grades_what_it_measures():
    names = {axis: [v[0] for v in values] for axis, values in CLASSIFICATION_VALUES_BY_AXIS.items()}
    assert names["Confidentiality"] == ["Public", "Internal", "Confidential", "Restricted"]
    assert names["Integrity"] == ["Low", "Moderate", "High", "Critical"]
    assert names["Availability"] == ["Standard", "Important", "Business-critical", "Mission-critical"]
    # Integrity and availability criteria no longer talk about disclosure.
    for _name, _value, criteria in (*INTEGRITY_VALUES, *AVAILABILITY_VALUES):
        assert "disclos" not in criteria.lower()


def test_the_grades_line_up_numerically_across_axes():
    for values in CLASSIFICATION_VALUES_BY_AXIS.values():
        assert [v[1] for v in values] == [1.0, 2.0, 3.0, 4.0]


def test_an_untouched_integrity_axis_is_regraded_in_place_by_value():
    plan = data_repairs.regrade_plan("Integrity", list(CONFIDENTIALITY_VALUES))
    assert plan is not None
    renames = {old: new for old, new, _criteria in plan}
    assert renames == {
        "Public": "Low", "Internal": "Moderate", "Confidential": "High", "Restricted": "Critical",
    }


def test_a_tenant_edited_axis_is_left_alone():
    edited = list(CONFIDENTIALITY_VALUES)
    edited[0] = ("Open", 1.0, "Anyone may see it")
    assert data_repairs.regrade_plan("Availability", edited) is None
    # Confidentiality itself is never regraded, and neither is an unknown axis.
    assert data_repairs.regrade_plan("Confidentiality", list(CONFIDENTIALITY_VALUES)) is None
    assert data_repairs.regrade_plan("Resilience", list(CONFIDENTIALITY_VALUES)) is None


def test_a_regraded_axis_is_not_regraded_again():
    assert data_repairs.regrade_plan("Integrity", list(INTEGRITY_VALUES)) is None


# --- controls ---------------------------------------------------------------------------
def test_planned_and_retired_controls_carry_no_test_clock():
    assert set(data_repairs.UNTESTABLE_CONTROL_STATUSES) == {ControlStatus.planned, ControlStatus.retired}


def test_the_repair_report_only_speaks_when_something_changed():
    assert not data_repairs.RepairReport().any()
    assert data_repairs.RepairReport(widgets_removed=1).any()
    assert data_repairs.RepairReport(indexes_skipped=["uq_frameworks_tenant_name"]).any()


# --- evidence -------------------------------------------------------------------------
def test_valid_evidence_needs_a_collection_date():
    assert evidence_status_problem(EvidenceStatus.valid, None) == NOT_COLLECTED_MESSAGE
    assert evidence_status_problem(EvidenceStatus.valid, date(2026, 9, 1)) is None
    assert evidence_status_problem(EvidenceStatus.pending, None) is None


def test_new_evidence_starts_pending():
    body = EvidenceCreate(title="Q3 access review", control_id="00000000-0000-0000-0000-000000000001")
    assert body.status == EvidenceStatus.pending


def test_creating_valid_evidence_without_a_date_is_refused():
    with pytest.raises(ValidationError, match="collected"):
        EvidenceCreate(
            title="Q3 access review",
            control_id="00000000-0000-0000-0000-000000000001",
            status=EvidenceStatus.valid,
        )


def _read(**kw):
    base = dict(
        id="00000000-0000-0000-0000-000000000002",
        control_id="00000000-0000-0000-0000-000000000001",
        title="Firewall rule review",
        created_at="2026-09-01T00:00:00Z",
    )
    return EvidenceRead(**{**base, **kw})


def test_legacy_valid_evidence_with_no_date_reads_as_not_collected():
    # Rows written before the rule still load, but never claim to be valid.
    assert _read(status=EvidenceStatus.valid).display_status == "not_collected"


def test_collected_evidence_shows_its_status_and_expiry_wins():
    assert _read(status=EvidenceStatus.valid, collected_at=date(2026, 9, 1)).display_status == "valid"
    stale = _read(status=EvidenceStatus.valid, collected_at=date(2025, 1, 1), valid_until=date(2025, 6, 1))
    assert stale.display_status == "expired"
