"""Decision 9 (2026-09-20): the attestation is the record owner's own certification.

Together with decision 6 (only an approved record can be attested) the old rules left
nobody able to attest: in a bank the first-line owner usually also entered the record, so
the owner refusal and the maker-checker default between them refused everyone. Market
practice — ServiceNow IRM attestation campaigns, Archer, SOX 302/404 certification,
ISO 27001 A.5.36 — is that the owner certifies and independence comes from the approval
and from a second signature.

Pinned here:

* the owner may attest; anyone else who may write the record may attest *on behalf of*
  the owner, and the row and the audit trail say so;
* four-eyes on ``(<type>, attest)`` applies only where an administrator configured it —
  no fall-back to the global segregation-of-duties switch, and no default rule;
* the second signature is **required** on a key control, a critical or high residual
  risk, a material outsourcing arrangement or third party, and every policy; optional
  everywhere else;
* the review clock resets only when the attestation is complete — on signing where no
  second signature is needed, on the confirmation where one is, and anchored to the date
  it was signed;
* **B10c**: a record already in force before the approval lifecycle existed is approved
  on upgrade, once, and never one with an approval history or a draft-equivalent status.

No database: the pure rules are called directly and the endpoints run against the
fake-session pattern of ``test_record_page_backend_a``.
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
from app.models.attestation import Attestation
from app.models.base import WorkflowState
from app.models.control import Control
from app.models.enums import ControlStatus, PolicyStatus, ReviewFrequency, RiskStatus, VendorStatus
from app.models.outsourcing import OutsourcingArrangement, OutsourcingMateriality, OutsourcingStatus
from app.models.policy import Policy
from app.models.risk import Risk
from app.models.vendor import Vendor
from app.schemas.attestation import AttestationCreate
from app.services import audit, default_governance as gov

pytestmark = pytest.mark.asyncio

ME = uuid.uuid4()
OWNER = uuid.uuid4()
TENANT = uuid.uuid4()
TODAY = date.today()


def _user(*perms, uid=ME, email="me@bank.pk"):
    return SimpleNamespace(id=uid, tenant_id=TENANT, email=email, permission_codes=list(perms))


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeDB:
    """Answers by the table a statement reads: the record, its attestation history, the
    maker from the audit trail and the (absent) dual-control rule."""

    def __init__(self, record=None, maker=None, rule=None, history=(), owner=None):
        self.record = record
        self.maker = maker
        self.rule = rule
        self.history = list(history)
        self.owner = owner
        self.added: list = []

    async def get(self, model, _id):
        from app.models.identity import User

        if model is User:
            return self.owner
        if isinstance(self.record, model):
            return self.record
        if isinstance(_id, uuid.UUID):
            return next((r for r in self.history if isinstance(r, model) and r.id == _id), None)
        return None

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


def _attestation(**kw):
    """An attestation row as the database would hold it (column defaults apply on insert,
    so a hand-built row fills them itself)."""
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, attested_by_email="", comment="", statement="",
        scope="", on_behalf_of_name="", confirmation_required=False,
        frequency=ReviewFrequency.annual,
    )
    base.update(kw)
    row = Attestation(**base)
    row.created_at = datetime.now(timezone.utc)
    return row


def _risk(**kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, title="Ransomware", reference="R-002",
        status=RiskStatus.assessed, workflow_status=WorkflowState.approved, owner_id=OWNER,
        inherent_likelihood=5, inherent_impact=5, residual_likelihood=5, residual_impact=5,
        review_frequency=ReviewFrequency.annual, next_review_date=TODAY + timedelta(days=30),
        last_assessed_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return Risk(**base)


def _control(**kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, name="Multi-factor authentication",
        reference="A.8.5", status=ControlStatus.operational,
        workflow_status=WorkflowState.approved, is_key=False,
    )
    base.update(kw)
    return Control(**base)


def _policy(**kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, title="Acceptable use", reference="POL-001",
        status=PolicyStatus.published, workflow_status=WorkflowState.approved, owner_id=OWNER,
        review_frequency=ReviewFrequency.annual, next_review_date=TODAY + timedelta(days=30),
    )
    base.update(kw)
    return Policy(**base)


def _arrangement(materiality=OutsourcingMateriality.material, status=OutsourcingStatus.active):
    return OutsourcingArrangement(
        id=uuid.uuid4(), tenant_id=TENANT, title="Core banking hosting",
        materiality=materiality, status=status,
    )


def _vendor(arrangements=(), **kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=TENANT, name="Amazon Web Services",
        status=VendorStatus.active, workflow_status=WorkflowState.approved,
        relationship_owner_id=OWNER, review_frequency=ReviewFrequency.annual,
        next_review_date=TODAY + timedelta(days=30),
    )
    base.update(kw)
    vendor = Vendor(**base)
    vendor.outsourcing_arrangements = list(arrangements)
    return vendor


# ============================================== the owner is the expected signer ===
async def test_the_owner_may_attest_their_own_record(sod_on):
    risk = _risk(owner_id=ME)
    assert await att.attest_eligibility(
        FakeDB(maker=ME), _user("risk:write"), "risk", risk.id, risk
    ) == (True, None)


async def test_a_reader_still_cannot_attest(sod_on):
    """The permission gate is unchanged: attesting needs the module's write permission."""
    risk = _risk(owner_id=ME)
    ok, why = await att.attest_eligibility(FakeDB(), _user("risk:read"), "risk", risk.id, risk)
    assert (ok, why) == (False, "You don't have permission to attest risk records.")


async def test_someone_else_attests_on_behalf_of_the_owner(sod_on, audited):
    from app.models.identity import User

    owner = User(id=OWNER, tenant_id=TENANT, email="ayesha@bank.pk", full_name="Ayesha Siddiqui")
    policy = _policy(owner_id=OWNER)
    db = FakeDB(record=policy, owner=owner)
    row = await att.record_attestation(db, _user("policy:write"), "policy", policy.id, policy)
    assert (row.on_behalf_of_id, row.on_behalf_of_name) == (OWNER, "Ayesha Siddiqui")
    assert att.on_behalf_of_text(row) == "attested by me@bank.pk on behalf of Ayesha Siddiqui"
    assert "on behalf of Ayesha Siddiqui" in audited[-1]["summary"]
    assert audited[-1]["changes"]["on_behalf_of"] == "Ayesha Siddiqui"


async def test_the_owner_signing_stands_in_for_nobody(sod_on, audited):
    policy = _policy(owner_id=ME)
    row = await att.record_attestation(FakeDB(record=policy), _user("policy:write"), "policy", policy.id, policy)
    assert (row.on_behalf_of_id, row.on_behalf_of_name) == (None, "")
    assert att.on_behalf_of_text(row) is None
    assert "on behalf of" not in audited[-1]["summary"]


# ================================================== the required second signature ===
@pytest.mark.parametrize("is_key,expected", [(True, att.KEY_CONTROL_REASON), (False, None)])
async def test_only_a_key_control_needs_a_second_signature(is_key, expected):
    control = _control(is_key=is_key)
    assert await att.second_signature_required(FakeDB(), _user(), "control", control) == expected


@pytest.mark.parametrize("likelihood,impact,expected", [
    (5, 5, att.HIGH_RISK_REASON),   # critical
    (4, 4, att.HIGH_RISK_REASON),   # high
    (1, 1, None),                   # low
])
async def test_a_critical_or_high_residual_risk_needs_a_second_signature(likelihood, impact, expected):
    risk = _risk(residual_likelihood=likelihood, residual_impact=impact)
    assert await att.second_signature_required(FakeDB(), _user(), "risk", risk) == expected


async def test_an_unscored_risk_needs_none():
    """A draft nobody scored has no band, so nothing makes it high-stakes."""
    risk = _risk(status=RiskStatus.draft, last_assessed_at=None)
    assert await att.second_signature_required(FakeDB(), _user(), "risk", risk) is None


async def test_only_a_material_live_outsourcing_third_party_needs_one():
    material = _vendor(arrangements=[_arrangement()])
    assert await att.second_signature_required(
        FakeDB(), _user(), "vendor", material
    ) == att.MATERIAL_OUTSOURCING_REASON
    non_material = _vendor(arrangements=[_arrangement(materiality=OutsourcingMateriality.non_material)])
    assert await att.second_signature_required(FakeDB(), _user(), "vendor", non_material) is None
    terminated = _vendor(arrangements=[_arrangement(status=OutsourcingStatus.terminated)])
    assert await att.second_signature_required(FakeDB(), _user(), "vendor", terminated) is None
    assert await att.second_signature_required(FakeDB(), _user(), "vendor", _vendor()) is None


async def test_the_arrangement_itself_counts_like_the_third_party_holding_it():
    assert await att.second_signature_required(
        FakeDB(), _user(), "outsourcing_arrangement", _arrangement()
    ) == att.MATERIAL_OUTSOURCING_REASON


async def test_every_policy_needs_a_second_signature():
    assert await att.second_signature_required(FakeDB(), _user(), "policy", _policy()) == att.POLICY_REASON


async def test_other_record_types_do_not():
    assert att.high_stakes_reason("asset", SimpleNamespace(name="Core banking database")) is None
    assert att.high_stakes_reason("incident", SimpleNamespace(reference="INC-007")) is None
    assert att.high_stakes_reason("control", None) is None


# ======================================================== one clock, when complete ===
async def test_a_required_signature_holds_the_review_clock(sod_on, audited):
    """The policy's own review dates do not move on signing: the certification is not
    complete until someone else confirms it."""
    policy = _policy(owner_id=ME)
    before = policy.next_review_date
    row = await att.record_attestation(FakeDB(record=policy), _user("policy:write"), "policy", policy.id, policy)
    assert row.confirmation_required is True
    assert policy.next_review_date == before
    assert getattr(policy, "last_review_date", None) is None
    assert "awaiting independent confirmation" in audited[-1]["summary"]


async def test_an_optional_signature_moves_the_clock_at_once(sod_on, audited):
    risk = _risk(owner_id=ME, residual_likelihood=1, residual_impact=1)
    row = await att.record_attestation(FakeDB(record=risk), _user("risk:write"), "risk", risk.id, risk)
    assert row.confirmation_required is False
    assert risk.next_review_date == row.next_due and risk.last_review_date == TODAY


async def test_the_confirmation_completes_it_and_dates_it_from_the_signature(sod_on, audited):
    policy = _policy(owner_id=OWNER)
    signed = TODAY - timedelta(days=3)
    row = _attestation(
        entity_type="policy", entity_id=policy.id, attested_by_id=OWNER,
        attested_by_email="ayesha@bank.pk", attested_at=signed,
        next_due=signed + timedelta(days=365), confirmation_required=True,
    )
    db = FakeDB(record=policy, history=[row])
    body = await att.confirm(row.id, db, _user("policy:read", "policy:write"))
    assert (row.confirmed_by_id, row.confirmed_at) == (ME, TODAY)
    # Anchored to the day it was certified, not to today.
    assert policy.last_review_date == signed and policy.next_review_date == row.next_due
    assert body.status == "current" and body.awaiting_confirmation is False
    assert audited[-1]["changes"]["last_review_date"] == str(signed)


async def test_a_later_attestation_is_not_pulled_back_by_an_old_confirmation():
    policy = _policy()
    policy.next_review_date = TODAY + timedelta(days=300)
    assert att.move_review_clock("policy", policy, TODAY - timedelta(days=400), TODAY - timedelta(days=35)) == {}
    assert policy.next_review_date == TODAY + timedelta(days=300)


async def test_the_read_says_what_is_waiting_and_leaves_the_status_alone(sod_on):
    policy = _policy(owner_id=OWNER)
    row = _attestation(
        entity_type="policy", entity_id=policy.id, attested_by_id=OWNER,
        attested_by_email="ayesha@bank.pk", attested_at=TODAY,
        next_due=TODAY + timedelta(days=365), confirmation_required=True,
    )
    body = await att.get_status(
        "policy", policy.id, FakeDB(record=policy, history=[row]), _user("policy:read", "policy:write")
    )
    assert body.awaiting_confirmation is True
    assert (body.awaiting_by, body.awaiting_at) == ("ayesha@bank.pk", TODAY)
    assert body.confirmation_required is True and body.confirmation_reason == att.POLICY_REASON
    # Nothing complete yet, so the record has never been attested.
    assert (body.status, body.last_attested_at) == ("never", None)


def test_completeness_is_one_rule():
    signed = SimpleNamespace(confirmation_required=True, confirmed_by_id=None)
    confirmed = SimpleNamespace(confirmation_required=True, confirmed_by_id=ME)
    optional = SimpleNamespace(confirmation_required=False, confirmed_by_id=None)
    assert [att.is_complete(r) for r in (signed, confirmed, optional)] == [False, True, True]
    assert att.awaiting_second_signature([signed]) is signed
    # A later, complete attestation supersedes an older one that was never confirmed.
    assert att.awaiting_second_signature([optional, signed]) is None


# ================================================ maker-checker only if configured ===
def _rule(**kw):
    from app.models.authority import DualControlStatus

    base = dict(enabled=True, status=DualControlStatus.active, requires_dual_control=True,
                threshold_amount=None)
    base.update(kw)
    return SimpleNamespace(**base)


async def test_attesting_no_longer_falls_back_to_the_global_switch(sod_on):
    assert await att.attest_dual_control_rule(FakeDB(), "risk") is None
    risk = _risk()
    assert await att.attest_eligibility(
        FakeDB(maker=ME), _user("risk:write"), "risk", risk.id, risk
    ) == (True, None)


async def test_a_configured_rule_still_refuses_whoever_entered_the_record(sod_on):
    risk = _risk()
    with pytest.raises(HTTPException) as exc:
        await att.attest(
            "risk", risk.id, AttestationCreate(),
            FakeDB(record=risk, maker=ME, rule=_rule()), _user("risk:write"),
        )
    assert exc.value.status_code == 403


def test_no_organisation_is_seeded_an_attest_rule():
    assert [r for r in gov.DEFAULT_RULES if r.action == "attest"] == []
    # The boot repair adds only what DEFAULT_RULES lists, so it cannot re-create one.
    assert [r for r in gov.rules_to_add([]) if r.action == "attest"] == []


# ========================================= My Work: the signature that completes it ===
class WorkDB:
    """Returns the queued results in order and keeps every statement, so the filters can
    be read back off the compiled SQL."""

    def __init__(self, *results):
        self.results = list(results)
        self.statements: list = []

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        return _Rows(self.results.pop(0) if self.results else [])

    def sql(self, i=0):
        from sqlalchemy.dialects import postgresql

        return str(self.statements[i].compile(dialect=postgresql.dialect())).replace("\n", " ")


def _work_ctx(*perms):
    from app.services import my_work as mw

    return mw.Ctx(
        user_id=ME, email="me@bank.pk", permissions=set(perms), role_names=set(), role_ids=set(),
        today=TODAY, horizon=TODAY + timedelta(days=14), directory=None, modules_off=set(),
    )


async def test_my_work_asks_someone_else_for_the_second_signature():
    from app.services import my_work as mw

    policy_id = uuid.uuid4()
    signed = TODAY - timedelta(days=2)
    pending = SimpleNamespace(
        id=uuid.uuid4(), entity_type="policy", entity_id=policy_id, attested_at=signed,
        attested_by_email="ayesha@bank.pk",
    )
    db = WorkDB([pending], [(policy_id, "POL-001", "Acceptable use", WorkflowState.approved)])
    items = await mw.attestations_to_confirm(db, _work_ctx("policy:write"))
    assert len(items) == 1
    item = items[0]
    assert (item.kind, item.entity_type, item.entity_id) == ("attestation_confirm", "policy", policy_id)
    assert item.title == "Acceptable use" and item.reference == "POL-001"
    assert item.due_date == signed + timedelta(days=mw.CONFIRM_DAYS)
    assert "ayesha@bank.pk" in item.subtitle and "confirm it" in item.subtitle
    # Only attestations that need a signature, that nobody has given, and that I did not sign.
    sql = db.sql(0)
    assert "attestations.confirmation_required IS true" in sql
    assert "attestations.confirmed_by_id IS NULL" in sql
    assert "attestations.attested_by_id IS NULL OR attestations.attested_by_id !=" in sql


async def test_a_certified_record_still_owes_its_review_until_it_is_confirmed():
    """My Work keeps listing it — the review is not complete — but stops asking for an
    attestation that has already been made."""
    from app.services import my_work as mw

    policy_id = uuid.uuid4()
    due = TODAY - timedelta(days=3)
    db = WorkDB(
        [(policy_id, "POL-001", "Acceptable use", due, WorkflowState.approved)],
        [],  # vendors
        [],  # assets
        [],  # every other attested type
        [("policy", policy_id)],  # awaiting its second signature
    )
    items = await mw.my_attestations(db, _work_ctx("policy:write"))
    assert [i.subtitle for i in items] == ["Attested — awaiting independent confirmation"]


def test_only_a_complete_attestation_stops_the_review_reminders():
    """My Work's and the alert sweep's "latest attestation" both mean the latest
    *complete* one, so a pending signature does not silence the review it owes."""
    from sqlalchemy.dialects import postgresql
    from app.services import my_work as mw

    sql = str(mw.complete_attestation().compile(dialect=postgresql.dialect()))
    assert "confirmation_required IS false" in sql and "confirmed_by_id IS NOT NULL" in sql


async def test_my_work_skips_records_i_cannot_write_or_that_are_retired():
    from app.services import my_work as mw

    policy_id = uuid.uuid4()
    pending = SimpleNamespace(
        id=uuid.uuid4(), entity_type="policy", entity_id=policy_id, attested_at=TODAY,
        attested_by_email="ayesha@bank.pk",
    )
    rows = [(policy_id, "POL-001", "Acceptable use", WorkflowState.retired)]
    assert await mw.attestations_to_confirm(WorkDB([pending], rows), _work_ctx("policy:write")) == []
    assert await mw.attestations_to_confirm(WorkDB([pending], rows), _work_ctx("policy:read")) == []


# ============================ B10c: records that predate the approval lifecycle ===
def test_the_live_states_are_the_ones_that_mean_in_force():
    """Never a draft equivalent, and never a state the record was never live in."""
    assert dr.LIVE_BUSINESS_STATUSES["policy"] == ("approved", "published")
    for draft_ish in ("draft", "under_review"):
        assert draft_ish not in dr.LIVE_BUSINESS_STATUSES["policy"]
    assert "planned" not in dr.LIVE_BUSINESS_STATUSES["control"]
    assert "draft" not in dr.LIVE_BUSINESS_STATUSES["risk"]
    assert "prospective" not in dr.LIVE_BUSINESS_STATUSES["vendor"]
    assert "open" not in dr.LIVE_BUSINESS_STATUSES["incident"]
    # A retired policy or control is no longer in force: it owes no attestation.
    assert "retired" not in dr.LIVE_BUSINESS_STATUSES["policy"] + dr.LIVE_BUSINESS_STATUSES["control"]


def test_every_grandfathered_type_builds_a_query_over_its_own_enum():
    from app.services import record_registry

    for entity_type, wanted in dr.LIVE_BUSINESS_STATUSES.items():
        model = record_registry.model_for(entity_type)
        assert model is not None, entity_type
        statuses = dr._enum_values(model.__table__.c["status"], wanted)
        assert [str(getattr(s, "value", s)) for s in statuses] == list(wanted), entity_type
        sql = str(dr.predated_approvals_query(model, entity_type))
        assert "workflow_status" in sql and "NOT (EXISTS" in sql


def test_the_query_asks_for_a_draft_approval_with_no_history():
    from app.models.policy import Policy as P

    sql = str(dr.predated_approvals_query(P, "policy")).replace("\n", " ")
    assert "policies.workflow_status = " in sql
    assert "audit_logs.action LIKE" in sql and "audit_logs.action !=" in sql
    assert "policies.deleted IS false" in sql


def test_the_audit_row_says_why_and_names_nobody():
    row = dr.predated_approval_audit("policy", "published")
    assert row["action"] == dr.IMPORT_ACTION
    assert row["summary"] == (
        "Approval recorded on upgrade: this policy was already published before the "
        "approval workflow existed, so it had no approval to complete"
    )
    assert row["changes"] == {"from": "draft", "to": "approved", "via": dr.PREDATES_VIA,
                              "business_status": "published"}


class RepairDB:
    """Answers each SELECT with the rows queued for the first table it names, and records
    the UPDATEs and audit rows the repair writes."""

    def __init__(self, rows: dict):
        self.rows = dict(rows)
        self.updates: list[str] = []
        self.added: list = []

    async def execute(self, stmt, *a, **k):
        sql = str(stmt).replace("\n", " ")
        if sql.startswith("UPDATE"):
            self.updates.append(sql)
            return None
        for table, rows in self.rows.items():
            if f"FROM {table}" in sql:
                return _Rows(rows)
        return _Rows([])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


async def test_the_repair_approves_each_candidate_once_and_audits_it():
    published = uuid.uuid4()
    db = RepairDB({"policies": [(published, PolicyStatus.published)]})
    assert await dr.approve_predated_records(db, TENANT) == 1
    assert len(db.updates) == 1 and "UPDATE policies" in db.updates[0]
    # The record's own last-updated time is untouched: recording history is not an edit.
    assert "updated_at=policies.updated_at" in db.updates[0].replace(" ", "")
    assert len(db.added) == 1
    entry = db.added[0]
    assert (entry.actor_id, entry.entity_type, entry.entity_id) == (None, "policy", published)
    assert entry.action == dr.IMPORT_ACTION
    assert entry.changes["via"] == dr.PREDATES_VIA

    # Idempotent: the row it wrote is an approval step, so the next start finds nothing.
    assert await dr.approve_predated_records(RepairDB({}), TENANT) == 0


async def test_the_repair_is_reported_and_counts_towards_any():
    report = dr.RepairReport()
    assert report.any() is False
    report.predated_approvals_recorded = 4
    assert report.any() is True
