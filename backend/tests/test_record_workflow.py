"""One lifecycle per record (§1.5): the transition table, who may take each step, the
guard that stops a form moving the state, and the write-back from the approvals inbox.

No database: the table and permission choice are pure; the guard is exercised on a real
SQLAlchemy ``Session`` with no bind — ``before_flush`` runs before any SQL, so a refused
change raises there, and a permitted one gets as far as asking for a connection.
"""
from __future__ import annotations

import importlib
import inspect
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session, make_transient_to_detached

import app.models  # noqa: F401 - populate mappers
from app.models.asset import Asset
from app.models.base import WorkflowState
from app.models.enums import WorkflowStatus
from app.models.organization import BusinessUnit
from app.models.risk import Risk
from app.services import record_workflow as rw


# ---------------------------------------------------------- transition table ---
def test_the_lifecycle_runs_draft_review_approved_retired():
    assert rw.next_state("draft", "submit") == "in_review"
    assert rw.next_state("in_review", "approve") == "approved"
    assert rw.next_state("approved", "retire") == "retired"


def test_reject_returns_a_record_in_review_to_draft():
    assert rw.next_state("in_review", "reject") == "draft"
    assert "reject" in rw.REASON_REQUIRED


def test_revise_reopens_an_approved_record_as_a_draft():
    assert rw.next_state("approved", "revise") == "draft"


def test_retired_is_terminal():
    assert rw.allowed_actions("retired") == []
    for action in rw.ACTIONS:
        assert rw.next_state("retired", action) is None


def test_steps_cannot_be_skipped():
    assert rw.next_state("draft", "approve") is None
    assert rw.next_state("draft", "retire") is None
    assert rw.next_state("in_review", "retire") is None
    assert rw.next_state("approved", "approve") is None


def test_allowed_actions_follow_the_table_in_button_order():
    assert rw.allowed_actions("draft") == ["submit"]
    assert rw.allowed_actions(WorkflowState.in_review) == ["approve", "reject"]
    assert rw.allowed_actions(WorkflowStatus.approved) == ["revise", "retire"]


def test_every_state_in_both_enums_is_in_the_table():
    for enum in (WorkflowState, WorkflowStatus):
        assert {s.value for s in enum} == set(rw.TRANSITIONS)


# ----------------------------------------------------------- permissions ---
def test_approve_uses_the_module_approve_permission_when_the_catalog_has_one():
    assert rw.required_permissions("exception", "approve") == ("exception:read", "exception:approve")


def test_approve_falls_back_to_the_generic_workflow_permission():
    assert rw.required_permissions("risk", "approve") == ("risk:read", "workflow:approve")
    assert rw.required_permissions("business_unit", "reject") == ("org:read", "workflow:approve")


def test_a_module_approve_permission_is_picked_up_from_the_catalog_given():
    catalog = {"risk:read", "risk:write", "risk:approve", "workflow:approve"}
    assert rw.required_permissions("risk", "approve", catalog) == ("risk:read", "risk:approve")


def test_submit_revise_and_retire_need_the_module_write_permission():
    for action in ("submit", "revise", "retire"):
        assert rw.required_permissions("control", action) == ("control:write",)


def test_an_unknown_action_is_a_422():
    with pytest.raises(HTTPException) as exc:
        rw.required_permissions("risk", "publish")
    assert exc.value.status_code == 422


def test_an_unknown_entity_type_is_a_422():
    with pytest.raises(HTTPException) as exc:
        rw.required_permissions("no_such_type", "submit")
    assert exc.value.status_code == 422


def test_actions_are_filtered_by_what_the_user_holds():
    editor = {"risk:read", "risk:write"}
    approver = {"risk:read", "workflow:approve"}
    assert rw.actions_for_user("draft", "risk", editor) == ["submit"]
    assert rw.actions_for_user("draft", "risk", approver) == []
    assert rw.actions_for_user("in_review", "risk", editor) == []
    assert rw.actions_for_user("in_review", "risk", approver) == ["approve", "reject"]


def test_a_live_route_takes_the_decision_away_from_the_record():
    approver = {"risk:read", "workflow:approve"}
    assert rw.actions_for_user("in_review", "risk", approver, routing=True) == []


# ------------------------------------------------------------------ guard ---
def test_guard_decision_refuses_a_change_outside_the_service():
    assert rw.guard_violation([WorkflowState.draft], [WorkflowState.approved], allowed=False)


def test_guard_decision_echoing_the_same_value_is_not_a_change():
    assert not rw.guard_violation([WorkflowState.draft], [WorkflowState.draft], allowed=False)
    assert not rw.guard_violation(["approved"], [WorkflowStatus.approved], allowed=False)


def test_guard_decision_allows_the_service_and_new_rows():
    assert not rw.guard_violation([WorkflowState.draft], [WorkflowState.approved], allowed=True)
    assert not rw.guard_violation([], [WorkflowState.approved], allowed=False)


def _persistent(model, **values):
    obj = model(id=uuid.uuid4(), **values)
    make_transient_to_detached(obj)
    session = Session()
    session.add(obj)
    return session, obj


def test_the_flush_refuses_a_form_moving_the_state():
    session, risk = _persistent(Risk, title="R", workflow_status=WorkflowState.draft)
    risk.workflow_status = WorkflowState.approved
    with pytest.raises(rw.WorkflowStateLocked) as exc:
        session.flush()
    assert exc.value.status_code == 409
    assert exc.value.detail == rw.LOCKED_DETAIL


def test_the_flush_lets_an_echoed_value_through():
    session, risk = _persistent(Risk, title="R", workflow_status=WorkflowState.in_review)
    risk.workflow_status = WorkflowState.in_review
    risk.title = "Renamed"
    with pytest.raises(UnboundExecutionError):  # got past the guard to the (absent) DB
        session.flush()


def test_the_flush_lets_the_lifecycle_service_through():
    session, risk = _persistent(Risk, title="R", workflow_status=WorkflowState.draft)
    risk.workflow_status = WorkflowState.in_review
    with rw.system_write():
        with pytest.raises(UnboundExecutionError):
            session.flush()


def test_the_guard_covers_assets_own_workflow_column():
    session, asset = _persistent(Asset, name="Core switch", workflow_status=WorkflowStatus.draft)
    asset.workflow_status = WorkflowStatus.approved
    with pytest.raises(rw.WorkflowStateLocked):
        session.flush()


def test_inserts_are_never_restricted():
    session = Session()
    session.add(Risk(id=uuid.uuid4(), title="Imported", workflow_status=WorkflowState.approved))
    with pytest.raises(UnboundExecutionError):
        session.flush()


def test_system_write_is_scoped_to_its_block():
    assert rw._WRITE_ALLOWED.get() is False
    with rw.system_write():
        assert rw._WRITE_ALLOWED.get() is True
    assert rw._WRITE_ALLOWED.get() is False


def test_the_guard_is_registered_once():
    rw.install_guard()
    rw.install_guard()
    from sqlalchemy import event

    assert event.contains(Session, "before_flush", rw._before_flush)


# ------------------------------------------------------------- write-back ---
def test_an_approval_promotes_a_draft_or_in_review_record():
    assert rw.write_back_target("in_review", approved=True) == "approved"
    assert rw.write_back_target("draft", approved=True) == "approved"


def test_a_rejection_returns_an_in_review_record_to_draft():
    assert rw.write_back_target("in_review", approved=False) == "draft"


def test_decisions_on_settled_records_leave_them_alone():
    assert rw.write_back_target("approved", approved=False) is None
    assert rw.write_back_target("approved", approved=True) is None
    assert rw.write_back_target("retired", approved=True) is None
    assert rw.write_back_target("draft", approved=False) is None


def test_the_approvals_inbox_writes_the_decision_back():
    from app.api.v1 import approvals

    source = inspect.getsource(approvals.decide_approval)
    assert "record_workflow.write_back" in source
    assert "on_approval_decided(db, obj, actor=user)" in source


def test_a_finished_route_writes_its_outcome_back():
    from app.services import workflow_engine

    source = inspect.getsource(workflow_engine.on_approval_decided)
    assert source.count("_record_outcome(") == 2  # approved and rejected endings
    assert "record_workflow.write_back" in inspect.getsource(workflow_engine._record_outcome)
    assert 'action="withdraw"' in inspect.getsource(workflow_engine.cancel)


# ---------------------------------------------------------------- apply() ---
class _FakeDb:
    def __init__(self):
        self.flushed = 0

    async def flush(self):
        self.flushed += 1


def _user(*perms):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@bank.pk", permission_codes=list(perms)
    )


@pytest.fixture
def quiet(monkeypatch):
    """Stub everything apply() calls outside itself; record what was audited."""
    from app.services import audit, authority_limits, dual_control, workflow_engine

    calls: dict[str, list] = {"audit": [], "sod": [], "start": []}

    async def _none(*a, **k):
        return None

    async def _sod(db, **kw):
        calls["sod"].append(kw)

    async def _audit(db, **kw):
        calls["audit"].append(kw)

    async def _start(db, **kw):
        calls["start"].append(kw)
        return None

    monkeypatch.setattr(workflow_engine, "instance_for", _none)
    monkeypatch.setattr(workflow_engine, "start", _start)
    monkeypatch.setattr(dual_control, "enforce_record_maker_checker", _sod)
    monkeypatch.setattr(dual_control, "enforce_maker_checker", _sod)
    monkeypatch.setattr(dual_control, "enforce_maker_role", _none)
    monkeypatch.setattr(authority_limits, "enforce", _none)
    monkeypatch.setattr(audit, "record", _audit)
    monkeypatch.setattr(rw, "last_submitter", _none)
    return calls


async def test_submit_moves_to_review_and_audits(quiet):
    # F-21: a risk is submitted with an owner and a business unit.
    risk = Risk(id=uuid.uuid4(), title="R", reference="R-1", workflow_status=WorkflowState.draft,
                owner_id=uuid.uuid4())
    risk.business_units.append(BusinessUnit(id=uuid.uuid4(), name="Retail"))
    result = await rw.apply(_FakeDb(), _user("risk:read", "risk:write"), risk, "risk", "submit")
    assert result.state == "in_review" and risk.workflow_status == WorkflowState.in_review
    assert quiet["start"], "submit must offer the record to an enabled route"
    entry = quiet["audit"][0]
    assert entry["action"] == "workflow_submit"
    assert entry["changes"] == {"from": "draft", "to": "in_review"}


async def test_approve_runs_four_eyes_before_moving(quiet):
    risk = Risk(id=uuid.uuid4(), title="R", workflow_status=WorkflowState.in_review)
    await rw.apply(_FakeDb(), _user("risk:read", "workflow:approve"), risk, "risk", "approve")
    assert risk.workflow_status == WorkflowState.approved
    assert [c["action"] for c in quiet["sod"]] == ["approve", "approve"]
    assert all(c["module"] == "risk" for c in quiet["sod"])


async def test_reject_needs_a_reason(quiet):
    risk = Risk(id=uuid.uuid4(), title="R", workflow_status=WorkflowState.in_review)
    with pytest.raises(HTTPException) as exc:
        await rw.apply(_FakeDb(), _user("risk:read", "workflow:approve"), risk, "risk", "reject", "  ")
    assert exc.value.status_code == 422
    await rw.apply(_FakeDb(), _user("risk:read", "workflow:approve"), risk, "risk", "reject", "No owner")
    assert risk.workflow_status == WorkflowState.draft
    assert quiet["audit"][-1]["changes"]["reason"] == "No owner"


async def test_a_missing_permission_is_a_403(quiet):
    risk = Risk(id=uuid.uuid4(), title="R", workflow_status=WorkflowState.in_review)
    with pytest.raises(HTTPException) as exc:
        await rw.apply(_FakeDb(), _user("risk:read", "risk:write"), risk, "risk", "approve")
    assert exc.value.status_code == 403
    assert risk.workflow_status == WorkflowState.in_review


async def test_a_step_the_table_does_not_allow_is_a_409(quiet):
    risk = Risk(id=uuid.uuid4(), title="R", workflow_status=WorkflowState.draft)
    with pytest.raises(HTTPException) as exc:
        await rw.apply(_FakeDb(), _user("risk:read", "workflow:approve"), risk, "risk", "approve")
    assert exc.value.status_code == 409


async def test_a_live_route_refuses_a_direct_decision(quiet, monkeypatch):
    from app.services import workflow_engine

    async def _live(*a, **k):
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(workflow_engine, "instance_for", _live)
    risk = Risk(id=uuid.uuid4(), title="R", workflow_status=WorkflowState.in_review)
    with pytest.raises(HTTPException) as exc:
        await rw.apply(_FakeDb(), _user("risk:read", "workflow:approve"), risk, "risk", "approve")
    assert exc.value.status_code == 409


async def test_four_eyes_refusal_leaves_the_state_alone(quiet, monkeypatch):
    from app.services import dual_control

    async def _refuse(db, **kw):
        raise HTTPException(status_code=403, detail="Segregation of duties")

    monkeypatch.setattr(dual_control, "enforce_record_maker_checker", _refuse)
    risk = Risk(id=uuid.uuid4(), title="R", workflow_status=WorkflowState.in_review)
    with pytest.raises(HTTPException) as exc:
        await rw.apply(_FakeDb(), _user("risk:read", "workflow:approve"), risk, "risk", "approve")
    assert exc.value.status_code == 403
    assert risk.workflow_status == WorkflowState.in_review


async def test_assets_are_moved_with_their_own_enum(quiet):
    asset = Asset(id=uuid.uuid4(), name="Core switch", workflow_status=WorkflowStatus.draft)
    await rw.apply(_FakeDb(), _user("asset:read", "asset:write"), asset, "asset", "submit")
    assert asset.workflow_status is WorkflowStatus.in_review


# ----------------------------------------------------- schemas and import ---
#: Schema modules this stream owns; the rest are migrated by their module engineers.
OWNED_SCHEMAS = (
    "aml", "asset", "authority", "bia", "continuity", "compliance", "declaration",
    "exception", "data_protection", "fraud", "icfr", "esg", "governance", "model_risk",
    "internal_audit", "outsourcing", "integrations", "risk_quant", "privacy", "shariah",
    "scenario", "whistleblowing", "vulnerability",
)


def _schema_classes(module_name):
    from pydantic import BaseModel

    module = importlib.import_module(f"app.schemas.{module_name}")
    return [
        obj for obj in vars(module).values()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == module.__name__
    ]


def test_no_owned_create_or_update_schema_accepts_workflow_status():
    bad = [
        f"{m}.{cls.__name__}"
        for m in OWNED_SCHEMAS
        for cls in _schema_classes(m)
        if cls.__name__.endswith(("Create", "Update", "Base", "Write"))
        and "workflow_status" in cls.model_fields
    ]
    assert bad == []


def test_read_schemas_still_report_workflow_status():
    readers = [
        cls for m in OWNED_SCHEMAS for cls in _schema_classes(m)
        if cls.__name__.endswith("Read") and "workflow_status" in cls.model_fields
    ]
    assert len(readers) >= 36


async def test_import_still_brings_the_legacy_state_on_create():
    """A CSV row from a legacy tool keeps its approved state, written in a system_write
    block after the module's own create function ran on a body without the field."""
    from app.models.compliance import Framework
    from app.schemas.compliance import FrameworkCreate
    from app.services import import_registry as ir

    seen = {}
    record = Framework(id=uuid.uuid4(), name="ISO", workflow_status=WorkflowState.draft)

    async def create(*, body, db, user):
        seen["body"] = body
        return SimpleNamespace(id=record.id)

    class _Db:
        async def get(self, model, rid):
            return record if rid == record.id else None

        async def flush(self):
            seen["allowed_at_flush"] = rw._WRITE_ALLOWED.get()

        def add(self, obj):  # the audit entry for the carried-over state
            seen.setdefault("added", []).append(obj)

    res = ir.ResourceIO(
        resource="x", label="X", model=Framework, create_schema=FrameworkCreate,
        create_func=create, read_perm="compliance:read", write_perm="compliance:write",
        importable=True, columns=[ir.text("name"), ir.enum_col("workflow_status", WorkflowState)],
    )
    wrapped = ir._importing_workflow_status(res)
    assert "workflow_status" in wrapped.create_schema.model_fields
    body = wrapped.create_schema(name="ISO", workflow_status="approved")
    import uuid as _uuid

    approver = SimpleNamespace(
        id=_uuid.uuid4(), tenant_id=_uuid.uuid4(), email="approver@bank.pk",
        permission_codes=["compliance:read", "workflow:approve"],
    )
    from app.services import audit as _audit

    async def _record(db, **kw):  # the carried-over state is audited; capture, don't write
        seen["audited"] = kw

    original, _audit.record = _audit.record, _record
    try:
        await wrapped.create_func(body=body, db=_Db(), user=approver)
    finally:
        _audit.record = original
    assert seen["audited"]["action"] == "import_state"
    assert type(seen["body"]) is FrameworkCreate
    assert "workflow_status" not in seen["body"].model_fields_set
    assert record.workflow_status == WorkflowState.approved
    assert seen["allowed_at_flush"] is True
