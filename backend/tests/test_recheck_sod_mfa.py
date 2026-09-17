"""Re-check of 17 Sep 2026, F-06: MFA by role set in the product, default approval routes
and dual-control rules for every organisation, and who may cancel an approval.

No DB: the policy pieces are pure functions (``services/mfa_policy.py``,
``services/default_governance.py``, ``api/v1/approvals.py``); the few database helpers
are exercised against small fakes.
"""
from __future__ import annotations

import inspect
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import approvals
from app.core.config import Settings, settings
from app.core.permissions import DEFAULT_ROLES
from app.services import default_governance as gov
from app.services import mfa_policy

NOW = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
APP = Path(__file__).resolve().parents[1] / "app"


# ============================================================ MFA: whose list applies ===
def test_no_organisation_list_means_the_deployment_default():
    assert mfa_policy.effective_required_roles(None, ["admin", "Risk Approver"]) == ["admin", "Risk Approver"]


def test_the_organisation_list_replaces_the_default_but_always_keeps_admin():
    assert mfa_policy.effective_required_roles(["Compliance Manager"], ["admin", "Auditor"]) == [
        "Compliance Manager", "admin",
    ]
    assert mfa_policy.effective_required_roles([], ["Auditor"]) == ["admin"]


def test_effective_roles_drop_duplicates_case_insensitively():
    assert mfa_policy.effective_required_roles(["Admin", " ADMIN ", "Viewer"], []) == ["Admin", "Viewer"]


def test_validation_uses_the_roles_own_spelling_and_re_adds_admin():
    roles, problem = mfa_policy.validate_required_roles(
        ["compliance manager", "COMPLIANCE MANAGER"], ["Admin", "Compliance Manager", "Viewer"]
    )
    assert problem is None
    assert roles == ["Compliance Manager", "Admin"]


def test_validation_refuses_a_role_the_organisation_does_not_have():
    roles, problem = mfa_policy.validate_required_roles(["CISO", "Admin"], ["Admin", "Viewer"])
    assert roles == [] and problem is not None and "CISO" in problem


def test_an_organisation_list_makes_its_roles_require_mfa():
    user = SimpleNamespace(role_names=["Compliance Manager"], permission_codes=["policy:write"])
    fake = SimpleNamespace(mfa_required=False, mfa_required_roles=["admin"])
    assert not mfa_policy.user_requires_mfa(user, fake)
    assert mfa_policy.user_requires_mfa(user, fake, ["Compliance Manager"])


def test_removing_admin_from_an_organisation_list_does_not_exempt_admins():
    admin = SimpleNamespace(role_names=["Admin"], permission_codes=[])
    fake = SimpleNamespace(mfa_required=False, mfa_required_roles=["admin"])
    assert mfa_policy.user_requires_mfa(admin, fake, [])


def test_the_everyone_switch_still_wins_over_an_organisation_list():
    viewer = SimpleNamespace(role_names=["Viewer"], permission_codes=["risk:read"])
    fake = SimpleNamespace(mfa_required=True, mfa_required_roles=["admin"])
    assert mfa_policy.user_requires_mfa(viewer, fake, [])


@pytest.mark.parametrize(
    "role, codes, listed, everyone, expected",
    [
        ("Viewer", ["risk:read"], [], True, "everyone"),
        ("Admin", [], [], False, "protected"),
        ("Auditor", ["risk:read"], ["auditor"], False, "listed"),
        ("Risk Approver", ["workflow:approve"], [], False, "approves"),
        ("Viewer", ["risk:read"], [], False, "not_required"),
    ],
)
def test_the_settings_screen_says_why_a_role_needs_mfa(role, codes, listed, everyone, expected):
    assert mfa_policy.role_requirement(
        role_name=role, permission_codes=codes, required_roles=listed, global_required=everyone
    ) == expected


def test_every_seeded_approver_role_is_required_implicitly():
    for name, (_, codes) in DEFAULT_ROLES.items():
        if any(c.endswith(":approve") for c in codes) and name != "Admin":
            assert mfa_policy.role_requirement(
                role_name=name, permission_codes=codes, required_roles=["admin"], global_required=False
            ) == "approves"


# ============================================================ MFA: the Users column ===
def _status(**kw):
    args = dict(required=True, mfa_enabled=False, grace_until=None, now=NOW, signs_in_with_sso=False)
    args.update(kw)
    return mfa_policy.user_mfa_status(**args)


def test_users_column_states():
    assert _status(mfa_enabled=True) == ("enabled", None)
    assert _status(required=False) == ("not_required", None)
    assert _status(signs_in_with_sso=True) == ("identity_provider", None)
    due = NOW + timedelta(days=3)
    assert _status(grace_until=due) == ("required", due)
    assert _status() == ("required", None)  # grace starts at the next sign-in
    past = NOW - timedelta(minutes=1)
    assert _status(grace_until=past) == ("overdue", past)


def test_enrolled_beats_sso_and_sso_beats_required():
    assert _status(mfa_enabled=True, signs_in_with_sso=True)[0] == "enabled"
    assert _status(signs_in_with_sso=True, grace_until=NOW - timedelta(days=1))[0] == "identity_provider"


class _ScalarDB:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def begin_nested(self):
        db = self

        class _Tx:
            async def __aenter__(self):
                return db

            async def __aexit__(self, *exc):
                return False

        return _Tx()

    async def scalar(self, *a, **k):
        if self.error:
            raise self.error
        return self.value


async def test_tenant_roles_read_the_column_and_fall_back_quietly():
    assert await mfa_policy.tenant_required_roles(_ScalarDB(["Admin", "Auditor"])) == ["Admin", "Auditor"]
    assert await mfa_policy.tenant_required_roles(_ScalarDB(None)) is None
    # A database that predates the column must not stop anyone signing in.
    assert await mfa_policy.tenant_required_roles(_ScalarDB(error=RuntimeError("no column"))) is None


def test_login_me_and_disable_read_the_organisation_list():
    from app.api.v1 import auth

    source = inspect.getsource(auth)
    assert source.count("mfa_policy.tenant_required_roles(") >= 3


def test_mfa_role_list_endpoint_validates_audits_and_needs_settings_manage():
    from app.api.v1 import tenant_settings

    source = inspect.getsource(tenant_settings.update_mfa_roles)
    assert "validate_required_roles" in source and "audit.record" in source
    route = next(r for r in tenant_settings.router.routes
                 if r.path == "/settings/organisation/security/mfa-roles")
    assert route.methods == {"PUT"} and route.dependencies
    after_path = inspect.getsource(tenant_settings).split('"/organisation/security/mfa-roles"')[1]
    assert 'require("settings:manage")' in after_path[:200]


def test_tenant_settings_read_exposes_the_mfa_role_list():
    from app.schemas.tenant_settings import TenantSettingsRead

    assert "mfa_required_roles" in TenantSettingsRead.model_fields


def test_user_read_carries_mfa_status():
    from app.schemas.user import UserRead

    assert {"mfa_status", "mfa_due"} <= set(UserRead.model_fields)


# ======================================================== e-mail links bypass MFA ===
def test_email_actions_are_off_unless_an_installation_opts_in(monkeypatch):
    monkeypatch.delenv("EMAIL_ACTIONS_ENABLED", raising=False)
    assert Settings(_env_file=None).email_actions_enabled is False
    compose = (APP.parents[1] / "docker-compose.prod.yml").read_text()
    assert "EMAIL_ACTIONS_ENABLED: ${EMAIL_ACTIONS_ENABLED:-false}" in compose
    example = (APP.parents[1] / ".env.example").read_text()
    assert "EMAIL_ACTIONS_ENABLED=false" in example


def test_with_links_off_the_digest_has_no_approve_buttons(monkeypatch):
    from app.services import action_tokens, email

    monkeypatch.setattr(settings, "email_actions_enabled", False)
    assert action_tokens.enabled() is False
    alert = SimpleNamespace(title="APR-001 awaiting you", body="", category="approval",
                            link="/approvals", entity_id=uuid.uuid4())
    _, html, text = email.render_user_digest("Acme", [alert], decisions=action_tokens.links_for([]))
    assert "Approve</a>" not in html and "Reject</a>" not in html


# ================================================= default routes and dual control ===
def test_default_routes_name_roles_that_exist_and_can_approve():
    for route in gov.DEFAULT_ROUTES:
        for stage in route.stages:
            assert stage.approver_mode == "role"
            assert stage.approver_ref in DEFAULT_ROLES, stage.approver_ref
            assert "workflow:approve" in DEFAULT_ROLES[stage.approver_ref][1]


def test_default_routes_are_for_record_types_with_a_lifecycle():
    from app.services import record_registry
    from app.services.entity_types import ENTITY_TYPES

    for route in gov.DEFAULT_ROUTES:
        assert route.entity_type in ENTITY_TYPES
        assert record_registry.has_workflow(record_registry.model_for(route.entity_type))


def test_routes_are_added_only_for_record_types_without_one():
    assert [r.entity_type for r in gov.routes_to_add([])] == ["risk", "policy", "exception"]
    assert [r.entity_type for r in gov.routes_to_add(["policy"])] == ["risk", "exception"]


def test_rules_never_come_back_for_a_key_that_has_one():
    everything = gov.rules_to_add([])
    assert len(everything) == len(gov.DEFAULT_RULES)
    assert all((r.module, r.action) != ("risk", "accept") for r in gov.rules_to_add([("risk", "accept")]))


def test_default_rules_have_unique_keys():
    keys = [(r.module, r.action) for r in gov.DEFAULT_RULES]
    assert len(keys) == len(set(keys))


_LITERAL_KEY = re.compile(r'module="([a-z_]+)",\s*action="([a-z_]+)"')


def test_every_literal_dual_control_key_in_the_code_has_a_default_rule():
    covered = {(r.module, r.action) for r in gov.DEFAULT_RULES}
    found: set[tuple[str, str]] = set()
    for path in (APP / "api").rglob("*.py"):
        found |= set(_LITERAL_KEY.findall(path.read_text()))
    found |= {("risk", "bulk_archive")}  # called positionally in api/v1/risks.py
    found |= {("issue", "validate"), ("issue", "close")}  # api/v1/issues.py passes `action`
    assert found and found <= covered, sorted(found - covered)


def test_legacy_demo_routes_are_upgraded_only_when_untouched():
    legacy_type, legacy_name, legacy_stages = gov.LEGACY_DEFAULT_ROUTES[1]
    spec = gov.legacy_upgrade_for(legacy_type, legacy_name, False, legacy_stages)
    assert spec is not None and spec.entity_type == "risk"
    assert gov.legacy_upgrade_for(legacy_type, legacy_name, True, legacy_stages) is None
    edited = (*legacy_stages[:-1], ("CRO approval", "role", "Chief Risk Officer"))
    assert gov.legacy_upgrade_for(legacy_type, legacy_name, False, edited) is None


def test_a_single_user_organisation_is_told_it_needs_a_second_user():
    assert gov.needs_second_user(1, True)
    assert gov.needs_second_user(0, True)
    assert not gov.needs_second_user(2, True)
    assert not gov.needs_second_user(1, False)
    assert "at least two users" in gov.SECOND_USER_MESSAGE


# ---------------------------------------------------------------- role holders ---
MAKER = uuid.uuid4()
HOLDER = uuid.uuid4()


def test_eligible_holders_leave_out_the_maker():
    holders = {"risk approver": {MAKER, HOLDER}}
    assert gov.eligible_holder_count(holders, "Risk Approver", MAKER) == 1
    assert gov.eligible_holder_count({"risk approver": {MAKER}}, "Risk Approver", MAKER) == 0
    assert gov.eligible_holder_count({}, "Risk Approver", None) == 0


def test_a_stage_with_a_holder_is_decided_only_by_a_holder():
    assert gov.stage_decision_refusal("Risk Approver", ["risk approver"], 1) is None
    refusal = gov.stage_decision_refusal("Risk Approver", ["Admin"], 1)
    assert refusal and "Risk Approver" in refusal


def test_a_stage_nobody_can_hold_does_not_dead_end():
    assert gov.stage_decision_refusal("Risk Approver", ["Admin"], 0) is None
    assert gov.stage_decision_refusal(None, ["Admin"], 3) is None
    assert gov.role_gap_message("Risk Approver").startswith("No one holds the Risk Approver role — assign it in Users")
    assert "Only the person who submitted this" in gov.role_gap_message("CRO", only_maker=True)


# ------------------------------------------------------------- database helpers ---
class _RulesDB:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.added = []

    async def execute(self, *a, **k):
        rows = self.existing

        class _R:
            def all(self):
                return rows

        return _R()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


@pytest.mark.parametrize("sod", [True, False])
async def test_default_rules_follow_the_segregation_switch(monkeypatch, sod):
    from app.models.authority import DualControlStatus
    from app.services import refs

    counter = iter(range(1, 100))

    async def next_reference(db, model, prefix, width=3):
        return f"{prefix}-{next(counter):03d}"

    monkeypatch.setattr(refs, "next_reference", next_reference)
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", sod)
    db = _RulesDB(existing=[("risk", "accept")])
    added = await gov.ensure_default_rules(db, uuid.uuid4())
    assert added == len(gov.DEFAULT_RULES) - 1
    assert all(r.enabled is sod for r in db.added)
    assert all(r.status == (DualControlStatus.active if sod else DualControlStatus.disabled) for r in db.added)
    assert all(r.requires_dual_control for r in db.added)
    assert {r.reference for r in db.added} == {f"MC-{i:03d}" for i in range(1, added + 1)}


def test_every_new_organisation_gets_the_defaults():
    from app.db import provisioning

    assert "ensure_default_governance(db, tenant.id)" in inspect.getsource(provisioning.create_organization)


def test_onboarding_completion_fills_in_missing_defaults():
    from app.api.v1 import tenant_settings

    assert "ensure_default_governance" in inspect.getsource(tenant_settings.complete_onboarding)
    fields = tenant_settings.OnboardingStatus.model_fields
    assert {"needs_second_user", "sod_enforced", "approval_routes_enabled", "role_gaps"} <= set(fields)


async def test_the_boot_repair_runs_once_per_organisation(monkeypatch):
    from app.db import data_repairs

    calls = []

    async def seeded(db):
        return True

    async def ensure(db, tenant_id, actor=None):
        calls.append(tenant_id)
        return gov.SeedResult(routes_added=["Risk approval"], rules_added=3)

    monkeypatch.setattr(gov, "already_seeded", seeded)
    monkeypatch.setattr(gov, "ensure_default_governance", ensure)
    assert await data_repairs.seed_default_governance(object(), uuid.uuid4()) == 0 and calls == []

    async def not_seeded(db):
        return False

    monkeypatch.setattr(gov, "already_seeded", not_seeded)
    assert await data_repairs.seed_default_governance(object(), uuid.uuid4()) == 4
    assert "seed_default_governance(db, tenant_id)" in inspect.getsource(data_repairs.repair_tenant)


def test_the_demo_admin_holds_the_route_roles_and_the_maker_is_seeded():
    from app.db import seed

    assert set(seed.DEMO_CHECKER_ROLES) == {s.approver_ref for r in gov.DEFAULT_ROUTES for s in r.stages}
    source = inspect.getsource(seed._seed_sample_data)
    assert "_seed_demo_maker" in source and "_grant_demo_checker_roles" in source


# ====================================================== approvals: who may cancel ===
def _approval(**kw):
    return SimpleNamespace(
        requested_by=kw.get("requested_by", MAKER),
        requested_by_email=kw.get("requested_by_email", "maker@bank.pk"),
    )


def test_the_maker_may_cancel_their_own_request():
    assert approvals.may_cancel(_approval(), MAKER, "maker@bank.pk", ["workflow:write"])
    assert approvals.may_cancel(_approval(requested_by=None), HOLDER, "MAKER@bank.pk", [])


def test_an_administrator_may_cancel_any_request():
    assert approvals.may_cancel(_approval(), HOLDER, "admin@bank.pk", ["automation:manage"])


def test_a_checker_may_not_cancel_someone_elses_request():
    assert not approvals.may_cancel(_approval(), HOLDER, "checker@bank.pk", ["workflow:write", "workflow:approve"])


async def test_cancel_is_refused_server_side_for_anyone_else(monkeypatch):
    from app.models.enums import ApprovalStatus

    obj = SimpleNamespace(status=ApprovalStatus.pending, requested_by=MAKER,
                          requested_by_email="maker@bank.pk", reference="APR-009")

    async def load(db, approval_id):
        return obj

    monkeypatch.setattr(approvals, "_load", load)
    checker = SimpleNamespace(id=HOLDER, email="checker@bank.pk", permission_codes=["workflow:write"])
    with pytest.raises(HTTPException) as exc:
        await approvals.cancel_approval(uuid.uuid4(), object(), checker)
    assert exc.value.status_code == 403
    assert obj.status == ApprovalStatus.pending
    with pytest.raises(HTTPException) as exc:
        await approvals.delete_approval(uuid.uuid4(), object(), checker)
    assert exc.value.status_code == 403


async def test_a_stage_role_is_enforced_when_someone_else_holds_it(monkeypatch):
    obj = SimpleNamespace(id=uuid.uuid4(), requested_by=MAKER)

    async def stage_roles(db, ids):
        return {obj.id: "Risk Approver"}

    async def holders(db):
        return {"risk approver": {HOLDER}}

    monkeypatch.setattr(gov, "stage_roles", stage_roles)
    monkeypatch.setattr(gov, "role_holders", holders)
    outsider = SimpleNamespace(role_names=["Admin"])
    with pytest.raises(HTTPException) as exc:
        await approvals.enforce_stage_role(object(), obj, outsider)
    assert exc.value.status_code == 403 and "Risk Approver" in exc.value.detail
    await approvals.enforce_stage_role(object(), obj, SimpleNamespace(role_names=["Risk Approver"]))

    async def nobody(db):
        return {"risk approver": {MAKER}}

    monkeypatch.setattr(gov, "role_holders", nobody)
    await approvals.enforce_stage_role(object(), obj, outsider)  # falls back, no dead end


def test_the_compliance_head_can_decide_the_policy_route():
    assert "workflow:approve" in DEFAULT_ROLES["Compliance Manager"][1]
