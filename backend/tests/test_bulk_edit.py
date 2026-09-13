"""Bulk edit on the registers (product review 3.2, F-15).

No database: the allow-list and the per-register rules (``services.bulk_edit``) are pure
and tested directly; the runner is driven with a fake session and a captured audit trail.

Pinned here:

1. **An explicit allow-list per register.** Every field maps to a real column; approval
   state (``workflow_status``) is never settable; policies have no bulk status (the
   lifecycle drives it); anything else is a 422 naming what the register accepts.
2. **Values are checked once** for the batch — one lookup per value, however many
   records — and a bad value is a 422 naming the field.
3. **Each record goes through its register's rules**: a planned or retired control has
   no test clock; a new frequency re-derives the next date as the record's edit does;
   going live starts the clock and retiring stops it; an issue can't be closed or
   reopened in bulk; an incident's status stamps its timeline and an out-of-order
   timeline is skipped.
4. **Live records of this organisation only**, each updated or skipped with a reason,
   in the order asked, with one audit entry per record carrying the batch id, and a
   one-line summary ("Updated 38; 2 skipped: archived").
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.fk_backfill import FK_LOOKUP_KEYS
from app.models.enums import ControlStatus, IncidentStatus, ReviewFrequency, VendorStatus
from app.models.identity import User
from app.models.issue import IssueStatus2
from app.models.lookup import Lookup
from app.schemas.bulk import BulkEditBody, BulkResultItem
from app.services import bulk_edit as be
from app.services import record_registry
from app.services.risk_scoring import next_review_date

TODAY = date(2026, 9, 12)
NOW = datetime(2026, 9, 12, 9, 30, tzinfo=timezone.utc)
F = ReviewFrequency


def _plan(entity_type, record, **values):
    return be.plan(be.REGISTERS[entity_type], record, values, today=TODAY, now=NOW)


def V(value, text="", column_text=None):
    return be.Value(value, text or str(value), column_text)


def _control(**kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), reference="C-1", name="MFA", deleted=False,
        status=ControlStatus.operational, owner_id=None, owner="", classification_id=None,
        classification="", audit_frequency=F.annual, next_audit_date=TODAY + timedelta(days=100),
        last_audit_date=date(2026, 3, 1), maintenance_frequency=F.quarterly,
        next_maintenance_date=TODAY + timedelta(days=40), last_maintenance_date=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ================================================================ the allow-list ===
@pytest.mark.parametrize("entity_type", sorted(be.REGISTERS))
def test_every_field_is_a_real_column_and_never_the_lifecycle(entity_type):
    register = be.REGISTERS[entity_type]
    model = record_registry.model_for(entity_type)
    columns = model.__table__.c
    for f in register.fields:
        assert f.key in be.KEYS
        assert f.column in columns, f"{entity_type}.{f.column}"
        assert f.column != "workflow_status" and f.text_column != "workflow_status"
        if f.text_column:
            assert f.text_column in columns
        if f.kind == "lookup":
            assert f.lookup_key == FK_LOOKUP_KEYS[(model.__tablename__, f.column)]
        if f.kind in ("status", "frequency"):
            assert f.choices


def test_registers_and_what_they_accept():
    assert set(be.REGISTERS) == {"control", "issue", "incident", "policy", "vendor", "asset", "risk"}
    assert "status" not in be.REGISTERS["policy"].keys  # the lifecycle drives a policy's status
    assert "status" not in be.REGISTERS["risk"].keys and "status" not in be.REGISTERS["asset"].keys
    assert be.REGISTERS["control"].field("next_review_date").column == "next_audit_date"
    assert be.REGISTERS["incident"].field("owner_id").column == "assignee_id"
    assert be.REGISTERS["vendor"].field("owner_id").column == "relationship_owner_id"
    assert be.REGISTERS["asset"].field("owner_id").kind == "unit"
    assert [c.value for c in be.REGISTERS["issue"].field("status").choices] == ["open", "in_progress"]


def test_the_body_never_carries_approval_state():
    with pytest.raises(ValidationError):
        BulkEditBody(ids=[uuid.uuid4()], patch={"workflow_status": "approved"})
    with pytest.raises(ValidationError):
        BulkEditBody(ids=[], patch={"owner_id": str(uuid.uuid4())})


def test_shape_rules():
    control = be.REGISTERS["control"]
    with pytest.raises(HTTPException) as exc:
        be.check_keys(control, {})
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        be.check_keys(be.REGISTERS["policy"], {"status": "published"})
    assert "can't have status set in bulk" in exc.value.detail and "owner_id" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        be.check_keys(control, {"owner_id": None})
    assert "owner_id: choose a value" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        be.check_keys(control, {"review_frequency": "annual", "next_review_date": TODAY})
    assert "not both" in exc.value.detail


def test_a_status_must_be_one_the_register_offers():
    issue_status = be.REGISTERS["issue"].field("status")
    assert be.choose(issue_status, "in_progress") == IssueStatus2.in_progress
    with pytest.raises(HTTPException) as exc:
        be.choose(issue_status, "closed")  # closing is Validate and Close
    assert exc.value.status_code == 422
    freq = be.REGISTERS["policy"].field("review_frequency")
    assert be.choose(freq, "quarterly") == F.quarterly
    with pytest.raises(HTTPException):
        be.choose(freq, "daily")  # not on the policy form


def test_unknown_or_unregistered_types():
    with pytest.raises(HTTPException) as exc:
        be.register_for("no_such_thing")
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        be.register_for("goal")
    assert "can't be edited in bulk" in exc.value.detail


# ====================================================================== controls ===
def test_planned_or_retired_controls_have_no_test_clock():
    for status, reason in ((ControlStatus.planned, "planned"), (ControlStatus.retired, "retired")):
        with pytest.raises(be.Skip) as why:
            _plan("control", _control(status=status, next_audit_date=None), next_review_date=V(TODAY + timedelta(days=9)))
        assert str(why.value).startswith(reason)


def test_an_operating_control_takes_the_date_given():
    target = TODAY + timedelta(days=9)
    assert _plan("control", _control(), next_review_date=V(target)) == {"next_audit_date": target}


def test_a_new_test_frequency_re_derives_from_the_last_test():
    c = _control(audit_frequency=F.annual, last_audit_date=date(2026, 3, 1))
    out = _plan("control", c, review_frequency=V(F.quarterly))
    assert out == {"audit_frequency": F.quarterly, "next_audit_date": next_review_date(F.quarterly, date(2026, 3, 1))}


def test_going_live_starts_both_clocks_and_retiring_stops_them():
    planned = _control(status=ControlStatus.planned, next_audit_date=None, next_maintenance_date=None)
    out = _plan("control", planned, status=V(ControlStatus.operational))
    assert out["status"] == ControlStatus.operational
    assert out["next_audit_date"] == next_review_date(F.annual, TODAY)
    assert out["next_maintenance_date"] == next_review_date(F.quarterly, TODAY)
    out = _plan("control", _control(), status=V(ControlStatus.retired))
    assert out == {"status": ControlStatus.retired, "next_audit_date": None, "next_maintenance_date": None}


def test_owner_keeps_the_legacy_text_in_step_and_same_owner_is_no_change():
    person = uuid.uuid4()
    out = _plan("control", _control(owner="CISO"), owner_id=V(person, "Ayesha Khan", "Ayesha Khan"))
    assert out == {"owner_id": person, "owner": "Ayesha Khan"}
    with pytest.raises(be.Skip) as why:
        _plan("control", _control(owner_id=person), owner_id=V(person, "Ayesha Khan", "Ayesha Khan"))
    assert str(why.value) == be.NO_CHANGE


# ======================================================================== issues ===
def test_issues_cannot_be_closed_or_reopened_in_bulk():
    closed = SimpleNamespace(status=IssueStatus2.remediated, owner_id=None, owner="", category_id=None, category="")
    with pytest.raises(be.Skip) as why:
        _plan("issue", closed, status=V(IssueStatus2.open))
    assert "reopen it from the issue itself" in str(why.value)
    # A closed issue's owner can still be changed.
    person = uuid.uuid4()
    assert _plan("issue", closed, owner_id=V(person, "A", "A"))["owner_id"] == person
    live = SimpleNamespace(status=IssueStatus2.open)
    assert _plan("issue", live, status=V(IssueStatus2.in_progress)) == {"status": IssueStatus2.in_progress}


# ===================================================================== incidents ===
def _incident(**kw):
    base = dict(
        status=IncidentStatus.investigating, occurred_at=NOW - timedelta(days=2),
        detected_at=NOW - timedelta(days=1), contained_at=None, resolved_at=None,
        near_miss=False, cost=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_incident_status_stamps_the_step_it_implies():
    out = _plan("incident", _incident(), status=V(IncidentStatus.contained))
    assert out == {"status": IncidentStatus.contained, "contained_at": NOW}
    recorded = NOW - timedelta(hours=3)
    out = _plan("incident", _incident(contained_at=recorded), status=V(IncidentStatus.resolved))
    assert out == {"status": IncidentStatus.resolved, "resolved_at": NOW}


def test_an_incident_whose_timeline_would_be_out_of_order_is_skipped():
    # Detected "tomorrow" (a typo on the record): containing it now would precede detection.
    with pytest.raises(be.Skip) as why:
        _plan("incident", _incident(detected_at=NOW + timedelta(days=1)), status=V(IncidentStatus.contained))
    assert "before detected" in str(why.value)
    with pytest.raises(be.Skip) as why:
        _plan("incident", _incident(near_miss=True, cost=500), status=V(IncidentStatus.closed))
    assert "near miss" in str(why.value)


# ========================================================== review cycles, others ===
def test_policy_frequency_re_derives_from_today_and_risk_from_its_last_review():
    policy = SimpleNamespace(review_frequency=F.annual, next_review_date=None)
    assert _plan("policy", policy, review_frequency=V(F.quarterly)) == {
        "review_frequency": F.quarterly, "next_review_date": next_review_date(F.quarterly, TODAY),
    }
    risk = SimpleNamespace(review_frequency=F.annual, next_review_date=None, last_review_date=date(2026, 1, 10))
    assert _plan("risk", risk, review_frequency=V(F.semiannual))["next_review_date"] == date(2026, 7, 10)


def test_vendor_and_asset_frequency_changes_only_the_frequency():
    vendor = SimpleNamespace(review_frequency=F.annual, next_review_date=TODAY, status=VendorStatus.active)
    assert _plan("vendor", vendor, review_frequency=V(F.quarterly)) == {"review_frequency": F.quarterly}
    assert _plan("vendor", vendor, status=V(VendorStatus.suspended)) == {"status": VendorStatus.suspended}
    asset = SimpleNamespace(review_frequency=F.annual, next_review_date=None, owner_id=None)
    unit = uuid.uuid4()
    assert _plan("asset", asset, owner_id=V(unit, "Retail")) == {"owner_id": unit}


# ======================================================================== summary ===
def _r(outcome, reason=""):
    return BulkResultItem(id=uuid.uuid4(), outcome=outcome, reason=reason)


def test_summary():
    assert be.summarize([_r("updated")] * 38 + [_r("skipped", "archived")] * 2) == "Updated 38; 2 skipped: archived"
    assert be.summarize([_r("updated")] * 3) == "Updated 3"
    mixed = [_r("updated"), _r("skipped", "archived"), _r("skipped", "archived"), _r("skipped", "no change")]
    assert be.summarize(mixed) == "Updated 1; 3 skipped: 2 archived, 1 no change"
    assert be.summarize([_r("skipped", "not found")]) == "Nothing updated; 1 skipped: not found"


def test_what_changed_reads_as_words():
    register = be.REGISTERS["control"]
    assert be.words_for(register, ["owner_id", "owner", "next_audit_date", "next_maintenance_date"]) == [
        "owner", "next test date", "next maintenance date",
    ]


# ========================================================================= runner ===
class FakeDB:
    """``get`` serves users and lookup values (counting each fetch); ``scalars`` serves
    the records asked for; ``flush`` is a no-op."""

    def __init__(self, records, *, people=None, lookups=None):
        self.records, self.people, self.lookups = records, people or {}, lookups or {}
        self.gets = 0
        self.flushed = False

    async def get(self, model, key):
        self.gets += 1
        if model is User:
            return self.people.get(key)
        if model is Lookup:
            return self.lookups.get(key)
        return None

    async def scalars(self, stmt, *a, **k):
        return SimpleNamespace(all=lambda: list(self.records))

    async def flush(self):
        self.flushed = True


def _user(perms=("issue:read", "issue:write"), tenant=None):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant or uuid.uuid4(), email="u@x", permission_codes=list(perms))


def _issue(tenant, **kw):
    base = dict(id=uuid.uuid4(), tenant_id=tenant, reference="ISS-1", title="Gap", deleted=False,
                status=IssueStatus2.open, owner_id=None, owner="", category_id=None, category="")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def audited(monkeypatch):
    rows = []

    async def record(db, **kw):
        rows.append(kw)

    monkeypatch.setattr(be.audit, "record", record)
    return rows


async def test_bulk_edit_needs_the_module_write_permission(audited):
    user = _user(perms=("issue:read",))
    with pytest.raises(HTTPException) as exc:
        await be.run(FakeDB([]), user, "issue", [uuid.uuid4()], {"status": "in_progress"})
    assert exc.value.status_code == 403
    assert not audited


async def test_bulk_edit_updates_live_rows_and_says_why_it_skipped_the_rest(audited):
    tenant = uuid.uuid4()
    user = _user(tenant=tenant)
    person = uuid.uuid4()
    people = {person: SimpleNamespace(id=person, is_active=True, full_name="Ayesha Khan", email="a@x")}
    a = _issue(tenant, reference="ISS-1")
    b = _issue(tenant, reference="ISS-2")
    same = _issue(tenant, reference="ISS-3", owner_id=person, owner="Ayesha Khan")
    gone = _issue(tenant, reference="ISS-4", deleted=True)
    foreign = _issue(uuid.uuid4(), reference="X-1")
    missing = uuid.uuid4()
    db = FakeDB([a, b, same, gone, foreign], people=people)
    ids = [b.id, missing, a.id, same.id, gone.id, foreign.id]
    result = await be.run(db, user, "issue", ids, {"owner_id": person})

    assert [r.id for r in result.results] == ids  # in the order asked
    outcome = {r.id: (r.outcome, r.reason) for r in result.results}
    assert outcome[a.id] == outcome[b.id] == ("updated", "")
    assert outcome[same.id] == ("skipped", "no change")
    assert outcome[gone.id] == ("skipped", "archived")
    assert outcome[missing] == outcome[foreign.id] == ("skipped", "not found")
    assert result.summary == "Updated 2; 4 skipped: 2 not found, 1 no change, 1 archived"
    assert (a.owner_id, a.owner) == (person, "Ayesha Khan")
    assert foreign.owner_id is None and gone.owner_id is None  # never touched
    # Checked once for the batch, not once per record.
    assert db.gets == 2  # master_data.check_user + the label (identity-map hit in a real session)
    # One audit entry per record changed, all with this run's batch id.
    assert [row["entity_id"] for row in audited] == [b.id, a.id]
    assert {row["changes"]["batch_id"] for row in audited} == {result.batch_id}
    assert all(row["action"] == "update" and row["entity_type"] == "issue" for row in audited)
    assert audited[0]["changes"]["fields"]["owner_id"] == {"from": None, "to": str(person)}
    assert "owner → Ayesha Khan" in audited[0]["summary"]
    assert db.flushed


async def test_a_bad_value_is_refused_before_any_record_is_touched(audited):
    tenant = uuid.uuid4()
    user = _user(tenant=tenant)
    wrong_list = uuid.uuid4()
    lookups = {wrong_list: SimpleNamespace(id=wrong_list, key="risk_category", active=True, label="Fraud")}
    rec = _issue(tenant)
    with pytest.raises(HTTPException) as exc:
        await be.run(FakeDB([rec], lookups=lookups), user, "issue", [rec.id], {"category_id": wrong_list})
    assert exc.value.status_code == 422 and exc.value.detail.startswith("category_id")
    assert rec.category_id is None and not audited
    with pytest.raises(HTTPException) as exc:
        await be.run(FakeDB([rec]), user, "issue", [rec.id], {"status": "closed"})
    assert exc.value.status_code == 422 and not audited


async def test_issue_status_in_bulk_skips_closed_issues(audited):
    tenant = uuid.uuid4()
    user = _user(tenant=tenant)
    live, closed = _issue(tenant), _issue(tenant, status=IssueStatus2.closed)
    result = await be.run(FakeDB([live, closed]), user, "issue", [live.id, closed.id], {"status": "in_progress"})
    assert live.status == IssueStatus2.in_progress and closed.status == IssueStatus2.closed
    assert result.summary == "Updated 1; 1 skipped: closed — reopen it from the issue itself"


def test_fields_menu_follows_the_permission():
    reader = _user(perms=("control:read",))
    menu = be.fields_for(reader, "control")
    assert menu.can_edit is False and menu.noun == "controls"
    labels = {f.key: f.label for f in menu.fields}
    assert labels["next_review_date"] == "Next test date" and labels["category_id"] == "Classification"
    status = next(f for f in menu.fields if f.key == "status")
    assert [o.value for o in status.options] == ["planned", "implemented", "operational", "retired"]
    assert be.fields_for(_user(perms=("control:read", "control:write")), "control").can_edit is True
    with pytest.raises(HTTPException) as exc:
        be.fields_for(_user(perms=()), "control")
    assert exc.value.status_code == 403
