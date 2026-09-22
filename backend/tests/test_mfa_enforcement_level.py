"""MFA enforcement level (2026-09-22): off / privileged / everyone, per organisation.

An evaluation or UAT install must be able to run without two-factor authentication, and a
bank must be able to pick its own level unless the deployment locks it. Pure functions in
``services/mfa_policy.py`` plus the settings parser and the endpoint's shape; no DB.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services import mfa_policy

VIEWER = dict(role_names=["Viewer"], permission_codes=["risk:read"])
ADMIN = dict(role_names=["Admin"], permission_codes=[])
CHECKER = dict(role_names=["Risk Approver"], permission_codes=["workflow:approve"])


# ------------------------------------------------------------- the pure policy ---
def test_off_requires_nobody_not_even_admins_or_checkers():
    for who in (VIEWER, ADMIN, CHECKER):
        assert not mfa_policy.mfa_required_for(
            **who, global_required=False, required_roles=["admin"], mode="off"
        )


def test_everyone_requires_everyone():
    assert mfa_policy.mfa_required_for(**VIEWER, global_required=False, required_roles=[], mode="everyone")


def test_privileged_is_the_role_rule():
    assert not mfa_policy.mfa_required_for(**VIEWER, global_required=False, required_roles=["admin"], mode="privileged")
    assert mfa_policy.mfa_required_for(**ADMIN, global_required=False, required_roles=["admin"], mode="privileged")
    assert mfa_policy.mfa_required_for(**CHECKER, global_required=False, required_roles=["admin"], mode="privileged")


def test_without_a_mode_the_legacy_switch_still_decides():
    assert mfa_policy.mfa_required_for(**VIEWER, global_required=True, required_roles=[])
    assert not mfa_policy.mfa_required_for(**VIEWER, global_required=False, required_roles=["admin"])


@pytest.mark.parametrize(
    "value, expected",
    [("off", "off"), ("OFF", "off"), (" disabled ", "off"), ("privileged", "privileged"),
     ("everyone", "everyone"), ("all", "everyone"), ("", None), (None, None), ("sometimes", None), (3, None)],
)
def test_levels_are_normalised_and_unknown_values_are_ignored(value, expected):
    assert mfa_policy.normalise_mode(value) == expected


def test_deployment_default_comes_from_mfa_enforcement_then_the_legacy_switch():
    assert mfa_policy.deployment_mode(SimpleNamespace(mfa_enforcement="off", mfa_required=True)) == "off"
    assert mfa_policy.deployment_mode(SimpleNamespace(mfa_enforcement=None, mfa_required=True)) == "everyone"
    assert mfa_policy.deployment_mode(SimpleNamespace(mfa_enforcement=None, mfa_required=False)) == "privileged"
    # A fake with neither attribute (older tests) is the privileged level.
    assert mfa_policy.deployment_mode(SimpleNamespace()) == "privileged"


def test_an_organisation_may_pick_its_own_level_unless_the_deployment_locks_it():
    open_ = SimpleNamespace(mfa_enforcement="everyone", mfa_required=True, mfa_enforcement_locked=False)
    locked = SimpleNamespace(mfa_enforcement="everyone", mfa_required=True, mfa_enforcement_locked=True)
    assert mfa_policy.effective_mode("off", open_) == "off"
    assert mfa_policy.effective_mode(None, open_) == "everyone"
    assert mfa_policy.effective_mode("garbage", open_) == "everyone"
    assert mfa_policy.effective_mode("off", locked) == "everyone"


def test_user_requires_mfa_honours_the_organisation_level():
    admin = SimpleNamespace(**ADMIN)
    fake = SimpleNamespace(mfa_required=True, mfa_required_roles=["admin"])
    assert mfa_policy.user_requires_mfa(admin, fake)
    assert not mfa_policy.user_requires_mfa(admin, fake, None, "off")
    assert mfa_policy.user_requires_mfa(admin, fake, None, "privileged")
    viewer = SimpleNamespace(**VIEWER)
    assert not mfa_policy.user_requires_mfa(viewer, fake, None, "privileged")
    assert mfa_policy.user_requires_mfa(viewer, fake, None, "everyone")


def test_the_settings_screen_shows_nothing_required_when_off():
    for role, codes in (("Admin", []), ("Risk Approver", ["workflow:approve"]), ("Viewer", ["risk:read"])):
        assert mfa_policy.role_requirement(
            role_name=role, permission_codes=codes, required_roles=["admin"], global_required=True, mode="off"
        ) == "not_required"
    assert mfa_policy.role_requirement(
        role_name="Admin", permission_codes=[], required_roles=["admin"], global_required=False, mode="privileged"
    ) == "protected"


def test_enrolment_state_is_not_required_when_off_even_after_a_lapsed_grace():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    state, _ = mfa_policy.enrolment_state(
        required=False, mfa_enabled=False, grace_until=now - timedelta(days=30), now=now, grace_days=7
    )
    assert state == "not_required"


# ------------------------------------------------------------- settings parsing ---
def test_settings_parse_the_level_and_refuse_a_misspelling(monkeypatch):
    monkeypatch.setenv("MFA_ENFORCEMENT", "Off")
    assert Settings(_env_file=None).mfa_enforcement == "off"
    monkeypatch.setenv("MFA_ENFORCEMENT", "")
    assert Settings(_env_file=None).mfa_enforcement is None
    monkeypatch.setenv("MFA_ENFORCEMENT", "sometimes")
    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_settings_lock_defaults_off(monkeypatch):
    monkeypatch.delenv("MFA_ENFORCEMENT_LOCKED", raising=False)
    assert Settings(_env_file=None).mfa_enforcement_locked is False


# ------------------------------------------------------------- the API's shape ---
def test_enforcement_endpoint_needs_settings_manage_audits_and_clears_grace():
    from app.api.v1 import tenant_settings

    source = inspect.getsource(tenant_settings.update_mfa_enforcement)
    assert "mfa_enforcement_locked" in source and "audit.record" in source
    assert "mfa_grace_until" in source and "normalise_mode" in source
    route = next(r for r in tenant_settings.router.routes
                 if r.path == "/settings/organisation/security/mfa-enforcement")
    assert route.methods == {"PUT"} and route.dependencies
    after_path = inspect.getsource(tenant_settings).split('"/organisation/security/mfa-enforcement"')[1]
    assert 'require("settings:manage")' in after_path[:200]


def test_policy_and_me_expose_the_level():
    from app.api.v1.tenant_settings import SecurityPolicyRead
    from app.schemas.auth import MeRead
    from app.schemas.tenant_settings import TenantSettingsRead

    for field in ("enforcement", "organisation_enforcement", "deployment_enforcement", "enforcement_locked"):
        assert field in SecurityPolicyRead.model_fields
    assert "mfa_enforcement" in MeRead.model_fields
    assert "mfa_enforcement" in TenantSettingsRead.model_fields


def test_tenant_policy_reads_both_columns_and_falls_back_quietly():
    import asyncio

    class _DB:
        def __init__(self, row=None, error=None):
            self.row, self.error = row, error

        def begin_nested(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return None

                async def __aexit__(self_inner, *a):
                    return False
            return _Ctx()

        async def execute(self, *a, **k):
            if self.error:
                raise self.error

            class _Res:
                def __init__(self, row):
                    self._row = row

                def first(self):
                    return self._row
            return _Res(self.row)

    async def run():
        assert await mfa_policy.tenant_policy(_DB(("off", ["Admin", "Auditor"]))) == ("off", ["Admin", "Auditor"])
        assert await mfa_policy.tenant_policy(_DB(None)) == (None, None)
        assert await mfa_policy.tenant_policy(_DB(("bogus", None))) == (None, None)
        assert await mfa_policy.tenant_policy(_DB(error=RuntimeError("no column"))) == (None, None)

    asyncio.run(run())
