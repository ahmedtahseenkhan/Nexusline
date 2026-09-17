"""Active Directory / LDAP checks, pure LDAP reads (``ldap3``, already a dependency).

Every check asks the directory with a narrowing LDAP filter and then re-applies the rule
in Python to what came back, so the rule is unit-testable with a fake connection (any
object with ``search(search_base, search_filter, search_scope=, attributes=, paged_size=,
paged_cookie=)`` that fills ``response`` and ``result``) and a directory that ignores
part of a filter cannot pass an account the rule would fail.

Connector ``config``: ``host``, ``port`` (389/636), ``use_ssl``, ``start_tls``,
``verify_tls`` (default true), ``ca_cert_path``, ``base_dn``, ``bind_dn``; secret
``bind_password``. The bind account needs read access only; connections are read-only.

What LDAP cannot show is said in the check's pass criterion (e.g. Group Policy "deny
log on locally" rights are not directory attributes).
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.services.ccm_checks.base import (
    CheckContext,
    CheckError,
    CheckOutcome,
    CheckSpec,
    ConnectionFailure,
    Param,
    as_int,
    as_list,
)

UAC_DISABLED = 0x2
UAC_DONT_EXPIRE_PASSWORD = 0x10000
#: Enabled user accounts (AD matching-rule OID for a bitwise AND on userAccountControl).
ENABLED_USERS = "(&(objectCategory=person)(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
PAGED_OID = "1.2.840.113556.1.4.319"
NESTED_MEMBER_OID = "1.2.840.113556.1.4.1941"
PAGE_SIZE = 500
MAX_ENTRIES = 250_000
_NEVER = (0, 0x7FFFFFFFFFFFFFFF)
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------- connection ---
def open_connection(config: dict, secrets: dict, timeout: float):
    """A bound, read-only ldap3 connection, or :class:`ConnectionFailure`."""
    try:
        import ssl

        import ldap3
    except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
        raise CheckError("The server has no 'ldap3' package, so directory checks cannot run.") from exc
    host = str(config.get("host") or "").strip()
    if not host:
        raise CheckError("The connector has no directory host.")
    use_ssl = bool(config.get("use_ssl"))
    port = as_int(config.get("port"), 636 if use_ssl else 389)
    tls = ldap3.Tls(
        validate=ssl.CERT_REQUIRED if config.get("verify_tls", True) else ssl.CERT_NONE,
        ca_certs_file=(config.get("ca_cert_path") or None),
    )
    server = ldap3.Server(host, port=port, use_ssl=use_ssl, tls=tls, get_info=ldap3.NONE,
                          connect_timeout=max(1, int(timeout)))
    try:
        conn = ldap3.Connection(
            server, user=(config.get("bind_dn") or None), password=(secrets.get("bind_password") or None),
            read_only=True, receive_timeout=max(1, int(timeout)), raise_exceptions=False,
        )
        if not conn.open():
            raise ConnectionFailure(f"Could not reach {host}:{port}: {conn.last_error or 'no response'}.")
        if config.get("start_tls") and not use_ssl and not conn.start_tls():
            raise ConnectionFailure(f"StartTLS to {host}:{port} failed: {conn.last_error or conn.result}.")
        if not conn.bind():
            desc = (conn.result or {}).get("description") or conn.last_error or "bind refused"
            raise ConnectionFailure(f"The directory refused the bind as {config.get('bind_dn') or 'anonymous'}: {desc}.")
    except ConnectionFailure:
        raise
    except Exception as exc:  # noqa: BLE001 - socket / TLS errors
        raise ConnectionFailure(f"Could not connect to {host}:{port}: {exc}.") from exc
    return conn


def connect(ctx: CheckContext):
    factory = ctx.ldap_factory or open_connection
    return factory(ctx.config, ctx.secrets, ctx.timeout)


def close(conn) -> None:
    try:
        conn.unbind()
    except Exception:  # noqa: BLE001
        pass


def search(conn, base: str, flt: str, attributes: Iterable[str], *, scope: str = "SUBTREE") -> list[dict]:
    """All entries (paged), each ``{"dn": …, attribute: value…}``. Raises CheckError on a
    directory error."""
    out: list[dict] = []
    cookie = None
    while True:
        ok = conn.search(search_base=base, search_filter=flt, search_scope=scope, attributes=list(attributes),
                         paged_size=PAGE_SIZE, paged_cookie=cookie)
        result = getattr(conn, "result", None) or {}
        if ok is False and result.get("result") not in (0, 4, None):  # 4 = size limit, keep what came
            raise CheckError(f"Directory search under {base} failed: {result.get('description') or result}.")
        for entry in getattr(conn, "response", None) or []:
            if entry.get("type", "searchResEntry") != "searchResEntry":
                continue
            attrs = entry.get("attributes") or {}
            out.append({"dn": entry.get("dn", ""), **{k: v for k, v in attrs.items()}})
            if len(out) >= MAX_ENTRIES:
                raise CheckError(f"More than {MAX_ENTRIES} entries under {base}; narrow the search base.")
        cookie = (((result.get("controls") or {}).get(PAGED_OID) or {}).get("value") or {}).get("cookie")
        if not cookie:
            return out


# ------------------------------------------------------------ attribute reads ---
def first(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def values(value: Any) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def uac(entry: dict) -> int:
    return as_int(first(entry.get("userAccountControl")), 0) or 0


def is_enabled(entry: dict) -> bool:
    return not uac(entry) & UAC_DISABLED


def account_name(entry: dict) -> str:
    for key in ("sAMAccountName", "userPrincipalName", "cn"):
        v = first(entry.get(key))
        if v:
            return str(v)
    return str(entry.get("dn", ""))


def ad_time(value: Any) -> datetime | None:
    """A FILETIME integer, a generalized-time string or a datetime → aware UTC datetime."""
    v = first(value)
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    text = str(v).strip()
    if text.lstrip("-").isdigit():
        n = int(text)
        if n in _NEVER or n < 0:
            return None
        if n > 10**14:  # FILETIME: 100-nanosecond intervals since 1601
            return _FILETIME_EPOCH + timedelta(microseconds=n // 10)
        return None
    for fmt in ("%Y%m%d%H%M%S.%fZ", "%Y%m%d%H%M%SZ", "%Y%m%d%H%M%S.0Z"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def escape(value: str) -> str:
    """RFC 4515 filter escaping."""
    out = []
    for ch in value:
        if ch in "\\*()\0":
            out.append("\\%02x" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def _base(ctx: CheckContext) -> str:
    base = str(ctx.parameters.get("search_base") or ctx.config.get("base_dn") or "").strip()
    if not base:
        raise CheckError("No search base: set the connector's base DN or the test's search base.")
    return base


def _norm_set(items: Iterable[str]) -> set[str]:
    return {str(i).strip().lower() for i in items if str(i).strip()}


def _row(entry: dict, **extra) -> dict:
    return {"account": account_name(entry), "dn": str(entry.get("dn", "")), **extra}


def _day(dt: datetime | None) -> str:
    return dt.date().isoformat() if dt else ""


# ------------------------------------------------------------------- checks ---
def privileged_group_members(ctx: CheckContext) -> CheckOutcome:
    """Members of privileged groups who are not on the approved list."""
    p = ctx.parameters
    groups = as_list(p.get("groups"))
    if not groups:
        raise CheckError("List the privileged groups to check.")
    approved = _norm_set(as_list(p.get("approved_accounts")))
    nested = p.get("include_nested", True) not in (False, "false", "no")
    include_disabled = p.get("include_disabled") in (True, "true", "yes")
    base = _base(ctx)
    conn = connect(ctx)
    try:
        members: dict[str, dict] = {}
        missing: list[str] = []
        for group in groups:
            if "=" in group:
                group_dn = group
            else:
                found = search(conn, base, f"(&(objectClass=group)(|(cn={escape(group)})(sAMAccountName={escape(group)})))",
                               ["cn"])
                if not found:
                    missing.append(group)
                    continue
                group_dn = str(found[0]["dn"])
            rule = f":{NESTED_MEMBER_OID}:" if nested else ""
            flt = f"(&(objectClass=user)(memberOf{rule}={escape(group_dn)}))"
            for entry in search(conn, base, flt, ["sAMAccountName", "userAccountControl", "displayName", "memberOf"]):
                key = account_name(entry).lower()
                row = members.setdefault(key, {"entry": entry, "groups": []})
                row["groups"].append(group)
    finally:
        close(conn)
    if missing:
        raise CheckError(f"Group(s) not found in the directory: {', '.join(missing)}.")
    population = [m for m in members.values() if include_disabled or is_enabled(m["entry"])]
    exceptions = [
        _row(m["entry"], groups=", ".join(sorted(set(m["groups"]))), enabled=is_enabled(m["entry"]),
             issue="not on the approved list")
        for m in population if account_name(m["entry"]).lower() not in approved
    ]
    exceptions.sort(key=lambda r: r["account"].lower())
    return CheckOutcome(
        population=len(population), exceptions=exceptions,
        summary=(f"{len(exceptions)} of {len(population)} member(s) of {len(groups)} privileged group(s) "
                 "are not on the approved list"),
        details={"groups": groups, "approved_accounts": len(approved), "nested": nested},
    )


def inactive_accounts(ctx: CheckContext) -> CheckOutcome:
    """Enabled accounts with no logon in N days (lastLogonTimestamp replicates within
    9–14 days, so N below 30 is not meaningful)."""
    p = ctx.parameters
    days = as_int(p.get("days"), 90) or 90
    cutoff = ctx.now - timedelta(days=days)
    excluded = _norm_set(as_list(p.get("excluded_accounts")))
    never_counts = p.get("include_never_logged_on", True) not in (False, "false", "no")
    conn = connect(ctx)
    try:
        entries = search(conn, _base(ctx), ENABLED_USERS,
                         ["sAMAccountName", "userAccountControl", "lastLogonTimestamp", "whenCreated", "displayName"])
    finally:
        close(conn)
    population = [e for e in entries if is_enabled(e) and account_name(e).lower() not in excluded]
    exceptions = []
    for e in population:
        last = ad_time(e.get("lastLogonTimestamp"))
        created = ad_time(e.get("whenCreated"))
        if last is not None and last < cutoff:
            exceptions.append(_row(e, last_logon=_day(last), days_inactive=(ctx.now - last).days))
        elif last is None and never_counts and (created is None or created < cutoff):
            exceptions.append(_row(e, last_logon="never", created=_day(created)))
    exceptions.sort(key=lambda r: (r.get("last_logon") != "never", r.get("last_logon", "")))
    return CheckOutcome(
        population=len(population), exceptions=exceptions,
        summary=f"{len(exceptions)} of {len(population)} enabled account(s) have not logged on in {days} days",
        details={"days": days, "excluded_accounts": len(excluded)},
    )


def password_never_expires(ctx: CheckContext) -> CheckOutcome:
    """Enabled accounts whose password is set never to expire, less approved exceptions."""
    approved = _norm_set(as_list(ctx.parameters.get("approved_accounts")))
    conn = connect(ctx)
    try:
        entries = search(conn, _base(ctx), ENABLED_USERS, ["sAMAccountName", "userAccountControl", "pwdLastSet"])
    finally:
        close(conn)
    population = [e for e in entries if is_enabled(e)]
    exceptions = [
        _row(e, password_last_set=_day(ad_time(e.get("pwdLastSet"))))
        for e in population
        if uac(e) & UAC_DONT_EXPIRE_PASSWORD and account_name(e).lower() not in approved
    ]
    exceptions.sort(key=lambda r: r["account"].lower())
    return CheckOutcome(
        population=len(population), exceptions=exceptions,
        summary=f"{len(exceptions)} of {len(population)} enabled account(s) have a password that never expires",
        details={"approved_accounts": len(approved)},
    )


def _leavers_from_file(ctx: CheckContext) -> list[str]:
    if ctx.file is None:
        return []
    text = ctx.file.content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    column = str(ctx.parameters.get("hr_column") or "").strip()
    fields = reader.fieldnames or []
    if not fields:
        return []
    if not column:
        column = next((f for f in fields if f.strip().lower() in
                       ("samaccountname", "username", "user id", "userid", "email", "mail", "employee id", "employeeid")),
                      fields[0])
    if column not in fields:
        raise CheckError(f"The HR file has no column '{column}' (columns: {', '.join(fields)}).")
    return [str(row.get(column) or "").strip() for row in reader if str(row.get(column) or "").strip()]


def leavers_still_enabled(ctx: CheckContext) -> CheckOutcome:
    """Leavers whose accounts are still enabled — from an HR leavers list (parameter or
    uploaded CSV) matched on an attribute, or every enabled account under a leavers OU."""
    p = ctx.parameters
    mode = str(p.get("mode") or "hr_list")
    conn = connect(ctx)
    try:
        if mode == "leavers_ou":
            ou = str(p.get("leavers_ou") or "").strip()
            if not ou:
                raise CheckError("Set the leavers OU.")
            entries = search(conn, ou, "(&(objectCategory=person)(objectClass=user))",
                             ["sAMAccountName", "userAccountControl", "whenChanged"])
            exceptions = [_row(e, issue="enabled in the leavers OU") for e in entries if is_enabled(e)]
            return CheckOutcome(
                population=len(entries), exceptions=sorted(exceptions, key=lambda r: r["account"].lower()),
                summary=f"{len(exceptions)} of {len(entries)} account(s) in the leavers OU are still enabled",
                details={"mode": mode, "leavers_ou": ou},
            )
        attribute = str(p.get("match_attribute") or "sAMAccountName")
        leavers = as_list(p.get("leavers")) + _leavers_from_file(ctx)
        wanted = {x.lower(): x for x in leavers}
        if not wanted:
            raise CheckError("No leavers to check: upload the HR leavers file or list the accounts.")
        entries = search(conn, _base(ctx), ENABLED_USERS, ["sAMAccountName", "userAccountControl", attribute])
    finally:
        close(conn)
    by_value: dict[str, dict] = {}
    for e in entries:
        for v in values(e.get(attribute)):
            by_value.setdefault(str(v).strip().lower(), e)
    exceptions = [
        _row(by_value[k], leaver=wanted[k], matched_on=attribute, issue="leaver's account is enabled")
        for k in sorted(wanted) if k in by_value and is_enabled(by_value[k])
    ]
    return CheckOutcome(
        population=len(wanted), exceptions=exceptions,
        summary=f"{len(exceptions)} of {len(wanted)} leaver(s) still have an enabled account",
        details={"mode": mode, "match_attribute": attribute,
                 "source": ctx.file.filename if ctx.file is not None else "parameters"},
    )


def service_accounts_interactive(ctx: CheckContext) -> CheckOutcome:
    """Enabled service accounts that can log on interactively as far as the directory
    shows: not restricted to named hosts (``userWorkstations`` empty) or a member of a
    group that grants interactive or remote logon."""
    p = ctx.parameters
    prefixes = [x.lower() for x in as_list(p.get("name_prefixes"))]
    ou = str(p.get("service_accounts_ou") or "").strip()
    if not ou and not prefixes:
        raise CheckError("Say how service accounts are recognised: their OU or their name prefixes.")
    interactive_groups = _norm_set(as_list(p.get("interactive_groups")))
    require_restriction = p.get("require_workstation_restriction", True) not in (False, "false", "no")
    base = ou or _base(ctx)
    if prefixes and not ou:
        flt = "(&(objectClass=user)(|" + "".join(f"(sAMAccountName={escape(x)}*)" for x in prefixes) + "))"
    else:
        flt = "(&(objectClass=user)(objectCategory=person))"
    conn = connect(ctx)
    try:
        entries = search(conn, base, flt, ["sAMAccountName", "userAccountControl", "userWorkstations", "memberOf"])
    finally:
        close(conn)
    population = [e for e in entries if is_enabled(e)
                  and (not prefixes or any(account_name(e).lower().startswith(x) for x in prefixes))]
    exceptions = []
    for e in population:
        reasons = []
        if require_restriction and not str(first(e.get("userWorkstations")) or "").strip():
            reasons.append("not restricted to named hosts")
        groups = [str(g) for g in values(e.get("memberOf"))]
        hits = [g for g in groups if g.strip().lower() in interactive_groups
                or _cn(g).lower() in interactive_groups]
        if hits:
            reasons.append("member of " + ", ".join(_cn(g) for g in hits))
        if reasons:
            exceptions.append(_row(e, issue="; ".join(reasons)))
    exceptions.sort(key=lambda r: r["account"].lower())
    return CheckOutcome(
        population=len(population), exceptions=exceptions,
        summary=f"{len(exceptions)} of {len(population)} service account(s) can log on interactively",
        details={"search_base": base, "name_prefixes": prefixes, "interactive_groups": sorted(interactive_groups)},
    )


def _cn(dn: str) -> str:
    head = dn.split(",", 1)[0]
    return head.split("=", 1)[1] if "=" in head else head


def connection_test(config: dict, secrets: dict, timeout: float, factory=None) -> str:
    """Bind and read the base DN; the sentence to show, or ConnectionFailure."""
    conn = (factory or open_connection)(config, secrets, timeout)
    try:
        base = str(config.get("base_dn") or "").strip()
        if base:
            conn.search(search_base=base, search_filter="(objectClass=*)", search_scope="BASE", attributes=["objectClass"])
            if not (getattr(conn, "response", None) or []):
                raise ConnectionFailure(f"Bound, but the base DN {base} cannot be read with this account.")
        who = config.get("bind_dn") or "anonymous"
        return f"Bound as {who}" + (f" and read {base}." if base else "; no base DN set yet.")
    finally:
        close(conn)


_AD = ("active_directory",)
_SEARCH_BASE = Param("search_base", "Search base", help="Distinguished name to search under. Blank = the connector's base DN.")

SPECS = (
    CheckSpec(
        key="ad_privileged_group_members", label="Privileged group members not approved", group="Active Directory",
        description="Lists the members of privileged groups (nested membership included) and flags anyone not on the approved list.",
        connector_types=_AD, input="connector",
        params=(
            Param("groups", "Privileged groups", "list", required=True, default=["Domain Admins", "Enterprise Admins", "Schema Admins"],
                  help="Group names or distinguished names, one per line."),
            Param("approved_accounts", "Approved members", "list", help="sAMAccountNames approved for these groups, one per line."),
            Param("include_nested", "Include nested membership", "bool", default=True),
            Param("include_disabled", "Count disabled members", "bool", default=False),
            _SEARCH_BASE,
        ),
        pass_criterion="Every enabled member of the privileged groups is on the approved list.",
        population="Enabled members of the listed privileged groups.",
        run=privileged_group_members,
    ),
    CheckSpec(
        key="ad_inactive_accounts", label="Enabled accounts inactive", group="Active Directory",
        description="Flags enabled accounts whose last logon (lastLogonTimestamp) is older than the set number of days, or that never logged on.",
        connector_types=_AD, input="connector",
        params=(
            Param("days", "Inactive after (days)", "number", required=True, default=90,
                  help="lastLogonTimestamp replicates every 9–14 days, so use 30 or more."),
            Param("include_never_logged_on", "Count accounts that never logged on", "bool", default=True),
            Param("excluded_accounts", "Excluded accounts", "list", help="Break-glass or other approved accounts, one per line."),
            _SEARCH_BASE,
        ),
        pass_criterion="No enabled account has gone without a logon for longer than the set number of days.",
        population="Enabled user accounts under the search base.",
        run=inactive_accounts,
    ),
    CheckSpec(
        key="ad_password_never_expires", label="Passwords set never to expire", group="Active Directory",
        description="Flags enabled accounts with the 'password never expires' flag, less the approved exceptions.",
        connector_types=_AD, input="connector",
        params=(
            Param("approved_accounts", "Approved exceptions", "list", help="Accounts approved to keep a non-expiring password, one per line."),
            _SEARCH_BASE,
        ),
        pass_criterion="No enabled account outside the approved exceptions has a password set never to expire.",
        population="Enabled user accounts under the search base.",
        run=password_never_expires,
    ),
    CheckSpec(
        key="ad_leavers_enabled", label="Leavers with enabled accounts", group="Active Directory",
        description="Matches an HR leavers list (uploaded CSV or listed accounts) to enabled accounts, or checks a leavers OU for enabled accounts.",
        connector_types=_AD, input="connector_or_file",
        params=(
            Param("mode", "Leavers come from", "select", default="hr_list", options=("hr_list", "leavers_ou"),
                  help="hr_list: an HR file or list; leavers_ou: accounts moved to a leavers OU."),
            Param("match_attribute", "Match HR identifiers on", "select", default="sAMAccountName",
                  options=("sAMAccountName", "mail", "userPrincipalName", "employeeID")),
            Param("hr_column", "HR file column", help="Column of the uploaded HR CSV holding the identifier. Blank = detected."),
            Param("leavers", "Leavers", "list", help="Identifiers, one per line (in addition to an uploaded file)."),
            Param("leavers_ou", "Leavers OU", help="Distinguished name of the OU leavers are moved to."),
            _SEARCH_BASE,
        ),
        pass_criterion="No leaver has an enabled directory account.",
        population="Leavers in the HR list (or accounts in the leavers OU).",
        run=leavers_still_enabled,
    ),
    CheckSpec(
        key="ad_service_accounts_interactive", label="Service accounts able to log on interactively", group="Active Directory",
        description=("Flags enabled service accounts not restricted to named hosts, or in a group that grants interactive "
                     "or remote logon. Group Policy logon rights are not visible over LDAP."),
        connector_types=_AD, input="connector",
        params=(
            Param("service_accounts_ou", "Service accounts OU", help="Distinguished name of the OU holding service accounts."),
            Param("name_prefixes", "Name prefixes", "list", default=["svc_", "svc-"], help="Used when no OU is set, one per line."),
            Param("interactive_groups", "Interactive-logon groups", "list", default=["Remote Desktop Users", "Domain Admins"],
                  help="Group names or DNs whose members can log on interactively."),
            Param("require_workstation_restriction", "Require a named-host restriction", "bool", default=True),
        ),
        pass_criterion=("Every enabled service account is restricted to named hosts and is in no interactive-logon group "
                        "(as recorded in the directory; deny-logon rights set by Group Policy are not checked)."),
        population="Enabled service accounts (by OU or name prefix).",
        run=service_accounts_interactive,
    ),
)
