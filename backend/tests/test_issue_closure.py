"""Issues: typed links, proven closure and due-date slippage (product review 2.3, F-12).

No database: the pure rules in ``services.issue_closure`` are tested directly, and the
endpoints are driven with a fake session, stubbed loaders and a captured audit trail.

Pinned here:

1. **The edit cannot close.** Moving an issue into closed / remediated / risk accepted
   through PATCH (or raising it closed) is a 422 pointing at Validate and Close; reopening
   through PATCH is allowed and clears the validation and the closed date.
2. **The closed date is the server's.** Not on the Create/Update schemas; set to today on
   close, cleared on reopen.
3. **Validation is independent and evidenced.** Not the owner, not whoever raised it
   (dual control ``issue/validate``); *effective* needs an attachment; *not effective*
   sends the issue back to in progress.
4. **Close refuses readably.** Open actions, no effective validation, risk acceptance
   without an approved acceptance or an approver's note — each a 409 that says what is
   missing; whoever raised the issue cannot close it (dual control ``issue/close``).
5. **Due dates.** Any change of an agreed date needs a reason and is logged; a later date
   on a regulator-related / high / critical issue waits for someone else's approval.
6. **Links.** An issue raised from a record gets the typed link; control links trigger
   the control's effectiveness recompute, skipped silently when that service is absent.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import issues as api
from app.models.enums import AcceptanceStatus, Severity
from app.models.issue import ActionStatus, Issue, IssueAction, IssueDueDateChange, IssueStatus2
from app.schemas.issue import (
    DueDateDecision,
    IssueClose,
    IssueCreate,
    IssueUpdatePatch,
    IssueValidate,
)
from app.services import issue_closure as ic

TODAY = date.today()
WRITER = ["issue:read", "issue:write"]
APPROVER = ["issue:read", "issue:write", "workflow:approve"]


def _user(perms=WRITER, uid=None):
    return SimpleNamespace(
        id=uid or uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x", full_name="U",
        permission_codes=perms,
    )


def _issue(**kw) -> Issue:
    base = dict(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), reference="ISS-7", title="Wire release SoD gap",
        status=IssueStatus2.open, severity=Severity.medium, regulator_related=False,
        due_date=TODAY + timedelta(days=30), closed_date=None, owner_id=None, source_id=None,
        validated_by_id=None, validated_at=None, validation_result=None, validation_note="",
    )
    base.update(kw)
    obj = Issue(**{k: v for k, v in base.items()})
    return obj


# ============================================================== pure: status ===
@pytest.mark.parametrize("cur,new,refused", [
    (IssueStatus2.open, IssueStatus2.closed, True),
    (IssueStatus2.in_progress, IssueStatus2.remediated, True),
    (IssueStatus2.open, IssueStatus2.risk_accepted, True),
    (IssueStatus2.open, IssueStatus2.in_progress, False),
    (IssueStatus2.closed, IssueStatus2.closed, False),  # a form resaving every field
    (IssueStatus2.closed, IssueStatus2.open, False),  # reopen
    (IssueStatus2.open, None, False),
])
def test_edit_cannot_move_into_a_closed_state(cur, new, refused):
    msg = ic.edit_status_refusal(cur, new)
    assert bool(msg) is refused
    if refused:
        assert "Validate and Close" in msg


def test_an_issue_is_raised_open():
    assert ic.create_status_refusal(IssueStatus2.closed)
    assert ic.create_status_refusal("remediated")
    assert ic.create_status_refusal(IssueStatus2.in_progress) is None


def test_closed_date_is_set_on_close_and_cleared_on_reopen():
    earlier = TODAY - timedelta(days=9)
    assert ic.closed_date_after(IssueStatus2.open, IssueStatus2.closed, None, TODAY) == TODAY
    assert ic.closed_date_after(IssueStatus2.closed, IssueStatus2.in_progress, earlier, TODAY) is None
    assert ic.closed_date_after(IssueStatus2.closed, IssueStatus2.closed, earlier, TODAY) == earlier
    assert ic.is_reopen(IssueStatus2.remediated, IssueStatus2.open)
    assert not ic.is_reopen(IssueStatus2.open, IssueStatus2.in_progress)


def test_closed_date_is_not_writable():
    assert "closed_date" not in IssueCreate.model_fields
    assert "closed_date" not in IssueUpdatePatch.model_fields
    # An older client still sending it is ignored, not failed.
    assert "closed_date" not in IssueUpdatePatch(closed_date="2026-01-01").model_dump(exclude_unset=True)


# ========================================================== pure: validation ===
def test_validation_rules():
    ok = dict(status=IssueStatus2.in_progress, result="effective", attachments=1, note="Re-performed the control")
    assert ic.validation_refusal(**ok) is None
    assert "evidence" in ic.validation_refusal(**{**ok, "attachments": 0})
    assert "note" in ic.validation_refusal(**{**ok, "note": "  "})
    assert "already closed" in ic.validation_refusal(**{**ok, "status": IssueStatus2.closed})
    # Not effective needs no evidence — the validator is sending it back.
    assert ic.validation_refusal(**{**ok, "result": "not_effective", "attachments": 0}) is None


def test_validator_is_neither_owner_nor_raiser():
    owner, raiser, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert "own" in ic.validator_conflict(owner, owner, raiser)
    assert "raised" in ic.validator_conflict(raiser, owner, raiser)
    assert ic.validator_conflict(other, owner, raiser) is None
    assert ic.validator_conflict(other, None, None) is None


# =============================================================== pure: close ===
def _close(**kw):
    base = dict(
        target=IssueStatus2.closed, current=IssueStatus2.in_progress, open_actions=[],
        validation_result="effective", has_approved_acceptance=False, note="", can_approve=False,
    )
    base.update(kw)
    return ic.close_refusal(**base)


def test_close_refuses_while_actions_are_open():
    msg = _close(open_actions=["Rotate keys", "Re-train staff"])
    assert "2 action(s) are still open" in msg and "Rotate keys" in msg


def test_close_needs_an_effective_validation():
    assert "No effective validation" in _close(validation_result=None)
    assert "not effective" in _close(validation_result="not_effective")
    assert _close() is None
    assert _close(target=IssueStatus2.remediated) is None


def test_close_as_risk_accepted():
    ra = dict(target=IssueStatus2.risk_accepted, validation_result=None)
    assert _close(**ra, has_approved_acceptance=True) is None
    assert "approved risk acceptance" in _close(**ra)
    assert "approve issues" in _close(**ra, note="Board accepted, minute 14")
    assert _close(**ra, note="Board accepted, minute 14", can_approve=True) is None


def test_close_target_and_current_state():
    assert "closed status" in _close(target=IssueStatus2.open)
    assert "already closed" in _close(current=IssueStatus2.closed)


def test_open_action_titles_count_open_and_in_progress_only():
    acts = [SimpleNamespace(title=t, status=s) for t, s in (
        ("a", ActionStatus.open), ("b", ActionStatus.in_progress),
        ("c", ActionStatus.done), ("d", ActionStatus.cancelled),
    )]
    assert ic.open_action_titles(acts) == ["a", "b"]


def test_acceptance_in_force():
    ok = SimpleNamespace(status=AcceptanceStatus.approved, expires_at=TODAY)
    lapsed = SimpleNamespace(status=AcceptanceStatus.approved, expires_at=TODAY - timedelta(days=1))
    pending = SimpleNamespace(status=AcceptanceStatus.pending, expires_at=None)
    assert ic.acceptance_in_force(ok, TODAY)
    assert not ic.acceptance_in_force(lapsed, TODAY)
    assert not ic.acceptance_in_force(pending, TODAY)


# ============================================================ pure: due dates ===
def test_due_date_moves_and_extensions():
    d = TODAY
    assert not ic.is_due_date_move(None, d)  # the first date is planning
    assert ic.is_due_date_move(d, d + timedelta(days=1))
    assert ic.is_due_date_move(d, None)
    assert ic.is_extension(d, d + timedelta(days=1))
    assert ic.is_extension(d, None)  # removing the deadline is the longest extension
    assert not ic.is_extension(d, d - timedelta(days=1))


@pytest.mark.parametrize("sev,reg,later,waits", [
    (Severity.high, False, True, True),
    (Severity.critical, False, True, True),
    (Severity.low, True, True, True),
    (Severity.medium, False, True, False),
    (Severity.critical, True, False, False),  # bringing a date forward never waits
])
def test_which_extensions_need_approval(sev, reg, later, waits):
    old = TODAY
    new = old + timedelta(days=14 if later else -3)
    assert ic.needs_extension_approval(old, new, regulator_related=reg, severity=sev) is waits


def test_due_date_moves_counts_approved_changes_of_a_date():
    rows = [
        SimpleNamespace(status="approved", old_due_date=TODAY),
        SimpleNamespace(status="approved", old_due_date=TODAY),
        SimpleNamespace(status="pending", old_due_date=TODAY),
        SimpleNamespace(status="rejected", old_due_date=TODAY),
        SimpleNamespace(status="approved", old_due_date=None),
    ]
    assert ic.due_date_moves(rows) == 2


def test_source_link_is_added_to_the_sent_list_or_as_an_addition():
    rid = uuid.uuid4()
    links, extra = ic.with_source_link({"risk_ids": []}, "risk", rid)
    assert links["risk_ids"] == [rid] and extra == {}
    links, extra = ic.with_source_link({"risk_ids": None}, "risk", rid)
    assert extra == {"risk_ids": [rid]}  # an update that sent no risks keeps the others
    links, extra = ic.with_source_link({"risk_ids": [rid]}, "risk", rid)
    assert links["risk_ids"] == [rid] and extra == {}
    assert ic.with_source_link({}, None, rid) == ({}, {})


# ================================================================ endpoints ===
class FakeDB:
    def __init__(self):
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


@pytest.fixture
def env(monkeypatch):
    """Stub the loaders, the trail, the link store and the control recompute."""
    state = SimpleNamespace(
        issue=_issue(), audit=[], recomputed=[], attachments=1, accepted=False,
        linked={"control": [], "risk": []}, sod=True, raiser=None, written=[], reasons=[],
    )

    async def load(db, iid):
        return state.issue

    async def read(db, iid):
        return state.issue

    async def record(db, **kw):
        state.audit.append(kw)

    async def linked_ids(db, issue_id, kind):
        return list(state.linked.get(kind, []))

    async def attachments(db, issue_id):
        return state.attachments

    async def accepted(db, risk_ids, today=None):
        return state.accepted

    async def recompute(db, ids, reason=""):
        state.recomputed.extend(ids)
        state.reasons.append(reason)
        return len(ids)

    async def required(db, module, action, amount=None):
        return state.sod, None

    async def maker_of(db, entity_type, entity_id, record=None):
        return state.raiser

    async def apply_refs(db, model, data, fields, *, record=None):
        return []

    async def checked(db, links):
        return {f: links.get(f) for f in ic.LINK_ID_FIELDS}

    async def write(db, issue_id, links, additions):
        state.written.append((links, additions))
        changes = {}
        for f, ids in {**{k: v for k, v in links.items() if v}, **additions}.items():
            changes[f.removesuffix("_ids") + "s"] = {"added": [str(i) for i in ids], "removed": []}
        return changes

    async def source_kind(db, source_id):
        return "risk" if source_id else None

    monkeypatch.setattr(api, "_load_issue", load)
    monkeypatch.setattr(api, "_issue_read", read)
    monkeypatch.setattr(api.audit_log, "record", record)
    monkeypatch.setattr(api.ic, "linked_ids", linked_ids)
    monkeypatch.setattr(api.ic, "attachment_count", attachments)
    monkeypatch.setattr(api.ic, "has_approved_acceptance", accepted)
    monkeypatch.setattr(api.ic, "recompute_controls", recompute)
    monkeypatch.setattr(api.ic, "source_kind", source_kind)
    monkeypatch.setattr(api.dual_control, "dual_control_required", required)
    monkeypatch.setattr(api.dual_control, "maker_of", maker_of)
    monkeypatch.setattr(api.rf, "apply_refs", apply_refs)
    monkeypatch.setattr(api, "_checked_links", checked)
    monkeypatch.setattr(api, "_write_links", write)
    return state


def _actions(env):
    return [a["action"] for a in env.audit]


# ------------------------------------------------------------------ PATCH ---
@pytest.mark.asyncio
async def test_patch_into_a_closed_state_is_a_422(env):
    with pytest.raises(HTTPException) as exc:
        await api.update_issue(env.issue.id, IssueUpdatePatch(status=IssueStatus2.closed), FakeDB(), _user())
    assert exc.value.status_code == 422 and "Validate and Close" in exc.value.detail
    assert env.issue.status == IssueStatus2.open


@pytest.mark.asyncio
async def test_patch_reopen_clears_validation_and_closed_date(env):
    control = uuid.uuid4()
    env.linked["control"] = [control]
    env.issue.status = IssueStatus2.closed
    env.issue.closed_date = TODAY - timedelta(days=3)
    env.issue.validation_result = "effective"
    env.issue.validated_by_id = uuid.uuid4()
    env.issue.validation_note = "ok"
    db = FakeDB()
    await api.update_issue(env.issue.id, IssueUpdatePatch(status=IssueStatus2.in_progress), db, _user())
    i = env.issue
    assert i.status == IssueStatus2.in_progress and i.closed_date is None
    assert i.validation_result is None and i.validated_by_id is None and i.validation_note == ""
    assert "reopen" in _actions(env)
    assert control in env.recomputed
    assert any(getattr(x, "note", "") == "Reopened" for x in db.added)


@pytest.mark.asyncio
async def test_changing_the_due_date_needs_a_reason(env):
    new = env.issue.due_date + timedelta(days=10)
    with pytest.raises(HTTPException) as exc:
        await api.update_issue(env.issue.id, IssueUpdatePatch(due_date=new), FakeDB(), _user())
    assert exc.value.status_code == 422 and "due_date_reason" in exc.value.detail


@pytest.mark.asyncio
async def test_first_due_date_needs_no_reason_and_is_not_a_move(env):
    env.issue.due_date = None
    db = FakeDB()
    await api.update_issue(env.issue.id, IssueUpdatePatch(due_date=TODAY), db, _user())
    assert env.issue.due_date == TODAY
    assert not [x for x in db.added if isinstance(x, IssueDueDateChange)]


@pytest.mark.asyncio
async def test_extension_on_a_high_issue_waits_for_approval(env):
    env.issue.severity = Severity.high
    old = env.issue.due_date
    new = old + timedelta(days=30)
    db = FakeDB()
    user = _user()
    await api.update_issue(
        env.issue.id, IssueUpdatePatch(due_date=new, due_date_reason="Vendor patch slipped"), db, user
    )
    change = next(x for x in db.added if isinstance(x, IssueDueDateChange))
    assert change.status == "pending" and change.requested_by_id == user.id
    assert (change.old_due_date, change.new_due_date, change.reason) == (old, new, "Vendor patch slipped")
    assert env.issue.due_date == old  # the date does not move until approved
    assert "due_date_change" in _actions(env)


@pytest.mark.asyncio
async def test_bringing_a_date_forward_applies_at_once_and_is_logged(env):
    env.issue.severity = Severity.critical
    new = env.issue.due_date - timedelta(days=5)
    db = FakeDB()
    await api.update_issue(env.issue.id, IssueUpdatePatch(due_date=new, due_date_reason="Board asked"), db, _user())
    change = next(x for x in db.added if isinstance(x, IssueDueDateChange))
    assert change.status == "approved" and change.approved_at is not None
    assert env.issue.due_date == new


@pytest.mark.asyncio
async def test_dropping_severity_in_the_same_edit_does_not_dodge_approval(env):
    env.issue.severity = Severity.high
    old = env.issue.due_date
    db = FakeDB()
    await api.update_issue(
        env.issue.id,
        IssueUpdatePatch(due_date=old + timedelta(days=60), due_date_reason="x", severity=Severity.low),
        db, _user(),
    )
    assert next(x for x in db.added if isinstance(x, IssueDueDateChange)).status == "pending"
    assert env.issue.due_date == old


@pytest.mark.asyncio
async def test_one_pending_extension_at_a_time(env):
    env.issue.regulator_related = True
    env.issue.due_date_changes = [IssueDueDateChange(status="pending", old_due_date=TODAY, new_due_date=TODAY)]
    with pytest.raises(HTTPException) as exc:
        await api.update_issue(
            env.issue.id,
            IssueUpdatePatch(due_date=env.issue.due_date + timedelta(days=1), due_date_reason="x"),
            FakeDB(), _user(),
        )
    assert exc.value.status_code == 409


# ------------------------------------------------------------------ create ---
@pytest.mark.asyncio
async def test_create_refuses_a_closed_status(env):
    with pytest.raises(HTTPException) as exc:
        await api.create_issue(IssueCreate(title="x", status=IssueStatus2.closed), FakeDB(), _user())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_raising_from_a_record_writes_the_typed_link(env, monkeypatch):
    async def next_ref(db, model, prefix):
        return "ISS-9"

    monkeypatch.setattr(api, "_next_ref", next_ref)
    risk = uuid.uuid4()
    await api.create_issue(IssueCreate(title="From R-1", source_id=risk, source_type="risk_assessment"), FakeDB(), _user())
    links, _additions = env.written[-1]
    assert links["risk_ids"] == [risk]
    create = next(a for a in env.audit if a["action"] == "create")
    assert create["changes"]["links"]["risks"]["added"] == [str(risk)]


# ---------------------------------------------------------------- validate ---
@pytest.mark.asyncio
async def test_owner_cannot_validate(env):
    owner = uuid.uuid4()
    env.issue.owner_id = owner
    with pytest.raises(HTTPException) as exc:
        await api.validate_issue(env.issue.id, IssueValidate(result="effective", note="ok"), FakeDB(), _user(uid=owner))
    assert exc.value.status_code == 403 and "own" in exc.value.detail


@pytest.mark.asyncio
async def test_raiser_cannot_validate_but_sod_off_allows_it(env):
    raiser = uuid.uuid4()
    env.raiser = raiser
    with pytest.raises(HTTPException):
        await api.validate_issue(env.issue.id, IssueValidate(result="effective", note="ok"), FakeDB(), _user(uid=raiser))
    env.sod = False
    await api.validate_issue(env.issue.id, IssueValidate(result="effective", note="ok"), FakeDB(), _user(uid=raiser))
    assert env.issue.validation_result == "effective"


@pytest.mark.asyncio
async def test_effective_needs_evidence(env):
    env.attachments = 0
    with pytest.raises(HTTPException) as exc:
        await api.validate_issue(env.issue.id, IssueValidate(result="effective", note="ok"), FakeDB(), _user())
    assert exc.value.status_code == 409 and "evidence" in exc.value.detail


@pytest.mark.asyncio
async def test_effective_validation_is_recorded(env):
    user = _user()
    await api.validate_issue(env.issue.id, IssueValidate(result="effective", note=" Retested 25 wires "), FakeDB(), user)
    i = env.issue
    assert (i.validated_by_id, i.validation_result, i.validation_note) == (user.id, "effective", "Retested 25 wires")
    assert i.validated_at is not None
    assert "validate" in _actions(env)


@pytest.mark.asyncio
async def test_not_effective_sends_it_back_to_in_progress(env):
    env.attachments = 0
    await api.validate_issue(env.issue.id, IssueValidate(result="not_effective", note="Still failing"), FakeDB(), _user())
    assert env.issue.status == IssueStatus2.in_progress
    assert env.issue.validation_result == "not_effective"


# ------------------------------------------------------------------- close ---
@pytest.mark.asyncio
async def test_close_refuses_with_open_actions(env):
    env.issue.validation_result = "effective"
    env.issue.actions = [IssueAction(title="Rotate keys", status=ActionStatus.open)]
    with pytest.raises(HTTPException) as exc:
        await api.close_issue(env.issue.id, IssueClose(status="closed"), FakeDB(), _user())
    assert exc.value.status_code == 409 and "Rotate keys" in exc.value.detail


@pytest.mark.asyncio
async def test_close_refuses_without_validation(env):
    with pytest.raises(HTTPException) as exc:
        await api.close_issue(env.issue.id, IssueClose(status="closed"), FakeDB(), _user())
    assert exc.value.status_code == 409 and "validation" in exc.value.detail


@pytest.mark.asyncio
async def test_close_after_effective_validation(env):
    control = uuid.uuid4()
    env.linked["control"] = [control]
    env.issue.validation_result = "effective"
    env.issue.actions = [IssueAction(title="Done", status=ActionStatus.done)]
    await api.close_issue(env.issue.id, IssueClose(status="remediated", note="Fixed"), FakeDB(), _user())
    assert env.issue.status == IssueStatus2.remediated and env.issue.closed_date == TODAY
    close = next(a for a in env.audit if a["action"] == "close")
    assert close["changes"]["basis"] == "validation"
    assert env.recomputed == [control]
    assert env.reasons[-1] == "ISS-7 closed"


@pytest.mark.asyncio
async def test_raiser_cannot_close(env):
    raiser = uuid.uuid4()
    env.raiser = raiser
    env.issue.validation_result = "effective"
    with pytest.raises(HTTPException) as exc:
        await api.close_issue(env.issue.id, IssueClose(status="closed"), FakeDB(), _user(uid=raiser))
    assert exc.value.status_code == 403 and "raised" in exc.value.detail


@pytest.mark.asyncio
async def test_risk_accepted_close_paths(env):
    # No acceptance and no approver rights: refused even with a note.
    with pytest.raises(HTTPException) as exc:
        await api.close_issue(env.issue.id, IssueClose(status="risk_accepted", note="Accepted"), FakeDB(), _user())
    assert exc.value.status_code == 409
    # An approver's note is enough.
    await api.close_issue(env.issue.id, IssueClose(status="risk_accepted", note="Accepted"), FakeDB(), _user(APPROVER))
    assert env.issue.status == IssueStatus2.risk_accepted
    assert env.audit[-1]["changes"]["basis"] == "approver_note"


@pytest.mark.asyncio
async def test_risk_accepted_with_an_approved_acceptance(env):
    env.accepted = True
    env.linked["risk"] = [uuid.uuid4()]
    await api.close_issue(env.issue.id, IssueClose(status="risk_accepted"), FakeDB(), _user())
    assert env.audit[-1]["changes"]["basis"] == "risk_acceptance"


# ------------------------------------------------------------------ decide ---
def _pending(env, requester):
    change = IssueDueDateChange(
        id=uuid.uuid4(), status="pending", old_due_date=env.issue.due_date,
        new_due_date=env.issue.due_date + timedelta(days=30), reason="slip", requested_by_id=requester,
    )
    env.issue.due_date_changes = [change]
    return change


@pytest.mark.asyncio
async def test_decide_needs_approver_rights(env):
    change = _pending(env, uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await api.decide_due_date_change(env.issue.id, change.id, DueDateDecision(approve=True), FakeDB(), _user())
    assert exc.value.status_code == 403 and "workflow:approve" in exc.value.detail


@pytest.mark.asyncio
async def test_requester_cannot_approve_own_extension(env, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)

    async def no_rule(db, module, action, amount=None):
        return True, None

    monkeypatch.setattr(api.dual_control, "dual_control_required", no_rule)
    requester = uuid.uuid4()
    change = _pending(env, requester)
    with pytest.raises(HTTPException) as exc:
        await api.decide_due_date_change(
            env.issue.id, change.id, DueDateDecision(approve=True), FakeDB(), _user(APPROVER, uid=requester)
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_approving_moves_the_date_rejecting_does_not(env):
    change = _pending(env, uuid.uuid4())
    old = env.issue.due_date
    approver = _user(APPROVER)
    await api.decide_due_date_change(env.issue.id, change.id, DueDateDecision(approve=True), FakeDB(), approver)
    assert env.issue.due_date == change.new_due_date
    assert (change.status, change.approved_by_id) == ("approved", approver.id)
    assert env.issue.due_date_moves == 1

    change2 = _pending(env, uuid.uuid4())
    env.issue.due_date = old
    await api.decide_due_date_change(env.issue.id, change2.id, DueDateDecision(approve=False, note="no"), FakeDB(), approver)
    assert env.issue.due_date == old and change2.status == "rejected"
    with pytest.raises(HTTPException) as exc:
        await api.decide_due_date_change(env.issue.id, change2.id, DueDateDecision(approve=True), FakeDB(), approver)
    assert exc.value.status_code == 409


# ---------------------------------------------------------- control recompute ---
@pytest.mark.asyncio
async def test_recompute_is_skipped_when_the_service_lacks_it(monkeypatch):
    from app.services import control_assurance

    monkeypatch.delattr(control_assurance, "recompute_effectiveness", raising=False)
    assert await ic.recompute_controls(object(), [uuid.uuid4()]) == 0
    assert await ic.recompute_controls(object(), []) == 0


@pytest.mark.asyncio
async def test_recompute_calls_the_service_for_each_live_control(monkeypatch):
    from app.services import control_assurance

    seen = []

    async def recompute(db, control, *, reason=""):
        seen.append((control, reason))

    monkeypatch.setattr(control_assurance, "recompute_effectiveness", recompute, raising=False)
    controls = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]

    class _DB:
        async def scalars(self, stmt):
            return SimpleNamespace(all=lambda: controls)

    assert await ic.recompute_controls(_DB(), [c.id for c in controls], reason="ISS-1 closed") == 2
    assert seen == [(c, "ISS-1 closed") for c in controls]

    # An older signature without ``reason`` is still called.
    plain = []

    def recompute_plain(db, control):
        plain.append(control)

    monkeypatch.setattr(control_assurance, "recompute_effectiveness", recompute_plain, raising=False)
    assert await ic.recompute_controls(_DB(), [controls[0].id], reason="x") == 2
    assert plain == controls


def test_backfill_statement_is_idempotent_sql():
    """The backfill is an INSERT … SELECT … ON CONFLICT DO NOTHING per link kind, joined
    to live targets only."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    link = ic.LINK_BY_KIND["risk"]
    model = link.model
    source = ic._live(model, select(Issue.id, model.id).join(model, model.id == Issue.source_id)
                      .where(Issue.deleted.is_(False), Issue.source_id.is_not(None)))
    sql = str(pg_insert(link.table).from_select(["issue_id", "risk_id"], source).on_conflict_do_nothing()
              .compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT DO NOTHING" in sql and "risks.deleted" in sql and "issue_risks" in sql
