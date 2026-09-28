"""Maker-checker gaps a bank is audited on (SBP: maker-checker on approvals and master data).

Pins three things:

1. **One rule set for create, edit and import** (``services.lifecycle_gates``): a policy
   is never created approved or published, a risk never created or edited to accepted, an
   access review never created completed, an exception never edited to approved — while
   an import row the import gate let through still carries its state. Records created in
   a decision state get the dates the decision path would give them (a closed finding's
   closed date, an incident's detection / containment / resolution stamps).
2. **Delegation-of-authority limits** (``services.authority_limits``): with no matrix
   lines a decision is unrestricted; with lines, only a role whose band covers the amount
   may approve, a governed decision with no amount is refused, and an amount in another
   currency is converted (or refused when there is no rate).
3. **Maker and checker roles** (``dual_control.role_gate_refusal``): a rule's role binds
   only while another active user holds it, so a vacated role never locks anyone out.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.enums import AuditFindingStatus, IncidentStatus
from app.services import authority_limits as al
from app.services import dual_control as dc
from app.services import fx
from app.services import incident_clock as clock
from app.services import lifecycle_gates as lg


# ============================================================ 1. lifecycle gates ===
@pytest.mark.parametrize("state", ["under_review", "approved", "published"])
def test_a_policy_is_never_created_in_a_decision_state(state):
    refusal = lg.create_refusal("policy", {"status": state})
    assert refusal and "starts as draft" in refusal
    with pytest.raises(HTTPException) as exc:
        lg.enforce_create("policy", {"status": state})
    assert exc.value.status_code == 422


def test_draft_and_retired_policies_may_be_created():
    assert lg.create_refusal("policy", {"status": "draft"}) is None
    assert lg.create_refusal("policy", {"status": "retired"}) is None


def test_an_import_row_the_gate_let_through_keeps_its_state():
    with lg.import_decided():
        assert lg.create_refusal("policy", {"status": "published"}) is None
        assert lg.create_refusal("risk", {"status": "accepted"}) is None
    # ... and only inside the import.
    assert lg.create_refusal("risk", {"status": "accepted"})


def test_a_risk_is_accepted_only_through_the_acceptance_flow():
    assert "risk:accept" in lg.create_refusal("risk", {"status": "accepted"})
    refusal = lg.edit_refusal("risk", SimpleNamespace(status="assessed"), {"status": "accepted"})
    assert refusal and "not by editing" in refusal
    # Echoing the stored value back, and moving out of it, pass.
    assert lg.edit_refusal("risk", SimpleNamespace(status="accepted"), {"status": "accepted"}) is None
    assert lg.edit_refusal("risk", SimpleNamespace(status="accepted"), {"status": "assessed"}) is None
    assert lg.edit_refusal("risk", SimpleNamespace(status="draft"), {"title": "x"}) is None


def test_an_access_review_is_completed_only_by_complete_review():
    assert lg.create_refusal("access_review", {"status": "completed"})
    assert lg.create_refusal("access_review", {"status": "in_progress"}) is None
    refusal = lg.edit_refusal("access_review", {"status": "in_progress"}, {"status": "completed"})
    assert refusal and refusal.startswith("An access review") and "Complete review" in refusal


@pytest.mark.parametrize("state", ["approved", "rejected", "expired"])
def test_an_exception_is_decided_only_by_its_decision(state):
    assert lg.edit_refusal("exception", SimpleNamespace(status="pending"), {"status": state})
    assert lg.edit_refusal("exception", SimpleNamespace(status="pending"), {"status": "closed"}) is None


def test_the_policy_edit_wording_is_kept():
    from app.api.v1.policies import status_edit_refusal
    from app.models.enums import PolicyStatus as P

    assert "Publish" in status_edit_refusal(P.draft, P.published)
    assert status_edit_refusal(P.draft, P.retired) is None


def test_create_edit_and_import_read_the_same_rule_objects():
    from app.services.import_registry import REGISTRY

    assert lg.POLICY_STATUS in REGISTRY["policies"].state_rules
    assert lg.RISK_STATUS in REGISTRY["risks"].state_rules
    assert lg.ISSUE_STATUS in REGISTRY["issues"].state_rules
    assert lg.ACCESS_REVIEW_STATUS in REGISTRY["access-reviews"].state_rules


def test_an_import_never_carries_an_access_review_completion():
    from app.services.import_registry import ImportGate

    gate = ImportGate(((lg.ACCESS_REVIEW_STATUS, ""),))  # even for an importer who may
    payload = {"status": "completed"}
    warnings = gate.apply(payload)
    assert payload["status"] == "draft" and warnings


def test_a_finding_logged_resolved_is_dated_like_a_closed_one():
    from app.api.v1.internal_audit import stamp_new_finding

    today = date(2026, 9, 25)
    data = {"status": AuditFindingStatus.closed, "closed_date": None}
    stamp_new_finding(data, today)
    assert data["closed_date"] == today
    data = {"status": AuditFindingStatus.risk_accepted, "closed_date": date(2026, 1, 3)}
    stamp_new_finding(data, today)
    assert data["closed_date"] == date(2026, 1, 3)  # the row's own date is kept
    data = {"status": AuditFindingStatus.open, "closed_date": date(2026, 1, 3)}
    stamp_new_finding(data, today)
    assert data["closed_date"] is None


def test_a_new_incident_gets_the_stamps_a_status_move_gives():
    now = datetime(2026, 9, 25, 10, tzinfo=timezone.utc)
    blank = {f: None for f in clock.TIMELINE_FIELDS}
    assert clock.creation_stamps(IncidentStatus.open, blank, now) == {"detected_at": now}
    closed = clock.creation_stamps(IncidentStatus.closed, blank, now)
    assert closed == {"detected_at": now, "resolved_at": now}
    contained = clock.creation_stamps(IncidentStatus.contained, {**blank, "detected_at": now}, now)
    assert contained == {"contained_at": now}  # a given detection time is kept


def test_an_exceptions_business_status_follows_its_approval():
    from app.services.record_workflow import synced_business_status as sync

    assert sync("exceptions", "pending", "approved") == "approved"
    assert sync("exceptions", "approved", "draft") == "pending"  # revised: re-approve
    assert sync("exceptions", "rejected", "approved") is None
    assert sync("exceptions", "pending", "in_review") is None


# ======================================================== 2. authority limits ===
LINES = [
    dc.MandateLine("DOA-1", "Risk Manager", 1, 0, 1_000_000, "PKR"),
    dc.MandateLine("DOA-2", "CRO", 2, 1_000_000, None, "PKR"),
]


@pytest.fixture
def matrix(monkeypatch):
    """Authority lines and exchange rates without a database."""
    state = {"lines": list(LINES)}

    async def _lines(db, category):
        return state["lines"]

    async def _reporting(db, tenant_id=None):
        return "PKR"

    async def _book(db, tenant_id=None, reporting=None):
        return fx.RateBook("PKR", [("USD", date(2026, 1, 1), 280)])

    monkeypatch.setattr(dc, "authority_lines", _lines)
    monkeypatch.setattr(fx, "reporting_currency", _reporting)
    monkeypatch.setattr(fx, "load_rate_book", _book)
    return state


def _who(*roles):
    return SimpleNamespace(role_names=list(roles), tenant_id=None, id=None)


def _subject(amount, currency="PKR", entity_type="loss_event"):
    return al.Subject(entity_type, al.CATEGORIES[entity_type], amount, currency, "gross loss")


async def test_no_lines_means_no_restriction(matrix):
    matrix["lines"] = []
    v = await al.verdict(None, _subject(9_000_000_000), _who())
    assert v.allowed and not v.governed


async def test_a_role_approves_within_its_band_only(matrix):
    assert (await al.verdict(None, _subject(500_000), _who("risk manager"))).allowed
    v = await al.verdict(None, _subject(5_000_000), _who("Risk Manager"))
    assert not v.allowed and "CRO" in v.reason and "signing off this loss event" in v.reason
    assert (await al.verdict(None, _subject(5_000_000), _who("CRO"))).allowed


async def test_a_governed_decision_without_an_amount_is_refused(matrix):
    v = await al.verdict(None, _subject(None, entity_type="outsourcing_arrangement"), _who("CRO"))
    assert not v.allowed and "contract value" in v.reason


async def test_a_foreign_amount_is_converted_before_the_check(matrix):
    # USD 10,000 at 280 = PKR 2.8M: above the Risk Manager's band.
    v = await al.verdict(None, _subject(10_000, "USD"), _who("Risk Manager"))
    assert not v.allowed and v.compared_amount == pytest.approx(2_800_000)
    # No rate for EUR: it cannot be compared with the mandate, so it is not within it.
    v = await al.verdict(None, _subject(10, "EUR"), _who("CRO"))
    assert not v.allowed and "exchange rate" in v.reason


async def test_enforce_raises_403_and_skips_ungoverned_types(matrix):
    loss = SimpleNamespace(gross_loss=5_000_000, currency="PKR", tenant_id=None)
    with pytest.raises(HTTPException) as exc:
        await al.enforce(None, "loss_event", loss, _who("Risk Manager"))
    assert exc.value.status_code == 403
    await al.enforce(None, "loss_event", loss, _who("CRO"))
    await al.enforce(None, "risk", SimpleNamespace(), _who())  # not a governed decision


async def test_an_acceptance_request_never_understates_a_quantified_exposure(monkeypatch, matrix):
    async def _quantified(db, risk):
        return 2_000_000.0, "PKR", "annual loss expectancy on the risk"

    monkeypatch.setattr(al, "risk_exposure", _quantified)
    risk = SimpleNamespace(tenant_id=None)
    assert (await al.acceptance_exposure(None, risk, 10.0))[0] == 2_000_000.0
    amount, _cur, basis = await al.acceptance_exposure(None, risk, 3_000_000.0)
    assert amount == 3_000_000.0 and "request" in basis

    async def _none(db, risk):
        return None, "", ""

    monkeypatch.setattr(al, "risk_exposure", _none)
    assert (await al.acceptance_exposure(None, risk, 750.0))[:2] == (750.0, "PKR")


# ===================================================== 3. maker/checker roles ===
def test_a_checker_role_binds_while_someone_else_holds_it():
    refusal = dc.role_gate_refusal("Risk Approver", ["Risk Manager"], available=1,
                                   step="checking this decision", reference="DCR-7")
    assert refusal and "Risk Approver" in refusal and "DCR-7" in refusal
    assert dc.role_gate_refusal("Risk Approver", [" risk  approver "], available=1, step="x") is None


def test_a_vacant_role_falls_back_to_anyone_who_may_decide():
    assert dc.role_gate_refusal("Risk Approver", ["Admin"], available=0, step="x") is None
    assert dc.role_gate_refusal("", ["Admin"], available=3, step="x") is None


def test_available_checkers_need_the_decisions_permission():
    assert dc.checker_permission("risk", "accept") == "risk:accept"
    assert dc.checker_permission("exception", "approve") == "exception:approve"
    assert dc.checker_permission("loss_event", "approve") in ("oprisk:approve", "workflow:approve")
    assert dc.checker_permission("capital_calculation", "reopen") == "scenario:write"
    assert dc.is_enforced_key("capital_calculation", "reopen")


async def test_the_finaliser_cannot_reopen_a_final_capital_figure(monkeypatch):
    from app.api.v1 import scenario

    async def _required(db, module, action, amount=None):
        return True, None

    monkeypatch.setattr(dc, "dual_control_required", _required)
    calc = SimpleNamespace(final_by="maker@bank.pk", final_orc=1_000_000)
    with pytest.raises(HTTPException) as exc:
        await scenario._check_reopen_four_eyes(None, calc, SimpleNamespace(email="Maker@Bank.pk", id=None))
    assert exc.value.status_code == 403 and "someone else must reopen" in exc.value.detail
