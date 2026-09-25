"""Platform fixes, 2026-09-25 (client report "the system is not working").

No database. Pinned here:

1. **Tag library** — create / rename / delete need ``org:write`` (the organisation-wide
   value-list permission); names are unique ignoring case and spacing; a write to a
   record's panel needs the record to exist.
2. **Module gating on shared surfaces** — import/export, custom fields, status rules,
   filters, collab, attestations, records and versions resolve their type key to a
   module and refuse a switched-off one, in the path or in a ``model`` body/query.
3. **"Everyone" alerts** reach only readers of the record's module; ``GET /dashboard``
   gives other registers' sizes only to their readers.
4. **Attestation** follows the approval state for types with an approval workflow; an
   unscored risk is refused with its real reason.
5. **Rules and filters** refuse fields the model doesn't have.
6. **TAT clock** starts at the record's own identified / detected date.
7. **Report builder** ``/run`` and ``/export`` need ``report:read`` like the rest.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.api.v1 import attestations as att
from app.api.v1 import collab, filters, report_builder, status_rules
from app.core.modules import MODULES
from app.models.base import WorkflowState
from app.models.enums import RiskStatus, Severity
from app.models.risk import Risk
from app.services import modules as mod
from app.services import notifications as ns
from app.services import sla
from app.services import status_rules as engine
from app.services.entity_types import ENTITY_TYPES

TENANT = uuid.uuid4()
ME = uuid.uuid4()


def _user(*perms):
    return SimpleNamespace(id=ME, tenant_id=TENANT, email="me@bank.pk", permission_codes=list(perms))


def _route_perms(router, path: str, method: str) -> set[str]:
    """The permission codes a route's ``require(...)`` dependencies demand."""
    for route in router.routes:
        if route.path == path and method in route.methods:
            codes: set[str] = set()
            for dep in route.dependant.dependencies:
                closure = getattr(dep.call, "__closure__", None) or ()
                for cell in closure:
                    if isinstance(cell.cell_contents, tuple):
                        codes |= set(cell.cell_contents)
            return codes
    raise AssertionError(f"no route {method} {path}")


# ============================================================ 1. tag library ===
@pytest.mark.parametrize("path,method", [
    ("/collab/tags", "POST"), ("/collab/tags/{tag_id}", "PATCH"), ("/collab/tags/{tag_id}", "DELETE"),
])
def test_managing_the_tag_library_needs_the_value_list_permission(path, method):
    assert _route_perms(collab.router, path, method) == {collab.TAG_LIBRARY_PERMISSION}
    assert collab.TAG_LIBRARY_PERMISSION == "org:write"


def test_reading_the_library_and_tagging_a_record_need_no_library_permission():
    assert _route_perms(collab.router, "/collab/tags", "GET") == set()
    assert _route_perms(collab.router, "/collab/{entity_type}/{entity_id}/tags", "POST") == set()


def test_tag_names_are_normalised_and_compared_ignoring_case():
    assert collab.normalise_tag_name("  PCI   DSS ") == "PCI DSS"
    assert collab.normalise_tag_name(None) == ""
    sql = str(collab._same_name(" Pci ").compile(dialect=postgresql.dialect(),
                                                compile_kwargs={"literal_binds": True}))
    assert "lower(tags.name) = 'pci'" in sql
    with pytest.raises(HTTPException) as exc:
        collab._valid_name("   ")
    assert exc.value.status_code == 422


class _GetDB:
    def __init__(self, record=None):
        self.record = record

    async def get(self, model, ident):
        return self.record


async def test_a_comment_needs_a_live_record_in_the_callers_organisation():
    user = _user("risk:write")
    with pytest.raises(HTTPException) as exc:
        await collab._require_record(_GetDB(None), user, "risk", uuid.uuid4())
    assert (exc.value.status_code, exc.value.detail) == (404, "Risk not found")
    archived = SimpleNamespace(tenant_id=TENANT, deleted=True)
    with pytest.raises(HTTPException):
        await collab._require_record(_GetDB(archived), user, "risk", uuid.uuid4())
    foreign = SimpleNamespace(tenant_id=uuid.uuid4(), deleted=False)
    with pytest.raises(HTTPException):
        await collab._require_record(_GetDB(foreign), user, "risk", uuid.uuid4())
    await collab._require_record(_GetDB(SimpleNamespace(tenant_id=TENANT, deleted=False)), user, "risk", uuid.uuid4())


async def test_the_comment_endpoint_refuses_an_orphan_before_writing():
    added = []

    class DB(_GetDB):
        def add(self, obj):
            added.append(obj)

    from app.schemas.collab import CommentCreate

    with pytest.raises(HTTPException) as exc:
        await collab.add_comment("risk", uuid.uuid4(), CommentCreate(body="x"), DB(None), _user("risk:write"))
    assert exc.value.status_code == 404
    assert added == []


# ====================================================== 2. module gating ===
def test_every_module_with_records_has_its_permission_namespace_mapped():
    assert set(mod.PERMISSION_MODULES.values()) <= set(MODULES)
    namespaces = {spec.read_perm.split(":")[0] for spec in ENTITY_TYPES.values()}
    gated = {mod.PERMISSION_MODULES[n] for n in namespaces if n in mod.PERMISSION_MODULES}
    # AI Assist is a feature, not a register; every other module owns records.
    assert set(MODULES) - gated == {"ai_assist"}


def test_record_types_resolve_to_their_module():
    assert mod.module_for_entity_type("key_risk_indicator") == "operational_risk"
    assert mod.module_for_entity_type("processing_activity") == "privacy"
    assert mod.module_for_entity_type("dpia") == "data_protection"
    assert mod.module_for_entity_type("suspicious_activity_report") == "aml"
    assert mod.module_for_entity_type("committee") == "governance_meetings"
    # Core records and custom-field keys of core records are never gated.
    for core in ("risk", "control", "it_asset", "information_asset", "tags", "", None):
        assert mod.module_for_entity_type(core) is None


def test_import_resources_resolve_through_their_read_permission():
    from app.services.import_registry import REGISTRY

    kri = [k for k, r in REGISTRY.items() if r.read_perm == "oprisk:read"]
    assert kri, "the KRI register is importable"
    assert {mod.module_for_resource(k) for k in kri} == {"operational_risk"}
    assert mod.module_for_resource("risks") is None
    assert mod.module_for_resource("resources") is None


@pytest.mark.parametrize("path,expected", [
    ("/api/v1/io/kris/export", {"operational_risk"}),
    ("/api/v1/io/risks/export", set()),
    ("/api/v1/io/resources", set()),
    ("/api/v1/custom-fields/key_risk_indicator/values/x", {"operational_risk"}),
    ("/api/v1/custom-fields/models", set()),
    ("/api/v1/collab/processing_activity/x", {"privacy"}),
    ("/api/v1/collab/tags", set()),
    ("/api/v1/attestations/dpia/x", {"data_protection"}),
    (f"/api/v1/attestations/{uuid.uuid4()}/confirm", set()),
    ("/api/v1/records/loss_event/archived", {"operational_risk"}),
    ("/api/v1/versions/record/shariah_review/x", {"shariah"}),
    ("/api/v1/status-rules/fields/key_risk_indicator", {"operational_risk"}),
    ("/api/v1/status-rules/evaluate/rcsa_assessment", {"operational_risk"}),
    ("/api/v1/filters/fields/key_risk_indicator", {"operational_risk"}),
    ("/api/v1/kris", set()),  # the module's own router: require_module's job
    ("/health", set()),
])
def test_type_keyed_paths_name_their_module(path, expected):
    assert mod.modules_named_by_path(path) == expected


def _request(method: str, path: str, body: dict | None = None, query: str = "") -> Request:
    raw = json.dumps(body).encode() if body is not None else b""

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    headers = [(b"content-type", b"application/json")] if body is not None else []
    return Request({"type": "http", "method": method, "path": path, "headers": headers,
                    "query_string": query.encode()}, receive)


async def test_a_model_in_the_body_or_query_names_its_module():
    req = _request("POST", "/api/v1/custom-fields", {"model": "key_risk_indicator", "label": "x"})
    assert await mod.modules_named_by_request(req) == {"operational_risk"}
    # The body is cached, so the endpoint can still read it afterwards.
    assert (await req.json())["label"] == "x"
    assert await mod.modules_named_by_request(_request("POST", "/api/v1/status-rules", {"model": "risk"})) == set()
    assert await mod.modules_named_by_request(
        _request("GET", "/api/v1/filters", query="model=dsar")
    ) == {"data_protection"}
    # Other collections' bodies are never read.
    assert await mod.modules_named_by_request(_request("POST", "/api/v1/risks", {"model": "dpia"})) == set()


@pytest.fixture
def oprisk_off_for_the_org(monkeypatch):
    monkeypatch.setattr(mod, "enabled_modules", lambda: set(MODULES))

    async def choice(tenant_id):
        return frozenset(set(MODULES) - {"operational_risk"})

    monkeypatch.setattr(mod, "organisation_choice", choice)


async def test_a_switched_off_module_is_refused_on_shared_surfaces(oprisk_off_for_the_org):
    for req in (
        _request("GET", "/api/v1/io/kris/export"),
        _request("POST", "/api/v1/custom-fields", {"model": "key_risk_indicator"}),
        _request("GET", "/api/v1/collab/key_risk_indicator/x"),
    ):
        with pytest.raises(HTTPException) as exc:
            await mod.gate_shared_request(req, TENANT)
        assert exc.value.status_code == 403
        assert "Operational Risk" in exc.value.detail and "switched off" in exc.value.detail
    await mod.gate_shared_request(_request("GET", "/api/v1/io/risks/export"), TENANT)
    await mod.gate_shared_request(_request("GET", "/api/v1/collab/aml_risk_assessment/x"), TENANT)
    assert "operational_risk" not in await mod.usable_modules(TENANT)
    assert not await mod.entity_type_usable("loss_event", TENANT)
    assert await mod.entity_type_usable("risk", TENANT)


async def test_an_unlicensed_module_is_refused_whatever_the_organisation_chose(monkeypatch):
    monkeypatch.setattr(mod, "enabled_modules", lambda: set(MODULES) - {"privacy"})

    async def everything(tenant_id):
        return None

    monkeypatch.setattr(mod, "organisation_choice", everything)
    with pytest.raises(HTTPException) as exc:
        await mod.require_entity_module("processing_activity", TENANT)
    assert "not enabled on this installation" in exc.value.detail
    await mod.require_entity_module("risk", TENANT)


async def test_status_rule_models_leave_out_a_switched_off_module(oprisk_off_for_the_org):
    models = await status_rules.list_models(_user())
    assert "key_risk_indicator" not in models and "rcsa_assessment" not in models
    assert "risk" in models and "screening_case" in models


def test_the_token_dependency_runs_the_gate():
    import inspect

    from app.core import deps

    assert "gate_shared_request" in inspect.getsource(deps.get_token_payload)


# ================================================ 3. everyone alerts / dashboard ===
def test_a_risk_reader_sees_only_risk_side_alerts_addressed_to_everyone():
    readable = ns.readable_entity_types(["risk:read"])
    assert "risk" in readable and "threat" in readable and "" in readable and "licence" in readable
    for other in ("processing_activity", "audit_finding", "suspicious_activity_report", "sar", "approval", "project"):
        assert other not in readable
    everyone = SimpleNamespace(user_id=None, role_name="", entity_type="processing_activity")
    assert ns.is_visible(everyone, ME, [], readable_types=readable) is False
    assert ns.is_visible(everyone, ME, []) is True  # unfiltered callers keep the old rule
    assert ns.is_visible(everyone, ME, [], readable_types=ns.readable_entity_types(["privacy:read"]))
    # Addressed rows are the scanner's decision and stay visible.
    mine = SimpleNamespace(user_id=ME, role_name="", entity_type="processing_activity")
    assert ns.is_visible(mine, ME, [], readable_types=readable)


def test_a_switched_off_modules_alerts_reach_nobody_as_everyone():
    readable = ns.readable_entity_types(["oprisk:read", "risk:read"], modules={"aml"})
    assert "key_risk_indicator" not in readable and "risk" in readable
    assert "key_risk_indicator" in ns.readable_entity_types(["oprisk:read"], modules={"operational_risk"})


def test_the_feed_sql_filters_everyone_rows_by_entity_type():
    sql = str(ns.visible_clause(ME, ["Risk Manager"], readable_types=["risk"]).compile(
        dialect=postgresql.dialect()))
    assert "notifications.entity_type IN" in sql
    assert "entity_type" not in str(ns.visible_clause(ME, ["Risk Manager"]).compile(dialect=postgresql.dialect()))


def test_the_digest_applies_the_same_rule():
    from app.services import scheduler

    now = datetime.now(timezone.utc)
    rows = [
        SimpleNamespace(user_id=None, role_name="", entity_type="processing_activity", dedup_key="ropa:1",
                        created_at=now, category=SimpleNamespace(value="warning")),
        SimpleNamespace(user_id=None, role_name="", entity_type="risk", dedup_key="risk:1",
                        created_at=now, category=SimpleNamespace(value="warning")),
    ]
    picked = scheduler.digest_for(rows, user_id=ME, role_names=[], since=None,
                                  readable_types=ns.readable_entity_types(["risk:read"]))
    assert [n.entity_type for n in picked] == ["risk"]


def test_the_sar_alert_uses_the_registry_type():
    import inspect

    assert '"sar", sar.id' not in inspect.getsource(ns.scan_alerts)
    assert "suspicious_activity_report" in inspect.getsource(ns.scan_alerts)


def test_dashboard_register_sizes_are_optional():
    from app.schemas.dashboard import DashboardStats

    fields = DashboardStats.model_fields
    assert fields["total_controls"].default is None and fields["total_assets"].default is None


# ============================================================= 4. attestation ===
def _risk(**kw):
    base = dict(id=uuid.uuid4(), tenant_id=TENANT, title="Ransomware", reference="R-025",
                status=RiskStatus.draft, workflow_status=WorkflowState.approved)
    base.update(kw)
    return Risk(**base)


def test_an_approved_risk_is_not_told_to_submit_it_for_review():
    scored = _risk(last_assessed_at=datetime.now(timezone.utc))
    assert att.attest_refusal(
        workflow_status=att.lifecycle_state(scored), approval=att.approval_state(scored),
        label="risk", unscored=att.risk_unscored("risk", scored),
    ) is None
    unscored = _risk()
    assert att.attest_refusal(
        workflow_status=att.lifecycle_state(unscored), approval=att.approval_state(unscored),
        label="risk", unscored=att.risk_unscored("risk", unscored),
    ) == (409, att.UNSCORED_REFUSAL)
    assert "Submit it for review" not in att.DRAFT_REFUSAL


def test_an_unapproved_risk_hears_the_approval_rule_first():
    risk = _risk(workflow_status=WorkflowState.in_review)
    assert att.attest_refusal(
        workflow_status=att.lifecycle_state(risk), approval=att.approval_state(risk),
        label="risk", unscored=att.risk_unscored("risk", risk),
    ) == (409, "Approve this risk before attesting it — its approval is in review.")


def test_only_a_risk_can_be_unscored():
    assert att.risk_unscored("risk", _risk(status=RiskStatus.assessed)) is False
    assert att.risk_unscored("control", SimpleNamespace(status="draft", last_assessed_at=None)) is False
    assert att.risk_unscored("risk", None) is False


# ======================================================= 5. rules and filters ===
def test_a_condition_on_a_missing_field_is_refused():
    assert engine.condition_problem("risk", "nonexistent", "eq").startswith("'nonexistent' is not a field")
    assert engine.condition_problem("risk", "title", "like") == "Unsupported operator 'like'"
    assert engine.condition_problem("nope", "title", "eq") == "Unsupported model 'nope'"
    assert engine.condition_problem("risk", "inherent_score", "gte") is None
    with pytest.raises(HTTPException) as exc:
        filters._check_conditions("risk", [{"field": "nonexistent", "operator": "eq", "value": "x"}])
    assert exc.value.status_code == 422
    filters._check_conditions("risk", [{"field": "title", "operator": "contains", "value": "x"}])


def test_every_status_rule_model_is_a_registered_entity_type():
    # Running a filter or evaluating labels takes its read permission from the registry.
    assert set(engine.MODEL_MAP) <= set(ENTITY_TYPES)
    for key in ("aml_risk_assessment", "suspicious_activity_report", "screening_case", "fraud_risk", "fraud_case"):
        assert key in engine.MODEL_MAP


async def test_evaluating_labels_needs_read_access():
    with pytest.raises(HTTPException) as exc:
        await status_rules.evaluate_one("key_risk_indicator", uuid.uuid4(), None, _user("risk:read"))
    assert exc.value.status_code == 403


# =============================================================== 6. TAT clock ===
def test_the_clock_starts_at_the_records_own_date():
    created = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    issue = SimpleNamespace(identified_date=date(2025, 1, 10), created_at=created)
    assert sla._started_on(issue, sla.ENTITIES["issue"].started_fields) == date(2025, 1, 10)
    incident = SimpleNamespace(detected_at=datetime(2025, 3, 2, 23, tzinfo=timezone.utc), created_at=created)
    assert sla._started_on(incident, sla.ENTITIES["incident"].started_fields) == date(2025, 3, 2)
    risk = SimpleNamespace(identified_date=None, created_at=created)
    assert sla._started_on(risk, sla.ENTITIES["risk"].started_fields) == date(2026, 9, 1)
    assert sla._started_on(SimpleNamespace(created_at=created)) == date(2026, 9, 1)


def test_an_imported_legacy_issue_is_breached_on_the_day_it_really_lapsed():
    today = date(2026, 9, 25)
    started = date(2025, 1, 10)
    due = sla.due_from(started, sla.DEFAULT_TARGETS["issue"][Severity.high])
    assert sla.state_of(started, due, today=today).state == sla.BREACHED
    assert sla.breached_on(due, today) == due + timedelta(days=1)
    assert sla.breached_on(today, today) == today


# ========================================================== 7. report builder ===
@pytest.mark.parametrize("path", ["/report-builder/run", "/report-builder/export"])
def test_running_and_exporting_need_report_read(path):
    assert _route_perms(report_builder.router, path, "POST") == {"report:read"}
