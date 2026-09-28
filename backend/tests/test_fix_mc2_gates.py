"""Maker-checker, part 2: specialist-register sign-offs, the legacy maker-role repair,
and what My Work / the Approvals inbox offer.

No database. The rules are pure (``lifecycle_gates``, ``default_governance``,
``vuln_acceptance.request_refusal``); the async decisions run against stubs of the
dual-control lookups they make.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException

import app.models  # noqa: F401 - populate mappers
from app.api.v1 import outsourcing as outsourcing_api
from app.services import default_governance as governance
from app.services import dual_control, lifecycle_gates as lg, my_work, record_workflow, vuln_acceptance


# ------------------------------------------------ decision states are not edits ---
@pytest.mark.parametrize("entity_type, value", [
    ("risk_quantification", "approved"),
    ("shariah_ruling", "approved"),
    ("shariah_ruling", "under_review"),
    ("islamic_product", "approved"),
    ("model_inventory", "validated"),
    ("vuln_finding", "risk_accepted"),
    ("dpia", "approved"),
])
def test_a_sign_off_state_is_refused_on_create_and_edit(entity_type, value):
    assert lg.create_refusal(entity_type, {"status": value})
    stored = NS(status="draft", workflow_status="draft")
    assert lg.edit_refusal(entity_type, stored, {"status": value})
    # Echoing the stored value back (a form that saves every field) is not a move.
    assert lg.edit_refusal(entity_type, NS(status=value, workflow_status="approved"), {"status": value}) is None


def test_moving_out_of_a_sign_off_state_and_plain_data_states_pass():
    assert lg.edit_refusal("dpia", NS(status="approved", workflow_status="approved"), {"status": "in_progress"}) is None
    assert lg.edit_refusal("shariah_ruling", NS(status="approved", workflow_status="approved"),
                           {"status": "superseded"}) is None
    assert lg.edit_refusal("vuln_finding", NS(status="open", workflow_status="draft"), {"status": "remediated"}) is None
    assert lg.create_refusal("dpia", {"status": "completed"}) is None
    assert lg.create_refusal("model_inventory", {"status": "under_review"}) is None


def test_an_import_row_the_gate_decided_is_not_refused_again():
    with lg.import_decided():
        assert lg.create_refusal("dpia", {"status": "approved"}) is None
        assert lg.create_refusal("outsourcing_arrangement", {"status": "active"}) is None


# ----------------------------------------------------- live only once approved ---
@pytest.mark.parametrize("entity_type, value", [
    ("islamic_product", "active"),
    ("model_inventory", "in_production"),
    ("outsourcing_arrangement", "active"),
    ("outsourcing_arrangement", "under_review"),
])
def test_going_live_needs_the_approval_first(entity_type, value):
    assert "Submit it for review" in lg.create_refusal(entity_type, {"status": value})
    before = NS(status="proposed", workflow_status="in_review")
    assert "before" in lg.edit_refusal(entity_type, before, {"status": value})
    approved = NS(status="approved", workflow_status="approved")
    assert lg.edit_refusal(entity_type, approved, {"status": value}) is None
    # A record that went live before the rule keeps saving its status.
    legacy = NS(status=value, workflow_status="draft")
    assert lg.edit_refusal(entity_type, legacy, {"status": value}) is None


def test_the_forms_offer_only_the_values_a_save_may_write():
    assert lg.allowed_values("dpia", "status", None, None) == {"approved"}
    assert lg.allowed_values("dpia", "status", "approved", "approved") == set()
    assert lg.allowed_values("islamic_product", "status", "in_development", "draft") == {"approved", "active"}
    assert lg.allowed_values("islamic_product", "status", "approved", "approved") == set()
    assert lg.allowed_values("outsourcing_arrangement", "status", "proposed", "draft") == {"active", "under_review"}


# ------------------------------------------- the business status follows the decision ---
@pytest.mark.parametrize("table, current, state, expected", [
    ("dpias", "completed", "approved", "approved"),
    ("dpias", "in_progress", "approved", None),
    ("dpias", "approved", "draft", "completed"),
    ("risk_quantifications", "simulated", "approved", "approved"),
    ("risk_quantifications", "approved", "draft", "simulated"),
    ("shariah_rulings", "draft", "in_review", "under_review"),
    ("shariah_rulings", "under_review", "approved", "approved"),
    ("shariah_rulings", "under_review", "draft", "draft"),
    ("shariah_rulings", "approved", "retired", "superseded"),
    ("islamic_products", "in_development", "approved", "approved"),
    ("islamic_products", "active", "draft", None),  # a live product stays live
    ("islamic_products", "active", "retired", "withdrawn"),
    ("model_inventory", "development", "approved", "validated"),
    ("model_inventory", "under_review", "approved", "validated"),
    ("model_inventory", "in_production", "draft", None),
    ("model_inventory", "validated", "draft", "development"),
    ("outsourcing_arrangements", "proposed", "approved", None),  # approval is not go-live
])
def test_the_lifecycle_moves_the_business_status(table, current, state, expected):
    assert record_workflow.synced_business_status(table, current, state) == expected


def test_policies_and_exceptions_keep_their_own_sync():
    assert record_workflow.synced_business_status("policies", "draft", "in_review") == "under_review"
    assert record_workflow.synced_business_status("exceptions", "pending", "approved") == "approved"


# ------------------------------------------------------- what an approval needs ---
def _validation(outcome, status="completed", day=1, ref="VAL-1"):
    return NS(outcome=outcome, status=status, validation_date=date(2026, 9, day), reference=ref,
              created_at=datetime(2026, 9, day, tzinfo=timezone.utc))


def test_approval_preconditions():
    pre = lg.approval_precondition
    assert "simulation" in pre("risk_quantification", NS(status="draft", last_simulated=None))
    assert pre("risk_quantification", NS(status="simulated", last_simulated=date(2026, 9, 1))) is None
    assert "Complete the assessment" in pre("dpia", NS(status="in_progress"))
    assert pre("dpia", NS(status="completed")) is None and pre("dpia", NS(status="not_required")) is None
    assert "Link the Shariah ruling" in pre("islamic_product", NS(status="in_development", approving_ruling=None))
    draft_ruling = NS(status="draft", deleted=False, reference="SR-1", title="t")
    assert "not approved yet" in pre("islamic_product", NS(status="in_development", approving_ruling=draft_ruling))
    ok_ruling = NS(status="approved", deleted=False, reference="SR-1", title="t")
    assert pre("islamic_product", NS(status="in_development", approving_ruling=ok_ruling)) is None
    assert "completed independent validation" in pre("model_inventory", NS(status="development", validations=[]))
    failed_last = [_validation("pass", day=1), _validation("fail", day=5, ref="VAL-2")]
    assert "VAL-2" in pre("model_inventory", NS(status="development", validations=failed_last))
    passed_last = [_validation("fail", day=1), _validation("pass_with_findings", day=5),
                   _validation("fail", status="planned", day=9)]
    assert pre("model_inventory", NS(status="development", validations=passed_last)) is None
    # Undated validations order by entry time and never compare None with a date.
    undated = [_validation("pass", day=1), NS(outcome="fail", status="completed", validation_date=None,
                                                reference="VAL-3", created_at=datetime(2026, 9, 2, tzinfo=timezone.utc))]
    assert pre("model_inventory", NS(status="development", validations=undated)) is None
    assert pre("policy", NS(status="draft")) is None


def test_enforced_precondition_is_a_422():
    with pytest.raises(HTTPException) as exc:
        lg.enforce_approval_precondition("dpia", NS(status="required"))
    assert exc.value.status_code == 422


def test_only_checked_types_load_their_record():
    assert lg.approval_is_checked("dpia") and lg.approval_is_checked("outsourcing_arrangement")
    assert lg.approval_is_checked("exception") and not lg.approval_is_checked("policy")
    assert not lg.approval_is_checked(None)


# ------------------------------------------------------------ outsourcing: SBP NOC ---
def _facts(**over):
    base = {"status": "proposed", "materiality": "non_material", "materiality_assessment": "",
            "exit_plan": "", "substitutability": "", "sbp_approval_required": True,
            "sbp_approval_status": "pending"}
    return {**base, **over}


def test_an_arrangement_needing_sbp_approval_does_not_start_without_it():
    err = outsourcing_api.activation_error
    assert "SBP's approval" in err(_facts(), _facts(status="active"))
    assert err(_facts(), _facts(status="active", sbp_approval_status="approved")) is None
    assert err(_facts(), _facts(status="active", sbp_approval_required=False)) is None
    # Live before the rule, still awaiting SBP: editing it keeps working.
    live = _facts(status="active")
    assert err(live, {**live, "exit_plan": "x"}) is None


# ------------------------------------------------------ legacy maker-role repair ---
def _rule(**over):
    spec = governance.LEGACY_MAKER_ROLE_RULES[0]
    base = {"module": spec.module, "action": spec.action, "maker_role": spec.maker_role,
            "checker_role": spec.checker_role, "description": spec.description,
            "requires_dual_control": True, "threshold_amount": None}
    return {**base, **over}


def test_only_an_untouched_legacy_default_loses_its_maker_role():
    assert governance.is_untouched_legacy_maker_rule(_rule(), touched=False)
    assert not governance.is_untouched_legacy_maker_rule(_rule(), touched=True)
    for change in ({"description": "ours"}, {"checker_role": "CRO"}, {"threshold_amount": 100},
                   {"requires_dual_control": False}, {"maker_role": ""}, {"action": "bulk_archive"}):
        assert not governance.is_untouched_legacy_maker_rule(_rule(**change), touched=False), change
    exc_spec = governance.LEGACY_MAKER_ROLE_RULES[2]
    assert governance.is_untouched_legacy_maker_rule(
        _rule(module=exc_spec.module, action=exc_spec.action, description=exc_spec.description), touched=False)


def test_the_new_defaults_name_no_maker_role_where_the_first_line_asks():
    by_key = {(r.module, r.action): r for r in governance.DEFAULT_RULES}
    for spec in governance.LEGACY_MAKER_ROLE_RULES:
        assert by_key[(spec.module, spec.action)].maker_role == ""
    assert ("vuln_finding", "accept_risk") in by_key
    assert dual_control.is_enforced_key("vuln_finding", "accept_risk")


# --------------------------------------------------- vulnerability risk acceptance ---
TODAY = date(2026, 9, 25)


def _finding(**over):
    base = {"status": "open", "acceptance_status": "", "acceptance_requested_by_id": None}
    return NS(**{**base, **over})


def test_who_may_ask_for_an_acceptance():
    ask = vuln_acceptance.request_refusal
    assert ask(_finding(), TODAY + timedelta(days=90), TODAY) is None
    assert "only an open finding" in ask(_finding(status="remediated"), TODAY + timedelta(days=9), TODAY)
    assert "already waiting" in ask(_finding(acceptance_status="requested"), TODAY + timedelta(days=9), TODAY)
    assert "future" in ask(_finding(), TODAY, TODAY)
    assert "at most" in ask(_finding(), TODAY + timedelta(days=366), TODAY)


@pytest.fixture
def four_eyes(monkeypatch):
    state = {"required": True, "rule": None, "role_refusal": None}

    async def required(db, module, action, amount=None):
        assert (module, action) == ("vuln_finding", "accept_risk")
        return state["required"], state["rule"]

    async def role_refusal(db, rule, **kw):
        return state["role_refusal"]

    monkeypatch.setattr(dual_control, "dual_control_required", required)
    monkeypatch.setattr(dual_control, "checker_role_refusal", role_refusal)
    return state


async def test_who_may_decide_an_acceptance(four_eyes):
    maker, checker = uuid.uuid4(), uuid.uuid4()
    pending = _finding(acceptance_status="requested", acceptance_requested_by_id=maker)
    perms = {"vuln:read", "workflow:approve"}
    decide = vuln_acceptance.decision_refusal
    assert await decide(None, pending, user_id=checker, permissions=perms) is None
    assert "maker" in await decide(None, pending, user_id=maker, permissions=perms)
    assert "workflow:approve" in await decide(None, pending, user_id=checker, permissions={"vuln:read"})
    assert "No acceptance request" in await decide(None, _finding(), user_id=checker, permissions=perms)
    four_eyes["role_refusal"] = "reserved for the CISO role"
    assert await decide(None, pending, user_id=checker, permissions=perms) == "reserved for the CISO role"
    four_eyes["role_refusal"] = None
    closed = _finding(status="remediated", acceptance_status="requested", acceptance_requested_by_id=maker)
    assert "Reject the request" in await decide(None, closed, user_id=checker, permissions=perms)
    assert await decide(None, closed, user_id=checker, permissions=perms, approve=False) is None
    four_eyes["required"] = False  # four-eyes off: the requester may decide
    assert await decide(None, pending, user_id=maker, permissions=perms) is None


# ------------------------------------------------------------------- My Work ---
async def test_my_work_asks_the_checker_role_once_per_maker(monkeypatch):
    seen = []

    async def role_refusal(db, rule, *, module, action, checker_id, maker_id, directory=None):
        seen.append(maker_id)
        return "reserved" if maker_id == "m2" else None

    monkeypatch.setattr(dual_control, "checker_role_refusal", role_refusal)
    ctx = NS(user_id="me", directory=object())
    rule = NS(checker_role="Risk Approver")
    assert await my_work._checker_blocked(None, ctx, rule, "control", "review_test", ("m1", "m2", None))
    assert not await my_work._checker_blocked(None, ctx, rule, "control", "review_test", ("m1",))
    assert not await my_work._checker_blocked(None, ctx, NS(checker_role=""), "control", "review_test", ("m2",))
    assert await my_work._checker_blocked(None, ctx, rule, "control", "review_test", ()) is False
    assert None in seen  # no maker known: still asked, as the decision is


def test_my_work_says_why_it_can_only_be_returned():
    assert my_work._approve_note(None) == ""
    assert my_work._approve_note("above your mandate").startswith("You can return it")
    assert "vuln_acceptance" in my_work.BUILDERS and "vuln_acceptance" in my_work.KIND_LABELS
