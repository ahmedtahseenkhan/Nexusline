"""Governed lookups and pickers: the rules that do not need a database.

* value slugging and clash handling;
* a parent must be a top-level value of the same list;
* "in use" discovery walks every foreign key to ``lookups.id`` in the metadata;
* list ordering (parent then children) and the active/search filter;
* the business-unit tree flattens depth-first with paths, surviving orphans and cycles;
* the default seed is idempotent and never duplicates a value typed as free text.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, ForeignKey, MetaData, Table, Uuid

from app.api.v1.lookups import (
    derive_value,
    filter_views,
    list_name,
    normalise_value,
    order_rows,
    parent_error,
    referencing_columns,
)
from app.api.v1.pickers import filter_units, flatten_tree, parse_ids
from app.db.fk_backfill import FK_LOOKUP_KEYS
from app.db.lookup_seed import BUILTIN_VALUES, DEFAULT_LOOKUPS, missing_defaults
from app.models.lookup import LOOKUP_LISTS


def lk(label, key="risk_category", parent_id=None, sort_order=0, active=True, value=None):
    return SimpleNamespace(
        id=uuid.uuid4(), key=key, label=label, value=value or normalise_value(label),
        parent_id=parent_id, sort_order=sort_order, active=active, description="",
    )


# ---------------------------------------------------------------- list keys ---
def test_unknown_list_is_404():
    with pytest.raises(HTTPException) as exc:
        list_name("favourite_colour")
    assert exc.value.status_code == 404


def test_known_list_has_a_name():
    assert list_name("risk_category") == "Risk category"


def test_every_list_has_defaults_and_every_default_list_exists():
    assert set(DEFAULT_LOOKUPS) == set(LOOKUP_LISTS)


def test_every_lookup_backed_column_draws_from_a_real_list():
    assert set(FK_LOOKUP_KEYS.values()) <= set(LOOKUP_LISTS)


# ------------------------------------------------------------------ slugging ---
@pytest.mark.parametrize(
    "label,expected",
    [
        ("Technology & Cyber", "technology_cyber"),
        ("  Business   Continuity ", "business_continuity"),
        ("AML/CFT", "aml_cft"),
        ("State Bank of Pakistan (SBP)", "state_bank_of_pakistan_sbp"),
        ("***", "value"),
    ],
)
def test_value_is_slugged_from_label(label, expected):
    assert normalise_value(label) == expected


def test_derived_value_when_free():
    assert derive_value("Fraud", None, set()) == ("fraud", None)


def test_derived_value_clash_is_an_error():
    value, err = derive_value("Fraud", None, {"fraud"})
    assert err and "already" in err


def test_child_clash_falls_back_to_parent_prefix():
    assert derive_value("Other", None, {"other"}, parent_value="credit") == ("credit_other", None)


def test_explicit_value_is_normalised_and_must_be_free():
    assert derive_value("State Bank of Pakistan", "SBP", set()) == ("sbp", None)
    value, err = derive_value("State Bank", "sbp", {"sbp"})
    assert value == "sbp" and err


def test_blank_explicit_value_falls_back_to_label():
    assert derive_value("Credit", "  ", set()) == ("credit", None)


# ------------------------------------------------------------------- parents ---
def test_parent_must_exist():
    assert parent_error("risk_category", None, None, False) == "The parent value does not exist."


def test_parent_must_be_in_the_same_list():
    other = lk("Public", key="incident_classification")
    assert "same list" in parent_error("risk_category", None, other, False)


def test_parent_must_be_top_level():
    top = lk("Operational")
    child = lk("Fraud", parent_id=top.id)
    assert "two levels" in parent_error("risk_category", None, child, False)


def test_value_cannot_be_its_own_parent():
    row = lk("Operational")
    assert "own parent" in parent_error("risk_category", row.id, row, False)


def test_value_with_children_cannot_become_a_child():
    top = lk("Operational")
    assert "child values" in parent_error("risk_category", uuid.uuid4(), top, True)


def test_valid_parent():
    assert parent_error("risk_category", uuid.uuid4(), lk("Operational"), False) is None


# ------------------------------------------------------------ usage discovery ---
def test_referencing_columns_found_in_metadata():
    md = MetaData()
    Table("lookups", md, Column("id", Uuid, primary_key=True),
          Column("parent_id", Uuid, ForeignKey("lookups.id")))
    Table("risks", md, Column("id", Uuid, primary_key=True),
          Column("category_id", Uuid, ForeignKey("lookups.id")))
    Table("vendors", md, Column("id", Uuid, primary_key=True),
          Column("category_id", Uuid, ForeignKey("lookups.id")),
          Column("country_id", Uuid, ForeignKey("lookups.id")))
    Table("users", md, Column("id", Uuid, primary_key=True))
    Table("issues", md, Column("id", Uuid, primary_key=True),
          Column("owner_id", Uuid, ForeignKey("users.id")))
    assert referencing_columns(md) == [
        ("risks", "category_id"), ("vendors", "category_id"), ("vendors", "country_id"),
    ]


def test_real_metadata_covers_every_backfilled_lookup_column():
    """Every lookup-backed column fk_backfill fills must block deletion of its value."""
    found = set(referencing_columns())
    assert ("lookups", "parent_id") not in found
    assert set(FK_LOOKUP_KEYS) <= found


# ------------------------------------------------------------ order & filter ---
def test_children_follow_their_parent_in_sort_order():
    op = lk("Operational", sort_order=20)
    credit = lk("Credit", sort_order=10)
    fraud = lk("Fraud", parent_id=op.id, sort_order=20)
    bcp = lk("Business Continuity", parent_id=op.id, sort_order=10)
    views = order_rows([fraud, op, bcp, credit])
    assert [v.path for v in views] == [
        "Credit", "Operational", "Operational › Business Continuity", "Operational › Fraud",
    ]
    assert [v.depth for v in views] == [0, 0, 1, 1]
    assert views[2].parent_label == "Operational"


def test_ties_break_on_label():
    views = order_rows([lk("beta"), lk("Alpha")])
    assert [v.row.label for v in views] == ["Alpha", "beta"]


def test_orphaned_child_is_shown_at_top_level():
    orphan = lk("Fraud", parent_id=uuid.uuid4())
    assert [(v.path, v.depth) for v in order_rows([orphan])] == [("Fraud", 0)]


def test_active_filter_and_search():
    op = lk("Operational")
    fraud = lk("Fraud", parent_id=op.id)
    old = lk("Legacy", active=False)
    views = order_rows([op, fraud, old])
    assert [v.row.label for v in filter_views(views, "true")] == ["Operational", "Fraud"]
    assert [v.row.label for v in filter_views(views, "false")] == ["Legacy"]
    assert len(filter_views(views, "all")) == 3
    # Searching the parent finds its children through the path.
    assert [v.row.label for v in filter_views(views, "all", "OPER")] == ["Operational", "Fraud"]
    assert [v.row.label for v in filter_views(views, "all", "fra")] == ["Fraud"]


# ------------------------------------------------------------------- the seed ---
def test_seed_from_empty_adds_every_default():
    assert missing_defaults("regulator", []) == DEFAULT_LOOKUPS["regulator"]


def test_seed_is_idempotent():
    for key, defaults in DEFAULT_LOOKUPS.items():
        assert missing_defaults(key, [(d.value, d.label) for d in defaults]) == [], key


def test_seed_matches_text_derived_rows_by_value_or_label():
    # fk_backfill made these from typed text: value = slug(text), label = text.
    existing = [("credit", "credit"), ("tech", "TECHNOLOGY & CYBER"), ("sbp", "SBP")]
    missing = {d.value for d in missing_defaults("risk_category", existing)}
    assert "credit" not in missing and "technology_cyber" not in missing
    assert "strategic" in missing
    assert "sbp" not in {d.value for d in missing_defaults("regulator", [("sbp", "SBP")])}


def test_country_matches_on_iso_code():
    missing = {d.value for d in missing_defaults("country", [("pk", "PK"), ("uae", "United Arab Emirates")])}
    assert "pk" not in missing and "ae" not in missing and "sa" in missing


def test_seed_content():
    risk = DEFAULT_LOOKUPS["risk_category"]
    top = {d.label for d in risk if d.parent is None}
    assert {"Strategic", "Credit", "Market", "Liquidity", "Operational", "Compliance",
            "Technology & Cyber", "Reputational", "Shariah"} <= top
    by_value = {d.value: d for d in risk}
    for child in (d for d in risk if d.parent):
        assert by_value[child.parent].parent is None, child.label  # two levels only
    l2 = {d.label for d in risk if d.parent}
    assert {"Information Security", "Business Continuity", "Third Party", "Fraud", "Process Execution"} <= l2
    assert len(DEFAULT_LOOKUPS["country"]) >= 40
    countries = {d.label for d in DEFAULT_LOOKUPS["country"]}
    assert {"Pakistan", "United Arab Emirates", "Saudi Arabia", "Oman", "Qatar", "Kuwait", "Bahrain",
            "United Kingdom", "United States", "China", "India", "Singapore", "Germany",
            "Ireland", "Netherlands"} <= countries
    assert {"sbp", "secp", "fmu", "pta", "fbr", "nacta"} == {d.value for d in DEFAULT_LOOKUPS["regulator"]}
    # Decision 8: the ISO/IEC 27002:2022 themes. The four natures (Preventive …) are the
    # Nature field's, not classifications, and are never seeded here (record-page B10a).
    assert [d.label for d in DEFAULT_LOOKUPS["control_classification"]] == [
        "Organizational", "People", "Physical", "Technological",
    ]
    from app.db.data_repairs import NATURE_CLASSIFICATIONS

    assert not {d.value for d in DEFAULT_LOOKUPS["control_classification"]} & set(NATURE_CLASSIFICATIONS)


def test_default_values_are_unique_within_each_list():
    for key, defaults in DEFAULT_LOOKUPS.items():
        values = [d.value for d in defaults]
        assert len(values) == len(set(values)), key
        assert all(len(v) <= 120 for v in values)


def test_builtin_flag_covers_defaults():
    assert ("regulator", "sbp") in BUILTIN_VALUES
    assert ("regulator", "my_own") not in BUILTIN_VALUES


# ------------------------------------------------------------------- pickers ---
def _units():
    retail, corp, ops, branch, north = (uuid.uuid4() for _ in range(5))
    return retail, corp, ops, branch, north, [
        (ops, "Branch Ops", retail),
        (retail, "Retail", None),
        (north, "North Region", ops),
        (corp, "Corporate", None),
        (branch, "Alternate Channels", retail),
    ]


def test_bu_tree_flattens_depth_first_with_paths():
    retail, corp, ops, branch, north, rows = _units()
    flat = flatten_tree(rows)
    assert [(u.path, u.depth) for u in flat] == [
        ("Corporate", 0),
        ("Retail", 0),
        ("Retail › Alternate Channels", 1),
        ("Retail › Branch Ops", 1),
        ("Retail › Branch Ops › North Region", 2),
    ]
    assert flat[4].parent_id == ops and flat[1].parent_id is None


def test_bu_search_keeps_path_matches():
    *_ids, rows = _units()
    hits = [u.path for u in filter_units(flatten_tree(rows), "branch ops")]
    assert hits == ["Retail › Branch Ops", "Retail › Branch Ops › North Region"]
    assert len(filter_units(flatten_tree(rows), None)) == 5


def test_bu_with_missing_parent_is_a_root():
    lost = uuid.uuid4()
    flat = flatten_tree([(lost, "Treasury", uuid.uuid4())])
    assert [(u.path, u.depth, u.parent_id) for u in flat] == [("Treasury", 0, None)]


def test_bu_cycle_does_not_loop_or_lose_units():
    a, b = uuid.uuid4(), uuid.uuid4()
    flat = flatten_tree([(a, "A", b), (b, "B", a)])
    assert sorted(u.name for u in flat) == ["A", "B"]


def test_parse_ids():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert parse_ids(f"{a}, {b},") == [a, b]
    assert parse_ids(None) == []
    with pytest.raises(HTTPException) as exc:
        parse_ids("not-an-id")
    assert exc.value.status_code == 422
