"""Delete impact (§1.4): which linked records are discovered for a record type, and how
they are counted — checked on the real mappers, without a database."""
from __future__ import annotations

import uuid

from sqlalchemy import Column, ForeignKey, MetaData, Table, Uuid
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 - populate mappers
from app.models.asset import Asset
from app.models.control import Control
from app.models.issue import Issue
from app.models.organization import BusinessUnit
from app.models.risk import Risk
from app.services import record_impact as ri
from app.services import record_registry


def _by_link(model):
    return {p.link_table.name: p for p in ri.impact_paths(model)}


def _types(model):
    return {ri.path_type(p)[0] for p in ri.impact_paths(model)}


def test_a_risk_reaches_its_many_to_many_links_both_declared_and_viewonly():
    paths = _by_link(Risk)
    # declared on Risk
    assert paths["risk_controls"].target_table.name == "controls"
    assert paths["risk_assets"].target_table.name == "assets"
    # viewonly reverse links declared on the other side
    assert paths["requirement_risks"].target_table.name == "requirements"
    assert paths["kri_risks"].target_table.name == "key_risk_indicators"
    assert {"control", "asset", "requirement", "key_risk_indicator", "policy", "vendor"} <= _types(Risk)


def test_a_risk_reaches_foreign_keys_no_relationship_declares():
    paths = _by_link(Risk)
    assert "continuity_plan_risks" in paths  # association table, no relationship on Risk
    assert paths["risk_quantifications"].remote_column is None  # a child table's own rows


def test_a_control_reaches_risks_and_its_children():
    types = _types(Control)
    assert {"risk", "requirement", "evidence", "policy"} <= types
    paths = _by_link(Control)
    assert paths["control_audits"].remote_column is None
    assert paths["risk_controls"].remote_column.name == "risk_id"


def test_many_to_one_pointers_are_not_dependents():
    """A risk points *at* its owner, category and business units via FK columns on the
    risk row; none of those make the user or lookup depend on the risk."""
    # The only path through the risks table itself is the phase-3 hierarchy: child risks
    # point at their parent (parent_id), so a parent's impact lists its children.
    self_paths = [p for p in ri.impact_paths(Risk) if p.link_table.name == "risks"]
    assert [p.local_column.name for p in self_paths] in ([], ["parent_id"])
    assert "users" not in {p.target_table.name for p in ri.impact_paths(Risk)}
    assert "lookups" not in {p.target_table.name for p in ri.impact_paths(Risk)}


def test_a_column_without_a_foreign_key_is_ignored():
    """``Issue.source_id`` names the record an issue came from but has no FK, so it cannot
    be followed reliably — the risk impact must not claim issues through it."""
    assert "source_id" not in {p.local_column.name for p in ri.impact_paths(Risk)}
    assert "issues" not in {p.link_table.name for p in ri.impact_paths(Risk)}


def test_self_referential_links_are_counted_both_ways():
    related = [p for p in ri.impact_paths(Asset) if p.link_table.name == "assets_related"]
    assert {p.local_column.name for p in related} == {"asset_id", "related_id"}
    children = [p for p in ri.impact_paths(BusinessUnit) if p.local_column.name == "parent_id"]
    assert children and children[0].target_table.name == "business_units"


def test_paths_are_unique_per_table_and_column():
    for model in (Risk, Control, Asset, BusinessUnit, Issue):
        keys = [p.key for p in ri.impact_paths(model)]
        assert len(keys) == len(set(keys)), model.__name__


def test_relationship_paths_only_follow_real_foreign_keys():
    from sqlalchemy import inspect

    for path in ri.relationship_paths(inspect(Risk)):
        assert any(fk.column.table.name == "risks" for fk in path.local_column.foreign_keys)


def test_foreign_key_paths_on_a_toy_schema():
    md = MetaData()
    parent = Table("parents", md, Column("id", Uuid, primary_key=True))
    child = Table(
        "children", md, Column("id", Uuid, primary_key=True),
        Column("parent_id", Uuid, ForeignKey("parents.id")),
    )
    other = Table("others", md, Column("id", Uuid, primary_key=True))
    link = Table(
        "parent_others", md,
        Column("parent_id", Uuid, ForeignKey("parents.id"), primary_key=True),
        Column("other_id", Uuid, ForeignKey("others.id"), primary_key=True),
    )
    paths = ri.foreign_key_paths(parent, md.tables, mapped={"parents", "children", "others"})
    by_table = {p.link_table.name: p for p in paths}
    assert by_table["children"].target_table is child and by_table["children"].remote_column is None
    assert by_table["parent_others"].target_table is other
    assert by_table["parent_others"].remote_column is link.c.other_id


def test_counts_exclude_archived_targets():
    path = _by_link(Risk)["risk_controls"]
    sql = str(ri._count(path, uuid.uuid4()).compile(dialect=postgresql.dialect()))
    assert "JOIN controls" in sql and "controls.deleted IS false" in sql
    child = _by_link(Control)["control_audits"]  # no soft delete on control tests
    assert "deleted" not in str(ri._count(child, uuid.uuid4()).compile(dialect=postgresql.dialect()))


def test_group_counts_sums_by_type_and_drops_zeros():
    paths = [p for p in ri.impact_paths(BusinessUnit) if p.link_table.name in ("assets", "risk_business_units")]
    counts = [2 if p.link_table.name == "assets" else 0 for p in paths]
    grouped = ri.group_counts(paths, counts)
    assert grouped == [{"type": "asset", "label": "Asset", "count": 2 * sum(1 for p in paths if p.link_table.name == "assets")}]


def test_types_are_named_for_people():
    labels = {ri.path_type(p) for p in ri.impact_paths(Risk)}
    assert ("vendor", "Third party") in labels
    assert ("risk_acceptances", "Risk acceptance") in labels
    assert record_registry.humanize("RcsaRisk") == "RCSA risk"


def test_every_registered_type_resolves_to_paths_without_error():
    from app.services.entity_types import ENTITY_TYPES

    for entity_type in ENTITY_TYPES:
        model = record_registry.model_for(entity_type)
        if model is not None:
            ri.impact_paths(model)


def test_record_labels():
    risk = Risk(id=uuid.uuid4(), reference="R-012", title="Ransomware")
    assert record_registry.label_of(risk) == "R-012 Ransomware"
    unit = BusinessUnit(id=uuid.uuid4(), name="Treasury")
    assert record_registry.label_of(unit) == "Treasury"
    assert record_registry.entity_type_for_model(Risk) == "risk"
    assert record_registry.link_for(risk) == f"/risks?id={risk.id}"
