"""The import/export engine round-trips what the product holds, and honours its workflow.

Two promises, pinned here without a database:

* What a register exports imports back to an equivalent record. Every field and link the
  record form offers is a column, every link column exports (through a relationship, the
  model's own foreign key, or a join table), and values the product derives — a
  control's tested effectiveness, a risk's impact from its dimension scores — never make
  the exported row fail on the way back in.
* An import is a create. A status the product reaches only through a workflow action
  (approved, published, closed, accepted) is brought in at the record's initial state
  with a row warning, unless the importer could have taken that decision alone in the
  app; preview reports exactly what the import will do.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import DataError, IntegrityError

from app.api.v1 import dataio
from app.api.v1.dataio import (
    _AMBIGUOUS,
    _clean_message,
    _export_link,
    _join_columns,
    _resolve_link,
    _row_to_payload,
)
from app.models.enums import ControlEffectiveness
from app.services import csv_io, import_registry as ir
from app.services.import_mapping import suggest_mapping
from app.services.import_registry import (
    REGISTRY,
    VIA_COLUMN,
    VIA_JOIN,
    ImportGate,
    StateRule,
    WORKFLOW_RULE,
)


def _cols(resource: str) -> dict[str, ir.Column]:
    return {c.header: c for c in REGISTRY[resource].all_columns}


# ========================================================== registry shape ===
def test_every_column_including_derived_feeds_a_create_schema_field():
    bad = [
        f"{key}.{col.header}"
        for key, res in REGISTRY.items()
        for col in res.all_columns
        if (col.link.create_field if col.link and not col.parse else col.field)
        not in res.create_schema.model_fields
    ]
    assert bad == []


def test_derived_columns_say_how_they_export():
    bad = [
        f"{key}.{col.header}"
        for key, res in REGISTRY.items()
        for col in res.derived
        if col.export_value is None and col.export_batch is None and col.link is None
    ]
    assert bad == []


def test_headers_stay_unique_with_derived_columns():
    bad = [k for k, r in REGISTRY.items() if len({c.header for c in r.all_columns}) != len(r.all_columns)]
    assert bad == []


def test_every_link_column_exports():
    """No link renders blank by design any more: a relationship link names a real
    relationship path, a column link a foreign key on the model, a join link a join
    table the target's relationship back to the model goes through."""
    bad = []
    for key, res in REGISTRY.items():
        for col in res.all_columns:
            link = col.link
            if link is None or col.parse is not None or col.export_batch is not None:
                continue
            if link.via == ir.VIA_RELATIONSHIP:
                model = res.model
                for step in link.export_attr.split("."):
                    rel = model.__mapper__.relationships.get(step)
                    if rel is None:
                        bad.append(f"{key}.{col.header}: no relationship {step}")
                        break
                    model = rel.mapper.class_
            elif link.via == VIA_COLUMN:
                column = res.model.__table__.c.get(link.create_field)
                if column is None or not column.foreign_keys:
                    bad.append(f"{key}.{col.header}: {link.create_field} is not a foreign key")
            elif link.via == VIA_JOIN:
                try:
                    _join_columns(res.model, link.target_model)
                except LookupError as exc:
                    bad.append(f"{key}.{col.header}: {exc}")
            else:
                bad.append(f"{key}.{col.header}: unknown via {link.via}")
    assert bad == []


def test_links_the_models_lack_a_relationship_for_now_export():
    """Previously exportable=False: exported blank, so the hierarchy and links were lost."""
    expected = {
        ("controls", "risks"): VIA_JOIN,
        ("legal", "assets"): VIA_JOIN,
        ("processes", "assets"): VIA_JOIN,
        ("business-units", "parent"): VIA_COLUMN,
        ("outsourcing-arrangements", "vendor"): VIA_COLUMN,
        ("risks", "parent_risk"): VIA_COLUMN,
        ("risks", "risk_owner"): VIA_COLUMN,
    }
    assert {k: _cols(k[0])[k[1]].link.via for k in expected} == expected


@pytest.mark.parametrize(
    ("resource", "headers"),
    [
        ("risks", {"risk_owner", "consequence_statement", "identified_by", "hierarchy_level",
                   "parent_risk", "residual_override_reason", "treatment_owner", "impact_dimensions"}),
        ("controls", {"operator", "iso27002_attributes", "assets", "risks"}),
        ("it-assets", {"media_type", "owner_business_unit", "guardian_business_unit",
                       "user_business_unit", "tags", "discovery_source", "auto_discovered",
                       "last_seen", "hosted_information_assets"}),
        ("information-assets", {"media_type", "classification_label", "classifications",
                                "owner_business_unit", "guardian_business_unit", "user_business_unit"}),
        ("vendors", {"type", "country", "data_classification", "relationship_owner",
                     "subcontractors", "controls", "requirements", "processes",
                     "data_residency_countries"}),
        ("continuity-plans", {"assets", "risks", "business_impact_analysis"}),
        ("threats", {"assets"}),
        ("vulnerabilities", {"assets"}),
        ("risk-scenarios", {"asset_kinds", "control_references"}),
        ("incidents", {"notified_at", "regulator_reference", "occurred_at", "detected_at"}),
        ("audit-findings", {"controls", "risks", "requirements"}),
        ("policies", {"classification_label", "use_attachments"}),
        ("processing-activities", {"right_to_access", "right_to_erasure"}),
        ("requirements", {"applicability_justification"}),
        ("issues", {"root_cause_category", "identified_date"}),
        ("dpias", {"title", "status", "workflow_status"}),
        ("dsars", {"request_type", "received_date", "workflow_status"}),
        ("consent-records", {"purpose", "consent_given", "lawful_basis"}),
    ],
)
def test_form_fields_are_columns(resource, headers):
    assert headers <= set(_cols(resource))


def test_links_that_a_create_needs_are_required_columns():
    """The template's example row fills a required link with a real record, and the
    wizard flags the column as missing when the file lacks it."""
    for resource, header in (("requirements", "framework"), ("evidence", "control"),
                             ("audit-findings", "engagement")):
        assert _cols(resource)[header].required, (resource, header)


def test_findings_of_archived_audits_are_not_exported():
    where = REGISTRY["audit-findings"].export_where
    assert where is not None
    sql = str(where()[0].compile(compile_kwargs={"literal_binds": True}))
    assert "audit_engagements.deleted" in sql and "false" in sql.lower()


def test_hosted_information_assets_only_resolve_information_assets():
    link = _cols("it-assets")["hosted_information_assets"].link
    assert link.scope == (("asset_class", ir.AssetClass.information_asset),)


# ======================================================== derived values ===
def test_a_tested_effectiveness_is_dropped_without_an_override_reason():
    payload = {"name": "C1", "effectiveness": "partially_effective"}
    warnings = ir._ignore_derived_effectiveness(payload)
    assert "effectiveness" not in payload
    assert warnings and "not assessed" in warnings[0]
    body = REGISTRY["controls"].create_schema(**payload)
    assert body.effectiveness == ControlEffectiveness.not_assessed


def test_an_effectiveness_with_a_reason_is_a_manual_override():
    payload = {"effectiveness": "effective", "effectiveness_override_reason": "Tested by IA"}
    assert ir._ignore_derived_effectiveness(payload) == []
    assert payload["effectiveness"] == "effective"


def test_not_assessed_is_dropped_silently():
    payload = {"effectiveness": "not_assessed"}
    assert ir._ignore_derived_effectiveness(payload) == []


def test_iso27002_attributes_round_trip_through_a_cell():
    control = SimpleNamespace(iso27002_attributes={
        "control_type": ["preventive", "detective"], "security_properties": ["confidentiality"],
    })
    cell = ir._iso_attributes_cell(control)
    assert cell == "control_type: preventive detective; security_properties: confidentiality"
    body = REGISTRY["controls"].create_schema(name="C", iso27002_attributes=ir._parse_iso_attributes(cell))
    assert body.iso27002_attributes == control.iso27002_attributes


def test_a_malformed_iso27002_cell_names_the_problem():
    with pytest.raises(ValueError, match="attribute: value"):
        ir._parse_iso_attributes("preventive")


def test_impact_dimension_cells_parse_by_basis():
    ids = {"financial": uuid.uuid4(), "reputational": uuid.uuid4()}
    rows = ir._parse_impact_dimensions(
        "inherent: Financial=4, Reputational=3; residual: Financial=2",
        lambda name: ids[name.lower()],
    )
    assert rows == [
        {"dimension_id": ids["financial"], "basis": "inherent", "score": 4},
        {"dimension_id": ids["reputational"], "basis": "inherent", "score": 3},
        {"dimension_id": ids["financial"], "basis": "residual", "score": 2},
    ]
    with pytest.raises(ValueError, match="inherent:, residual: or target:"):
        ir._parse_impact_dimensions("gross: Financial=4", lambda n: n)
    with pytest.raises(ValueError, match="Dimension=score"):
        ir._parse_impact_dimensions("inherent: Financial", lambda n: n)


def test_a_basis_scored_per_dimension_takes_its_impact_from_the_scores():
    payload = {"inherent_impact": 5, "residual_impact": 4,
               "impact_dimensions": [{"basis": "residual", "score": 3}]}
    ir._dimension_scores_decide_impact(payload)
    assert payload["inherent_impact"] == 5 and "residual_impact" not in payload


def test_an_incident_notification_exports_only_for_a_reportable_incident():
    assert ir._incident_notified_at(SimpleNamespace(is_reportable=False, regulatory_reports=[1])) is None
    assert ir._incident_regulator_reference(SimpleNamespace(is_reportable=False)) == ""


# =================================================== the workflow gate ===
def test_every_register_with_an_approval_lifecycle_gates_it():
    missing = [
        key for key, res in REGISTRY.items()
        if any(c.field == "workflow_status" for c in res.all_columns)
        and WORKFLOW_RULE not in res.state_rules
    ]
    assert missing == []


def test_workflow_only_business_statuses_are_gated():
    rules = {k: {r.field: r for r in REGISTRY[k].state_rules} for k in ("policies", "issues", "risks")}
    assert rules["policies"]["status"].later == {"under_review", "approved", "published"}
    assert rules["issues"]["status"].later == {"remediated", "closed", "risk_accepted"}
    assert rules["issues"]["status"].clears == ("closed_date",)
    assert rules["risks"]["status"].later == {"accepted"}


def _gate(rule: StateRule, blocked: str) -> ImportGate:
    return ImportGate(((rule, blocked),))


def test_a_blocked_state_comes_in_at_the_initial_state_with_a_warning():
    rule = REGISTRY["issues"].state_rules[0]
    payload = {"title": "t", "status": "closed", "closed_date": "2026-01-01"}
    warnings = _gate(rule, "maker-checker applies").apply(payload)
    assert payload["status"] == "open" and "closed_date" not in payload
    assert len(warnings) == 1
    assert warnings[0].startswith("status: imported as 'open', not 'closed' (closed_date left blank)")
    assert "maker-checker" in warnings[0]


def test_a_state_the_importer_could_decide_alone_is_carried():
    payload = {"workflow_status": "approved"}
    assert _gate(WORKFLOW_RULE, "").apply(payload) == []
    assert payload["workflow_status"] == "approved"


def test_in_review_is_never_carried():
    payload = {"workflow_status": "in_review"}
    warnings = _gate(WORKFLOW_RULE, "").apply(payload)
    assert payload["workflow_status"] == "draft" and "approval route" in warnings[0]


def test_initial_and_free_states_pass_untouched():
    for value in ("draft", "", None):
        payload = {"workflow_status": value}
        assert _gate(WORKFLOW_RULE, "blocked").apply(payload) == []
        assert payload["workflow_status"] == value


def _user(*codes):
    return SimpleNamespace(id=uuid.uuid4(), permission_codes=list(codes))


async def test_the_gate_needs_approval_rights(monkeypatch):
    gate = await ir.import_gate(object(), REGISTRY["policies"], _user("policy:read", "policy:write"))
    assert all(blocked.startswith("that takes approval rights") for _, blocked in gate.decisions)


async def test_the_gate_refuses_the_carry_when_four_eyes_applies(monkeypatch):
    from app.services import dual_control, workflow_engine

    async def required(db, module, action, amount=None):
        return (module, action) == ("policy", "publish"), None

    async def no_route(db, entity_type):
        return None

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    monkeypatch.setattr(workflow_engine, "definition_for", no_route)
    gate = await ir.import_gate(object(), REGISTRY["policies"], _user("policy:read", "workflow:approve"))
    decisions = {rule.field: blocked for rule, blocked in gate.decisions}
    # Approving alone is allowed here, publishing is not: the workflow state carries,
    # the published status does not.
    assert decisions["workflow_status"] == ""
    assert "maker-checker" in decisions["status"]


async def test_the_gate_refuses_the_carry_when_an_approval_route_is_configured(monkeypatch):
    from app.services import dual_control, workflow_engine

    async def not_required(db, module, action, amount=None):
        return False, None

    async def route(db, entity_type):
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(dual_control, "dual_control_required", not_required)
    monkeypatch.setattr(workflow_engine, "definition_for", route)
    gate = await ir.import_gate(object(), REGISTRY["legal"], _user("org:read", "workflow:approve"))
    assert "approval route" in dict((r.field, b) for r, b in gate.decisions)["workflow_status"]


async def test_a_register_without_state_rules_needs_no_lookup():
    gate = await ir.import_gate(None, REGISTRY["threats"], _user())
    assert gate.decisions == ()


# ===================================================== link resolution ===
def _link_col(**kw):
    return ir.link_col("things", "thing_ids", ir.Risk, "risks", match_field="title", **kw)


def test_a_repeated_token_links_once():
    col = _link_col()
    rid = uuid.uuid4()
    index = {"Risk": {"r-1": rid, "fraud": rid}}
    assert _resolve_link("R-1, fraud; r-1", col, index) == [rid]


def test_an_ambiguous_name_fails_the_row_instead_of_guessing():
    col = _link_col()
    with pytest.raises(ValueError, match="matches more than one Risk"):
        _resolve_link("Fraud", col, {"Risk": {"fraud": _AMBIGUOUS}})


def test_a_lenient_link_skips_what_it_cannot_match_with_a_warning():
    col = ir.user_col("risk_owner", "owner_id")
    warnings: list[str] = []
    assert _resolve_link("Head of Ops (vacant)", col, {"User": {}}, warnings) is None
    assert warnings and "no User matching 'Head of Ops (vacant)'" in warnings[0]
    with pytest.raises(ValueError):
        _resolve_link("nobody", _link_col(), {"Risk": {}}, [])


def test_scoped_lookups_get_their_own_index():
    country = _cols("vendors")["country"].link
    assert dataio._index_name(country) == "Lookup[key=country]"


def test_a_parsed_column_resolves_names_through_its_index():
    col = _cols("risks")["impact_dimensions"]
    dim = uuid.uuid4()
    payload = _row_to_payload(
        {"impact_dimensions": "inherent: Financial=4"},
        {col.header: col},
        {dataio._index_name(col.link): {"financial": dim}},
    )
    assert payload["impact_dimensions"] == [{"dimension_id": dim, "basis": "inherent", "score": 4}]


# ============================================================ exporting ===
def test_export_skips_archived_targets_sorts_and_follows_dotted_paths():
    live = SimpleNamespace(name="Payroll data", reference="", deleted=False,
                           asset_class=ir.AssetClass.information_asset)
    gone = SimpleNamespace(name="Old data", reference="", deleted=True,
                           asset_class=ir.AssetClass.information_asset)
    other = SimpleNamespace(name="Cards data", reference="", deleted=False,
                            asset_class=ir.AssetClass.information_asset)
    server = SimpleNamespace(hosted_dependencies=[
        SimpleNamespace(information_asset=live), SimpleNamespace(information_asset=gone),
        SimpleNamespace(information_asset=other),
    ])
    link = _cols("it-assets")["hosted_information_assets"].link
    assert _export_link(server, link) == "Cards data, Payroll data"


def test_a_shared_reference_exports_the_name_instead():
    link = _cols("legal")["business_units"].link
    unit = SimpleNamespace(reference="BU-1", name="Treasury", deleted=False)
    record = SimpleNamespace(business_units=[unit])
    assert _export_link(record, link) == "BU-1"
    assert _export_link(record, link, shared=frozenset({"bu-1"})) == "Treasury"


def test_column_and_join_links_render_what_was_prefetched():
    link = _cols("business-units")["parent"].link
    parent = SimpleNamespace(name="Head Office", deleted=False)
    child = SimpleNamespace(id=uuid.uuid4())
    assert _export_link(child, link, {child.id: [parent]}) == "Head Office"
    assert _export_link(child, link, {}) == ""


def test_classification_values_export_with_their_axis():
    value = SimpleNamespace(name="High", type=SimpleNamespace(name="Integrity"))
    assert ir._classification_label(value) == "Integrity: High"


# ========================================================= row messages ===
class _Body(BaseModel):
    control_id: uuid.UUID


def test_messages_are_sentences_not_tracebacks_or_sql():
    assert _clean_message(HTTPException(422, "Before this risk leaves Draft, give it a risk owner.")) \
        == "Before this risk leaves Draft, give it a risk owner."
    try:
        _Body()
    except ValidationError as exc:
        assert _clean_message(exc, REGISTRY["evidence"]) == "control: Field required"

    class _Truncated(Exception):
        pass

    _Truncated.__name__ = "StringDataRightTruncationError"
    err = DataError("INSERT INTO assets (currency) VALUES ($1)", {}, _Truncated("value too long for type character varying(8)"))
    message = _clean_message(err)
    assert message.startswith("A value is longer than allowed") and "INSERT" not in message

    class _Unique(Exception):
        detail = "Key (tenant_id, name)=(x, y) already exists."
        constraint_name = "uq_things_name"
        table_name = "things"

    _Unique.__name__ = "UniqueViolationError"
    message = _clean_message(IntegrityError("INSERT INTO things ...", {}, _Unique("dup")))
    assert message == "A record with this name already exists."


# ===================================================== column matching ===
def test_a_consequence_score_column_is_not_taken_for_the_risk_statement():
    suggestions, unmapped, _ = suggest_mapping(
        ["Risk Title", "Consequence", "Level"], REGISTRY["risks"].all_columns, resource="risks"
    )
    by_source = {s.source: s.target for s in suggestions}
    assert by_source.get("Consequence") == "inherent_impact"
    assert "Level" in unmapped


def test_an_exported_file_maps_onto_its_own_columns():
    for key, res in REGISTRY.items():
        headers = [c.header for c in res.all_columns]
        suggestions, unmapped, _ = suggest_mapping(headers, res.all_columns, resource=key)
        assert unmapped == [] and all(s.source == s.target for s in suggestions), key


# ============================================================ templates ===
def test_template_examples_pass_validation():
    fx = {c.header: c for c in REGISTRY["fx-rates"].all_columns}
    row = csv_io.example_row(list(fx.values()))
    assert row["currency"] == "USD" and float(row["rate"]) > 0
    bia = csv_io.example_row(REGISTRY["bia-assessments"].all_columns)
    assert bia["process_name"]
    kri = csv_io.example_row(REGISTRY["kris"].all_columns)
    assert kri["warning_threshold"] == "" and kri["limit_threshold"] == ""


# ============================================== preview == import (engine) ===
class _Savepoint:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self.db.savepoints += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.db.rolled_back += 1
        return False


class _Db:
    """The slice of an AsyncSession the engine uses, with no link targets."""

    def __init__(self):
        self.info: dict = {}
        self.savepoints = 0
        self.rolled_back = 0
        self.sync_session = SimpleNamespace(identity_map=SimpleNamespace(all_states=lambda: []))

    def begin_nested(self):
        return _Savepoint(self)

    async def scalars(self, *_a, **_k):
        return SimpleNamespace(all=lambda: [])

    async def flush(self):
        return None

    def add(self, obj):
        return None


async def test_preview_runs_the_create_and_reports_what_the_import_will(monkeypatch):
    """The dry run goes through the module's create (inside a savepoint that is rolled
    back) and the workflow gate, so preview and import agree row for row."""
    calls: list[str] = []

    async def create(*, body, db, user):
        calls.append(body.status.value)
        if body.title == "No owner":
            raise HTTPException(422, "Give the issue an owner first.")
        return SimpleNamespace(id=uuid.uuid4())

    audited: list = []

    async def record(db, **kw):
        audited.append(kw)

    import dataclasses

    monkeypatch.setitem(dataio.REGISTRY, "issues", dataclasses.replace(REGISTRY["issues"], create_func=create))
    monkeypatch.setattr(dataio.audit_log, "record", record)
    content = "title,status,closed_date\nOld finding,closed,2026-01-10\nNo owner,open,\n"
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), permission_codes=["issue:read", "issue:write"])

    db = _Db()
    preview = await dataio.preview_import(
        "issues", dataio.PreviewRequest(content=content), db, user
    )
    assert calls == ["open", "open"]  # the closed row was created open, in the dry run
    assert db.rolled_back == 2 and audited == []
    first, second = preview.rows
    assert first.error == "" and first.warnings[0].startswith("status: imported as 'open', not 'closed'")
    assert second.error == "Give the issue an owner first." and second.warnings == []
    assert preview.valid == 1

    calls.clear()
    result = await dataio.import_resource("issues", dataio.ImportRequest(content=content), _Db(), user)
    assert calls == ["open", "open"] and result.created == 1
    assert [(e.row, e.message) for e in result.errors] == [(3, second.error)]
    assert [(w.row, w.message) for w in result.warnings] == [(2, first.warnings[0])]


async def test_the_menu_leaves_out_switched_off_modules(monkeypatch):
    from app.services import modules

    async def usable(tenant_id):
        return {"risk"}

    monkeypatch.setattr(modules, "usable_modules", usable)
    monkeypatch.setattr(modules, "module_for_permission",
                        lambda perm: "risk" if perm.startswith("risk") else ("vendor" if perm.startswith("vendor") else None))
    listed = {r["resource"] for r in await dataio.list_resources(SimpleNamespace(tenant_id=uuid.uuid4()))}
    assert "risks" in listed and "vendors" not in listed and "fx-rates" in listed
