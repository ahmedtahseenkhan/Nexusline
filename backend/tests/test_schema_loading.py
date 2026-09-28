"""List queries load what their response schema serialises, not the whole record graph.

``schema_loading.options_for`` walks a Read schema to decide which relationships a list
query loads; everything else it would have eager-loaded is made lazy. Pinned here
without a database: what the walk reaches, what it leaves out, and that every property
declared in ``PROPERTY_READS`` names relationships that exist.
"""
from __future__ import annotations

import app.models  # noqa: F401 - every mapper, so relationships resolve
from sqlalchemy import inspect
from sqlalchemy.orm import configure_mappers

from app.core import schema_loading as sl
from app.core.database import Base
from app.models.control import Control
from app.models.risk import Risk
from app.models.vendor import Vendor
from app.schemas.common import GraphRef
from app.schemas.risk import RiskRead


def test_a_nested_ref_loads_the_link_but_none_of_its_links():
    tree = sl._needs(Risk, RiskRead, frozenset())
    # Controls are a ControlAssuranceRef (id, name, reference ...): their tests and
    # findings come from ``Risk.control_health``, nothing else of the control is read.
    assert tree["controls"] == {"audits": {}, "audit_findings": {}}
    assert tree["vendors"] == {} and tree["policies"] == {}


def test_relationships_the_schema_never_reads_are_made_lazy():
    options = sl.options_for(Control, GraphRef)
    lazy = {
        opt.path[1].key for opt in options
        if dict(opt.context[0].strategy or ()).get("lazy") == "select"
    }
    eager = {r.key for r in inspect(Control).relationships if r.lazy in sl._EAGER}
    assert eager and lazy == eager  # a bare reference reads no link at all


def test_also_adds_what_the_endpoint_reads_itself():
    tree_without = sl._needs(Vendor, GraphRef, frozenset())
    options = sl.options_for(Vendor, GraphRef, ("contracts",))
    assert "contracts" not in tree_without
    loaded = [opt for opt in options if opt.path[1].key == "contracts"]
    assert loaded and dict(loaded[0].context[0].strategy or ()).get("lazy") == "selectin"


def test_every_declared_property_read_names_real_relationships():
    configure_mappers()
    by_name = {m.class_.__name__: m.class_ for m in Base.registry.mappers}
    for model_name, props in sl.PROPERTY_READS.items():
        model = by_name[model_name]
        for prop, paths in props.items():
            assert isinstance(getattr(model, prop, None), property), f"{model_name}.{prop}"
            for dotted in paths:
                current = model
                for key in dotted.split("."):
                    rels = inspect(current).relationships
                    assert key in rels, f"{model_name}.{prop}: {dotted} ({key})"
                    current = rels[key].mapper.class_
