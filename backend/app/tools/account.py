"""CLI: recover an account when nobody can sign in.

An on-prem bank has no vendor to click "forgot password" for them. If the only admin's
password is lost, their authenticator is wiped, or lockout has locked everyone out, the
install is unusable and there is no path back through the UI — the reset paths all require
an authenticated session. This gives the bank's own server administrator that path.

  python -m app.tools.account list
  python -m app.tools.account show      --org acme --email admin@acme.com
  python -m app.tools.account reset-password --org acme --email admin@acme.com
  python -m app.tools.account clear-mfa --org acme --email admin@acme.com
  python -m app.tools.account unlock    --org acme --email admin@acme.com
  python -m app.tools.account deactivate --org acme --email leaver@acme.com

It needs shell access to the application server, which already implies database access, so
it grants nothing a host administrator did not have. What it does add is an audit trail:
every action writes an ``admin_*`` event naming ``cli:<os user>`` as the actor, so a reset
performed out of band is visible in the organisation's log rather than invisible.

The password is prompted for, never passed on the command line, so it stays out of shell
history and the process list. It is checked against the configured password policy.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import system_session, tenant_session
from app.core.security import hash_password
from app.models.identity import User
from app.models.tenant import Tenant
from app.services import audit, password_policy


def _actor() -> str:
    """Who ran this, as well as a shell can say: the OS account on the server."""
    try:
        return f"cli:{getpass.getuser()}"
    except Exception:
        return f"cli:uid{os.getuid()}"


async def _tenant(slug: str) -> uuid.UUID:
    async with system_session() as db:
        tid = await db.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tid is None:
        raise SystemExit(f"No organisation with slug '{slug}'. Run 'list' to see them.")
    return tid


async def _load(db, email: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        raise SystemExit(f"No user '{email}' in that organisation.")
    return user


def _describe(user: User) -> str:
    locked = "no"
    if user.locked_until is not None:
        now = datetime.now(timezone.utc)
        until = user.locked_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        locked = f"until {until:%Y-%m-%d %H:%M:%S %Z}" if until > now else f"expired ({until:%Y-%m-%d})"
    expired = password_policy.is_expired(user.password_changed_at)
    return (
        f"  active            : {'yes' if user.is_active else 'NO — cannot sign in'}\n"
        f"  auth source       : {user.auth_source}"
        + ("  (password is held in the directory, not here)" if user.auth_source == "ldap" else "") + "\n"
        f"  MFA              : {'on' if user.mfa_enabled else 'off'}"
        + ("  — the password alone will not sign in" if user.mfa_enabled else "") + "\n"
        f"  failed attempts   : {user.failed_login_attempts}\n"
        f"  locked            : {locked}\n"
        f"  password set      : "
        + (f"{user.password_changed_at:%Y-%m-%d %H:%M:%S %Z}" if user.password_changed_at
           else "never recorded (still the seeded password, unless it was changed before this field existed)")
        + ("   EXPIRED by policy" if expired else "") + "\n"
        f"  roles             : {', '.join(user.role_names) or 'none — will see almost nothing'}\n"
        f"  platform admin    : {'yes' if user.is_platform_admin else 'no'}"
    )


async def list_accounts() -> None:
    async with system_session() as db:
        tenants = (await db.execute(select(Tenant.id, Tenant.slug, Tenant.name, Tenant.is_active))).all()
    if not tenants:
        print("No organisations in this database.")
        return
    for tid, slug, name, active in tenants:
        print(f"\n{slug}  ({name}){'' if active else '   [SUSPENDED]'}")
        async with tenant_session(tid) as db:
            users = (await db.scalars(select(User).order_by(User.email))).all()
            if not users:
                print("  (no users)")
            for u in users:
                flags = []
                if not u.is_active:
                    flags.append("inactive")
                if u.mfa_enabled:
                    flags.append("MFA")
                if u.locked_until is not None:
                    flags.append("locked")
                if u.auth_source != "local":
                    flags.append(u.auth_source)
                if u.is_platform_admin:
                    flags.append("platform-admin")
                suffix = f"  [{', '.join(flags)}]" if flags else ""
                print(f"  {u.email:<30} {', '.join(u.role_names) or '(no roles)'}{suffix}")


async def show(slug: str, email: str) -> None:
    tid = await _tenant(slug)
    async with tenant_session(tid) as db:
        user = await _load(db, email)
        print(f"{email}  in '{slug}'")
        print(_describe(user))


async def reset_password(slug: str, email: str, password: str | None, clear_mfa: bool) -> None:
    tid = await _tenant(slug)
    async with tenant_session(tid) as db:
        user = await _load(db, email)
        if user.auth_source != "local":
            raise SystemExit(
                f"'{email}' authenticates against {user.auth_source}, so its password lives in the "
                f"directory. Reset it there, or switch the account to local sign-in first."
            )
        if password is None:
            password = getpass.getpass("New password: ")
            if password != getpass.getpass("Repeat: "):
                raise SystemExit("The two passwords differ — nothing changed.")
        try:
            password_policy.validate_password(password)
        except HTTPException as exc:
            raise SystemExit(str(exc.detail)) from exc

        user.hashed_password = hash_password(password)
        user.password_changed_at = datetime.now(timezone.utc)
        # A lost password and a lockout arrive together; leaving the counter set would
        # lock the account again on the next typo.
        user.failed_login_attempts = 0
        user.locked_until = None
        if not user.is_active:
            user.is_active = True
            print("The account was inactive; it has been reactivated.")
        changes: dict = {"reset_by": _actor()}
        if clear_mfa and user.mfa_enabled:
            user.mfa_enabled = False
            user.mfa_secret = ""
            user.mfa_grace_until = None
            changes["mfa"] = "cleared"
        await audit.record_auth(
            db, tenant_id=tid, actor_id=user.id, actor_email=email,
            action="admin_password_reset",
            summary=f"Password reset from the server console by {_actor()}",
            changes=changes,
        )
    print(f"Password reset for {email} in '{slug}'.")
    if clear_mfa:
        print("MFA cleared — the next sign-in will re-enrol if policy requires it.")
    elif (await _mfa_on(tid, email)):
        print("NOTE: MFA is still on for this account, so the password alone will not sign in. "
              "Add --clear-mfa if the authenticator is also lost.")
    print("Tell the holder to change it after signing in.")


async def _mfa_on(tid: uuid.UUID, email: str) -> bool:
    async with tenant_session(tid) as db:
        return bool((await _load(db, email)).mfa_enabled)


async def clear_mfa(slug: str, email: str) -> None:
    """Drop a lost authenticator. The account keeps its password."""
    tid = await _tenant(slug)
    async with tenant_session(tid) as db:
        user = await _load(db, email)
        if not user.mfa_enabled:
            print(f"MFA is already off for {email}.")
            return
        user.mfa_enabled = False
        user.mfa_secret = ""
        user.mfa_grace_until = None
        await audit.record_auth(
            db, tenant_id=tid, actor_id=user.id, actor_email=email,
            action="admin_mfa_cleared",
            summary=f"MFA enrolment cleared from the server console by {_actor()}",
            changes={"cleared_by": _actor()},
        )
    print(f"MFA cleared for {email}. They will be asked to enrol again if policy requires it.")


async def unlock(slug: str, email: str) -> None:
    tid = await _tenant(slug)
    async with tenant_session(tid) as db:
        user = await _load(db, email)
        if user.locked_until is None and user.failed_login_attempts == 0:
            print(f"{email} is not locked.")
            return
        user.failed_login_attempts = 0
        user.locked_until = None
        await audit.record_auth(
            db, tenant_id=tid, actor_id=user.id, actor_email=email,
            action="admin_account_unlocked",
            summary=f"Lockout cleared from the server console by {_actor()}",
            changes={"cleared_by": _actor()},
        )
    print(f"Unlocked {email}.")


async def deactivate(slug: str, email: str) -> None:
    """Stop an account signing in, without deleting it.

    There is deliberately no delete: a user is an actor in the audit trail, and removing
    the row would orphan every event they caused. Deactivating is what the UI does too.
    """
    tid = await _tenant(slug)
    async with tenant_session(tid) as db:
        user = await _load(db, email)
        if not user.is_active:
            print(f"{email} is already inactive.")
            return
        admins = 0
        if "Admin" in user.role_names:
            for other in (await db.scalars(select(User))).all():
                if other.id != user.id and other.is_active and "Admin" in other.role_names:
                    admins += 1
            if admins == 0:
                raise SystemExit(
                    f"'{email}' is the last active Admin in '{slug}'. Deactivating it would lock "
                    f"the organisation out. Give another user the Admin role first."
                )
        user.is_active = False
        await audit.record_auth(
            db, tenant_id=tid, actor_id=user.id, actor_email=email,
            action="admin_account_deactivated",
            summary=f"Account deactivated from the server console by {_actor()}",
            changes={"deactivated_by": _actor()},
        )
    print(f"Deactivated {email}. Reactivate with 'reset-password' or from Settings -> Users.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.account",
        description="Recover an account from the server console when nobody can sign in.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="every organisation and its users, with MFA and lock state")

    def _target(name: str, help_text: str):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--org", required=True, help="organisation slug (see 'list')")
        p.add_argument("--email", required=True)
        return p

    _target("show", "why this account cannot sign in")
    rp = _target("reset-password", "set a new password (prompted, not on the command line)")
    rp.add_argument("--clear-mfa", action="store_true",
                    help="also drop the MFA enrolment, for a lost authenticator")
    rp.add_argument("--password", help=argparse.SUPPRESS)  # non-interactive use; shows in ps
    _target("clear-mfa", "drop a lost authenticator enrolment")
    _target("unlock", "clear a lockout and the failed-attempt counter")
    _target("deactivate", "stop an account signing in (refuses the last active Admin)")

    args = parser.parse_args(argv)
    if args.cmd == "list":
        asyncio.run(list_accounts())
    elif args.cmd == "show":
        asyncio.run(show(args.org, args.email))
    elif args.cmd == "reset-password":
        asyncio.run(reset_password(args.org, args.email, args.password, args.clear_mfa))
    elif args.cmd == "clear-mfa":
        asyncio.run(clear_mfa(args.org, args.email))
    elif args.cmd == "deactivate":
        asyncio.run(deactivate(args.org, args.email))
    else:
        asyncio.run(unlock(args.org, args.email))
    return 0


if __name__ == "__main__":
    sys.exit(main())
