"""MFA enforcement: who must enrol, the grace period, and the enrol-only session.

Pure functions (``services/mfa_policy.py``) plus the token-scope check in
``core/deps.py``; no DB.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.deps import check_session_scope
from app.core.security import create_access_token, create_mfa_challenge, decode_access_token
from app.services import mfa_policy

NOW = datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------- who must enrol ---
def test_admin_role_is_privileged_case_insensitively():
    assert mfa_policy.is_privileged(["Admin"], [], ["admin"])
    assert mfa_policy.is_privileged(["ADMIN"], [], [" Admin "])


def test_any_approve_permission_is_privileged():
    assert mfa_policy.is_privileged(["Risk Approver"], ["risk:read", "workflow:approve"], ["admin"])


def test_plain_maker_is_not_privileged():
    codes = ["risk:read", "risk:write", "risk:accept", "control:write"]
    assert not mfa_policy.is_privileged(["Risk Manager"], codes, ["admin"])


def test_global_switch_requires_everyone():
    assert mfa_policy.mfa_required_for(
        role_names=["Viewer"], permission_codes=["risk:read"], global_required=True, required_roles=[]
    )


def test_role_list_can_be_extended():
    assert mfa_policy.mfa_required_for(
        role_names=["Compliance Manager"],
        permission_codes=[],
        global_required=False,
        required_roles=["admin", "compliance manager"],
    )


def test_seeded_admin_role_requires_mfa_by_default():
    from app.core.permissions import DEFAULT_ROLES

    _, codes = DEFAULT_ROLES["Admin"]
    assert mfa_policy.mfa_required_for(
        role_names=["Admin"],
        permission_codes=codes,
        global_required=False,
        required_roles=settings.mfa_required_roles,
    )


def test_user_requires_mfa_reads_user_and_settings(monkeypatch):
    class U:
        role_names = ["Viewer"]
        permission_codes = ["risk:read"]

    monkeypatch.setattr(settings, "mfa_required", False)
    assert not mfa_policy.user_requires_mfa(U(), settings)
    monkeypatch.setattr(settings, "mfa_required", True)
    assert mfa_policy.user_requires_mfa(U(), settings)


# --------------------------------------------------------------- grace ---
def _state(**kw):
    args = {"required": True, "mfa_enabled": False, "grace_until": None, "now": NOW, "grace_days": 7}
    args.update(kw)
    return mfa_policy.enrolment_state(**args)


def test_not_required():
    assert _state(required=False) == ("not_required", None)


def test_already_enrolled():
    assert _state(mfa_enabled=True, grace_until=NOW - timedelta(days=30)) == ("enrolled", None)


def test_first_login_starts_grace_period():
    state, deadline = _state()
    assert state == "grace"
    assert deadline == NOW + timedelta(days=7)


def test_within_grace_keeps_existing_deadline():
    deadline = NOW + timedelta(days=2)
    assert _state(grace_until=deadline) == ("grace", deadline)


def test_after_grace_is_enrol_only():
    deadline = NOW - timedelta(minutes=1)
    assert _state(grace_until=deadline) == ("enrol_only", deadline)


def test_zero_grace_days_is_enrol_only_immediately():
    state, deadline = _state(grace_days=0)
    assert state == "enrol_only"
    assert deadline == NOW


def test_naive_deadline_treated_as_utc():
    naive = (NOW + timedelta(hours=1)).replace(tzinfo=None)
    state, deadline = _state(grace_until=naive)
    assert state == "grace"
    assert deadline.tzinfo is not None


# ---------------------------------------------------- enrol-only session ---
@pytest.mark.parametrize(
    "path",
    ["/api/v1/auth/me", "/api/v1/auth/mfa/setup", "/api/v1/auth/mfa/activate/", "/api/v1/auth/logout"],
)
def test_enrol_only_paths_allowed(path):
    assert mfa_policy.enrol_only_path_allowed(path)


@pytest.mark.parametrize(
    "path",
    ["/api/v1/risks", "/api/v1/auth/mfa/disable", "/api/v1/auth/change-password", "/api/v1/system/status", ""],
)
def test_other_paths_refused_for_enrol_only(path):
    assert not mfa_policy.enrol_only_path_allowed(path)


def test_scope_check_refuses_enrol_only_token_elsewhere():
    with pytest.raises(HTTPException) as exc:
        check_session_scope({"sub": "u", "tid": "t", mfa_policy.ENROL_ONLY_CLAIM: True}, "/api/v1/risks")
    assert exc.value.status_code == 403
    assert exc.value.detail == "Set up two-factor authentication to continue."
    assert exc.value.headers["X-Error-Code"] == mfa_policy.ENROL_REQUIRED_CODE


def test_scope_check_allows_enrol_only_token_on_enrolment():
    check_session_scope({"sub": "u", "tid": "t", mfa_policy.ENROL_ONLY_CLAIM: True}, "/api/v1/auth/mfa/setup")


def test_scope_check_allows_full_token_everywhere():
    check_session_scope({"sub": "u", "tid": "t"}, "/api/v1/risks")


def test_mfa_challenge_token_is_not_a_session():
    # The challenge proves only the password step; accepting it as a bearer token would
    # make the second factor optional.
    payload = decode_access_token(create_mfa_challenge("user-id", "tenant-id"))
    with pytest.raises(HTTPException) as exc:
        check_session_scope(payload, "/api/v1/auth/me")
    assert exc.value.status_code == 401


def test_enrol_only_claim_round_trips_and_cannot_override_subject():
    token = create_access_token(
        subject="real-user",
        tenant_id="tenant",
        roles=[],
        permissions=[],
        extra_claims={mfa_policy.ENROL_ONLY_CLAIM: True, "sub": "someone-else"},
    )
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    assert payload[mfa_policy.ENROL_ONLY_CLAIM] is True
    assert payload["sub"] == "real-user"


def test_settings_accept_comma_separated_roles(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("MFA_REQUIRED_ROLES", "Admin, Risk Approver")
    assert Settings().mfa_required_roles == ["Admin", "Risk Approver"]
    monkeypatch.setenv("MFA_REQUIRED_ROLES", '["Admin"]')
    assert Settings().mfa_required_roles == ["Admin"]
