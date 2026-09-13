"""Per-person alerts (product review F-15, plan §3.2): who each alert goes to.

No database. The routing rules are pure functions over a :class:`Directory` (the
organisation's people and roles); ``scan_alerts`` is driven with a fake session that
hands back canned rows per register, to check the wiring end to end.

Pinned here:

1. **Addressing** — one row per recipient, the recipient in the dedup key
   (``…@u:<id>`` / ``…@r:<role>``); no resolvable recipient → one row for everyone,
   under the plain key, so nothing is silently lost.
2. **Grouping per recipient** — the Phase 0 threshold applies to each person's (or
   role's) own alerts; decisions are never grouped.
3. **Reconcile** — text refresh as before; an alert everyone was already shown that is
   now addressed to its owner keeps its date (not news); a reassigned alert is news.
4. **Visibility** — own + role + everyone; ``mine`` drops everyone.
5. **Who** — owners, operators, text owners, approvers (person / role / approving
   roles, never the maker), KRI escalations, SLA escalation roles, DPO roles.
6. **Links** — every individual alert opens its record (``/risks?id=…``).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.models.approval import ApprovalRequest
from app.models.enums import ApprovalStatus, NotificationCategory
from app.models.notification import EVENT_PREFIX, Notification
from app.models.operational_risk import KeyRiskIndicator, KriEscalation
from app.services import master_data
from app.services import notifications as ns
from app.services.notifications import ROLE, USER, Directory, DirectoryUser

W = NotificationCategory.warning
C = NotificationCategory.critical

ALICE, BOB, CAROL, DAN, GONE = (uuid.uuid4() for _ in range(5))


def _directory() -> Directory:
    return Directory(
        users={
            ALICE: DirectoryUser(ALICE, "alice@bank.pk", "Alice Khan", True, ("Risk Manager",)),
            BOB: DirectoryUser(BOB, "bob@bank.pk", "Bob Ali", True, ("Risk Approver",)),
            CAROL: DirectoryUser(CAROL, "carol@bank.pk", "Carol Shah", True, ("Admin", "Data Protection Officer")),
            DAN: DirectoryUser(DAN, "dan@bank.pk", "Bob Ali", True, ("Viewer",)),  # same name as Bob
            GONE: DirectoryUser(GONE, "gone@bank.pk", "Former Staff", False, ("Risk Manager",)),
        },
        role_permissions={
            "Admin": frozenset({"workflow:approve", "issue:read", "risk:write"}),
            "Risk Approver": frozenset({"workflow:approve", "risk:read"}),
            "Risk Manager": frozenset({"risk:write", "issue:read"}),
            "Viewer": frozenset({"risk:read"}),
            "CRO": frozenset(),
            "Data Protection Officer": frozenset({"dpo:read"}),
        },
    )


def _alert(family="control-audit", ref="C-1", *, to=(), eid=None, category=W):
    eid = eid or uuid.uuid4()
    return {
        "dedup_key": f"{family}:{eid}", "title": f"Something overdue: {ref}", "body": f"{ref} was due",
        "category": category, "entity_type": "control", "entity_id": eid,
        "link": f"/controls?id={eid}", "to": list(to),
    }


# ================================================================ addressing ===
def test_an_alert_with_an_owner_becomes_that_persons_row():
    a = _alert(to=[(USER, ALICE)])
    (row,) = ns.address_alerts([a], _directory())
    assert row["dedup_key"] == f"{a['dedup_key']}@u:{ALICE}"
    assert row["user_id"] == ALICE and row["role_name"] == ""
    assert "to" not in row


def test_owner_and_operator_each_get_a_row():
    a = _alert(to=[(USER, ALICE), (USER, BOB)])
    rows = ns.address_alerts([a], _directory())
    assert [r["user_id"] for r in rows] == [ALICE, BOB]
    assert len({r["dedup_key"] for r in rows}) == 2


def test_an_alert_nobody_can_receive_stays_for_everyone():
    """An inactive owner, an unknown user, an unknown role: the plain key, no addressee."""
    for to in ([], [(USER, GONE)], [(USER, uuid.uuid4())], [(ROLE, "No Such Role")], [(USER, None)]):
        a = _alert(to=to)
        (row,) = ns.address_alerts([a], _directory())
        assert row["dedup_key"] == a["dedup_key"], to
        assert row["user_id"] is None and row["role_name"] == ""


def test_roles_are_canonicalised_and_duplicates_dropped():
    a = _alert(to=[(ROLE, "risk approver"), (ROLE, "Risk Approver"), (USER, ALICE), (USER, ALICE)])
    rows = ns.address_alerts([a], _directory())
    assert [(r["user_id"], r["role_name"]) for r in rows] == [(None, "Risk Approver"), (ALICE, "")]
    assert rows[0]["dedup_key"].endswith("@r:Risk Approver")


def test_the_recipient_never_changes_the_family_or_the_condition():
    a = _alert("risk-review", to=[(USER, ALICE)])
    (row,) = ns.address_alerts([a], _directory())
    assert ns.family_of(row["dedup_key"]) == "risk-review"
    assert ns.base_key(row["dedup_key"]) == a["dedup_key"]
    assert len(row["dedup_key"]) < 255


# ================================================================== grouping ===
def test_grouping_happens_per_recipient():
    mine = [ns.address_alerts([_alert(to=[(USER, ALICE)])], _directory())[0] for _ in range(7)]
    bobs = [ns.address_alerts([_alert(to=[(USER, BOB)])], _directory())[0] for _ in range(3)]
    everyone = [ns.address_alerts([_alert()], _directory())[0] for _ in range(6)]
    out = ns.group_alerts(mine + bobs + everyone)
    keys = [a["dedup_key"] for a in out]
    assert keys[0] == f"group:control-audit@u:{ALICE}"
    assert out[0]["user_id"] == ALICE and out[0]["title"] == "7 controls have tests overdue"
    assert keys[1:4] == [a["dedup_key"] for a in bobs]  # three stay individual
    assert keys[4] == "group:control-audit" and out[4]["user_id"] is None and out[4]["role_name"] == ""
    assert len(out) == 5


def test_role_buckets_group_separately_and_decisions_never_group():
    rows = ns.address_alerts([_alert(to=[(ROLE, "Admin")]) for _ in range(9)], _directory())
    (g,) = ns.group_alerts(rows)
    assert g["dedup_key"] == "group:control-audit@r:Admin" and g["role_name"] == "Admin"
    approvals = ns.address_alerts([_alert("approval-pending", to=[(USER, BOB)]) for _ in range(12)], _directory())
    assert ns.group_alerts(approvals) == approvals
    assert "issue-extension" in ns.NEVER_GROUPED and "issue-action" in ns.GROUPABLE_FAMILIES


# ================================================================= reconcile ===
def _row(key, *, user_id=None, role_name="", created=None, **kw):
    base = dict(title="Something overdue: C-1", body="C-1 was due", category=W, link="/controls",
                entity_type="control", entity_id=None)
    return SimpleNamespace(dedup_key=key, user_id=user_id, role_name=role_name,
                           created_at=created or datetime(2026, 9, 1, tzinfo=timezone.utc), **{**base, **kw})


def test_an_alert_everyone_was_shown_keeps_its_date_when_addressed_to_its_owner():
    """The upgrade (or an owner being named): not news, so no unread flip, no digest."""
    a = _alert(to=[(USER, ALICE)])
    (addressed,) = ns.address_alerts([a], _directory())
    old = _row(a["dedup_key"], created=datetime(2026, 8, 1, tzinfo=timezone.utc))
    plan = ns.reconcile_plan({old.dedup_key: old}, [addressed])
    ((created, carried),) = plan.creates
    assert created["dedup_key"] == addressed["dedup_key"]
    assert carried == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert plan.deletes == [old.dedup_key]


def test_a_reassigned_alert_is_news_to_the_new_owner():
    a = _alert(to=[(USER, BOB)])
    (to_bob,) = ns.address_alerts([a], _directory())
    alices = _row(f"{a['dedup_key']}@u:{ALICE}", user_id=ALICE)
    plan = ns.reconcile_plan({alices.dedup_key: alices}, [to_bob])
    ((_created, carried),) = plan.creates
    assert carried is None
    assert plan.deletes == [alices.dedup_key]


def test_reconcile_rewrites_text_and_never_sweeps_events():
    a = _alert(to=[(USER, ALICE)])
    (addressed,) = ns.address_alerts([a], _directory())
    stored = _row(addressed["dedup_key"], user_id=ALICE, body="stale")
    event = _row(f"{EVENT_PREFIX}kri-escalation:1:2")
    plan = ns.reconcile_plan({stored.dedup_key: stored, event.dedup_key: event}, [addressed])
    assert plan.creates == [] and plan.deletes == []
    ((row, changes),) = plan.updates
    assert row is stored and changes["body"] == addressed["body"]


def test_refresh_keeps_the_event_prefix_rule():
    import inspect

    assert "EVENT_PREFIX" in inspect.getsource(ns.refresh)
    assert "address_alerts" in inspect.getsource(ns.refresh)


# ================================================================ visibility ===
def test_a_user_sees_their_own_their_roles_and_everyones():
    mine = SimpleNamespace(user_id=ALICE, role_name="")
    role = SimpleNamespace(user_id=None, role_name="Risk Manager")
    everyone = SimpleNamespace(user_id=None, role_name="")
    bobs = SimpleNamespace(user_id=BOB, role_name="")
    other_role = SimpleNamespace(user_id=None, role_name="Admin")
    both = SimpleNamespace(user_id=BOB, role_name="Risk Manager")  # an event: Bob and the role
    roles = ["Risk Manager"]
    assert [ns.is_visible(r, ALICE, roles) for r in (mine, role, everyone, bobs, other_role, both)] == [
        True, True, True, False, False, True]
    assert [ns.is_visible(r, ALICE, roles, mine=True) for r in (mine, role, everyone, both)] == [
        True, True, False, True]
    assert [ns.audience_of(r, ALICE) for r in (mine, role, everyone, both)] == ["me", "role", "everyone", "role"]


def test_the_sql_filter_matches_the_rule():
    sql = str(ns.visible_clause(ALICE, ["Risk Manager"]).compile(dialect=postgresql.dialect()))
    assert "notifications.user_id =" in sql and "notifications.role_name IN" in sql
    assert "notifications.user_id IS NULL AND notifications.role_name =" in sql
    mine_sql = str(ns.visible_clause(ALICE, ["Risk Manager"], mine=True).compile(dialect=postgresql.dialect()))
    assert "IS NULL" not in mine_sql
    no_roles = str(ns.visible_clause(ALICE, []).compile(dialect=postgresql.dialect()))
    assert "IN" not in no_roles


# ================================================================ the people ===
def test_a_free_text_owner_resolves_only_to_exactly_one_active_person():
    d = _directory()
    assert d.person("ALICE@bank.pk ") == ALICE
    assert d.person("Alice  Khan") == ALICE
    assert d.person("Bob Ali") is None  # two people share the name
    assert d.person("Former Staff") is None  # inactive
    assert d.person("CISO") is None and d.person("") is None


def test_roles_granting_and_first_active():
    d = _directory()
    assert d.roles_granting("workflow:approve") == ["Admin", "Risk Approver"]
    assert d.roles_granting("issue:read", "workflow:approve") == ["Admin"]
    assert d.first_active(GONE, None, BOB) == [(USER, BOB)]
    assert d.active_users(ALICE, GONE, ALICE, CAROL) == [(USER, ALICE), (USER, CAROL)]
    assert d.dpo_roles() == ["Data Protection Officer"]
    assert d.members("Risk Manager") == [ALICE]
    assert d.permissions_of(CAROL) == {"workflow:approve", "issue:read", "risk:write", "dpo:read"}


def _approval(approver="", requested_by=None, email="maker@bank.pk", **kw) -> ApprovalRequest:
    base = dict(id=uuid.uuid4(), reference="APR-001", title="Accept R-117", approver=approver,
                requested_by=requested_by, requested_by_email=email, status=ApprovalStatus.pending,
                required_approvals=1)
    base.update(kw)
    return ApprovalRequest(**base)


def test_an_approval_goes_to_the_named_person_or_role_else_to_the_approving_roles():
    d = _directory()
    approvers = [(ROLE, "Admin"), (ROLE, "Risk Approver")]
    assert ns.approval_recipients(_approval("bob@bank.pk"), d) == [(USER, BOB)]
    assert ns.approval_recipients(_approval("risk approver"), d) == [(ROLE, "Risk Approver")]
    for generic in ("", "any approver", "line manager of x@bank.pk", "Bob Ali", "Head of Treasury"):
        assert ns.approval_recipients(_approval(generic), d) == approvers, generic


def test_a_named_approver_who_cant_decide_brings_in_the_approving_roles():
    """Alice holds no workflow:approve and the CRO role has nobody who does: they are
    told, and so is everyone who could actually decide the request."""
    d = _directory()
    assert ns.approval_recipients(_approval("Alice Khan"), d) == [(USER, ALICE), (ROLE, "Admin"), (ROLE, "Risk Approver")]
    assert ns.approval_recipients(_approval("cro"), d) == [(ROLE, "CRO"), (ROLE, "Admin"), (ROLE, "Risk Approver")]


def test_an_approval_naming_its_own_maker_goes_to_the_approving_roles():
    d = _directory()
    by_id = _approval("bob@bank.pk", requested_by=BOB, email="")
    by_email = _approval("bob@bank.pk", email="BOB@bank.pk")
    for ap in (by_id, by_email):
        assert ns.approval_recipients(ap, d) == [(ROLE, "Admin"), (ROLE, "Risk Approver")]


def test_with_no_approving_role_an_approval_is_for_everyone():
    d = Directory(users={ALICE: DirectoryUser(ALICE, "alice@bank.pk", "Alice")}, role_permissions={"Viewer": frozenset()})
    assert ns.approval_recipients(_approval(), d) == []
    (row,) = ns.address_alerts([_alert("approval-pending", to=ns.approval_recipients(_approval(), d))], d)
    assert row["user_id"] is None and row["role_name"] == ""


def test_who_may_decide_mirrors_the_decision_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    ap = _approval(requested_by=ALICE, email="alice@bank.pk")
    perms = {"workflow:approve"}
    assert ns.approval_refusal(ap, user_id=BOB, email="bob@bank.pk", permissions=perms) is None
    assert "raised this request" in ns.approval_refusal(ap, user_id=ALICE, email="alice@bank.pk", permissions=perms)
    assert "workflow:approve" in ns.approval_refusal(ap, user_id=BOB, email="bob@bank.pk", permissions=set())
    assert "already recorded" in ns.approval_refusal(ap, user_id=BOB, email="b", permissions=perms, voted_ids=[BOB])
    ap.status = ApprovalStatus.approved
    assert "already approved" in ns.approval_refusal(ap, user_id=BOB, email="b", permissions=perms)
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", False)
    ap.status = ApprovalStatus.pending
    assert ns.approval_refusal(ap, user_id=ALICE, email="alice@bank.pk", permissions=perms) is None


# ====================================================================== KRIs ===
def _kri(**kw) -> KeyRiskIndicator:
    base = dict(id=uuid.uuid4(), tenant_id=uuid.uuid4(), reference="KRI-007", name="Failed wires",
                unit="%", direction="higher_is_worse", warning_threshold=2, limit_threshold=5,
                lower_bound=None, upper_bound=None, current_value=7, owner="", owner_id=ALICE)
    base.update(kw)
    return KeyRiskIndicator(**base)


def test_a_kri_breach_goes_to_the_owner_and_the_red_escalation():
    kri = _kri()
    kri.escalations = [KriEscalation(level="red", escalate_to_id=BOB, escalate_to_role="CRO", action="Freeze")]
    assert ns.kri_breach_recipients(kri, _directory()) == [(USER, ALICE), (USER, BOB), (ROLE, "CRO")]
    kri.escalations = []
    assert ns.kri_breach_recipients(kri, _directory()) == [(USER, ALICE)]


def test_an_escalation_event_names_the_person_and_the_role_on_one_row():
    people = {BOB: SimpleNamespace(id=BOB), ALICE: SimpleNamespace(id=ALICE)}
    esc = SimpleNamespace(escalate_to_id=BOB, escalate_to_role="CRO")
    assert ns.escalation_addressee(esc, ALICE, people) == (BOB, "CRO")
    assert ns.escalation_addressee(SimpleNamespace(escalate_to_id=None, escalate_to_role="CRO"), ALICE, people) == (None, "CRO")
    assert ns.escalation_addressee(None, ALICE, people) == (ALICE, "")  # no escalation: the owner
    assert ns.escalation_addressee(None, None, people) == (None, "")  # nobody: everyone
    gone = {BOB: SimpleNamespace(id=BOB, is_active=False)}
    assert ns.escalation_addressee(SimpleNamespace(escalate_to_id=BOB, escalate_to_role=""), None, gone) == (None, "")


async def test_raise_kri_escalation_stores_one_addressed_row(monkeypatch):
    jane = SimpleNamespace(id=BOB, full_name="Jane Doe", email="jane@bank.pk")

    async def users_by_id(db, ids):
        return {i: jane for i in ids if i == BOB}

    monkeypatch.setattr(master_data, "users_by_id", users_by_id)
    added = []
    db = SimpleNamespace(add=added.append)
    kri = _kri(owner_id=None)
    kri.escalations = [KriEscalation(level="red", escalate_to_id=BOB, escalate_to_role="CRO", action="Freeze")]
    out = await ns.raise_kri_escalation(db, kri, "red", value=9, as_of=date(2026, 9, 12), measurement_id=uuid.uuid4())
    (note,) = added
    assert isinstance(note, Notification) and note.user_id == BOB and note.role_name == "CRO"
    assert note.dedup_key.startswith(f"{EVENT_PREFIX}kri-escalation:") and "@" not in note.dedup_key
    assert note.link == f"/operational-risk?id={kri.id}"
    assert out["target"] == "Jane Doe and the CRO role" and out["user_id"] == BOB


# ===================================================================== links ===
def test_links_open_the_record():
    rid = uuid.uuid4()
    assert ns.with_id("/risks", rid) == f"/risks?id={rid}"
    assert ns.with_id("/aml", rid, param="sar") == f"/aml?sar={rid}"
    assert ns.with_id("/x?tab=a", rid) == f"/x?tab=a&id={rid}"
    assert ns.with_id("/risks", None) == "/risks"
    assert ns.link_to("risk", rid) == f"/risks?id={rid}"
    assert ns.link_to("control", rid) == f"/controls?id={rid}"
    assert ns.link_to("access_review", rid) == f"/access-reviews?id={rid}"
    assert ns.link_to("asset", rid, asset_class="it_asset") == f"/it-assets?id={rid}"
    assert ns.link_to("asset", rid, asset_class="information_asset") == f"/information-assets?id={rid}"


def test_the_owner_column_skips_non_user_owners():
    from app.models.asset import Asset
    from app.models.control import Control
    from app.models.vendor import Vendor

    assert ns.owner_column(Control).key in ("owner_id", "workflow_owner_id")
    assert ns.owner_column(Vendor).key in ("relationship_owner_id", "workflow_owner_id")
    col = ns.owner_column(Asset)
    assert col is None or col.key != "owner_id"  # Asset.owner_id is a business unit, not a person


# ======================================================= the scan, end to end ===
class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class ScanDB:
    """Hands back canned rows by the first entity a statement selects."""

    def __init__(self, by_entity: dict):
        self.by_entity = by_entity

    def _rows(self, stmt):
        desc = stmt.column_descriptions[0] if getattr(stmt, "column_descriptions", None) else {}
        entity = desc.get("entity")
        return self.by_entity.get(getattr(entity, "__name__", None), [])

    async def scalars(self, stmt, *a, **k):
        return _Rows(self._rows(stmt))

    async def execute(self, stmt, *a, **k):
        return _Rows(self._rows(stmt))

    async def scalar(self, stmt, *a, **k):
        return None


@pytest.fixture
def scan_env(monkeypatch):
    from app.services import sla

    async def settings_(db, tenant_id):
        return SimpleNamespace()

    class Book:
        min_tolerance = 12

        @staticmethod
        def tolerance_for(category_id):
            return 12

    async def book(db, tenant_id, s):
        return Book()

    async def reconcile(db, tenant_id):
        return []

    monkeypatch.setattr(ns, "get_or_create_settings", settings_)
    monkeypatch.setattr(ns, "load_appetite_book", book)
    monkeypatch.setattr(sla, "reconcile", reconcile)


async def test_scan_addresses_owners_operators_and_approvers(scan_env):
    from app.models.control import Control
    from app.models.enums import ControlStatus
    from app.models.risk import Risk

    today = date.today()
    risk = Risk(id=uuid.uuid4(), reference="R-117", title="Card fraud", owner_id=ALICE,
                next_review_date=today - timedelta(days=3), inherent_score=6, residual_score=None, category_id=None)
    control = Control(id=uuid.uuid4(), reference="A.8.5", name="MFA", owner_id=ALICE, operator_id=BOB,
                      status=ControlStatus.operational, next_audit_date=today - timedelta(days=1),
                      next_maintenance_date=None, workflow_owner_id=None)
    ap = _approval("")
    db = ScanDB({"Risk": [risk], "Control": [control], "ApprovalRequest": [ap]})
    alerts = await ns.scan_alerts(db, uuid.uuid4(), directory=_directory())
    by_family = {ns.family_of(a["dedup_key"]): a for a in alerts}
    assert by_family["risk-review"]["to"] == [(USER, ALICE)]
    assert by_family["risk-review"]["link"] == f"/risks?id={risk.id}"
    assert by_family["control-audit"]["to"] == [(USER, ALICE), (USER, BOB)]
    assert by_family["control-audit"]["link"] == f"/controls?id={control.id}"
    assert by_family["approval-pending"]["to"] == [(ROLE, "Admin"), (ROLE, "Risk Approver")]
    assert by_family["approval-pending"]["link"] == f"/approvals?id={ap.id}"

    rows = ns.address_alerts(alerts, _directory())
    keys = {r["dedup_key"] for r in rows}
    assert f"control-audit:{control.id}@u:{BOB}" in keys and f"risk-review:{risk.id}@u:{ALICE}" in keys
    assert f"approval-pending:{ap.id}@r:Risk Approver" in keys


async def test_a_risk_without_an_owner_stays_for_everyone(scan_env):
    from app.models.risk import Risk

    risk = Risk(id=uuid.uuid4(), reference="R-2", title="Orphan", owner_id=None,
                next_review_date=date.today() - timedelta(days=1), inherent_score=4, residual_score=None, category_id=None)
    alerts = await ns.scan_alerts(ScanDB({"Risk": [risk]}), uuid.uuid4(), directory=_directory())
    (row,) = ns.address_alerts(alerts, _directory())
    assert row["dedup_key"] == f"risk-review:{risk.id}" and row["user_id"] is None and row["role_name"] == ""
