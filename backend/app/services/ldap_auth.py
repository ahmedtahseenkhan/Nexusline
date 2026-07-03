"""LDAP / Active Directory bind authentication.

Two-step bind: (1) connect with the service account and search for the user by
``user_filter`` to resolve their DN and read display attributes; (2) re-bind as that
DN with the supplied password to prove the credentials. Returns the directory
profile on success or ``None`` on bad credentials.

``ldap3`` is imported lazily so the application runs without it (SaaS / local-auth
deployments); on-prem bundles that enable LDAP must include the package. A missing
package surfaces as a clear 501 rather than an import-time crash.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from app.models.ldap_config import LdapConfig


@dataclass(frozen=True)
class LdapProfile:
    email: str
    full_name: str


def _require_ldap3():
    try:
        import ldap3  # noqa: PLC0415 - intentional lazy import
    except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="LDAP authentication requires the 'ldap3' package to be installed on the server.",
        ) from exc
    return ldap3


def authenticate(config: LdapConfig, username: str, password: str) -> LdapProfile | None:
    """Verify credentials against the directory; return the profile or None.

    ``None`` means the directory rejected the credentials (or the user was not found).
    Connection/config errors raise so the caller can distinguish "wrong password" from
    "directory unreachable".
    """
    if not password:
        return None
    ldap3 = _require_ldap3()

    server = ldap3.Server(
        config.host,
        port=config.port,
        use_ssl=config.use_ssl,
        get_info=ldap3.NONE,
    )

    # (1) Service-account bind + search for the user DN.
    try:
        svc = ldap3.Connection(
            server, user=config.bind_dn or None, password=config.bind_password or None,
            auto_bind=True,
        )
        if config.start_tls and not config.use_ssl:
            svc.start_tls()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Directory service unavailable: {exc}",
        ) from exc

    try:
        search_filter = config.user_filter.replace("{username}", _escape(username))
        attrs = [a for a in (config.email_attribute, config.name_attribute) if a]
        svc.search(config.base_dn, search_filter, attributes=attrs)
        if not svc.entries:
            return None
        entry = svc.entries[0]
        user_dn = entry.entry_dn
        email = _attr(entry, config.email_attribute) or username
        full_name = _attr(entry, config.name_attribute) or email
    finally:
        svc.unbind()

    # (2) Re-bind as the user to verify the password.
    try:
        user_conn = ldap3.Connection(server, user=user_dn, password=password, auto_bind=True)
        if config.start_tls and not config.use_ssl:
            user_conn.start_tls()
        user_conn.unbind()
    except Exception:  # noqa: BLE001 - any bind failure == invalid credentials
        return None

    return LdapProfile(email=str(email), full_name=str(full_name))


def _attr(entry, name: str) -> str:
    if not name:
        return ""
    try:
        value = entry[name].value
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "")


def _escape(value: str) -> str:
    """Escape LDAP filter special characters (RFC 4515) to prevent filter injection."""
    out = []
    for ch in value:
        if ch in "\\*()\0":
            out.append("\\%02x" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)
