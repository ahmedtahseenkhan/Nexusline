"""A session is renewed while in use, up to a maximum length (no DB required).

People entering data were signed out an hour after signing in, however active: the
token's lifetime was a hard cap. ``POST /auth/refresh`` renews it, so the lifetime is the
idle timeout and ``session_max_hours`` bounds the session.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.auth import refresh_session
from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.services import mfa_policy

NOW = datetime.now(timezone.utc)


def _user(**over):
    base = dict(id=uuid.uuid4(), tenant_id=uuid.uuid4(), role_names=["Admin"],
                permission_codes=["risk:read"], password_changed_at=None, email="a@bank.com",
                full_name="A", is_active=True, created_at=NOW, mfa_enabled=False,
                auth_source="local", is_platform_admin=False)
    return SimpleNamespace(**{**base, **over})


def _payload(started: datetime, **extra):
    return {"sub": "x", "tid": "y", "iat": int(started.timestamp()),
            "auth_time": int(started.timestamp()), **extra}


def _refresh(user, payload):
    return asyncio.run(refresh_session(user=user, payload=payload))


def test_a_new_token_records_when_the_person_signed_in():
    claims = decode_access_token(create_access_token("u", "t", [], []))
    assert abs(claims["auth_time"] - claims["iat"]) <= 1


def test_an_active_session_is_renewed_and_keeps_its_sign_in_time():
    started = NOW - timedelta(minutes=55)
    result = _refresh(_user(), _payload(started))
    claims = decode_access_token(result.access_token)
    assert claims["auth_time"] == int(started.timestamp())
    assert claims["exp"] > int((NOW + timedelta(minutes=settings.access_token_expire_minutes - 1)).timestamp())
    assert claims["perms"] == ["risk:read"]


def test_a_renewed_token_never_outlives_the_maximum_session():
    started = NOW - timedelta(hours=settings.session_max_hours) + timedelta(minutes=20)
    claims = decode_access_token(_refresh(_user(), _payload(started)).access_token)
    assert claims["exp"] <= int((started + timedelta(hours=settings.session_max_hours)).timestamp())


def test_a_session_at_its_maximum_length_must_sign_in_again():
    started = NOW - timedelta(hours=settings.session_max_hours)
    with pytest.raises(HTTPException) as exc:
        _refresh(_user(), _payload(started))
    assert exc.value.status_code == 401


def test_a_password_change_since_sign_in_ends_the_session():
    started = NOW - timedelta(minutes=30)
    with pytest.raises(HTTPException) as exc:
        _refresh(_user(password_changed_at=NOW - timedelta(minutes=5)), _payload(started))
    assert exc.value.status_code == 401


def test_an_mfa_enrol_only_session_is_not_renewed():
    with pytest.raises(HTTPException) as exc:
        _refresh(_user(), _payload(NOW, **{mfa_policy.ENROL_ONLY_CLAIM: True}))
    assert exc.value.status_code == 403


def test_a_token_from_before_this_change_is_renewed_from_its_issue_time():
    started = NOW - timedelta(minutes=50)
    payload = _payload(started)
    del payload["auth_time"]
    claims = decode_access_token(_refresh(_user(), payload).access_token)
    assert claims["auth_time"] == int(started.timestamp())
