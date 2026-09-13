"""Who must use two-factor authentication, and what an unenrolled session may do.

``settings.mfa_required`` existed for a long time without anything reading it, so a
bank that switched it on got nothing. This module is the policy; the login flow
(``api/v1/auth.py``) and the token dependency (``core/deps.py``) apply it.

**Who must enrol** (:func:`mfa_required_for`), first match wins:

1. ``settings.mfa_required`` is true → every user who signs in with a password.
2. The user holds a role named in ``settings.mfa_required_roles`` (compared
   case-insensitively; default ``["admin"]``, which matches the seeded ``Admin`` role).
3. The user holds any permission whose code ends in ``:approve`` — a checker. Approving
   is the act segregation of duties protects; a password alone is not enough for it.

**Exemptions.** SSO sign-ins never pass through the password login, so the policy is
not applied to them: the identity provider owns the second factor, and asking for a
second TOTP on top of the bank's own IdP MFA only teaches people to click through. LDAP /
Active Directory users *are* subject to it — a directory bind is still just a password.

**Grace, then enrol-only.** The first time a user who must enrol signs in without
having done so, ``User.mfa_grace_until`` is stamped ``now + mfa_grace_days``. Until then
they sign in normally and the response carries ``mfa_enrolment_due``. After it, the
login issues a token carrying :data:`ENROL_ONLY_CLAIM`; with that token the API answers
only the paths in :data:`ENROL_ONLY_PATHS` and refuses everything else with 403
:data:`ENROL_REQUIRED_DETAIL`. Activating MFA clears the grace stamp.

Everything here is a pure function so it can be tested without a database.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Literal

#: JWT claim marking a session that may do nothing but enrol in MFA.
ENROL_ONLY_CLAIM = "mfa_enrol_only"
#: Machine-readable reason, sent as the ``X-Error-Code`` header on the 403.
ENROL_REQUIRED_CODE = "mfa_enrolment_required"
#: What the user reads. The frontend matches on this text when the header is not exposed.
ENROL_REQUIRED_DETAIL = "Set up two-factor authentication to continue."

#: API paths (suffixes, below ``/api/v1``) an enrol-only session may reach.
ENROL_ONLY_PATHS: tuple[str, ...] = (
    "/auth/me",
    "/auth/mfa/setup",
    "/auth/mfa/activate",
    "/auth/logout",
)

#: A permission code with this suffix makes its holder a checker, and so privileged.
PRIVILEGED_PERMISSION_SUFFIX = ":approve"

EnrolmentState = Literal["not_required", "enrolled", "grace", "enrol_only"]


def is_privileged(
    role_names: Iterable[str],
    permission_codes: Iterable[str],
    required_roles: Iterable[str],
) -> bool:
    """True when a role is in ``required_roles`` (case-insensitive) or any permission
    code ends in ``:approve``."""
    wanted = {r.strip().lower() for r in required_roles if r and r.strip()}
    if any((name or "").strip().lower() in wanted for name in role_names):
        return True
    return any((code or "").endswith(PRIVILEGED_PERMISSION_SUFFIX) for code in permission_codes)


def mfa_required_for(
    *,
    role_names: Iterable[str],
    permission_codes: Iterable[str],
    global_required: bool,
    required_roles: Iterable[str],
) -> bool:
    """Whether a password sign-in by this user must be backed by MFA."""
    if global_required:
        return True
    return is_privileged(role_names, permission_codes, required_roles)


def user_requires_mfa(user, settings) -> bool:
    """:func:`mfa_required_for` applied to a ``User`` and the app settings."""
    return mfa_required_for(
        role_names=user.role_names,
        permission_codes=user.permission_codes,
        global_required=settings.mfa_required,
        required_roles=settings.mfa_required_roles,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def enrolment_state(
    *,
    required: bool,
    mfa_enabled: bool,
    grace_until: datetime | None,
    now: datetime,
    grace_days: int,
) -> tuple[EnrolmentState, datetime | None]:
    """Where this user stands, and the grace deadline that applies.

    Returns ``(state, grace_until)``. When ``grace_until`` was ``None`` and enrolment is
    required, the returned deadline is the one to stamp on the user (``now`` plus the
    grace period). ``grace_days <= 0`` means no grace: enrol-only from the first login.
    """
    if not required:
        return "not_required", None
    if mfa_enabled:
        return "enrolled", None
    now = _aware(now)
    deadline = _aware(grace_until)
    if deadline is None:
        deadline = now + timedelta(days=max(0, grace_days))
    if now < deadline:
        return "grace", deadline
    return "enrol_only", deadline


def enrol_only_path_allowed(path: str) -> bool:
    """Whether an enrol-only session may call ``path`` (the request URL path)."""
    normalised = (path or "").split("?", 1)[0].rstrip("/")
    return any(normalised.endswith(suffix) for suffix in ENROL_ONLY_PATHS)
