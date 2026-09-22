"""Product decisions 1–3 (plan §11): licence grace / read-only / seats, ten-year retention,
MFA for every password user in release builds. No database."""
from __future__ import annotations

import inspect
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core import build
from app.core.config import Settings, settings
from app.core.licence_guard import LicenceReadOnlyMiddleware, refusal
from app.services import license as lic
from app.services import licence_state as ls
from app.tools import license as lic_cli

TODAY = date(2026, 9, 17)
BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _info(expires: date | None, status: str = "valid", seats: int = 0) -> lic.LicenseInfo:
    return lic.LicenseInfo(
        valid=status == "valid", status=status, licensed_to="Test Bank", seats=seats,
        expires=expires.isoformat() if expires else "",
    )


# =========================================================== licence state machine ===
@pytest.mark.parametrize(
    "offset,state",
    [
        (365, "active"),
        (61, "active"),
        (60, "expiring"),
        (7, "expiring"),
        (0, "expiring"),      # last licensed day
        (-1, "grace"),        # first day of grace
        (-30, "grace"),       # last day of grace
        (-31, "read_only"),   # first read-only day
        (-400, "read_only"),
    ],
)
def test_state_by_date(offset, state):
    s = ls.evaluate(_info(TODAY + timedelta(days=offset)), TODAY, enforcing=True)
    assert s.state == state
    assert s.read_only is (state == "read_only")


def test_grace_counts_down_and_names_the_dates():
    expires = TODAY - timedelta(days=1)
    s = ls.evaluate(_info(expires, status="expired"), TODAY, enforcing=True)
    assert s.grace_until == expires + timedelta(days=30)
    assert s.grace_days_left == 29
    assert "16 September 2026" in s.message and "read-only" in s.message
    last = ls.evaluate(_info(expires, status="expired"), expires + timedelta(days=30), enforcing=True)
    assert last.state == "grace" and last.grace_days_left == 0


def test_read_only_message_is_the_one_the_api_returns():
    s = ls.evaluate(_info(date(2026, 7, 1), status="expired"), TODAY, enforcing=True)
    assert s.message == "The licence expired on 1 July 2026. Records are read-only until a renewed licence is installed."


def test_dev_build_reports_but_never_enforces_read_only():
    s = ls.evaluate(_info(TODAY - timedelta(days=90), status="expired"), TODAY, enforcing=False)
    assert s.state == "read_only" and not s.read_only


def test_unlicensed_invalid_and_perpetual():
    none = lic.LicenseInfo(status="unlicensed")
    assert ls.evaluate(none, TODAY, enforcing=False).state == "evaluation"
    assert ls.evaluate(none, TODAY, enforcing=True).state == "unlicensed"
    assert ls.evaluate(lic.LicenseInfo(status="invalid"), TODAY, enforcing=True).state == "invalid"
    assert ls.evaluate(_info(None), TODAY, enforcing=True).state == "active"


def test_state_is_evaluated_against_todays_date_not_the_cache(monkeypatch):
    info = _info(TODAY - timedelta(days=31), status="valid")  # cached before expiry
    monkeypatch.setattr(lic, "load_current", lambda refresh=False: info)
    monkeypatch.setattr(lic, "enforcement_enabled", lambda: True)
    assert ls.current(TODAY).read_only
    assert ls.current(TODAY - timedelta(days=1)).state == "grace"


@pytest.mark.parametrize(
    "offset,stage",
    [(90, None), (61, None), (60, "expiry-60"), (45, "expiry-60"), (30, "expiry-30"), (8, "expiry-30"),
     (7, "expiry-7"), (2, "expiry-7"), (1, "expiry-1"), (0, "expiry-1"), (-1, "grace"), (-31, "read_only")],
)
def test_notice_stages(offset, stage):
    s = ls.evaluate(_info(TODAY + timedelta(days=offset)), TODAY, enforcing=True)
    assert ls.notice_stage(s) == stage


def test_notice_key_is_per_stage_role_and_licence():
    a = ls.evaluate(_info(TODAY + timedelta(days=5)), TODAY, enforcing=True)
    b = ls.evaluate(_info(TODAY + timedelta(days=370)), TODAY, enforcing=True)
    assert ls.notice_key("expiry-7", a, "Admin") != ls.notice_key("expiry-7", b, "Admin")
    assert ls.notice_key("expiry-7", a, "Admin") != ls.notice_key("expiry-1", a, "Admin")
    assert ls.notice_key("grace", a, "Admin").startswith("event:licence:")


# ================================================================ write allowlist ===
@pytest.mark.parametrize(
    "method,path,allowed",
    [
        ("GET", "/api/v1/risks", True),
        ("HEAD", "/api/v1/risks", True),
        ("OPTIONS", "/api/v1/risks", True),
        ("POST", "/api/v1/risks", False),
        ("PATCH", "/api/v1/risks/1", False),
        ("PUT", "/api/v1/settings/organisation/security/mfa-roles", False),
        ("DELETE", "/api/v1/controls/1", False),
        ("POST", "/api/v1/auth/login", True),
        ("POST", "/api/v1/auth/logout", True),
        ("POST", "/api/v1/auth/mfa/setup", True),
        ("POST", "/api/v1/auth/mfa/activate", True),
        ("POST", "/api/v1/system/license", True),
        ("POST", "/api/v1/system/license/", True),
        ("POST", "/api/v1/system/backups", False),
        ("POST", "/api/v1/report-builder/run", True),
        ("POST", "/api/v1/report-builder/export", True),
        ("POST", "/api/v1/report-builder/saved", False),
        ("POST", "/api/v1/io/risks/preview", True),
        ("POST", "/api/v1/io/risks/commit", False),
        ("POST", "/api/v1/notifications/seen", True),
        ("POST", "/health", True),
    ],
)
def test_write_allowlist(method, path, allowed):
    assert ls.write_allowed(method, path) is allowed


def _read_only(monkeypatch, read_only=True):
    state = ls.evaluate(_info(TODAY - timedelta(days=45 if read_only else 5), status="expired"), TODAY, enforcing=True)
    monkeypatch.setattr(ls, "current", lambda today=None: state)
    return state


def test_guard_refuses_writes_with_423_and_the_expiry_date(monkeypatch):
    state = _read_only(monkeypatch)
    resp = refusal("POST", "/api/v1/risks")
    assert resp is not None and resp.status_code == 423
    assert resp.headers["X-Error-Code"] == ls.READ_ONLY_CODE
    assert b"Records are read-only until a renewed licence is installed." in resp.body
    assert state.expires.day == 3 and b"3 August 2026" in resp.body
    assert refusal("GET", "/api/v1/risks") is None
    assert refusal("POST", "/api/v1/system/license") is None


def test_guard_lets_grace_and_active_through(monkeypatch):
    _read_only(monkeypatch, read_only=False)
    assert refusal("DELETE", "/api/v1/risks/1") is None


def test_guard_as_middleware(monkeypatch):
    _read_only(monkeypatch)
    app = FastAPI()
    app.add_middleware(LicenceReadOnlyMiddleware)

    @app.get("/api/v1/risks")
    async def read():
        return {"ok": True}

    @app.post("/api/v1/risks")
    async def write():
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/api/v1/risks").status_code == 200
    refused = client.post("/api/v1/risks")
    assert refused.status_code == 423 and refused.json()["code"] == "licence_read_only"
    assert client.post("/api/v1/auth/login").status_code == 200


def test_the_app_installs_the_guard_inside_cors():
    source = (BACKEND / "app/main.py").read_text()
    assert source.index("add_middleware(LicenceReadOnlyMiddleware)") < source.index("CORSMiddleware,")


# ======================================================== start-up and installation ===
@pytest.fixture
def vendor(tmp_path, monkeypatch):
    private_pem, public_pem = lic_cli.generate_keypair()
    monkeypatch.setattr(build, "VENDOR_PUBLIC_KEY_PEM", public_pem.decode("ascii"))
    path = tmp_path / "license.key"
    monkeypatch.setattr(settings, "license_file", str(path))

    def token(**payload) -> str:
        base = {"licensed_to": "Test Bank", "plan": "test", "seats": 10,
                "issued": date.today().isoformat(),
                "expires": (date.today() + timedelta(days=365)).isoformat()}
        base.update(payload)
        return lic_cli.sign_payload(base, private_pem)

    yield SimpleNamespace(token=token, path=path)
    lic._cached = None
    lic._cached_source = None
    ls.reset_daily_check()


def test_release_build_starts_with_an_expired_licence(vendor, monkeypatch):
    monkeypatch.setattr(build, "PRODUCTION_BUILD", True)
    vendor.path.write_text(vendor.token(expires=(date.today() - timedelta(days=200)).isoformat()))
    lic.enforce_on_startup()  # must not raise: expiry is never a lockout
    assert ls.current().read_only


def test_release_build_still_refuses_a_forged_licence(vendor, monkeypatch):
    monkeypatch.setattr(build, "PRODUCTION_BUILD", True)
    other_priv, _ = lic_cli.generate_keypair()
    vendor.path.write_text(lic_cli.sign_payload({"licensed_to": "Self", "expires": "2099-01-01"}, other_priv))
    with pytest.raises(RuntimeError, match="invalid"):
        lic.enforce_on_startup()


def test_install_writes_the_file_keeps_the_previous_and_reloads(vendor):
    vendor.path.write_text(vendor.token(expires=(date.today() - timedelta(days=40)).isoformat()))
    assert lic.load_current(refresh=True).status == "expired"
    info = lic.install_token(vendor.token(seats=25))
    assert info.valid and info.seats == 25
    assert lic.load_current().seats == 25
    assert (vendor.path.parent / "license.key.previous").is_file()


@pytest.mark.parametrize("bad,match", [("", "empty"), ("not.a-token", "not a valid licence")])
def test_install_refuses_garbage(vendor, bad, match):
    with pytest.raises(lic.LicenceInstallError, match=match):
        lic.install_token(bad)
    assert not vendor.path.exists()


def test_install_refuses_an_expired_licence(vendor):
    with pytest.raises(lic.LicenceInstallError, match="expired"):
        lic.install_token(vendor.token(expires=(date.today() - timedelta(days=1)).isoformat()))


def test_a_licence_replaced_on_disk_is_picked_up_without_refresh(vendor):
    vendor.path.write_text(vendor.token(seats=5))
    assert lic.load_current(refresh=True).seats == 5
    vendor.path.write_text(vendor.token(seats=50))
    os.utime(vendor.path, (1, 1))  # a different modification time
    assert lic.load_current().seats == 50


def test_install_endpoint_exists_and_is_admin_only():
    from app.api.v1 import system

    routes = {(r.path, tuple(sorted(r.methods))) for r in system.router.routes}
    assert ("/system/license", ("POST",)) in routes
    assert 'require("role:write")' in inspect.getsource(system).split("async def install_license")[0].rsplit("@router.post", 1)[1]


# ========================================================================= seats ===
def test_seat_status_warns_at_ninety_percent():
    assert ls.seat_status(10, 8) == {"seats_warning": False, "seats_full": False}
    assert ls.seat_status(10, 9) == {"seats_warning": True, "seats_full": False}
    assert ls.seat_status(10, 10) == {"seats_warning": True, "seats_full": True}
    assert ls.seat_status(0, 500) == {"seats_warning": False, "seats_full": False}


def test_seat_refusal():
    assert ls.seat_refusal(limit=10, used=9, enforcing=True) is None
    msg = ls.seat_refusal(limit=10, used=10, enforcing=True)
    assert msg and "allows 10 active users and 10 are active" in msg
    assert ls.seat_refusal(limit=10, used=12, enforcing=False) is None  # dev build
    assert ls.seat_refusal(limit=0, used=12, enforcing=True) is None    # no cap


async def test_dev_build_never_counts_seats(monkeypatch):
    async def boom():
        raise AssertionError("no seat count in a dev build")

    monkeypatch.setattr(build, "PRODUCTION_BUILD", False)
    monkeypatch.setattr(ls, "seats_used", boom)
    await ls.ensure_seat_available()


async def test_release_build_refuses_beyond_the_seat_count(monkeypatch):
    monkeypatch.setattr(build, "PRODUCTION_BUILD", True)
    monkeypatch.setattr(lic, "load_current", lambda refresh=False: _info(TODAY + timedelta(days=100), seats=5))
    used = {"n": 5}

    async def count():
        return used["n"]

    monkeypatch.setattr(ls, "seats_used", count)
    with pytest.raises(HTTPException) as exc:
        await ls.ensure_seat_available()
    assert exc.value.status_code == 403 and exc.value.headers["X-Error-Code"] == ls.SEAT_LIMIT_CODE
    used["n"] = 4
    await ls.ensure_seat_available()


async def test_reactivating_a_user_takes_a_seat_but_existing_users_are_untouched(monkeypatch):
    from app.api.v1 import users

    target = SimpleNamespace(id=uuid.uuid4(), is_active=False, is_platform_admin=False, email="a@b")
    actor = SimpleNamespace(id=uuid.uuid4())

    async def load(db, uid):
        return target

    async def full():
        raise HTTPException(status_code=403, detail="seats")

    monkeypatch.setattr(users, "_load_user", load)
    monkeypatch.setattr(users.licence_state, "ensure_seat_available", full)
    with pytest.raises(HTTPException):
        await users._set_active(target.id, SimpleNamespace(), actor, True)
    assert target.is_active is False

    # Deactivating never needs a seat, and an already-active user is not re-counted.
    calls = []

    async def record(*a, **k):
        calls.append(k)

    async def flush():
        return None

    monkeypatch.setattr(users.audit, "record", record)
    monkeypatch.setattr(users.UserRead, "model_validate", classmethod(lambda cls, u: u))
    target.is_active = True
    db = SimpleNamespace(flush=flush)
    assert (await users._set_active(target.id, db, actor, False)).is_active is False


def test_every_user_creation_path_checks_seats():
    from app.api.v1 import auth, users
    from app.services import sso

    assert "ensure_seat_available" in inspect.getsource(users.create_user)
    assert "ensure_seat_available" in inspect.getsource(users.update_user)
    assert "ensure_seat_available" in inspect.getsource(users._set_active)
    assert "ensure_seat_available" in inspect.getsource(auth._jit_upsert)
    assert "ensure_seat_available" in inspect.getsource(sso)


# ======================================================================== banner ===
def test_banner_audience():
    from app.api.v1.system import licence_banner

    expiring = ls.evaluate(_info(TODAY + timedelta(days=20)), TODAY, enforcing=True)
    assert licence_banner(expiring, is_admin=False, seats_used=None) is None
    assert licence_banner(expiring, is_admin=True, seats_used=None)["tone"] == "warning"
    grace = ls.evaluate(_info(TODAY - timedelta(days=3), status="expired"), TODAY, enforcing=True)
    assert licence_banner(grace, is_admin=False, seats_used=None) is None
    assert licence_banner(grace, is_admin=True, seats_used=None)["tone"] == "critical"
    read_only = ls.evaluate(_info(TODAY - timedelta(days=60), status="expired"), TODAY, enforcing=True)
    assert licence_banner(read_only, is_admin=False, seats_used=None)["state"] == "read_only"
    seats = ls.evaluate(_info(TODAY + timedelta(days=300), seats=10), TODAY, enforcing=True)
    assert licence_banner(seats, is_admin=True, seats_used=9)["state"] == "seats"
    assert licence_banner(seats, is_admin=True, seats_used=5) is None


def test_status_exposes_the_lifecycle():
    s = ls.evaluate(_info(TODAY - timedelta(days=3), status="expired", seats=10), TODAY, enforcing=True)
    out = s.to_public(seats_used=9)
    assert out["state"] == "grace" and out["expires"] == "2026-09-14" and out["grace_until"] == "2026-10-14"
    assert out["seats_used"] == 9 and out["seats_limit"] == 10 and out["seats_warning"] is True
    assert set(ls.STATES) >= {"active", "expiring", "grace", "read_only", "unlicensed", "evaluation"}


# ============================================================== daily re-check ===
async def test_daily_recheck_reloads_once_a_day_and_notifies(monkeypatch):
    import app.core.database as database

    reloads = []
    state_info = _info(TODAY + timedelta(days=7))

    def load(refresh=False):
        if refresh:
            reloads.append(1)
        return state_info

    notices = []

    async def notify(db, tenant_id, stage, state, seats_used=None):
        notices.append((tenant_id, stage))
        return 1

    @asynccontextmanager
    async def session(tid):
        yield SimpleNamespace()

    monkeypatch.setattr(lic, "load_current", load)
    monkeypatch.setattr(lic, "enforcement_enabled", lambda: True)
    monkeypatch.setattr(ls, "notify_admins", notify)
    monkeypatch.setattr(database, "tenant_session", session)
    ls.reset_daily_check()
    tenants = [(uuid.uuid4(), "A"), (uuid.uuid4(), "B")]
    try:
        assert await ls.run_daily(tenants, today=TODAY) == 2
        assert [s for _, s in notices] == ["expiry-7", "expiry-7"]
        assert await ls.run_daily(tenants, today=TODAY) == 0  # same day: no reload
        assert len(reloads) == 1
        await ls.run_daily(tenants, today=TODAY + timedelta(days=1))
        assert len(reloads) == 2
        ls.reset_daily_check()  # a licence was installed
        await ls.run_daily(tenants, today=TODAY + timedelta(days=1))
        assert len(reloads) == 3
    finally:
        ls.reset_daily_check()


async def test_notices_are_deduplicated_per_stage(monkeypatch):
    from app.services import audit, notifications

    existing: set[str] = set()
    added = []

    class Db:
        async def scalar(self, stmt):
            key = stmt.whereclause.right.value
            return uuid.uuid4() if key in existing else None

        def add(self, row):
            added.append(row)
            existing.add(row.dedup_key)

        async def flush(self):
            return None

    async def directory(db):
        return SimpleNamespace(roles_granting=lambda *p: ["Admin", "Compliance Admin"])

    async def record_system(db, **kw):
        return None

    monkeypatch.setattr(notifications, "load_directory", directory)
    monkeypatch.setattr(audit, "record_system", record_system)
    state = ls.evaluate(_info(TODAY - timedelta(days=2), status="expired"), TODAY, enforcing=True)
    tid = uuid.uuid4()
    assert await ls.notify_admins(Db(), tid, "grace", state) == 2
    assert await ls.notify_admins(Db(), tid, "grace", state) == 0
    assert {r.role_name for r in added} == {"Admin", "Compliance Admin"}
    assert all(r.category.value == "critical" for r in added)


def test_the_scheduler_runs_the_licence_check():
    from app.services import scheduler

    assert "licence_state.run_daily(tenants)" in inspect.getsource(scheduler.run_sweep)


# ===================================================================== retention ===
def test_retention_defaults_to_ten_years_everywhere():
    from app.models.settings import TenantSettings
    from app.schemas.tenant_settings import DEFAULTS, RETENTION_MAX_DAYS, RETENTION_MIN_DAYS
    from app.services import scheduler

    assert DEFAULTS["retention_days"] == 3650
    assert TenantSettings.__table__.c.retention_days.default.arg == 3650
    assert scheduler.DEFAULT_RETENTION_DAYS == 3650
    assert (RETENTION_MIN_DAYS, RETENTION_MAX_DAYS) == (365, 3650)


@pytest.mark.parametrize("days", [30, 90, 364, 3651])
def test_retention_range_message(days):
    from app.schemas.tenant_settings import validate_retention_days

    with pytest.raises(ValueError, match=r"between 365 days \(1 year\) and 3650 days \(10 years\)"):
        validate_retention_days(days)


class _RepairDb:
    def __init__(self, marker, row):
        self._answers = [marker, row]
        self.added = []

    async def scalar(self, stmt):
        return self._answers.pop(0)

    def add(self, row):
        self.added.append(row)


async def test_boot_repair_moves_ninety_days_to_ten_years_once():
    from app.db import data_repairs

    row = SimpleNamespace(id=uuid.uuid4(), retention_days=90)
    db = _RepairDb(None, row)
    assert await data_repairs.upgrade_retention_default(db, uuid.uuid4()) is True
    assert row.retention_days == 3650
    (entry,) = db.added
    assert entry.action == "retention_default_upgrade" and entry.actor_id is None
    assert entry.changes["retention_days"] == [90, 3650]

    # Already run (marker present): nothing touched, even a row on 90 again.
    again = SimpleNamespace(id=uuid.uuid4(), retention_days=90)
    db = _RepairDb(uuid.uuid4(), again)
    assert await data_repairs.upgrade_retention_default(db, uuid.uuid4()) is False
    assert again.retention_days == 90 and db.added == []


async def test_boot_repair_keeps_an_organisations_own_choice():
    from app.db import data_repairs

    row = SimpleNamespace(id=uuid.uuid4(), retention_days=1825)
    db = _RepairDb(None, row)
    assert await data_repairs.upgrade_retention_default(db, uuid.uuid4()) is False
    assert row.retention_days == 1825
    assert db.added[0].changes["kept"] == 1825  # marker written: runs once


def test_boot_repair_is_wired_into_repair_tenant():
    from app.db import data_repairs

    assert "upgrade_retention_default(db, tenant_id)" in inspect.getsource(data_repairs.repair_tenant)


def test_the_audit_trail_is_never_purged():
    """Guard: nothing in the application deletes audit rows, and the retention purge
    never covers them."""
    from app.models.audit import AuditLog
    from app.services import record_registry, scheduler

    assert not {"audit", "audit_log", "audit_logs"} & set(scheduler.RETENTION_ENTITY_TYPES)
    for entity_type in scheduler.RETENTION_ENTITY_TYPES:
        assert record_registry.model_for(entity_type) is not AuditLog
    pattern = re.compile(r"delete\(\s*AuditLog|AuditLog\.__table__\.delete|DELETE\s+FROM\s+audit_logs?\b|TRUNCATE[^\n]*audit_log", re.I)
    offenders = [
        str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# =========================================================================== MFA ===
def test_mfa_required_by_default_only_in_a_release_build(monkeypatch):
    monkeypatch.delenv("MFA_REQUIRED", raising=False)
    monkeypatch.setattr(build, "PRODUCTION_BUILD", False)
    assert Settings(_env_file=None).mfa_required is False
    monkeypatch.setattr(build, "PRODUCTION_BUILD", True)
    assert Settings(_env_file=None).mfa_required is True
    monkeypatch.setenv("MFA_REQUIRED", "false")  # an explicit setting always wins
    assert Settings(_env_file=None).mfa_required is False


def test_production_config_requires_mfa_for_everyone():
    compose = (REPO / "docker-compose.prod.yml").read_text()
    assert re.search(r"MFA_ENFORCEMENT:\s*\$\{MFA_ENFORCEMENT:-everyone\}", compose)
    assert re.search(r"MFA_REQUIRED:\s*\$\{MFA_REQUIRED:-true\}", compose)
    example = (REPO / ".env.example").read_text()
    assert re.search(r"^MFA_ENFORCEMENT=everyone$", example, re.M)
    assert re.search(r"^MFA_REQUIRED=true$", example, re.M)


def test_mfa_for_everyone_covers_ldap_but_not_sso():
    from app.services import mfa_policy

    assert mfa_policy.mfa_required_for(
        role_names=["Viewer"], permission_codes=[], global_required=True, required_roles=[],
    )
    status, _ = mfa_policy.user_mfa_status(
        required=True, mfa_enabled=False, grace_until=None, now=__import__("datetime").datetime.now(),
        signs_in_with_sso=True,
    )
    assert status == "identity_provider"


def test_me_says_when_mfa_is_required_for_everyone():
    from app.schemas.auth import MeRead

    assert "mfa_required_for_everyone" in MeRead.model_fields
