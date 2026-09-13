"""Record-page backend, part A (spec §3.6: B1, B4, B5, B9, B10a, B10b).

No database: the pure rules are tested directly, the endpoints and repairs with fake
sessions that answer by the table a statement reads (the pattern of
``test_attestations`` and ``test_risk_integrity``).

Pinned here:

* **B1** ``GET /attestations/{type}/{id}`` says whether *this* user may attest the record
  (``can_attest``) and why not (``blocked_reason``), with the attest call's own gates in
  its order — write permission, the owner / draft rule on the business status first,
  then four-eyes — and the attest call's own words. The attest call still raises.
* **B4** Attesting an asset is its review: it takes the asset's cycle and moves its
  review dates. Asset reminders keep following the attestation (no second sweep).
* **B5** A route is named and linked by the server, never by the browser's label.
* **B9** A status-rule verdict carries the condition that fired it.
* **B10a** Framework names leave control classifications; natures move to ``nature``;
  the misfiled values are deactivated once, each change audited as ``system``.
* **B10b** An approved or retired record with no approval step on file gets one
  "Imported as …: no approver recorded" row from ``system``, once.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import attestations as att
from app.core.config import settings
from app.db import data_repairs as dr
from app.models.asset import Asset
from app.models.attestation import Attestation
from app.models.audit import AuditLog
from app.models.base import WorkflowState
from app.models.enums import ReviewFrequency, RiskStatus, WorkflowStatus
from app.models.risk import Risk
from app.schemas.attestation import AttestationCreate
from app.services import audit, dual_control, webhooks
from app.services.audit import SYSTEM_ACTOR_EMAIL
from app.services.notifications import NATIVE_REVIEW_ENTITY_TYPES
from app.services.risk_scoring import next_review_date

ME = uuid.uuid4()
OTHER = uuid.uuid4()
TENANT = uuid.uuid4()


def _user(*perms, uid=ME):
    return SimpleNamespace(id=uid, tenant_id=TENANT, email="me@bank.pk", permission_codes=list(perms))


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


# ============================================================================ B1 ===
class AttestDB:
    """Answers the attestation endpoints: the record, its history, the maker from the
    audit trail and the (absent or given) dual-control rule."""

    def __init__(self, record=None, maker=None, rule=None, history=()):
        self.record = record
        self.maker = maker
        self.rule = rule
        self.history = list(history)
        self.added: list = []

    async def get(self, model, _id):
        return self.record if isinstance(self.record, model) else None

    async def scalar(self, stmt, *a, **k):
        sql = str(stmt)
        if "audit_logs" in sql:
            return self.maker
        if "dual_control_rules" in sql:
            return self.rule
        return None

    async def scalars(self, stmt, *a, **k):
        return _Rows(self.history if "FROM attestations" in str(stmt) else [])

    def add(self, obj):
        if isinstance(obj, Attestation):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)
            self.history.insert(0, obj)
        self.added.append(obj)

    async def flush(self):
        return None


def _risk(**kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, title="Ransomware", reference="R-002",
        status=RiskStatus.assessed, workflow_status=WorkflowState.approved, owner_id=OTHER,
        review_frequency=ReviewFrequency.quarterly, next_review_date=date(2027, 1, 1),
    )
    base.update(kw)
    return Risk(**base)


def _asset(**kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, name="Core banking database",
        workflow_status=WorkflowStatus.approved, review_frequency=ReviewFrequency.annual,
        next_review_date=date(2027, 7, 3),
    )
    base.update(kw)
    return Asset(**base)


@pytest.fixture
def sod_on(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)


@pytest.fixture
def audited(monkeypatch):
    calls: list[dict] = []

    async def _record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit, "record", _record)
    return calls


def test_a_type_label_reads_naturally_inside_a_sentence():
    assert att.label_in_text("Risk") == "risk"
    assert att.label_in_text("Third party") == "third party"
    assert att.label_in_text("DPIA") == "DPIA"
    assert att.label_in_text("RCSA assessment") == "RCSA assessment"


async def test_without_write_permission_the_reason_names_the_permission_not_a_code(sod_on):
    ok, why = await att.attest_eligibility(AttestDB(), _user("risk:read"), "risk", uuid.uuid4(), _risk())
    assert ok is False
    assert why == "You don't have permission to attest risk records."
    ok, why = await att.attest_eligibility(AttestDB(), _user("vendor:read"), "vendor", uuid.uuid4(), None)
    assert why == "You don't have permission to attest third party records."


async def test_permission_is_judged_before_everything_else(sod_on):
    """Even on the user's own draft: the first gate the attest call applies wins."""
    mine = _risk(owner_id=ME, status=RiskStatus.draft)
    _ok, why = await att.attest_eligibility(AttestDB(maker=ME), _user("risk:read"), "risk", mine.id, mine)
    assert why.startswith("You don't have permission")


async def test_a_missing_record_cannot_be_attested(sod_on):
    ok, why = await att.attest_eligibility(AttestDB(), _user("risk:write"), "risk", uuid.uuid4(), None)
    assert (ok, why) == (False, "Risk not found")


async def test_the_owner_is_told_why_before_the_draft_rule(sod_on):
    mine = _risk(owner_id=ME, status=RiskStatus.draft)
    ok, why = await att.attest_eligibility(AttestDB(), _user("risk:write"), "risk", mine.id, mine)
    assert (ok, why) == (False, att.OWNER_REFUSAL)


async def test_a_draft_is_refused_on_its_business_status(sod_on):
    draft = _risk(status=RiskStatus.draft, workflow_status=WorkflowState.approved)
    ok, why = await att.attest_eligibility(AttestDB(), _user("risk:write"), "risk", draft.id, draft)
    assert (ok, why) == (False, att.DRAFT_REFUSAL)


async def test_the_lifecycle_rule_is_the_attest_calls_own_no_b1b(sod_on):
    """B1b is a pending product decision: an Assessed risk whose approval is still Draft
    can be attested today, so the page must not be told otherwise."""
    risk = _risk(status=RiskStatus.assessed, workflow_status=WorkflowState.draft)
    ok, why = await att.attest_eligibility(AttestDB(maker=OTHER), _user("risk:write"), "risk", risk.id, risk)
    assert (ok, why) == (True, None)


async def test_whoever_entered_the_record_hears_the_four_eyes_refusal(sod_on):
    risk = _risk()
    ok, why = await att.attest_eligibility(AttestDB(maker=ME), _user("risk:write"), "risk", risk.id, risk)
    assert ok is False
    assert why == dual_control.maker_checker_message("risk")


async def test_an_independent_writer_may_attest(sod_on):
    risk = _risk()
    assert await att.attest_eligibility(
        AttestDB(maker=OTHER), _user("risk:write"), "risk", risk.id, risk
    ) == (True, None)


async def test_with_segregation_off_the_maker_may_attest(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", False)
    risk = _risk()
    assert await att.attest_eligibility(
        AttestDB(maker=ME), _user("risk:write"), "risk", risk.id, risk
    ) == (True, None)


# ---------------------------------------------- the non-raising maker-checker ---
async def test_the_question_returns_exactly_what_the_gate_raises(sod_on):
    kw = dict(module="risk", action="attest", entity_type="risk", entity_id=uuid.uuid4(),
              checker_id=ME, subject="risk")
    text = await dual_control.record_maker_checker_refusal(AttestDB(maker=ME), **kw)
    with pytest.raises(HTTPException) as exc:
        await dual_control.enforce_record_maker_checker(AttestDB(maker=ME), **kw)
    assert exc.value.status_code == 403
    assert text == exc.value.detail


async def test_the_question_never_raises_and_answers_none_when_allowed(sod_on):
    kw = dict(module="risk", action="attest", entity_type="risk", entity_id=uuid.uuid4(), subject="risk")
    assert await dual_control.record_maker_checker_refusal(AttestDB(maker=OTHER), checker_id=ME, **kw) is None
    assert await dual_control.record_maker_checker_refusal(AttestDB(maker=None), checker_id=ME, **kw) is None
    assert await dual_control.record_maker_checker_refusal(AttestDB(maker=ME), checker_id=None, **kw) is None


async def test_an_explicit_opt_out_rule_lets_the_maker_through(sod_on):
    from app.models.authority import DualControlStatus

    rule = SimpleNamespace(enabled=True, status=DualControlStatus.active, requires_dual_control=False,
                           threshold_amount=None)
    assert await dual_control.record_maker_checker_refusal(
        AttestDB(maker=ME, rule=rule), module="risk", action="attest", entity_type="risk",
        entity_id=uuid.uuid4(), checker_id=ME,
    ) is None


async def test_a_custom_message_is_kept(sod_on):
    text = await dual_control.record_maker_checker_refusal(
        AttestDB(maker=ME), module="control", action="audit", entity_type="control",
        entity_id=uuid.uuid4(), checker_id=ME, message="Someone else must test it.",
    )
    assert text == "Someone else must test it."


# ----------------------------------------------------------------- the endpoints ---
async def test_the_read_carries_can_attest_and_blocked_reason(sod_on):
    risk = _risk()
    body = await att.get_status("risk", risk.id, AttestDB(record=risk, maker=OTHER), _user("risk:read", "risk:write"))
    assert body.can_attest is True and body.blocked_reason is None
    body = await att.get_status("risk", risk.id, AttestDB(record=risk, maker=ME), _user("risk:read", "risk:write"))
    assert body.can_attest is False
    assert body.blocked_reason == dual_control.maker_checker_message("risk")
    body = await att.get_status("risk", risk.id, AttestDB(record=risk), _user("risk:read"))
    assert body.can_attest is False
    assert body.blocked_reason == "You don't have permission to attest risk records."


async def test_the_read_still_answers_for_a_missing_record(sod_on):
    body = await att.get_status("risk", uuid.uuid4(), AttestDB(), _user("risk:read", "risk:write"))
    assert body.status == "never"
    assert (body.can_attest, body.blocked_reason) == (False, "Risk not found")


def test_the_read_schema_defaults_to_not_allowed():
    from app.schemas.attestation import AttestationStatus

    fields = AttestationStatus.model_fields
    assert fields["can_attest"].default is False
    assert fields["blocked_reason"].default is None


async def test_the_attest_call_still_raises_its_refusals(sod_on, audited):
    mine = _risk(owner_id=ME)
    with pytest.raises(HTTPException) as exc:
        await att.attest("risk", mine.id, AttestationCreate(), AttestDB(record=mine), _user("risk:write"))
    assert (exc.value.status_code, exc.value.detail) == (403, att.OWNER_REFUSAL)

    draft = _risk(status=RiskStatus.draft)
    with pytest.raises(HTTPException) as exc:
        await att.attest("risk", draft.id, AttestationCreate(), AttestDB(record=draft), _user("risk:write"))
    assert (exc.value.status_code, exc.value.detail) == (409, att.DRAFT_REFUSAL)

    risk = _risk()
    with pytest.raises(HTTPException) as exc:
        await att.attest("risk", risk.id, AttestationCreate(), AttestDB(record=risk, maker=ME), _user("risk:write"))
    assert (exc.value.status_code, exc.value.detail) == (403, dual_control.maker_checker_message("risk"))

    with pytest.raises(HTTPException) as exc:
        await att.attest("risk", risk.id, AttestationCreate(), AttestDB(record=risk), _user("risk:read"))
    assert exc.value.status_code == 403
    assert audited == []


# ============================================================================ B4 ===
def test_the_asset_has_one_review_clock_with_its_own_sweep():
    assert "asset" in att.REVIEW_CLOCK_ENTITY_TYPES
    # The alert scanner and My Work skip these types' attestations and watch the
    # record's own date instead (the asset review sweep): one clock, no drift.
    assert "asset" in NATIVE_REVIEW_ENTITY_TYPES
    assert att._native("asset", _asset())


async def test_attesting_an_asset_records_its_review_and_moves_the_next_date(sod_on, audited):
    asset = _asset(last_review_date=None)
    db = AttestDB(record=asset, maker=OTHER)
    body = await att.attest(
        "asset", asset.id, AttestationCreate(frequency=ReviewFrequency.monthly), db, _user("asset:write"),
    )
    today = date.today()
    due = next_review_date(ReviewFrequency.annual, today)
    assert asset.last_review_date == today
    assert asset.next_review_date == due
    row = db.history[0]
    assert row.frequency == ReviewFrequency.annual  # the asset's cycle, not the form's
    assert row.next_due == due
    assert body.native_review is True
    assert (body.next_due, body.frequency, body.status) == (due, ReviewFrequency.annual, "current")
    assert audited[0]["action"] == "attest"
    assert audited[0]["changes"]["next_review_date"] == str(due)


async def test_an_assets_attestation_reads_its_own_review_date(sod_on):
    asset = _asset(next_review_date=date(2027, 7, 3))
    body = await att.get_status("asset", asset.id, AttestDB(record=asset, maker=OTHER), _user("asset:read", "asset:write"))
    assert body.native_review is True
    assert body.next_due == date(2027, 7, 3)
    assert body.frequency == ReviewFrequency.annual


async def test_a_draft_asset_is_refused_on_its_workflow_state(sod_on):
    asset = _asset(workflow_status=WorkflowStatus.draft)
    ok, why = await att.attest_eligibility(AttestDB(maker=OTHER), _user("asset:write"), "asset", asset.id, asset)
    assert (ok, why) == (False, att.DRAFT_REFUSAL)


# ============================================================================ B5 ===
def test_a_route_is_named_from_the_records_own_reference_and_title():
    from app.api.v1.workflows import route_label

    assert route_label("risk", _risk()) == "R-002 Ransomware"
    assert route_label("risk", None) == "Risk"
    long = _risk(title="x" * 400)
    assert len(route_label("risk", long)) == 255


def test_a_route_links_to_the_records_register_with_the_browser_link_as_fallback():
    from app.api.v1.workflows import route_link

    risk = _risk()
    assert route_link(risk, "/risks?id=someone-else") == f"/risks?id={risk.id}"
    assert route_link(None, "/custom?id=1") == "/custom?id=1"
    assert route_link(SimpleNamespace(id=uuid.uuid4()), "/fallback") == "/fallback"


class StartDB:
    def __init__(self, record):
        self.record = record

    async def get(self, model, _id):
        return self.record if isinstance(self.record, model) else None

    async def scalar(self, *a, **k):
        return None


async def test_starting_a_route_ignores_the_browsers_label(monkeypatch, audited):
    """The R-002 / R-001 defect: a stale page sent another record's label."""
    from app.api.v1 import workflows
    from app.models.workflow import WorkflowInstanceStatus
    from app.schemas.workflow import StartRequest

    started: list[dict] = []

    async def _start(db, **kw):
        started.append(kw)
        return SimpleNamespace(
            id=uuid.uuid4(), definition_id=uuid.uuid4(), entity_type=kw["entity_type"],
            entity_id=kw["entity_id"], entity_label=kw["entity_label"],
            status=WorkflowInstanceStatus.in_progress, started_by_email="me@bank.pk",
            completed_at=None, total_stages=1, completed_stages=0, steps=[],
            created_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(workflows.workflow_engine, "start", _start)
    risk = _risk()  # approved: routed, not submitted
    body = StartRequest(entity_type="risk", entity_id=risk.id, entity_label="R-001 Unauthorized access",
                        link="/risks?id=wrong")
    result = await workflows.start_workflow(body, StartDB(risk), _user("risk:write", "workflow:write"))
    assert result.started is True
    assert started[0]["entity_label"] == "R-002 Ransomware"
    assert started[0]["link"] == f"/risks?id={risk.id}"
    assert audited[0]["action"] == "submit"
    assert audited[0]["summary"] == "Started approval route for R-002 Ransomware"
    assert "R-001" not in audited[0]["summary"]


async def test_a_route_for_a_record_that_cannot_be_found_is_named_by_its_type(monkeypatch, audited):
    from app.api.v1 import workflows
    from app.schemas.workflow import StartRequest

    async def _none(db, **kw):
        return None

    monkeypatch.setattr(workflows.workflow_engine, "start", _none)
    body = StartRequest(entity_type="risk", entity_id=uuid.uuid4(), entity_label="R-001 Unauthorized access")
    result = await workflows.start_workflow(body, StartDB(None), _user("risk:write", "workflow:write"))
    assert result.started is False and audited == []


# ============================================================================ B9 ===
def _rule(**kw):
    base = dict(label="High exposure", color="#dc2626", field="inherent_score", operator="gte",
                value="15", priority=0, enabled=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_verdict_says_which_condition_fired():
    from app.services import status_rules as engine

    out = engine.evaluate(SimpleNamespace(inherent_score=20), [_rule()])
    assert out == [{"label": "High exposure", "color": "#dc2626", "field": "inherent_score",
                    "operator": "gte", "value": "15"}]


def test_a_valueless_operator_reports_no_stale_value():
    from app.services import status_rules as engine

    stale = _rule(label="Overdue", field="next_review_date", operator="overdue", value="15")
    out = engine.evaluate(SimpleNamespace(next_review_date=date.today() - timedelta(days=1)), [stale])
    assert out[0]["operator"] == "overdue" and out[0]["value"] == ""
    assert engine.VALUELESS_OPERATORS <= set(engine.OPERATORS)


def test_verdicts_keep_priority_order_and_skip_disabled_rules():
    from app.services import status_rules as engine

    rules = [_rule(label="B", priority=2), _rule(label="A", priority=1), _rule(label="Off", enabled=False)]
    assert [v["label"] for v in engine.evaluate(SimpleNamespace(inherent_score=20), rules)] == ["A", "B"]


async def test_the_evaluate_endpoint_returns_the_condition(monkeypatch):
    from app.api.v1 import status_rules as api

    async def _rules(db, model):
        return [_rule()]

    class _DB:
        async def scalar(self, stmt):
            return SimpleNamespace(id=uuid.uuid4(), inherent_score=16)

    monkeypatch.setattr(api, "_rules_for", _rules)
    out = await api.evaluate_one("risk", uuid.uuid4(), _DB(), None)
    assert [(v.label, v.field, v.operator, v.value) for v in out] == [
        ("High exposure", "inherent_score", "gte", "15"),
    ]


def test_the_label_schema_stays_backward_compatible():
    from app.schemas.status_rule import StatusLabel

    assert StatusLabel(label="X", color="#000").model_dump() == {
        "label": "X", "color": "#000", "field": None, "operator": None, "value": None,
    }


# ======================================================================= B10 audit ===
class _AddOnly:
    def __init__(self):
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)


def test_a_repair_row_is_the_platforms_and_fires_no_webhook(monkeypatch):
    async def _boom(*a, **k):
        raise AssertionError("a start-up repair must not call out per record")

    monkeypatch.setattr(webhooks, "dispatch", _boom)
    db = _AddOnly()
    dr.system_audit(db, TENANT, action="update", entity_type="control", entity_id=ME,
                    summary="x" * 600, changes={"via": dr.REPAIR_VIA})
    (row,) = db.added
    assert isinstance(row, AuditLog)
    assert (row.actor_id, row.actor_email, row.tenant_id) == (None, SYSTEM_ACTOR_EMAIL, TENANT)
    assert len(row.summary) == 500


# ============================================================================ B10a ===
FW = {dr._norm("ISO/IEC 27001:2022"), dr._norm("PCI DSS v4.0.1")}


def _lookup(label, value=None, active=True):
    from app.db.fk_backfill import slug

    return SimpleNamespace(id=uuid.uuid4(), key=dr.CLASSIFICATION_LIST, label=label,
                           value=value or slug(label), active=active)


def test_a_value_is_misfiled_when_it_names_a_framework_or_a_nature():
    assert dr.misfiled_as("ISO/IEC 27001:2022", "iso_iec_27001_2022", FW) == dr.MISFILED_FRAMEWORK
    assert dr.misfiled_as("  iso/iec   27001:2022 ", "x", FW) == dr.MISFILED_FRAMEWORK
    assert dr.misfiled_as("Preventive", "preventive", FW) == dr.MISFILED_NATURE
    assert dr.misfiled_as("Something", "directive", FW) == dr.MISFILED_NATURE
    assert dr.misfiled_as("Technical", "technical", FW) is None
    assert dr.misfiled_as("", "", FW) is None


def test_misfiled_values_are_retired_once_and_an_admins_choice_stands():
    iso, prev, tech = _lookup("ISO/IEC 27001:2022"), _lookup("Preventive"), _lookup("Technical")
    retire, respected = dr.plan_value_retirement([iso, prev, tech], FW, set())
    assert [(r.label, k) for r, k in retire] == [("ISO/IEC 27001:2022", "framework"), ("Preventive", "nature")]
    assert respected == set()

    # After the first start: both inactive and audited — nothing more to do.
    iso.active = prev.active = False
    assert dr.plan_value_retirement([iso, prev, tech], FW, {iso.id, prev.id}) == ([], set())

    # An administrator brings Preventive back: it is theirs now.
    prev.active = True
    assert dr.plan_value_retirement([iso, prev, tech], FW, {iso.id, prev.id}) == ([], {prev.id})

    # A value a tenant deactivated themselves needs nothing either.
    assert dr.plan_value_retirement([_lookup("Detective", active=False)], FW, set()) == ([], set())


def test_a_framework_link_and_its_text_are_cleared_together():
    fix = dr.plan_classification_fix(
        text_value="ISO/IEC 27001:2022", lookup_label="ISO/IEC 27001:2022", has_lookup=True,
        nature=None, framework_names=FW,
    )
    assert (fix.clear_id, fix.clear_text, fix.framework, fix.nature) == (True, True, "ISO/IEC 27001:2022", None)
    assert dr.classification_fix_summary(fix) == (
        "Cleared the classification 'ISO/IEC 27001:2022': it names a framework, "
        "not a kind of control (data repair)"
    )


def test_a_nature_value_is_copied_only_into_an_empty_nature():
    fix = dr.plan_classification_fix(text_value="", lookup_label="Detective", lookup_value="detective",
                                     has_lookup=True, nature=None, framework_names=FW)
    assert (fix.clear_id, fix.nature, fix.nature_source) == (False, "detective", "Detective")
    assert dr.classification_fix_summary(fix) == "Nature set to Detective from the classification 'Detective' (data repair)"
    kept = dr.plan_classification_fix(text_value="", lookup_label="Detective", has_lookup=True,
                                      nature="preventive", framework_names=FW)
    assert not kept


def test_unlinked_text_is_judged_on_its_own():
    fix = dr.plan_classification_fix(text_value="corrective", lookup_label=None, has_lookup=False,
                                     nature="", framework_names=FW)
    assert fix.nature == "corrective" and not fix.clear_text
    fix = dr.plan_classification_fix(text_value="PCI DSS v4.0.1", lookup_label=None, has_lookup=False,
                                     nature=None, framework_names=FW)
    assert fix.clear_text and not fix.clear_id and fix.framework == "PCI DSS v4.0.1"


def test_a_genuine_classification_is_left_alone():
    assert not dr.plan_classification_fix(text_value="Technical", lookup_label="Technical",
                                          has_lookup=True, nature=None, framework_names=FW)


def test_the_audit_changes_record_from_and_to():
    fix = dr.ClassificationFix(clear_id=True, clear_text=True, framework="ISO", nature="preventive",
                               nature_source="Preventive")
    assert dr.classification_fix_changes(fix, classification_id=ME, text_value="ISO") == {
        "classification_id": {"from": str(ME), "to": None},
        "classification": {"from": "ISO", "to": ""},
        "nature": {"from": None, "to": "preventive"},
        "via": dr.REPAIR_VIA,
    }


class RepairDB:
    """An in-memory tenant: frameworks, the classification list, controls and the trail.
    Updates are applied, audit rows appended, so a second start sees the first's work."""

    def __init__(self, frameworks, lookups, controls):
        self.frameworks = list(frameworks)
        self.lookups = {row.id: row for row in lookups}
        self.controls = {c.id: c for c in controls}
        self.trail: list = []
        self.control_query_params: dict = {}

    def add(self, obj):
        self.trail.append(obj)

    async def scalars(self, stmt, *a, **k):
        sql = str(stmt)
        if "FROM frameworks" in sql:
            return _Rows(self.frameworks)
        if "FROM lookups" in sql:
            return _Rows(self.lookups.values())
        if "FROM audit_logs" in sql:
            params = stmt.compile().params
            kind = params.get("entity_type_1")
            need_key = "changes_2" in params and params["changes_2"]
            return _Rows(
                r.entity_id for r in self.trail
                if r.entity_type == kind and r.actor_id is None
                and (r.changes or {}).get("via") == dr.REPAIR_VIA
                and (not need_key or need_key in (r.changes or {}))
            )
        raise AssertionError(sql)

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        params = stmt.compile().params
        if sql.startswith("UPDATE controls"):
            control = self.controls[params["id_1"]]
            for name in ("classification_id", "classification", "nature"):
                if name in params:
                    setattr(control, name, params[name])
            return None
        if "FROM controls" in sql:
            self.control_query_params = params
            return _Rows(
                (c.id, c.classification, c.classification_id, c.nature)
                for c in self.controls.values() if not c.deleted
            )
        raise AssertionError(sql)

    def writes(self) -> int:
        return len(self.trail)


def _control(classification="", classification_id=None, nature=None, deleted=False):
    return SimpleNamespace(id=uuid.uuid4(), classification=classification,
                           classification_id=classification_id, nature=nature, deleted=deleted)


async def test_the_classification_repair_audits_every_change_and_runs_once():
    iso, prev, tech = _lookup("ISO/IEC 27001:2022"), _lookup("Preventive"), _lookup("Technical")
    from_pack = _control("ISO/IEC 27001:2022", iso.id)
    typed_framework = _control("ISO/IEC 27001:2022")
    preventive = _control("Preventive", prev.id)
    already = _control("Preventive", prev.id, nature="detective")
    technical = _control("Technical", tech.id)
    db = RepairDB(["ISO/IEC 27001:2022"], [iso, prev, tech],
                  [from_pack, typed_framework, preventive, already, technical])

    assert await dr.repair_control_classifications(db, TENANT) == (2, 1, 2)
    assert (from_pack.classification_id, from_pack.classification) == (None, "")
    assert typed_framework.classification == ""
    assert preventive.nature == "preventive" and preventive.classification_id == prev.id
    assert already.nature == "detective"
    assert technical.classification_id == tech.id
    assert (iso.active, prev.active, tech.active) == (False, False, True)

    by_record = {r.entity_id: r for r in db.trail}
    assert set(by_record) == {from_pack.id, typed_framework.id, preventive.id, iso.id, prev.id}
    for row in db.trail:
        assert (row.actor_id, row.actor_email, row.tenant_id) == (None, SYSTEM_ACTOR_EMAIL, TENANT)
        assert row.action == "update" and row.changes["via"] == dr.REPAIR_VIA
    assert by_record[iso.id].entity_type == "lookup"
    assert by_record[iso.id].changes["active"] == {"from": True, "to": False}
    assert by_record[prev.id].summary == (
        "Deactivated 'Preventive' in Control classification: it is a control's nature, "
        "recorded in the Nature field (data repair)"
    )
    assert by_record[preventive.id].changes["nature"] == {"from": None, "to": "preventive"}

    # Every later start is a no-op.
    before = db.writes()
    assert await dr.repair_control_classifications(db, TENANT) == (0, 0, 0)
    assert db.writes() == before


async def test_a_value_an_admin_brought_back_is_not_fought_over():
    prev = _lookup("Preventive")
    first = _control("Preventive", prev.id)
    db = RepairDB([], [prev], [first])
    assert await dr.repair_control_classifications(db, TENANT) == (0, 1, 1)

    prev.active = True  # an administrator re-activates it
    later = _control("Preventive", prev.id)
    typed = _control("preventive")
    db.controls.update({later.id: later, typed.id: typed})
    before = db.writes()
    assert await dr.repair_control_classifications(db, TENANT) == (0, 0, 0)
    assert db.writes() == before and prev.active is True
    assert later.nature is None and typed.nature is None
    assert prev.id not in db.control_query_params.get("classification_id_1", [])


async def test_a_nature_the_owner_cleared_is_not_copied_back_on_the_next_start():
    prev = _lookup("Preventive")
    c7 = _control("Preventive", prev.id)
    db = RepairDB([], [prev], [c7])
    assert await dr.repair_control_classifications(db, TENANT) == (0, 1, 1)
    assert c7.nature == "preventive"

    c7.nature = None  # the owner judges nature not applicable (PATCH nature: null)
    before = db.writes()
    assert await dr.repair_control_classifications(db, TENANT) == (0, 0, 0)
    assert c7.nature is None and db.writes() == before
    # ...and a third start still leaves it alone.
    assert await dr.repair_control_classifications(db, TENANT) == (0, 0, 0)
    assert c7.nature is None and db.writes() == before


def test_the_planner_copies_a_nature_once():
    kw = dict(text_value="", lookup_label="Preventive", lookup_value="preventive", has_lookup=True,
              nature=None, framework_names=set())
    assert dr.plan_classification_fix(**kw).nature == "preventive"
    assert not dr.plan_classification_fix(**kw, nature_copied_before=True)


async def test_a_clean_tenant_costs_reads_only():
    db = RepairDB(["ISO/IEC 27001:2022"], [_lookup("Technical")], [_control("Technical")])
    assert await dr.repair_control_classifications(db, TENANT) == (0, 0, 0)
    assert db.writes() == 0


# ============================================================================ B10b ===
def test_the_import_row_names_no_person():
    assert dr.imported_approval_audit("approved") == {
        "action": "workflow_import",
        "summary": "Imported as approved: no approver recorded",
        "changes": {"from": None, "to": "approved", "via": "import"},
    }
    assert dr.imported_approval_audit("retired")["summary"] == "Imported as retired: no approver recorded"


def test_the_import_row_is_itself_an_approval_step_so_it_is_written_once():
    from app.services.record_workflow import AUDIT_PREFIX

    assert dr.IMPORT_ACTION.startswith(AUDIT_PREFIX)
    assert dr.IMPORT_ACTION != f"{AUDIT_PREFIX}owner"
    assert len(dr.IMPORT_ACTION) <= AuditLog.__table__.c.action.type.length


def test_the_candidates_are_approved_or_retired_live_records_with_no_step():
    from sqlalchemy.dialects import postgresql

    stmt = dr.imported_approvals_query(Asset, "asset")
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "NOT (EXISTS" in sql and "audit_logs.entity_id = assets.id" in sql
    assert "assets.deleted IS false" in sql
    params = compiled.params
    assert "workflow\\_%" in params.values() or "workflow_%" in params.values()
    assert "workflow_owner" in params.values()  # an owner change approves nothing
    assert "asset" in params.values()
    states = next(v for v in params.values() if isinstance(v, list))
    assert {getattr(s, "value", s) for s in states} == {"approved", "retired"}


def test_a_type_without_a_lifecycle_has_no_candidates():
    from app.models.audit import AuditLog as NoLifecycle

    assert dr.imported_approvals_query(NoLifecycle, "audit") is None


class ImportDB:
    """Approved / retired records per table, answering the candidate query the way the
    SQL does: no ``workflow_*`` step (other than an owner change) under that type."""

    def __init__(self, records: dict[str, list[tuple[uuid.UUID, object]]], trail=()):
        self.records = records
        self.trail = list(trail)

    def add(self, obj):
        self.trail.append(obj)

    def _has_step(self, entity_type, rid):
        return any(
            r.entity_type == entity_type and r.entity_id == rid
            and r.action.startswith("workflow_") and r.action != "workflow_owner"
            for r in self.trail
        )

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        entity_type = next(v for v in stmt.compile().params.values() if isinstance(v, str) and not v.startswith("workflow"))
        for table, rows in self.records.items():
            if f"FROM {table} " in sql or sql.rstrip().endswith(f"FROM {table}"):
                return _Rows((rid, st) for rid, st in rows if not self._has_step(entity_type, rid))
        return _Rows([])


async def test_the_backfill_writes_one_system_row_per_record_once():
    approved, retired, stepped, owner_only = (uuid.uuid4() for _ in range(4))
    trail = [
        SimpleNamespace(entity_type="risk", entity_id=stepped, action="workflow_approve"),
        SimpleNamespace(entity_type="risk", entity_id=owner_only, action="workflow_owner"),
    ]
    db = ImportDB({
        "risks": [(approved, WorkflowState.approved), (stepped, WorkflowState.approved),
                  (owner_only, WorkflowState.approved)],
        "assets": [(retired, WorkflowStatus.retired)],
    }, trail)

    assert await dr.backfill_imported_approvals(db, TENANT) == 3
    rows = [r for r in db.trail if isinstance(r, AuditLog)]
    by_id = {r.entity_id: r for r in rows}
    assert set(by_id) == {approved, owner_only, retired}
    assert by_id[approved].entity_type == "risk" and by_id[retired].entity_type == "asset"
    assert by_id[retired].summary == "Imported as retired: no approver recorded"
    assert by_id[approved].changes == {"from": None, "to": "approved", "via": "import"}
    for row in rows:
        assert (row.actor_id, row.actor_email, row.action) == (None, SYSTEM_ACTOR_EMAIL, "workflow_import")
        assert "@" not in row.summary

    assert await dr.backfill_imported_approvals(db, TENANT) == 0  # the next start


async def test_the_approval_history_reads_the_import_as_its_own_step():
    from app.services import record_workflow

    row = AuditLog(action="workflow_import", actor_id=None, actor_email=SYSTEM_ACTOR_EMAIL,
                   changes={"from": None, "to": "approved", "via": "import"},
                   summary="Imported as approved: no approver recorded")
    row.created_at = datetime.now(timezone.utc)

    class _DB:
        async def scalars(self, stmt):
            return _Rows([row])

    (item,) = await record_workflow.history(_DB(), "asset", uuid.uuid4())
    assert (item["action"], item["from_state"], item["to_state"], item["via"]) == (
        "import", None, "approved", "import",
    )
    assert item["actor_id"] is None and item["actor_email"] == SYSTEM_ACTOR_EMAIL


# ------------------------------------------------------------- start-up safety ---
class _NestedDB:
    def __init__(self):
        self.rolled_back = False

    def begin_nested(self):
        outer = self

        class _Savepoint:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                outer.rolled_back = exc_type is not None
                return False

        return _Savepoint()


async def test_a_failing_repair_is_rolled_back_logged_and_skipped():
    report = dr.RepairReport()
    db = _NestedDB()

    async def _fails():
        raise RuntimeError("bad row")

    assert await dr._guarded(db, report, "imported_approvals", _fails) is None
    assert db.rolled_back and report.repairs_failed == ["imported_approvals"]
    assert report.any()

    async def _works():
        return 7

    assert await dr._guarded(_NestedDB(), report, "control_classifications", _works) == 7


# ============================================================ round 2 integration ===
def test_no_nature_value_is_seeded_as_a_control_classification():
    """A new tenant must not get classifications the B10a repair retires on restart."""
    from app.db.lookup_seed import DEFAULT_LOOKUPS, missing_defaults

    seeded = DEFAULT_LOOKUPS["control_classification"]
    assert not [v for v in seeded if dr.misfiled_as(v.label, v.value, set())]
    assert missing_defaults("control_classification", []) == seeded
