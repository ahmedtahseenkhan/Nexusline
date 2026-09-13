"""Phase 1 of the product-review remediation: the structured-data schema layer.

A picker-backed key beside every free-text owner, unit and category column; the lists
those keys draw from; and the start-up backfill that carries existing text across.
"""
import app.models  # noqa: F401 - registers every table
from app.core.database import Base
from app.db import fk_backfill
from app.db.rls import TENANT_SCOPED_TABLES
from app.db.schema_patches import (
    PHASE1_FK_COLUMNS,
    PHASE1_TEXT_COLUMNS,
    phase1_ddl_statements,
    workflow_tables,
)
from app.models.lookup import LOOKUP_LISTS


def test_every_new_key_exists_on_its_model_and_points_where_the_patch_says():
    for table, col, target, anchor in PHASE1_FK_COLUMNS:
        t = Base.metadata.tables[table]
        assert col in t.c, (table, col)
        assert anchor in t.c, (table, anchor)  # the free text it replaces is still there
        targets = {fk.column.table.name for fk in t.c[col].foreign_keys}
        assert targets == {target}, (table, col, targets)
        assert t.c[col].nullable


def test_every_workflow_table_gets_an_owner_key():
    tables = workflow_tables()
    assert "risks" in tables and "policies" in tables and "controls" in tables
    for table in tables:
        assert "workflow_owner_id" in Base.metadata.tables[table].c, table


def test_the_patch_is_idempotent_and_never_scans_a_big_table():
    ddl = phase1_ddl_statements()
    for table, col, _target, _anchor in PHASE1_FK_COLUMNS:
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} UUID" in ddl
    constraints = [s for s in ddl if "ADD CONSTRAINT" in s]
    assert constraints and all("NOT VALID" in s and "IF NOT EXISTS" in s for s in constraints)
    for table, col, _ddl in PHASE1_TEXT_COLUMNS:
        assert any(s.startswith(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} ") for s in ddl)


def test_constraint_names_fit_postgres_identifier_limit():
    for s in phase1_ddl_statements():
        if "ADD CONSTRAINT" in s:
            name = s.split("ADD CONSTRAINT ")[1].split(" ")[0]
            assert len(name) <= 63, name


def test_new_tenant_tables_are_isolated_by_row_level_security():
    for table in ("tenant_settings", "lookups"):
        assert table in TENANT_SCOPED_TABLES


def test_every_lookup_backed_key_names_a_real_list():
    lookup_cols = {(t, c) for t, c, target, _a in PHASE1_FK_COLUMNS if target == "lookups"}
    assert set(fk_backfill.FK_LOOKUP_KEYS) == lookup_cols
    for key in fk_backfill.FK_LOOKUP_KEYS.values():
        assert key in LOOKUP_LISTS, key


def test_country_is_matched_never_invented_from_free_text():
    # "Karachi, PK" typed into a location field is not a country.
    assert LOOKUP_LISTS["country"][1] is False
    assert LOOKUP_LISTS["risk_category"][1] is True


def test_matching_ignores_case_and_spacing():
    assert fk_backfill.norm("  Information   Security ") == "information security"
    assert fk_backfill.norm(None) == ""


def test_seeded_lookup_values_get_stable_keys():
    assert fk_backfill.slug("Technology & Cyber") == "technology_cyber"
    assert fk_backfill.slug("!!!") == "value"
    assert len(fk_backfill.slug("x" * 500)) <= 120


def test_kri_breach_alerts_are_not_filtered_on_a_python_property():
    # KeyRiskIndicator.status is computed in Python; comparing it inside a SQL WHERE
    # compiled to "false", so no KRI breach alert ever fired. Guard the regression.
    import inspect

    from app.models.operational_risk import KeyRiskIndicator
    from app.services import notifications

    assert isinstance(inspect.getattr_static(KeyRiskIndicator, "status"), property)
    assert "KeyRiskIndicator.status ==" not in inspect.getsource(notifications)


def test_the_request_session_commits_before_the_response_is_sent():
    # With the default request scope a failure at commit (a constraint, the workflow
    # guard) rolled the write back after the client had already been told 200.
    import typing

    from app.core import deps

    for annotated in (deps.DbSession, typing.get_type_hints(deps.get_current_user, include_extras=True)["db"]):
        depends = typing.get_args(annotated)[1]
        assert depends.dependency is deps.get_db
        assert depends.scope == "function"


def test_every_register_with_a_lifecycle_can_import_its_legacy_state():
    from app.services import import_registry as ir

    for key, res in ir.REGISTRY.items():
        if "workflow_status" in res.model.__table__.c:
            assert any(c.field == "workflow_status" for c in res.columns), key


def test_only_an_approver_may_import_records_past_draft():
    from app.services.import_registry import import_state_refusal

    needed = ("policy:read", "workflow:approve")
    assert import_state_refusal("draft", needed, set(), "policies") is None
    assert import_state_refusal("", needed, set(), "policies") is None
    refusal = import_state_refusal("approved", needed, {"policy:read", "policy:write"}, "policies")
    assert refusal and "approval rights" in refusal and "workflow:approve" in refusal
    assert import_state_refusal("approved", needed, {"policy:read", "workflow:approve"}, "policies") is None


def test_a_policy_moves_through_review_and_approval_not_by_editing_its_status():
    from app.api.v1.policies import publish_refusal, status_edit_refusal
    from app.models.enums import PolicyStatus as P

    assert status_edit_refusal(P.draft, P.published) and "Publish" in status_edit_refusal(P.draft, P.published)
    assert "Approve" in status_edit_refusal(P.draft, P.approved)
    assert status_edit_refusal(P.draft, P.retired) is None
    assert status_edit_refusal(P.approved, P.approved) is None  # echoing the value back
    assert publish_refusal("draft", P.draft)
    assert publish_refusal("approved", P.draft) is None
    assert publish_refusal("draft", P.published) is None  # legacy published policy


def test_the_policy_business_status_follows_its_lifecycle():
    from app.services.record_workflow import synced_business_status as sync

    assert sync("policies", "draft", "in_review") == "under_review"
    assert sync("policies", "under_review", "approved") == "approved"
    assert sync("policies", "under_review", "draft") == "draft"  # rejected
    assert sync("policies", "published", "draft") is None  # revising keeps the live version
    assert sync("policies", "published", "retired") == "retired"
    assert sync("risks", "draft", "approved") is None
