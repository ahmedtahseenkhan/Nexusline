"""Who must use two-factor authentication, and what an unenrolled session may do.

``settings.mfa_required`` existed for a long time without anything reading it, so a
bank that switched it on got nothing. This module is the policy; the login flow
(``api/v1/auth.py``) and the token dependency (``core/deps.py``) apply it.

**Enforcement level** (:func:`effective_mode`). Each organisation runs at one of three
levels: ``off`` (nobody is made to enrol; people who enrolled keep being asked for their
code, and may switch it off themselves), ``privileged`` (the rules below) or ``everyone``
(every password sign-in). The deployment sets the default (``MFA_ENFORCEMENT``, else
``everyone`` when the legacy ``MFA_REQUIRED`` is true, else ``privileged``); an
organisation may pick its own under Settings → Organisation → Security
(``TenantSettings.mfa_enforcement``) unless the deployment locks it
(``MFA_ENFORCEMENT_LOCKED``), which a bank does when its IT security policy, not its GRC
team, owns the decision.

**Who must enrol** (:func:`mfa_required_for`), first match wins:

1. The level is ``everyone`` → every user who signs in with a password.
2. The user holds a role named in the organisation's required roles (compared
   case-insensitively). An organisation sets that list itself under Settings →
   Organisation → Security (``TenantSettings.mfa_required_roles``); until it does
   (``NULL``) the deployment default ``settings.mfa_required_roles`` applies (default
   ``["admin"]``, which matches the seeded ``Admin`` role). See
   :func:`effective_required_roles`: an organisation may add roles but may never drop
   the administrator role (:data:`PROTECTED_ROLES`).
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

Everything above the database helpers at the end is a pure function so it can be
tested without a database.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Literal, NamedTuple

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

#: Enforcement levels, weakest first.
Mode = Literal["off", "privileged", "everyone"]
MODES: tuple[Mode, ...] = ("off", "privileged", "everyone")
#: Spellings accepted from ``.env`` and the API, mapped to the canonical level.
_MODE_ALIASES: dict[str, Mode] = {
    "off": "off", "none": "off", "disabled": "off", "optional": "off",
    "privileged": "privileged", "roles": "privileged",
    "everyone": "everyone", "all": "everyone", "everybody": "everyone", "required": "everyone",
}


def normalise_mode(value: object) -> Mode | None:
    """The canonical enforcement level for a stored or typed value, or ``None`` when it
    is empty or unknown (an unknown value never makes the policy stricter or looser: the
    deployment default applies instead)."""
    if not isinstance(value, str):
        return None
    return _MODE_ALIASES.get(value.strip().lower())


def deployment_mode(settings) -> Mode:
    """The level this deployment defaults every organisation to: ``MFA_ENFORCEMENT``
    when set, else ``everyone`` if the legacy ``MFA_REQUIRED`` is true, else
    ``privileged``."""
    explicit = normalise_mode(getattr(settings, "mfa_enforcement", None))
    if explicit is not None:
        return explicit
    return "everyone" if getattr(settings, "mfa_required", False) else "privileged"


def effective_mode(tenant_mode: object, settings) -> Mode:
    """The level one organisation actually runs at: its own choice, unless it made none
    or the deployment locks the level (``MFA_ENFORCEMENT_LOCKED``)."""
    base = deployment_mode(settings)
    if getattr(settings, "mfa_enforcement_locked", False):
        return base
    return normalise_mode(tenant_mode) or base


def _mode_from(global_required: bool, mode: Mode | None) -> Mode:
    if mode is not None:
        return mode
    return "everyone" if global_required else "privileged"


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
    mode: Mode | None = None,
) -> bool:
    """Whether a password sign-in by this user must be backed by MFA.

    ``mode`` is the organisation's effective level; when omitted, ``global_required``
    stands in for it (``everyone`` when true, else ``privileged``).
    """
    level = _mode_from(global_required, mode)
    if level == "off":
        return False
    if level == "everyone":
        return True
    return is_privileged(role_names, permission_codes, required_roles)


#: Roles an organisation can never take off its MFA list (compared case-insensitively).
#: Administrators can grant themselves any permission, so a stolen administrator password
#: is the whole bank; a Pakistani bank's IT security policy asks for MFA on it regardless.
PROTECTED_ROLES: tuple[str, ...] = ("admin",)


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


def effective_required_roles(
    tenant_roles: Iterable[str] | None, deployment_roles: Iterable[str]
) -> list[str]:
    """The role names that must use MFA in one organisation.

    ``tenant_roles`` is the organisation's own list (``None`` = not set, use the
    deployment default). The protected roles are always included, whatever either list
    says. Order is kept, duplicates (case-insensitive) dropped.
    """
    source = list(deployment_roles) if tenant_roles is None else list(tenant_roles)
    out: list[str] = []
    seen: set[str] = set()
    for name in [*source, *PROTECTED_ROLES]:
        key = _norm(name)
        if key and key not in seen:
            seen.add(key)
            out.append(name.strip())
    return out


def validate_required_roles(
    requested: Iterable[str], existing_role_names: Iterable[str]
) -> tuple[list[str], str | None]:
    """Check an organisation's requested MFA role list against its roles.

    Returns ``(roles, problem)``. ``roles`` uses each role's own spelling, keeps the
    protected roles (added when they exist and were left out) and drops duplicates;
    ``problem`` is the message to show when a name matches no role.
    """
    by_key = {_norm(n): n for n in existing_role_names if _norm(n)}
    unknown = sorted({r.strip() for r in requested if _norm(r) and _norm(r) not in by_key})
    if unknown:
        return [], f"No role is called {', '.join(unknown)}. Choose from the organisation's roles."
    out: list[str] = []
    seen: set[str] = set()
    protected = [by_key[k] for k in PROTECTED_ROLES if k in by_key]
    for name in [*(by_key[_norm(r)] for r in requested if _norm(r)), *protected]:
        if _norm(name) not in seen:
            seen.add(_norm(name))
            out.append(name)
    return out, None


def is_protected_role(name: str) -> bool:
    return _norm(name) in PROTECTED_ROLES


RoleReason = Literal["everyone", "protected", "listed", "approves", "not_required"]


def role_requirement(
    *,
    role_name: str,
    permission_codes: Iterable[str],
    required_roles: Iterable[str],
    global_required: bool,
    mode: Mode | None = None,
) -> RoleReason:
    """Why holders of this role must (or need not) use MFA, for the settings screen.

    ``everyone`` — the level requires MFA for all; ``protected`` — the administrator
    role, which cannot be taken off; ``listed`` — the organisation (or deployment default)
    names it; ``approves`` — it is not listed but holds an ``:approve`` permission, so
    its holders are checkers and must use MFA anyway; ``not_required`` (always, when the
    level is ``off``).
    """
    level = _mode_from(global_required, mode)
    if level == "off":
        return "not_required"
    if level == "everyone":
        return "everyone"
    if is_protected_role(role_name):
        return "protected"
    if _norm(role_name) in {_norm(r) for r in required_roles}:
        return "listed"
    if any((c or "").endswith(PRIVILEGED_PERMISSION_SUFFIX) for c in permission_codes):
        return "approves"
    return "not_required"


def user_requires_mfa(
    user, settings, tenant_roles: Iterable[str] | None = None, tenant_mode: object = None
) -> bool:
    """:func:`mfa_required_for` applied to a ``User``, the app settings and the
    organisation's own role list and enforcement level (``None`` = the deployment
    default for each)."""
    return mfa_required_for(
        role_names=user.role_names,
        permission_codes=user.permission_codes,
        global_required=getattr(settings, "mfa_required", False),
        required_roles=effective_required_roles(tenant_roles, settings.mfa_required_roles),
        mode=effective_mode(tenant_mode, settings),
    )


UserMfaStatus = Literal["enabled", "required", "overdue", "identity_provider", "not_required"]


def user_mfa_status(
    *,
    required: bool,
    mfa_enabled: bool,
    grace_until: datetime | None,
    now: datetime,
    signs_in_with_sso: bool = False,
) -> tuple[UserMfaStatus, datetime | None]:
    """What the Users list shows in its MFA column, and the deadline that goes with it.

    ``enabled`` beats everything. A user who signs in through the organisation's single
    sign-on is ``identity_provider``: the IdP enforces the second factor and this policy
    never sees those sign-ins. Otherwise a required user is ``required`` (with the grace
    deadline, ``None`` when they have not signed in since it became required) or
    ``overdue`` once the deadline has passed.
    """
    if mfa_enabled:
        return "enabled", None
    if signs_in_with_sso:
        return "identity_provider", None
    if not required:
        return "not_required", None
    deadline = _aware(grace_until)
    if deadline is not None and _aware(now) >= deadline:
        return "overdue", deadline
    return "required", deadline


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


# ------------------------------------------------------------------ database helpers ---
class TenantPolicy(NamedTuple):
    """An organisation's own MFA choices; ``None`` = the deployment default applies."""

    mode: Mode | None
    roles: list[str] | None


async def tenant_policy(db, tenant_id=None) -> TenantPolicy:
    """The organisation's enforcement level and MFA role list, in one read.

    Reads through the session's tenant scope (RLS) when ``tenant_id`` is omitted; pass it
    from a tenant-less session (the login flow). Never raises for a missing row or a
    database that predates the columns — the deployment default applies then.
    """
    from sqlalchemy import select

    from app.models.settings import TenantSettings

    stmt = select(TenantSettings.mfa_enforcement, TenantSettings.mfa_required_roles)
    if tenant_id is not None:
        stmt = stmt.where(TenantSettings.tenant_id == tenant_id)
    try:
        async with db.begin_nested():
            row = (await db.execute(stmt.limit(1))).first()
    except Exception:  # noqa: BLE001 - an unpatched schema must not stop sign-in
        return TenantPolicy(None, None)
    if row is None:
        return TenantPolicy(None, None)
    mode, roles = row
    return TenantPolicy(normalise_mode(mode), list(roles) if isinstance(roles, list) else None)


async def tenant_required_roles(db, tenant_id=None) -> list[str] | None:
    """The organisation's own MFA role list, or ``None`` when it has not set one.

    Reads through the session's tenant scope (RLS) when ``tenant_id`` is omitted; pass it
    from a tenant-less session (the login flow). Never raises for a missing row or a
    database that predates the column — the deployment default applies then.
    """
    from sqlalchemy import select

    from app.models.settings import TenantSettings

    stmt = select(TenantSettings.mfa_required_roles)
    if tenant_id is not None:
        stmt = stmt.where(TenantSettings.tenant_id == tenant_id)
    try:
        async with db.begin_nested():
            value = await db.scalar(stmt.limit(1))
    except Exception:  # noqa: BLE001 - an unpatched schema must not stop sign-in
        return None
    return list(value) if isinstance(value, list) else None


async def sso_enabled(db) -> bool:
    """Whether the organisation signs people in through its identity provider."""
    from sqlalchemy import select

    from app.models.sso import SsoConfig

    try:
        async with db.begin_nested():
            return bool(await db.scalar(select(SsoConfig.enabled).limit(1)))
    except Exception:  # noqa: BLE001 - no SSO table / row: no SSO
        return False


async def sso_signers(db, user_ids) -> set:
    """Users whose most recent successful sign-in went through single sign-on.

    Accounts created by SSO look like local accounts (``auth_source`` stays ``local``),
    so the sign-in trail is what tells them apart: the ``login`` entries carry the method.
    """
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.services.audit import AUTH_ENTITY

    ids = [i for i in user_ids if i is not None]
    if not ids:
        return set()
    rows = (await db.execute(
        select(AuditLog.actor_id, AuditLog.changes)
        .where(
            AuditLog.entity_type == AUTH_ENTITY,
            AuditLog.action == "login",
            AuditLog.actor_id.in_(ids),
        )
        .order_by(AuditLog.actor_id, AuditLog.created_at.desc())
        .distinct(AuditLog.actor_id)
    )).all()
    return {uid for uid, changes in rows if (changes or {}).get("method") == "sso"}


async def statuses_for(db, users, settings, *, now: datetime | None = None) -> dict:
    """``{user_id: (status, deadline)}`` for the Users list's MFA column
    (:func:`user_mfa_status`), reading the organisation's role list once."""
    now = now or datetime.now(timezone.utc)
    policy = await tenant_policy(db)
    sso = await sso_signers(db, [u.id for u in users]) if await sso_enabled(db) else set()
    return {
        u.id: user_mfa_status(
            required=user_requires_mfa(u, settings, policy.roles, policy.mode),
            mfa_enabled=u.mfa_enabled,
            grace_until=u.mfa_grace_until,
            now=now,
            signs_in_with_sso=u.id in sso,
        )
        for u in users
    }
