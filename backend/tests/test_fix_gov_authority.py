"""Delegation of authority and maker-checker configuration (client report).

Pins: a maker-checker rule can only name a decision the code actually checks (a rule for
"payments / disburse" enforced nothing); relaxing a rule — switching it off, exempting
an action, adding or raising a threshold, moving or deleting it — needs an administrator
(``settings:manage``), so the maker a rule binds cannot switch it off with plain
``authority:write``; tightening needs no more than before; and the authority-matrix
mandate check refuses an amount above every mandate the user's roles hold. Pure.
"""
from types import SimpleNamespace

import pytest

from app.api.v1 import authority
from app.models.authority import DualControlStatus
from app.schemas.authority import AuthorityMatrixCreate
from app.services import dual_control as dc
from app.services.default_governance import DEFAULT_RULES


def rule(module="policy", action="publish", *, requires=True, threshold=None, enabled=True,
         status=DualControlStatus.active):
    return {"module": module, "action": action, "requires_dual_control": requires,
            "threshold_amount": threshold, "enabled": enabled, "status": status}


# ------------------------------------------------------------- enforced keys ---
def test_enforced_keys_cover_every_default_rule():
    # Every rule an organisation is seeded with names a key the code checks.
    for spec in DEFAULT_RULES:
        assert dc.is_enforced_key(spec.module, spec.action), (spec.module, spec.action)


def test_enforced_keys_include_the_dynamic_families():
    assert dc.is_enforced_key("board_pack", "release")
    assert dc.is_enforced_key("legal", "delete")
    assert dc.is_enforced_key("risk", "approve")      # risks have a review lifecycle
    assert dc.is_enforced_key("vendor", "attest")


def test_free_text_keys_the_old_form_suggested_are_not_enforced():
    for module, action in [("payments", "disburse"), ("policy_publish", "approve"), ("vendor", "create")]:
        assert not dc.is_enforced_key(module, action)
    assert "enforce nothing" in dc.unknown_key_message("payments", "disburse")


def test_keys_route_is_declared_before_the_rule_id_route():
    paths = [r.path for r in authority.router.routes]
    assert paths.index("/dual-control-rules/keys") < paths.index("/dual-control-rules/{rid}")
    assert paths.index("/authority-matrix/mandate") < paths.index("/authority-matrix/{aid}")


# -------------------------------------------------------------- relaxations ---
@pytest.mark.parametrize("after", [
    rule(enabled=False),                      # switched off (falls to the switch, which is off)
    rule(requires=False),                     # explicit exemption
    rule(threshold=1_000_000),                # threshold added
    rule(status=DualControlStatus.disabled),  # status disabled
])
def test_switching_off_or_thresholding_is_a_relaxation(after):
    assert dc.relaxations(before=rule(), after=after, global_switch=False)


def test_disabling_is_not_a_relaxation_while_the_global_switch_is_on():
    # A disabled rule falls through to the fail-closed global switch: nothing escapes.
    assert dc.relaxations(before=rule(), after=rule(enabled=False), global_switch=True) == []
    # ... but an explicit exemption does.
    assert dc.relaxations(before=rule(), after=rule(requires=False), global_switch=True)


def test_raising_a_threshold_relaxes_and_lowering_it_does_not():
    before = rule(threshold=100_000)
    assert dc.relaxations(before=before, after=rule(threshold=500_000), global_switch=True)
    assert dc.relaxations(before=before, after=rule(threshold=50_000), global_switch=True) == []
    assert dc.relaxations(before=before, after=rule(threshold=None), global_switch=True) == []


def test_tightening_and_cosmetic_edits_are_not_relaxations():
    assert dc.relaxations(before=rule(requires=False), after=rule(), global_switch=True) == []
    assert dc.relaxations(before=rule(enabled=False), after=rule(), global_switch=False) == []
    assert dc.relaxations(before=rule(), after=rule(), global_switch=True) == []


def test_creating_an_exempting_rule_relaxes_whatever_decides_today():
    assert dc.relaxations(before=None, after=rule(requires=False), global_switch=True, superseded=None)
    # With the switch off and no rule, nothing was enforced: exempting changes nothing.
    assert dc.relaxations(before=None, after=rule(requires=False), global_switch=False, superseded=None) == []
    # A new enforcing rule is never a relaxation.
    assert dc.relaxations(before=None, after=rule(), global_switch=False, superseded=None) == []


def test_deleting_a_rule_relaxes_only_when_the_default_is_weaker():
    assert dc.relaxations(before=rule(), after=None, global_switch=False)
    assert dc.relaxations(before=rule(), after=None, global_switch=True) == []
    # Attestation keys never fall back to the switch: deleting their rule drops four-eyes.
    assert dc.relaxations(before=rule("risk", "attest"), after=None, global_switch=True)


def test_moving_a_rule_to_another_key_is_checked_on_both_keys():
    reasons = dc.relaxations(before=rule(), after=rule("risk", "accept"), global_switch=False)
    assert any("policy / publish" in r for r in reasons)


def test_rule_effect_reads_orm_rows_too():
    row = SimpleNamespace(**rule(threshold=5))
    assert dc.rule_effect(row, action="publish", global_switch=False) == dc.Effect(True, 5.0)


def test_only_an_administrator_may_relax():
    reasons = ["it switches four-eyes off for this action"]
    refusal = dc.relax_refusal(reasons, ["authority:read", "authority:write"])
    assert refusal and "administrator" in refusal and "switches four-eyes off" in refusal
    assert dc.relax_refusal(reasons, ["authority:write", "settings:manage"]) is None
    assert dc.relax_refusal([], ["authority:write"]) is None


# -------------------------------------------------------- authority mandates ---
LINES = [
    dc.MandateLine("DOA-1", "Risk Manager", 1, 0, 1_000_000, "PKR"),
    dc.MandateLine("DOA-2", "CRO", 2, 1_000_000, 50_000_000, "PKR"),
    dc.MandateLine("DOA-3", "Board Risk Committee", 3, 50_000_000, None, "PKR"),
]


def test_mandate_within_band_is_allowed():
    assert dc.mandate_refusal(LINES, amount=500_000, role_names=["risk manager"]) is None
    assert dc.mandate_refusal(LINES, amount=60_000_000, role_names=["Board  Risk Committee"]) is None


def test_mandate_above_the_users_band_names_who_can_approve():
    refusal = dc.mandate_refusal(LINES, amount=5_000_000, role_names=["Risk Manager"], currency="PKR",
                                 activity="Accepting this risk")
    assert refusal and "CRO" in refusal and "5,000,000" in refusal


def test_mandate_not_configured_or_no_amount_does_not_block():
    assert dc.mandate_refusal([], amount=5_000_000, role_names=[]) is None
    assert dc.mandate_refusal(LINES, amount=None, role_names=[]) is None
    # Lines in another currency do not govern a USD decision.
    assert dc.mandate_refusal(LINES, amount=5_000_000, role_names=[], currency="USD") is None


# ------------------------------------------------------------- matrix bands ---
def test_upper_limit_below_lower_limit_is_refused():
    with pytest.raises(Exception) as exc:
        authority._band_or_422(100, 10)
    assert exc.value.status_code == 422
    authority._band_or_422(10, None)
    authority._band_or_422(10, 10)


def test_negative_limits_are_refused_by_the_schema():
    with pytest.raises(ValueError):
        AuthorityMatrixCreate(activity="x", amount_from=-1)
