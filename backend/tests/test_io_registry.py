"""Structural invariants of the CSV import/export registry.

Every resource is a declaration wired to a real model, Create schema and permission
code. A mismatch — a column naming a field the Create schema does not accept, a link
whose export attribute is not a relationship — only surfaces when a client runs an
import, which is exactly the wrong time to find out. These tests fail at build time
instead.
"""
from app.core.permissions import ALL_PERMISSIONS
from app.models.enums import AssetClass
from app.services.import_registry import REGISTRY


def test_permission_codes_exist():
    known = set(ALL_PERMISSIONS)
    bad = {
        key: (res.read_perm, res.write_perm)
        for key, res in REGISTRY.items()
        if res.read_perm not in known or res.write_perm not in known
    }
    assert bad == {}


def test_every_column_maps_to_a_create_schema_field():
    """Import builds ``create_schema(**payload)``; a stray field name raises per row."""
    bad = []
    for key, res in REGISTRY.items():
        fields = set(res.create_schema.model_fields)
        for col in res.columns:
            target = col.link.create_field if col.link else col.field
            if target not in fields:
                bad.append(f"{key}.{col.header} -> {target}")
    assert bad == []


def test_every_plain_column_exists_on_the_model():
    """Export reads ``getattr(obj, col.field)``; a stale name exports silent blanks."""
    bad = [
        f"{key}.{col.field}"
        for key, res in REGISTRY.items()
        for col in res.columns
        if col.link is None and not hasattr(res.model, col.field)
    ]
    assert bad == []


def test_exportable_links_have_a_real_relationship():
    bad = [
        f"{key}.{col.header} -> {col.link.export_attr}"
        for key, res in REGISTRY.items()
        for col in res.columns
        if col.link is not None
        and col.link.exportable
        and col.link.export_attr not in res.model.__mapper__.relationships
    ]
    assert bad == []


def test_fixed_discriminators_exist_on_the_model():
    bad = [
        f"{key}.{attr}"
        for key, res in REGISTRY.items()
        for attr in res.fixed
        if not hasattr(res.model, attr)
    ]
    assert bad == []


def test_headers_are_unique_within_a_resource():
    """Import maps CSV headers to columns by name; a duplicate would shadow silently."""
    bad = {
        key: [c.header for c in res.columns]
        for key, res in REGISTRY.items()
        if len({c.header for c in res.columns}) != len(res.columns)
    }
    assert bad == {}


# ------------------------------------------------------------- the asset split ---
def test_asset_registers_are_separate_and_discriminated():
    """The two asset registers share one table, so each must stamp its own class —
    otherwise every imported row defaults to information_asset."""
    it, info = REGISTRY["it-assets"], REGISTRY["information-assets"]
    assert it.fixed == {"asset_class": AssetClass.it_asset}
    assert info.fixed == {"asset_class": AssetClass.information_asset}
    assert it.model is info.model


def test_asset_class_is_not_a_csv_column():
    """The discriminator is the resource's identity; exposing it as a column would let
    a CSV row route itself into the other register."""
    for key in ("it-assets", "information-assets"):
        assert "asset_class" not in {c.field for c in REGISTRY[key].columns}


def test_it_asset_inventory_fields_are_importable():
    """The CMDB fields a bank bulk-loads — previously absent from the CSV entirely."""
    headers = {c.header for c in REGISTRY["it-assets"].columns}
    assert {"hostname", "ip_address", "serial_number", "os_version", "environment"} <= headers


def test_banking_registers_are_importable():
    """The registers a bank arrives with already populated in spreadsheets."""
    expected = {
        "issues", "rcsa-assessments", "kris", "loss-events", "obligations",
        "regulatory-changes", "audit-engagements", "icfr-processes", "models",
        "outsourcing-arrangements", "bia-assessments",
    }
    missing = expected - set(REGISTRY)
    assert missing == set()
    assert all(REGISTRY[k].importable for k in expected)
