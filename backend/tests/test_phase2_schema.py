"""Phase 2 of the product-review remediation: the record-depth schema layer."""
import app.models  # noqa: F401 - registers every table
from app.core.database import Base
from app.db.lookup_seed import DEFAULT_LOOKUPS
from app.db.rls import TENANT_SCOPED_TABLES
from app.db.schema_patches import (
    PHASE2_COLUMNS,
    PHASE2_ENUM_VALUES,
    PHASE2_FK_COLUMNS,
    PHASE2_TIMESTAMP_COLUMNS,
    phase2_ddl_statements,
)
from app.models.enums import KriDirection, ReviewFrequency, TestResult
from app.models.lookup import LOOKUP_LISTS
from app.services.risk_scoring import next_review_date

NEW_TENANT_TABLES = (
    "issue_due_date_changes", "risk_impact_dimensions", "risk_appetites",
    "risk_treatment_actions", "kri_escalations", "vendor_certifications",
)
NEW_LINK_TABLES = (
    "control_business_units", "control_processes", "issue_risks", "issue_controls",
    "issue_requirements", "issue_assets", "issue_vendors", "policy_business_units",
    "policy_roles", "vendor_processes", "vendor_subcontractors", "vendor_data_residency",
)


def test_every_patched_column_exists_on_its_model():
    for table, col, _ddl in PHASE2_COLUMNS:
        assert col in Base.metadata.tables[table].c, (table, col)
    for table, col, target in PHASE2_FK_COLUMNS:
        fks = {fk.column.table.name for fk in Base.metadata.tables[table].c[col].foreign_keys}
        assert fks == {target}, (table, col, fks)


def test_new_tables_exist_and_tenant_tables_are_isolated():
    for table in NEW_TENANT_TABLES + NEW_LINK_TABLES:
        assert table in Base.metadata.tables, table
    for table in NEW_TENANT_TABLES:
        assert "tenant_id" in Base.metadata.tables[table].c
        assert table in TENANT_SCOPED_TABLES, table


def test_regulatory_clocks_are_timestamps_not_dates():
    for table, col, _time in PHASE2_TIMESTAMP_COLUMNS:
        column = Base.metadata.tables[table].c[col]
        assert column.type.__class__.__name__ == "DateTime" and column.type.timezone, (table, col)


def test_date_to_timestamp_conversion_is_guarded_and_keeps_deadline_days_whole():
    ddl = [s for s in phase2_ddl_statements() if "ALTER COLUMN" in s and "TIMESTAMPTZ" in s]
    assert len(ddl) == len(PHASE2_TIMESTAMP_COLUMNS)
    assert all("= 'date'" in s for s in ddl)  # only converts a column that is still a date
    deadline = next(s for s in ddl if "deadline" in s)
    assert "23:59" in deadline  # a deadline never moves earlier


def test_enum_additions_are_idempotent_and_match_python():
    ddl = phase2_ddl_statements()
    for type_name, value, _pos in PHASE2_ENUM_VALUES:
        assert any(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'" in s for s in ddl)
    assert TestResult.passed_with_exceptions.value == "passed_with_exceptions"
    assert KriDirection.within_range.value == "within_range"
    assert {ReviewFrequency.daily, ReviewFrequency.weekly} <= set(ReviewFrequency)


def test_daily_and_weekly_have_intervals():
    from datetime import date

    anchor = date(2026, 9, 12)
    assert next_review_date(ReviewFrequency.daily, anchor) == date(2026, 9, 13)
    assert next_review_date(ReviewFrequency.weekly, anchor) == date(2026, 9, 19)


def test_existing_control_tests_are_legacy_and_new_ones_need_review():
    ddl = phase2_ddl_statements()
    assert any("review_status VARCHAR(16) DEFAULT 'legacy'" in s for s in ddl)
    assert "ALTER TABLE control_audits ALTER COLUMN review_status SET DEFAULT 'pending'" in ddl
    assert Base.metadata.tables["control_audits"].c["review_status"].default.arg == "pending"


def test_new_lookup_lists_are_seeded():
    for key in ("impact_dimension", "data_classification"):
        assert key in LOOKUP_LISTS and DEFAULT_LOOKUPS.get(key), key
    labels = [v.label for v in DEFAULT_LOOKUPS["impact_dimension"]]
    assert labels == ["Financial", "Regulatory", "Reputational", "Customer", "Operational"]


def test_custom_roles_keep_the_right_to_record_tests_when_it_is_split_out():
    from app.db.provisioning import implied_grants

    assert implied_grants({"control:test"}, {"control:write"}) == {"control:test"}
    # only on the start-up that introduces the code: afterwards an admin's removal sticks
    assert implied_grants(set(), {"control:write"}) == set()
    assert implied_grants({"control:test"}, {"control:read"}) == set()


def test_an_unassessed_draft_risk_cannot_be_accepted():
    from datetime import datetime, timezone

    from app.services.risk_integrity import acceptance_refusal

    now = datetime.now(timezone.utc)
    assert acceptance_refusal("draft", None, "")
    assert acceptance_refusal("draft", now, "")  # scored but no rationale
    assert acceptance_refusal("draft", now, "Assessed at the Q3 RCSA") is None
    assert acceptance_refusal("assessed", None, "") is None  # legacy assessed risks


def test_reports_group_categories_by_the_appetite_they_inherit():
    import uuid

    from app.services.report_builder import category_thresholds
    from app.services.risk_scoring import AppetiteBook

    credit, fraud, cyber = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    book = AppetiteBook(
        appetite=6, tolerance=12,
        by_category={credit: (4, 8)},
        parents={credit: None, fraud: credit, cyber: None},
    )
    groups = category_thresholds(book)
    assert groups == {(4, 8): [credit, fraud]}  # the sub-category inherits; cyber uses the default


def test_the_risk_pdf_judges_each_risk_by_its_category():
    import uuid
    from types import SimpleNamespace

    from app.services.pdf_report import RiskReportContext
    from app.services.risk_scoring import AppetiteBook

    credit = uuid.uuid4()
    ctx = RiskReportContext(
        org_name="Bank", appetite=6, tolerance=12, max_score=25, matrix_size=5,
        book=AppetiteBook(appetite=6, tolerance=12, by_category={credit: (4, 8)}, parents={credit: None}),
    )
    assert ctx.thresholds(SimpleNamespace(category_id=credit)) == (4, 8)
    assert ctx.thresholds(SimpleNamespace(category_id=None)) == (6, 12)


def test_version_history_never_holds_a_credential():
    # A restore writes the snapshot back, so a secret in history would resurrect a
    # revoked KRI feed token or a rotated webhook secret.
    from app.services.versioning import _SKIP

    for column in ("feed_token_hash", "access_hash", "hashed_password", "mfa_secret",
                   "client_secret", "secret"):
        assert column in _SKIP
