"""Segment-scoped risk assessment: risks linked to business units and processes.

A bank convenes a risk workshop around a segment — "Digital Banking", "Trade Finance" —
not around an asset. These pin the two things that make that cut work: the register's
filter, and the importer recognising the segment column a client's existing spreadsheet
already has.

No DB required: the query builder returns a Select, which compiles to inspectable SQL.
"""
import uuid

from sqlalchemy.dialects import postgresql

from app.services.risk_query import build_risk_query
from app.models.enums import RiskStatus
from app.models.organization import BusinessUnit, Process
from app.models.risk import Risk, risk_business_units, risk_processes
from app.services.import_mapping import suggest_mapping
from app.services.import_registry import REGISTRY

RISKS = REGISTRY["risks"]


def sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


# ------------------------------------------------------------- the data model ---
def test_a_risk_can_sit_in_several_segments_at_once():
    """A control failure like "MFA not enforced" belongs to Retail and Corporate at the
    same time. A single owning unit would force a choice that either duplicates the risk
    or hides it from one of them."""
    for relationship in ("business_units", "processes"):
        assert Risk.__mapper__.relationships[relationship].uselist is True


def test_the_segments_can_read_their_own_risks_without_owning_the_edge():
    for model in (BusinessUnit, Process):
        rel = model.__mapper__.relationships["risks"]
        assert rel.viewonly is True, f"{model.__name__}.risks must not write the join"


def test_deleted_segments_drop_out_of_a_risk():
    """Soft delete is respected on the join, as everywhere else in the graph."""
    for relationship in ("business_units", "processes"):
        condition = str(Risk.__mapper__.relationships[relationship].secondaryjoin)
        assert "deleted" in condition


def test_the_segment_side_of_each_join_is_indexed():
    """"Show me Digital Banking's risks" scans by segment; the composite primary key
    only indexes the risk side."""
    assert {i.name for i in risk_business_units.indexes} == {"ix_risk_business_units_unit"}
    assert {i.name for i in risk_processes.indexes} == {"ix_risk_processes_process"}


# ---------------------------------------------------------------- the register ---
def test_an_unfiltered_query_returns_the_live_register():
    text = sql(build_risk_query())
    assert "deleted" in text
    assert "risk_business_units" not in text


def test_filtering_by_business_unit_uses_an_exists_not_a_join():
    """A join would return a risk once per matching segment row and inflate every count
    on the page."""
    text = sql(build_risk_query(business_unit_id=uuid.uuid4()))
    assert "EXISTS" in text.upper()
    assert "risk_business_units" in text
    assert " JOIN " not in text.upper()


def test_filtering_by_process_uses_an_exists_not_a_join():
    text = sql(build_risk_query(process_id=uuid.uuid4()))
    assert "EXISTS" in text.upper()
    assert "risk_processes" in text
    assert " JOIN " not in text.upper()


def test_filtering_by_asset_uses_an_exists_not_a_join():
    text = sql(build_risk_query(asset_id=uuid.uuid4()))
    assert "EXISTS" in text.upper()
    assert "risk_assets" in text
    assert " JOIN " not in text.upper()


def test_filters_combine():
    """A workshop scopes to one segment *and* one status at a time."""
    text = sql(
        build_risk_query(
            status=RiskStatus.assessed,
            category="Operational",
            business_unit_id=uuid.uuid4(),
            process_id=uuid.uuid4(),
            search="fraud",
        )
    )
    for fragment in ("risk_business_units", "risk_processes", "status", "category", "ILIKE"):
        assert fragment in text or fragment in text.upper()


# ----------------------------------------------------------------- the importer ---
def test_the_risk_importer_accepts_segment_columns():
    fields = {c.field for c in RISKS.columns}
    assert {"business_unit_ids", "process_ids"} <= fields


def test_a_banks_own_segment_wording_maps_on_import():
    """The register a client hands over already has one of these headings. Failing to
    recognise it means re-tagging several hundred rows by hand."""
    for header, expected in (
        ("Department", "business_units"),
        ("Division", "business_units"),
        ("Segment", "business_units"),
        ("Business Unit", "business_units"),
        ("BU", "business_units"),
        ("Business Process", "processes"),
        ("Sub-Process", "processes"),
        ("Process Name", "processes"),
    ):
        suggestions, _, _ = suggest_mapping(["Risk Title", header], RISKS.columns, resource="risks")
        hit = next((s for s in suggestions if s.source == header), None)
        assert hit is not None, f"{header!r} was not recognised"
        assert hit.target == expected, f"{header!r} mapped to {hit.target}"


def test_a_generic_word_never_claims_a_segment_column():
    """A lone "branch" or "unit" in the synonym list is enough for the token-subset tier
    to swallow any header containing it. A wrong silent mapping is worse than none."""
    for header in ("Branch Manager Signature", "Unit Price", "Process Owner", "Functional Head"):
        _, unmapped, _ = suggest_mapping(["Risk Title", header], RISKS.columns, resource="risks")
        assert header in unmapped, f"{header!r} was guessed instead of reported"
