"""My Work (product review F-15, plan §3.2): everything waiting for one person.

No database: the pure rules are tested directly, each kind's builder is driven with a
fake session that returns canned rows, and the statements are compiled for PostgreSQL
to pin what they filter on.

Pinned here:

1. **Shape** — sections in a fixed order (decisions first), overdue first inside each,
   counts per kind, at most ``MAX_ITEMS`` shown.
2. **Decisions** — an approval is "waiting for me" only when it is addressed to me, my
   role or nobody in particular, and I may decide it (permission, not the maker, not
   voted); records in review exclude their maker and submitter while four-eyes applies
   and anything an approval route owns.
3. **Due items** — the look-ahead window, KRI reading cadence, policy acknowledgement
   scope, locked modules hidden.
4. **Quick action** — the owner (or ``risk:write``) marks a treatment action done; it is
   audited and the risk's treatment deadline follows.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.models.approval import ApprovalRequest
from app.models.enums import ApprovalStatus, ReviewFrequency
from app.models.risk import Risk, RiskTreatmentAction
from app.schemas.my_work import MyWorkItem
from app.services import audit as audit_service
from app.services import dual_control
from app.services import my_work as mw
from app.services.notifications import Directory, DirectoryUser

TODAY = date(2026, 9, 12)
HORIZON = TODAY + timedelta(days=mw.HORIZON_DAYS)
ME, OTHER, MAKER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _item(title, due=None, **kw):
    return mw.item("treatment_action", TODAY, HORIZON, due=due, id=uuid.uuid4(), title=title, **kw)


# ==================================================================== shape ===
def test_due_flags():
    assert mw.due_flags(TODAY - timedelta(days=1), TODAY, HORIZON) == (True, False)
    assert mw.due_flags(TODAY, TODAY, HORIZON) == (False, True)
    assert mw.due_flags(HORIZON, TODAY, HORIZON) == (False, True)
    assert mw.due_flags(HORIZON + timedelta(days=1), TODAY, HORIZON) == (False, False)
    assert mw.due_flags(None, TODAY, HORIZON) == (False, False)


def test_overdue_first_then_by_date_undated_last():
    items = [_item("c", TODAY + timedelta(days=5)), _item("undated"), _item("b", TODAY - timedelta(days=1)),
             _item("a", TODAY - timedelta(days=9)), _item("d", TODAY)]
    assert [i.title for i in mw.sort_items(items)] == ["a", "b", "d", "c", "undated"]


def test_a_section_counts_everything_and_shows_at_most_max_items():
    items = [_item(f"t{i}", TODAY - timedelta(days=1)) for i in range(mw.MAX_ITEMS + 7)]
    s = mw.build_section("treatment_action", items)
    assert s.count == mw.MAX_ITEMS + 7 and s.overdue == mw.MAX_ITEMS + 7
    assert len(s.items) == mw.MAX_ITEMS and s.truncated
    assert s.label == "Your risk treatment actions" and s.hint


def test_assemble_keeps_the_kind_order_and_totals():
    found = {"policy_ack": [_item("p")], "approval": [_item("a", TODAY - timedelta(days=2))]}
    out = mw.assemble(ME, TODAY, found)
    assert [s.kind for s in out.sections] == [k for k, _l, _h in mw.KINDS]
    assert out.sections[0].kind == "approval"
    assert out.total == 2 and out.overdue == 1 and out.counts["approval"] == 1 and out.counts["issue"] == 0
    assert set(mw.BUILDERS) == {k for k, _l, _h in mw.KINDS}


# ==================================================================== rules ===
def test_kri_readings_fall_due_one_cycle_after_the_last():
    assert mw.kri_next_due(ReviewFrequency.monthly, date(2026, 8, 20), TODAY) == date(2026, 9, 20)
    assert mw.kri_next_due(ReviewFrequency.daily, date(2026, 9, 11), TODAY) == date(2026, 9, 12)
    assert mw.kri_next_due("weekly", date(2026, 9, 1), TODAY) == date(2026, 9, 8)
    assert mw.kri_next_due(ReviewFrequency.monthly, None, TODAY) == TODAY  # never measured
    assert mw.kri_next_due(ReviewFrequency.none, None, TODAY) is None


def test_four_eyes_filter():
    assert mw.decided_by_others_only(ME, [MAKER, None], required=True)
    assert not mw.decided_by_others_only(ME, [MAKER, ME], required=True)
    assert mw.decided_by_others_only(ME, [ME], required=False)


def test_the_trail_names_the_first_creator_and_the_last_submitter():
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = [
        ("risk", 1, "workflow_submit", OTHER, t0 + timedelta(days=3)),
        ("risk", 1, "create", MAKER, t0),
        ("risk", 1, "create", OTHER, t0 + timedelta(days=1)),
        ("risk", 1, "workflow_submit", ME, t0 + timedelta(days=5)),
        ("risk", 2, "create", None, t0),
    ]
    created, submitted = mw.makers_from_trail(rows)
    assert created == {("risk", 1): MAKER} and submitted == {("risk", 1): ME}


def test_policy_acknowledgement_scope():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert mw.policy_ack_applies([], [a])  # a policy naming no role asks everyone
    assert mw.policy_ack_applies([a, b], [b])
    assert not mw.policy_ack_applies([a], [b])
    assert not mw.policy_ack_applies([a], [])


def test_who_may_mark_a_treatment_action_done():
    action = SimpleNamespace(owner_id=ME, status="open")
    assert mw.can_mark_done(action, ME, []) is None
    assert mw.can_mark_done(action, OTHER, ["risk:write"]) is None
    assert "owner" in mw.can_mark_done(action, OTHER, ["risk:read"])
    assert "cancelled" in mw.can_mark_done(SimpleNamespace(owner_id=ME, status="cancelled"), ME, [])


# ================================================================ the builders ===
class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """Returns canned results in order, recording every statement."""

    def __init__(self, *results, scalar=None, get=None):
        self.results = list(results)
        self.statements = []
        self._scalar = scalar
        self.tables = get or {}
        self.added = []
        self.flushed = 0

    def _next(self, stmt):
        self.statements.append(stmt)
        return _Rows(self.results.pop(0) if self.results else [])

    async def execute(self, stmt, *a, **k):
        return self._next(stmt)

    async def scalars(self, stmt, *a, **k):
        return self._next(stmt)

    async def scalar(self, stmt, *a, **k):
        self.statements.append(stmt)
        return self._scalar(stmt) if callable(self._scalar) else self._scalar

    async def get(self, model, key):
        return self.tables.get(key)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1

    def sql(self, i=0):
        return str(self.statements[i].compile(dialect=postgresql.dialect()))


def _ctx(perms=(), roles=(), directory=None, modules_off=()):
    return mw.Ctx(
        user_id=ME, email="me@bank.pk", permissions=set(perms), role_names=set(roles),
        role_ids={uuid.uuid4()} if roles else set(), today=TODAY, horizon=HORIZON,
        directory=directory, modules_off=set(modules_off),
    )


def _directory():
    return Directory(
        users={
            ME: DirectoryUser(ME, "me@bank.pk", "Me Myself", True, ("Risk Approver",)),
            OTHER: DirectoryUser(OTHER, "other@bank.pk", "Omar Other", True, ("Admin",)),
            MAKER: DirectoryUser(MAKER, "maker@bank.pk", "Mona Maker", True, ("Risk Manager",)),
        },
        role_permissions={
            "Admin": frozenset({"workflow:approve"}), "Risk Approver": frozenset({"workflow:approve"}),
            "Risk Manager": frozenset(), "CRO": frozenset(),
        },
    )


def _approval(approver="", maker=MAKER, due=None):
    return ApprovalRequest(id=uuid.uuid4(), reference="APR-9", title="Accept R-117", approver=approver,
                           requested_by=maker, requested_by_email="maker@bank.pk", status=ApprovalStatus.pending,
                           required_approvals=2, due_date=due, entity_label="R-117 Card fraud")


async def test_approvals_waiting_for_me(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    unaddressed = _approval(due=TODAY - timedelta(days=1))
    to_me = _approval("me@bank.pk")
    to_my_role = _approval("Risk Approver")
    to_someone_else = _approval("other@bank.pk")
    to_other_role = _approval("Admin")
    # Nobody in the CRO role can decide, so the approvers (me included) are told too.
    to_role_that_cant_decide = _approval("CRO")
    mine_as_maker = _approval("", maker=ME)
    db = FakeDB([unaddressed, to_me, to_my_role, to_someone_else, to_other_role, to_role_that_cant_decide,
                 mine_as_maker])
    items = await mw.approvals_waiting(db, _ctx(["workflow:approve"], ["Risk Approver"], _directory()))
    assert [i.id for i in items] == [unaddressed.id, to_me.id, to_my_role.id, to_role_that_cant_decide.id]
    first = items[0]
    assert first.overdue and first.link == f"/approvals?id={unaddressed.id}"
    assert "About R-117 Card fraud" in first.subtitle and "2 approvals needed" in first.subtitle
    sql = db.sql()
    assert "approval_requests.status" in sql and "NOT (EXISTS" in sql and "approval_actions.actor_id" in sql


async def test_no_approve_permission_means_no_approvals():
    db = FakeDB([_approval()])
    assert await mw.approvals_waiting(db, _ctx([], ["Risk Approver"], _directory())) == []
    assert db.statements == []


async def test_records_in_review_skip_my_own_routed_and_four_eyes(monkeypatch):
    async def required(db, module, action, amount=None):
        return True, None

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    mine_made = SimpleNamespace(entity_type="risk", id=uuid.uuid4(), reference="R-1", title="Made by me",
                                maker_hint=None, since=None)
    mine_submitted = SimpleNamespace(entity_type="risk", id=uuid.uuid4(), reference="R-2", title="Submitted by me",
                                     maker_hint=None, since=None)
    owned_by_me = SimpleNamespace(entity_type="risk", id=uuid.uuid4(), reference="R-3", title="Imported, I own it",
                                  maker_hint=ME, since=None)
    routed = SimpleNamespace(entity_type="control", id=uuid.uuid4(), reference="A.5", title="On a route",
                             maker_hint=None, since=None)
    ok = SimpleNamespace(entity_type="policy", id=uuid.uuid4(), reference="POL-1", title="Somebody else's",
                         maker_hint=OTHER, since=None)
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    trail = [("risk", mine_made.id, "create", ME, t0), ("risk", mine_submitted.id, "create", OTHER, t0),
             ("risk", mine_submitted.id, "workflow_submit", ME, t0 + timedelta(hours=1))]
    db = FakeDB([mine_made, mine_submitted, owned_by_me, routed, ok], [("control", routed.id)], trail)
    perms = ["risk:read", "workflow:approve", "control:read", "policy:read"]
    items = await mw.records_in_review(db, _ctx(perms))
    assert [i.id for i in items] == [ok.id]
    assert items[0].link == f"/policies?id={ok.id}" and items[0].subtitle == "Policy"
    union = db.sql(0)
    assert "UNION ALL" in union and "workflow_status" in union and "deleted IS false" in union


def test_review_types_follow_the_approve_permission():
    assert mw.review_types(["risk:read"]) == []
    types = dict(mw.review_types(["risk:read", "workflow:approve"]))
    assert "risk" in types and "control" not in types
    exceptions = dict(mw.review_types(["exception:read", "exception:approve"]))
    assert "exception" in exceptions  # the module's own approve permission wins


async def test_tests_to_review_exclude_everyone_who_touched_the_test(monkeypatch):
    async def required(db, module, action, amount=None):
        return True, None

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    mine = SimpleNamespace(id=uuid.uuid4(), control_id=uuid.uuid4(), test_type="operating", result="passed",
                           tested_by_id=ME, reference="A.8.5", name="MFA")
    edited = SimpleNamespace(id=uuid.uuid4(), control_id=uuid.uuid4(), test_type=None, result="failed",
                             tested_by_id=OTHER, reference="A.8.6", name="PAM")
    fine = SimpleNamespace(id=uuid.uuid4(), control_id=uuid.uuid4(), test_type="design",
                           result="passed_with_exceptions", tested_by_id=OTHER, reference="A.8.7", name="Logging")
    db = FakeDB([mine, edited, fine], [(edited.id, ME)])
    items = await mw.tests_to_review(db, _ctx(["control:test"]))
    assert [i.id for i in items] == [fine.id]
    assert items[0].title == "Passed with exceptions design test of Logging"
    assert items[0].link == f"/controls?id={fine.control_id}"
    assert await mw.tests_to_review(FakeDB(), _ctx([])) == []


async def test_issue_validations_exclude_the_owner_and_the_raiser(monkeypatch):
    async def required(db, module, action, amount=None):
        return True, None

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    owned = SimpleNamespace(id=uuid.uuid4(), reference="ISS-1", title="Mine", due_date=None, owner_id=ME,
                            validation_result=None)
    raised = SimpleNamespace(id=uuid.uuid4(), reference="ISS-2", title="Raised by me", due_date=None,
                             owner_id=OTHER, validation_result=None)
    again = SimpleNamespace(id=uuid.uuid4(), reference="ISS-3", title="Rework", due_date=TODAY - timedelta(days=2),
                            owner_id=OTHER, validation_result="not_effective")
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    db = FakeDB([owned, raised, again], [("issue", raised.id, "create", ME, t0)])
    items = await mw.issues_to_validate(db, _ctx(["issue:write"]))
    assert [i.id for i in items] == [again.id]
    assert items[0].overdue and "not-effective" in items[0].subtitle
    sql = db.sql(0)
    assert "issue_actions.status" in sql and "NOT (EXISTS" in sql and "validation_result" in sql


async def test_extensions_to_approve_skip_my_own_request(monkeypatch):
    async def required(db, module, action, amount=None):
        return True, None

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    mine = SimpleNamespace(id=uuid.uuid4(), issue_id=uuid.uuid4(), old_due_date=TODAY, new_due_date=HORIZON,
                           reason="Vendor delay", requested_by_id=ME, reference="ISS-1", title="A")
    theirs = SimpleNamespace(id=uuid.uuid4(), issue_id=uuid.uuid4(), old_due_date=TODAY, new_due_date=HORIZON,
                             reason="Vendor delay", requested_by_id=OTHER, reference="ISS-2", title="B")
    db = FakeDB([mine, theirs])
    items = await mw.extensions_to_approve(db, _ctx(["issue:read", "workflow:approve"], directory=_directory()))
    assert [i.id for i in items] == [theirs.id]
    assert items[0].previous_date == TODAY and items[0].due_date == HORIZON
    assert items[0].subtitle == "Omar Other: Vendor delay" and not items[0].overdue
    assert await mw.extensions_to_approve(FakeDB([theirs]), _ctx(["issue:read"])) == []


async def test_my_treatment_actions_offer_mark_done_and_use_the_window():
    row = SimpleNamespace(id=uuid.uuid4(), title="Deploy MFA", due_date=TODAY - timedelta(days=1), status="open",
                          percent_complete=40, risk_id=uuid.uuid4(), reference="R-117", risk_title="Card fraud")
    db = FakeDB([row])
    (it,) = await mw.my_treatment_actions(db, _ctx())
    assert it.actions == [mw.MARK_DONE] and it.overdue and it.subtitle == "Card fraud · 40% done"
    assert it.link == f"/risks?id={row.risk_id}"
    sql = db.sql()
    assert "risk_treatment_actions.owner_id" in sql and "risk_treatment_actions.due_date <=" in sql
    assert "risks.deleted IS false" in sql


async def test_kri_readings_due_only_within_a_few_days_and_only_with_the_module():
    due = SimpleNamespace(id=uuid.uuid4(), reference="KRI-1", name="Failed wires", frequency=ReviewFrequency.daily,
                          last_measured_date=TODAY - timedelta(days=2))
    later = SimpleNamespace(id=uuid.uuid4(), reference="KRI-2", name="Monthly", frequency=ReviewFrequency.monthly,
                            last_measured_date=TODAY - timedelta(days=3))
    never = SimpleNamespace(id=uuid.uuid4(), reference="KRI-3", name="New", frequency=ReviewFrequency.quarterly,
                            last_measured_date=None)
    db = FakeDB([due, later, never])
    items = await mw.my_kri_readings(db, _ctx())
    assert [i.id for i in items] == [due.id, never.id]
    assert items[0].overdue and items[1].due_date == TODAY and "no reading yet" in items[1].subtitle
    sql = db.sql()
    assert "data_provider_id" in sql and "owner_id" in sql and "frequency !=" in sql
    assert await mw.my_kri_readings(FakeDB([due]), _ctx(modules_off=["operational_risk"])) == []
    assert await mw.my_rcsa_actions(FakeDB([due]), _ctx(modules_off=["operational_risk"])) == []


async def test_policies_to_acknowledge_are_scoped_by_role():
    row = SimpleNamespace(id=uuid.uuid4(), reference="POL-3", title="Information security", version="2.0")
    db = FakeDB([row])
    (it,) = await mw.policies_to_acknowledge(db, _ctx(["policy:read"], ["Risk Approver"]))
    assert it.actions == [mw.ACK] and it.link == f"/policies?id={row.id}" and it.due_date is None
    sql = db.sql()
    assert "policy_roles.role_id IN" in sql and "policy_acknowledgments.user_id" in sql
    assert "policies.status" in sql
    no_roles = FakeDB([row])
    (no_read,) = await mw.policies_to_acknowledge(no_roles, _ctx([], []))
    assert no_read.actions == []
    assert "role_id IN" not in no_roles.sql() and "false" in no_roles.sql()  # only role-less policies apply


async def test_control_tests_due_for_owner_or_operator():
    owned = SimpleNamespace(id=uuid.uuid4(), reference="A.8.5", name="MFA", next_audit_date=TODAY, owner_id=ME)
    operated = SimpleNamespace(id=uuid.uuid4(), reference="A.8.6", name="PAM", next_audit_date=HORIZON, owner_id=OTHER)
    db = FakeDB([owned, operated])
    items = await mw.my_control_tests(db, _ctx())
    assert [i.subtitle for i in items] == ["You own this control", "You operate this control"]
    sql = db.sql()
    assert "controls.owner_id" in sql and "controls.operator_id" in sql and "controls.status NOT IN" in sql


async def test_the_endpoint_returns_the_service_answer(monkeypatch):
    from app.api.v1 import my_work as api

    expected = mw.assemble(ME, TODAY, {})

    async def fake(db, user):
        return expected

    monkeypatch.setattr(mw, "my_work", fake)
    assert await api.get_my_work(FakeDB(), SimpleNamespace(id=ME)) is expected
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert {"/api/v1/my/work", "/api/v1/my/work/treatment-actions/{action_id}/done",
            "/api/v1/actions/{token}", "/api/v1/actions/{token}/confirm"} <= paths


# ============================================================== quick action ===
@pytest.fixture
def audit_calls(monkeypatch):
    calls = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit_service, "record", record)
    return calls


def _action(**kw):
    base = dict(id=uuid.uuid4(), risk_id=uuid.uuid4(), title="Deploy MFA", owner_id=ME, status="open",
                percent_complete=40, due_date=TODAY, completed_at=None)
    base.update(kw)
    return RiskTreatmentAction(**base)


async def test_the_owner_marks_their_action_done(audit_calls):
    action = _action()
    later = _action(risk_id=action.risk_id, status="open", due_date=TODAY + timedelta(days=30))
    risk = Risk(id=action.risk_id, reference="R-117", title="Card fraud", deleted=False, treatment_deadline=None)
    db = FakeDB([action, later], get={action.id: action, risk.id: risk})
    user = SimpleNamespace(id=ME, permission_codes=["risk:read"])
    out = await mw.mark_treatment_action_done(db, user, action.id)
    assert out.status == "done" and out.percent_complete == 100 and out.completed_at is not None
    assert risk.treatment_deadline == later.due_date == out.treatment_deadline
    (call,) = audit_calls
    assert call["action"] == "update_treatment_action" and call["entity_id"] == risk.id
    assert call["changes"]["via"] == "my_work" and "open -> done" == call["changes"]["status"]


async def test_someone_else_needs_risk_write(audit_calls):
    action = _action(owner_id=OTHER)
    risk = Risk(id=action.risk_id, reference="R-1", title="x", deleted=False)
    db = FakeDB(get={action.id: action, risk.id: risk})
    with pytest.raises(HTTPException) as exc:
        await mw.mark_treatment_action_done(db, SimpleNamespace(id=ME, permission_codes=["risk:read"]), action.id)
    assert exc.value.status_code == 403 and audit_calls == []
    cancelled = _action(status="cancelled")
    db = FakeDB(get={cancelled.id: cancelled, cancelled.risk_id: Risk(id=cancelled.risk_id, deleted=False)})
    with pytest.raises(HTTPException) as exc:
        await mw.mark_treatment_action_done(db, SimpleNamespace(id=ME, permission_codes=[]), cancelled.id)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await mw.mark_treatment_action_done(FakeDB(), SimpleNamespace(id=ME, permission_codes=[]), uuid.uuid4())
    assert exc.value.status_code == 404


async def test_marking_a_done_action_again_changes_nothing(audit_calls):
    action = _action(status="done", percent_complete=100, completed_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    risk = Risk(id=action.risk_id, reference="R-1", title="x", deleted=False, treatment_deadline=TODAY)
    out = await mw.mark_treatment_action_done(FakeDB(get={action.id: action, risk.id: risk}),
                                              SimpleNamespace(id=ME, permission_codes=[]), action.id)
    assert out.status == "done" and audit_calls == []


def test_items_carry_what_the_page_needs():
    fields = set(MyWorkItem.model_fields)
    assert {"kind", "title", "reference", "due_date", "overdue", "link", "actions", "entity_type",
            "entity_id", "previous_date", "due_soon"} <= fields
