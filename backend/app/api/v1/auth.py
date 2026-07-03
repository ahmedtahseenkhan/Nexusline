"""Authentication: org registration, per-org login, MFA, password change, current-user.

Login is hardened for banking: brute-force lockout, optional LDAP/AD directory auth
with JIT provisioning, and TOTP multi-factor. Failed-attempt counters are persisted
by completing the DB transaction first and only then raising the HTTP error, so a
rollback can never erase a recorded failure.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.config import settings
from app.core.database import set_session_tenant, system_session, tenant_session
from app.core.deps import CurrentUser, DbSession
from app.core.security import (
    create_access_token,
    create_mfa_challenge,
    decode_mfa_challenge,
    hash_password,
    verify_password,
)
from app.db.provisioning import create_organization
from app.models.identity import Role, User
from app.models.ldap_config import LdapConfig
from app.models.tenant import Tenant
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResult,
    MfaActivateRequest,
    MfaDisableRequest,
    MfaSetupResponse,
    MfaVerifyRequest,
    RegisterOrgRequest,
    TokenResponse,
)
from app.schemas.user import UserRead
from app.services import ldap_auth, password_policy, totp

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


def _token_response(user: User, tenant_id) -> TokenResponse:
    token = create_access_token(
        subject=str(user.id),
        tenant_id=str(tenant_id),
        roles=user.role_names,
        permissions=user.permission_codes,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserRead.model_validate(user),
    )


def _login_result(user: User, tenant_id) -> LoginResult:
    tr = _token_response(user, tenant_id)
    return LoginResult(
        mfa_required=False,
        access_token=tr.access_token,
        expires_in=tr.expires_in,
        user=tr.user,
    )


# --------------------------------------------------------------- registration ---
@router.post(
    "/register-org",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new organization and its first admin",
)
async def register_org(body: RegisterOrgRequest) -> TokenResponse:
    password_policy.validate_password(body.admin_password)
    async with tenant_session(None) as db:
        if await db.scalar(select(Tenant).where(Tenant.slug == body.slug)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Organization slug already taken"
            )
        tenant, admin = await create_organization(
            db,
            name=body.org_name,
            slug=body.slug,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
            admin_full_name=body.admin_full_name,
        )
        admin.password_changed_at = datetime.now(timezone.utc)
        return _token_response(admin, tenant.id)


# ---------------------------------------------------------------------- login ---
@dataclass
class _Outcome:
    error: HTTPException | None = None
    result: LoginResult | None = None


def _register_failed(user: User) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= settings.max_failed_logins:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.lockout_minutes)
        user.failed_login_attempts = 0


def _reset_lockout(user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None


async def _jit_upsert(db, tenant_id, profile: ldap_auth.LdapProfile, default_role: str, existing: User | None) -> User:
    if existing is not None:
        existing.full_name = profile.full_name or existing.full_name
        existing.auth_source = "ldap"
        existing.is_active = True
        return existing
    user = User(
        tenant_id=tenant_id,
        email=profile.email,
        full_name=profile.full_name,
        hashed_password=hash_password(secrets.token_urlsafe(32)),  # unusable for local login
        auth_source="ldap",
        is_active=True,
    )
    role = await db.scalar(select(Role).where(Role.name == default_role))
    if role is not None:
        user.roles = [role]
    db.add(user)
    await db.flush()
    return user


async def _do_login(db, body: LoginRequest) -> _Outcome:
    tenant = await db.scalar(
        select(Tenant).where(Tenant.slug == body.tenant_slug, Tenant.is_active.is_(True))
    )
    if tenant is None:
        return _Outcome(error=_INVALID)
    await set_session_tenant(db, tenant.id)

    ldap_cfg = await db.scalar(select(LdapConfig).where(LdapConfig.enabled.is_(True)))
    user = await db.scalar(select(User).where(User.email == body.email))

    now = datetime.now(timezone.utc)
    if user is not None and user.locked_until is not None and user.locked_until > now:
        return _Outcome(
            error=HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account locked due to failed attempts. Try again after {user.locked_until:%H:%M UTC}.",
            )
        )

    authed: User | None = None
    if user is not None and user.auth_source == "local" and user.is_active:
        if verify_password(body.password, user.hashed_password):
            authed = user
        else:
            _register_failed(user)
            return _Outcome(error=_INVALID)
    elif ldap_cfg is not None:
        try:
            profile = ldap_auth.authenticate(ldap_cfg, body.email, body.password)
        except HTTPException as exc:
            return _Outcome(error=exc)
        if profile is None:
            if user is not None:
                _register_failed(user)
            return _Outcome(error=_INVALID)
        authed = await _jit_upsert(db, tenant.id, profile, ldap_cfg.default_role, existing=user)
    else:
        return _Outcome(error=_INVALID)

    if not authed.is_active:
        return _Outcome(error=_INVALID)
    _reset_lockout(authed)

    if authed.auth_source == "local" and password_policy.is_expired(authed.password_changed_at):
        return _Outcome(
            error=HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your password has expired and must be reset by an administrator.",
            )
        )
    await db.flush()

    if authed.mfa_enabled:
        challenge = create_mfa_challenge(str(authed.id), str(tenant.id))
        return _Outcome(result=LoginResult(mfa_required=True, challenge_token=challenge))
    return _Outcome(result=_login_result(authed, tenant.id))


@router.post("/login", response_model=LoginResult, summary="Log in (password → MFA if enabled)")
async def login(body: LoginRequest) -> LoginResult:
    async with system_session() as db:
        outcome = await _do_login(db, body)
    # Transaction is committed here — lockout counters persist before we raise.
    if outcome.error is not None:
        raise outcome.error
    return outcome.result  # type: ignore[return-value]


# ------------------------------------------------------------------------ MFA ---
@router.post("/mfa/verify", response_model=TokenResponse, summary="Complete MFA and get a token")
async def mfa_verify(body: MfaVerifyRequest) -> TokenResponse:
    try:
        data = decode_mfa_challenge(body.challenge_token)
    except jwt.PyJWTError as exc:
        raise _INVALID from exc
    async with tenant_session(data["tid"]) as db:
        user = await db.scalar(select(User).where(User.id == uuid.UUID(data["sub"])))
        if user is None or not user.is_active or not user.mfa_enabled:
            raise _INVALID
        if not totp.verify(user.mfa_secret, body.code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")
        return _token_response(user, data["tid"])


@router.post("/mfa/setup", response_model=MfaSetupResponse, summary="Begin TOTP enrolment")
async def mfa_setup(db: DbSession, user: CurrentUser) -> MfaSetupResponse:
    secret = totp.generate_secret()
    user.mfa_secret = secret          # stored but not yet active
    user.mfa_enabled = False
    await db.flush()
    return MfaSetupResponse(
        secret=secret,
        otpauth_uri=totp.provisioning_uri(secret, user.email, settings.mfa_issuer),
    )


@router.post("/mfa/activate", response_model=UserRead, summary="Confirm TOTP code and enable MFA")
async def mfa_activate(body: MfaActivateRequest, db: DbSession, user: CurrentUser) -> UserRead:
    if not user.mfa_secret:
        raise HTTPException(status_code=400, detail="Start MFA setup first")
    if not totp.verify(user.mfa_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code — check your authenticator app")
    user.mfa_enabled = True
    await db.flush()
    return UserRead.model_validate(user)


@router.post("/mfa/disable", response_model=UserRead, summary="Disable MFA for the current user")
async def mfa_disable(body: MfaDisableRequest, db: DbSession, user: CurrentUser) -> UserRead:
    if user.mfa_enabled and not totp.verify(user.mfa_secret, body.code):
        raise HTTPException(status_code=400, detail="A valid MFA code is required to disable MFA")
    user.mfa_enabled = False
    user.mfa_secret = ""
    await db.flush()
    return UserRead.model_validate(user)


# ----------------------------------------------------------- password change ---
@router.post("/change-password", status_code=204, summary="Change the current user's password")
async def change_password(body: ChangePasswordRequest, db: DbSession, user: CurrentUser) -> None:
    if user.auth_source != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Directory-managed accounts change their password in the directory.",
        )
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current password is incorrect")
    password_policy.validate_password(body.new_password)
    user.hashed_password = hash_password(body.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    await db.flush()


@router.get("/me", response_model=UserRead, summary="Current authenticated user")
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
