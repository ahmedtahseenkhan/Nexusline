"""Policy record depth (plan §2.7).

No database: the pure rules are tested directly and the endpoints are driven with a fake
session, stubbed loaders and a captured audit trail.

Pinned here:

1. **Requirement links from the policy side** — ``requirements_ids`` is written into
   ``requirement_policies`` on create, replaced on update, left alone when absent, and an
   unknown requirement is refused (it was never silently dropped; this pins it).
2. **Supersession** — not itself, no cycles (direct or down the chain), the target must
   be live; publishing retires the superseded policy through the lifecycle service
   (system transition, audited as ``workflow_retire`` naming the successor), and so does
   pointing an already-published policy at another.
3. **Effective date** — can't precede approval (edit: 422, publish: 409); Publish sets it
   to the publication date when empty.
4. **Approving authority and applicability** — a live committee; units and roles
   validated (422 naming the field) and written.
5. **Acknowledgement targeting** — members of the policy's roles, or every active user
   when it names none; business units don't narrow it (users carry no unit) and the
   response says so.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql.dml import Delete, Insert

from app.api.v1 import policies as api
from app.models.base import WorkflowState
from app.models.enums import PolicyStatus
from app.models.policy import Policy
from app.schemas import policy as s
from app.services import audit as audit_service
from app.services.import_registry import REGISTRY

TODAY = date.today()


# ================================================================== fakes ===
class FakeDB:
    """``scalars`` answers id lookups with ``known`` (every id asked for that is known);
    ``execute`` records DML and answers selects from ``rows``."""

    def __init__(self, known=(), scalar=None, rows=None):
        self.known = set(known)
        self._scalar = scalar
        self.rows = rows if rows is not None else []
        self.executed: list = []
        self.added: list = []
        self.flushed = 0

    async def scalar(self, stmt, *_a, **_k):
        return self._scalar(stmt) if callable(self._scalar) else self._scalar

    async def scalars(self, stmt, *_a, **_k):
        wanted = set()
        for crit in stmt.whereclause.get_children() if stmt.whereclause is not None else ():
            value = getattr(getattr(crit, "right", None), "value", None)
            if isinstance(value, (list, tuple, set)):
                wanted |= set(value)
        found = [i for i in wanted if i in self.known] if wanted else []
        return SimpleNamespace(all=lambda: found)

    async def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        rows = self.rows
        return SimpleNamespace(all=lambda: rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "id", "x") is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", "x") is None:
                obj.created_at = datetime.now(timezone.utc)

    async def refresh(self, obj):
        return None

    def dml(self, table_name):
        out = []
        for stmt, params in self.executed:
            if isinstance(stmt, (Delete, Insert)) and stmt.table.name == table_name:
                out.append((type(stmt).__name__, params))
        return out


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit_service, "record", record)
    return calls


@pytest.fixture
def stub_io(monkeypatch):
    """Reference numbers and the read-back are not what these tests are about."""
    async def next_ref(db):
        return "POL-042"

    async def read(db, policy):
        return policy

    monkeypatch.setattr(api, "_next_ref", next_ref)
    monkeypatch.setattr(api, "_read", read)


def _user(perms=("policy:read", "policy:write")):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="author@bank.pk",
                           permission_codes=list(perms))


def _policy(**kw) -> Policy:
    base = dict(id=uuid.uuid4(), tenant_id=uuid.uuid4(), reference="POL-001", title="Information Security",
                status=PolicyStatus.draft, workflow_status=WorkflowState.draft, supersedes_id=None,
                approving_authority_id=None, effective_date=None, deleted=False, owner="", category="",
                version="1.0")
    base.update(kw)
    return Policy(**base)


def _loader(monkeypatch, policy):
    async def load(db, policy_id):
        return policy

    monkeypatch.setattr(api, "_load", load)


# ============================================================= requirements ===
async def test_requirement_links_are_written_from_the_policy_side(monkeypatch, audit_calls, stub_io):
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    created = {}

    async def load(db, policy_id):
        return created["policy"]

    monkeypatch.setattr(api, "_load", load)
    db = FakeDB(known={r1, r2})
    orig_add = db.add

    def add(obj):
        created.setdefault("policy", obj)
        orig_add(obj)

    db.add = add
    await api.create_policy(s.PolicyCreate(title="Access Control", requirements_ids=[r1, r2]), db, _user())
    policy = created["policy"]
    writes = db.dml("requirement_policies")
    assert writes[0][0] == "Delete"
    assert writes[1] == ("Insert", [{"policy_id": policy.id, "requirement_id": r1},
                                    {"policy_id": policy.id, "requirement_id": r2}])
    assert audit_calls[-1]["action"] == "create"


async def test_update_replaces_requirement_links_and_leaves_them_when_absent(monkeypatch, audit_calls, stub_io):
    policy = _policy()
    _loader(monkeypatch, policy)
    r3 = uuid.uuid4()
    db = FakeDB(known={r3})
    await api.update_policy(policy.id, s.PolicyUpdate(requirements_ids=[r3]), db, _user())
    assert db.dml("requirement_policies") == [
        ("Delete", None), ("Insert", [{"policy_id": policy.id, "requirement_id": r3}])]

    db = FakeDB()
    await api.update_policy(policy.id, s.PolicyUpdate(title="Renamed"), db, _user())
    assert db.dml("requirement_policies") == []  # not sent: untouched

    db = FakeDB()
    await api.update_policy(policy.id, s.PolicyUpdate(requirements_ids=[]), db, _user())
    assert db.dml("requirement_policies") == [("Delete", None)]  # sent empty: cleared


async def test_an_unknown_requirement_is_refused_not_dropped(monkeypatch, audit_calls, stub_io):
    policy = _policy()
    _loader(monkeypatch, policy)
    with pytest.raises(HTTPException) as exc:
        await api.update_policy(policy.id, s.PolicyUpdate(requirements_ids=[uuid.uuid4()]), FakeDB(), _user())
    assert exc.value.status_code == 400 and "requirement" in exc.value.detail


# ============================================================== supersession ===
def test_supersession_rules():
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    assert api.supersession_refusal(a, None, {}) is None
    assert "itself" in api.supersession_refusal(a, a, {})
    # b already supersedes a: a may not supersede b.
    assert "cycle" in api.supersession_refusal(a, b, {b: a})
    # c → b → a: a may not supersede c either.
    assert "cycle" in api.supersession_refusal(a, c, {c: b, b: a})
    # d → c → b: a may supersede d (no path back to a).
    assert api.supersession_refusal(a, d, {d: c, c: b}) is None
    # A new policy (no id yet) can supersede anything.
    assert api.supersession_refusal(None, b, {b: a}) is None
    # A pre-existing loop elsewhere doesn't hang the walk.
    assert api.supersession_refusal(a, c, {c: d, d: c}) is None


async def test_governance_checks_on_write(monkeypatch):
    policy = _policy()
    # Unknown committee.
    with pytest.raises(HTTPException) as exc:
        await api._check_governance(FakeDB(scalar=None), {"approving_authority_id": uuid.uuid4()}, policy)
    assert exc.value.status_code == 422 and exc.value.detail.startswith("approving_authority_id:")
    # Itself.
    with pytest.raises(HTTPException) as exc:
        await api._check_governance(FakeDB(scalar=policy.id), {"supersedes_id": policy.id}, policy)
    assert "itself" in exc.value.detail
    # Unknown / archived target.
    with pytest.raises(HTTPException) as exc:
        await api._check_governance(FakeDB(scalar=None), {"supersedes_id": uuid.uuid4()}, policy)
    assert "does not exist or is archived" in exc.value.detail
    # A cycle through the stored links.
    other = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await api._check_governance(FakeDB(scalar=other, rows=[(other, policy.id)]), {"supersedes_id": other}, policy)
    assert "cycle" in exc.value.detail
    # Unchanged values are not re-checked (a committee since archived doesn't block edits).
    policy.approving_authority_id = uuid.uuid4()
    await api._check_governance(FakeDB(scalar=None), {"approving_authority_id": policy.approving_authority_id}, policy)


def test_effective_date_rule():
    assert api.effective_date_refusal(None, date(2026, 9, 1)) is None
    assert api.effective_date_refusal(date(2026, 9, 1), None) is None  # never approved: nothing to compare
    assert api.effective_date_refusal(date(2026, 9, 1), date(2026, 9, 1)) is None
    assert "before the policy was approved" in api.effective_date_refusal(date(2026, 8, 31), date(2026, 9, 1))


async def test_an_effective_date_before_approval_is_refused_on_edit(monkeypatch):
    policy = _policy(workflow_status=WorkflowState.approved, status=PolicyStatus.approved)

    async def approved_on(db, p):
        return date(2026, 9, 10)

    monkeypatch.setattr(api, "_approved_on", approved_on)
    with pytest.raises(HTTPException) as exc:
        await api._check_governance(FakeDB(), {"effective_date": date(2026, 9, 1)}, policy)
    assert exc.value.status_code == 422 and exc.value.detail.startswith("effective_date:")
    await api._check_governance(FakeDB(), {"effective_date": date(2026, 9, 15)}, policy)


def _publishable(monkeypatch, policy, approved=None):
    _loader(monkeypatch, policy)

    async def no_sod(*a, **k):
        return None

    async def approved_on(db, p):
        return approved

    monkeypatch.setattr(api.dual_control, "enforce_record_maker_checker", no_sod)
    monkeypatch.setattr(api, "_approved_on", approved_on)


async def test_publishing_retires_the_superseded_policy_and_dates_the_new_one(monkeypatch, audit_calls, stub_io):
    old = _policy(reference="POL-001", status=PolicyStatus.published, workflow_status=WorkflowState.approved)
    new = _policy(reference="POL-009", status=PolicyStatus.approved, workflow_status=WorkflowState.approved,
                  supersedes_id=old.id)
    _publishable(monkeypatch, new)
    db = FakeDB(scalar=old)
    await api.publish_policy(new.id, db, _user())
    assert new.status == PolicyStatus.published and new.effective_date == new.published_at == TODAY
    assert old.workflow_status == WorkflowState.retired and old.status == PolicyStatus.retired
    retire, publish = audit_calls[-2], audit_calls[-1]
    assert retire["action"] == "workflow_retire" and retire["entity_id"] == old.id
    assert retire["changes"]["via"] == "supersession" and retire["changes"]["superseded_by_reference"] == "POL-009"
    assert "superseded by POL-009" in retire["summary"]
    assert publish["action"] == "publish" and "retired POL-001" in publish["summary"]


async def test_publishing_keeps_a_later_effective_date_and_refuses_an_earlier_one(monkeypatch, audit_calls, stub_io):
    later = _policy(status=PolicyStatus.approved, workflow_status=WorkflowState.approved,
                    effective_date=date(2030, 1, 1))
    _publishable(monkeypatch, later, approved=date(2026, 9, 1))
    await api.publish_policy(later.id, FakeDB(), _user())
    assert later.effective_date == date(2030, 1, 1) and later.status == PolicyStatus.published

    early = _policy(status=PolicyStatus.approved, workflow_status=WorkflowState.approved,
                    effective_date=date(2026, 8, 1))
    _publishable(monkeypatch, early, approved=date(2026, 9, 1))
    with pytest.raises(HTTPException) as exc:
        await api.publish_policy(early.id, FakeDB(), _user())
    assert exc.value.status_code == 409 and early.status == PolicyStatus.approved


async def test_an_already_retired_predecessor_is_left_alone(monkeypatch, audit_calls, stub_io):
    old = _policy(status=PolicyStatus.retired, workflow_status=WorkflowState.retired)
    new = _policy(status=PolicyStatus.approved, workflow_status=WorkflowState.approved, supersedes_id=old.id)
    _publishable(monkeypatch, new)
    await api.publish_policy(new.id, FakeDB(scalar=old), _user())
    assert [c["action"] for c in audit_calls] == ["publish"]


async def test_pointing_a_published_policy_at_another_retires_it(monkeypatch, audit_calls, stub_io):
    old = _policy(reference="POL-002", status=PolicyStatus.published, workflow_status=WorkflowState.approved)
    live = _policy(reference="POL-010", status=PolicyStatus.published, workflow_status=WorkflowState.approved)
    _loader(monkeypatch, live)

    def scalar(stmt):
        return old if "policies.deleted" in str(stmt) and "policies.id =" in str(stmt) and stmt.column_descriptions[0]["type"] is Policy else old.id

    db = FakeDB(scalar=scalar, rows=[])
    await api.update_policy(live.id, s.PolicyUpdate(supersedes_id=old.id), db, _user())
    assert live.supersedes_id == old.id
    assert old.status == PolicyStatus.retired and old.workflow_status == WorkflowState.retired
    assert audit_calls[-2]["action"] == "workflow_retire" and "retired POL-002" in audit_calls[-1]["summary"]

    # A draft pointing at a policy retires nothing yet: that happens when it is published.
    draft_target = _policy(status=PolicyStatus.published, workflow_status=WorkflowState.approved)
    draft = _policy()
    _loader(monkeypatch, draft)
    await api.update_policy(draft.id, s.PolicyUpdate(supersedes_id=draft_target.id),
                            FakeDB(scalar=lambda stmt: draft_target.id, rows=[]), _user())
    assert draft_target.status == PolicyStatus.published


# ============================================================ applicability ===
async def test_unknown_units_and_roles_are_422_naming_the_field():
    with pytest.raises(HTTPException) as exc:
        await api._load_strict(FakeDB(), api.BusinessUnit, [uuid.uuid4()], "business_unit_ids", "business unit")
    assert exc.value.status_code == 422 and exc.value.detail.startswith("business_unit_ids:")
    with pytest.raises(HTTPException) as exc:
        await api._load_strict(FakeDB(), api.Role, [uuid.uuid4()], "role_ids", "role")
    assert exc.value.detail.startswith("role_ids:")
    assert await api._load_strict(FakeDB(), api.Role, [], "role_ids", "role") == []


def test_schemas_carry_the_governance_fields():
    create = set(s.PolicyCreate.model_fields)
    assert {"approving_authority_id", "effective_date", "supersedes_id", "business_unit_ids", "role_ids",
            "requirements_ids"} <= create
    assert {"approving_authority_id", "effective_date", "supersedes_id", "business_unit_ids",
            "role_ids"} <= set(s.PolicyUpdate.model_fields)
    read = set(s.PolicyRead.model_fields)
    assert {"approving_authority_ref", "supersedes_ref", "superseded_by", "business_units", "roles"} <= read
    assert s.PolicyUpdate(title="x").model_dump(exclude_unset=True) == {"title": "x"}


def test_the_import_registry_carries_the_new_columns():
    cols = {c.field: c for c in REGISTRY["policies"].columns}
    assert cols["approving_authority_id"].link.target_model.__name__ == "Committee"
    assert cols["supersedes_id"].link.target_model is Policy and not cols["supersedes_id"].link.multi
    assert cols["business_unit_ids"].link.multi and cols["role_ids"].link.match_field == "name"
    assert cols["effective_date"].kind == "date"
    assert cols["requirements_ids"].link.create_field == "requirements_ids"


async def test_reads_fill_the_committee_and_both_ends_of_supersession():
    committee = uuid.uuid4()
    old, mid, new = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    page = [SimpleNamespace(id=mid, approving_authority_id=committee, supersedes_id=old)]
    items = [SimpleNamespace(approving_authority_ref=None, supersedes_ref=None, superseded_by=[])]

    class DB(FakeDB):
        async def execute(self, stmt, params=None):
            sql = str(stmt)
            if "committees" in sql:
                return SimpleNamespace(all=lambda: [(committee, "BRC", "Board Risk Committee")])
            return SimpleNamespace(all=lambda: [(old, "POL-001", "Old", None), (new, "POL-020", "New", mid)])

    await api._fill_governance(DB(), page, items)
    item = items[0]
    assert item.approving_authority_ref.name == "Board Risk Committee"
    assert item.supersedes_ref.reference == "POL-001"
    assert [g.reference for g in item.superseded_by] == ["POL-020"]


# ======================================================== acknowledgements ===
def _role(name):
    return SimpleNamespace(id=uuid.uuid4(), name=name)


def _person(name, roles, active=True):
    return SimpleNamespace(id=uuid.uuid4(), full_name=name, email=f"{name.split()[0].lower()}@bank.pk",
                           roles=roles, is_active=active)


def test_acknowledgement_scope_is_the_policy_roles():
    tellers, it = _role("Tellers"), _role("IT")
    alia, bilal, chen, dana = (_person("Alia Raza", [tellers]), _person("Bilal Shah", [tellers, it]),
                               _person("Chen Wu", [_role("Audit")]), _person("Dana Ali", [tellers], active=False))
    when = datetime(2026, 9, 1, tzinfo=timezone.utc)
    policy = SimpleNamespace(
        id=uuid.uuid4(), roles=[tellers], business_units=[SimpleNamespace(id=uuid.uuid4(), name="Retail")],
        acknowledgments=[SimpleNamespace(user_id=bilal.id, created_at=when),
                         SimpleNamespace(user_id=chen.id, created_at=when)],
    )
    status = api.ack_status(policy, [alia, bilal, chen, dana])
    assert status.scope == "roles" and status.roles == ["Tellers"]
    assert [u.full_name for u in status.users] == ["Alia Raza", "Bilal Shah"]  # pending first; inactive out
    assert (status.total, status.acknowledged, status.pending, status.outside_scope) == (2, 1, 1, 1)
    assert status.users[1].acknowledged and status.users[1].acknowledged_at == when
    assert not status.users[0].acknowledged and status.users[0].acknowledged_at is None
    assert "users aren't linked to business units" in status.note


def test_a_policy_without_roles_asks_everyone():
    people = [_person("Alia Raza", []), _person("Bilal Shah", [_role("IT")])]
    policy = SimpleNamespace(id=uuid.uuid4(), roles=[], business_units=[], acknowledgments=[])
    status = api.ack_status(policy, people)
    assert status.scope == "everyone" and status.total == 2 and status.pending == 2
    assert "every active user" in status.note and "business units" not in status.note


async def test_acknowledging_is_audited_once(monkeypatch, audit_calls):
    from app.models.policy import PolicyAcknowledgment

    policy = _policy(reference="POL-003", version="2.0")
    _loader(monkeypatch, policy)
    user = _user()
    db = FakeDB(scalar=None)
    read = await api.acknowledge_policy(policy.id, db, user)
    assert read.user_id == user.id and read.policy_id == policy.id
    assert [c["action"] for c in audit_calls] == ["acknowledge"]
    assert "POL-003 (version 2.0)" in audit_calls[0]["summary"]
    existing = PolicyAcknowledgment(id=uuid.uuid4(), tenant_id=user.tenant_id, policy_id=policy.id,
                                    user_id=user.id, user_email=user.email,
                                    created_at=datetime.now(timezone.utc))
    await api.acknowledge_policy(policy.id, FakeDB(scalar=existing), user)
    assert len(audit_calls) == 1  # acknowledging again changes nothing
