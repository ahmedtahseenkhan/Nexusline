"""Licence lifecycle: expiry warnings, grace, read-only mode and seats (decision 1).

``services/license.py`` verifies the signed licence file. This module decides what that
means for a running installation, following on-prem enterprise licensing practice for a
regulated bank that must always be able to read its records for an examiner:

* **Dev / evaluation build** (``build.PRODUCTION_BUILD`` false): nothing is enforced. No
  licence file means ``evaluation`` (everything open, the evaluation banner shows).
* **Release build, no or invalid licence**: start-up is refused (``license.enforce_on_startup``).
* **Active** → **expiring** from :data:`WARN_DAYS` before ``expires`` (administrators see a
  banner with the days left, and are notified at :data:`NOTICE_DAYS`).
* **Grace**: for :data:`GRACE_DAYS` after ``expires`` everything still works; administrators
  are warned on every page.
* **Read-only** after grace: sign-in, every read, exports and installing a licence work;
  every other write is refused with 423 and :func:`read_only_detail`
  (``core/licence_guard.py``). Never a lockout, and start-up is never refused for expiry.
* **Seats**: the licence's ``seats`` caps *active* users who are not platform operators
  (``0`` = no cap). Administrators are warned at :data:`SEAT_WARN_RATIO`; creating or
  re-activating a user beyond the cap is refused with 403. Existing users keep working.

``expires`` is the last day the licence is current; grace runs through ``expires +
GRACE_DAYS``; read-only starts the day after. The state is evaluated against today's date
on every call, so crossing a boundary needs no restart. The file itself is re-read daily by
the scheduler (:func:`run_daily`), whenever it changes on disk, and when a licence is
installed through ``POST /system/license``.

Everything above the database helpers is pure.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.services import license as lic

logger = logging.getLogger("nexusline.licence")

#: Days of full function after ``expires`` before read-only mode.
GRACE_DAYS = 30
#: Administrators see the expiry banner from this many days before ``expires``.
WARN_DAYS = 60
#: Days before expiry on which administrators are notified (in-app and e-mail digest).
NOTICE_DAYS: tuple[int, ...] = (60, 30, 7, 1)
#: Share of the seat limit in use at which administrators are warned.
SEAT_WARN_RATIO = 0.9

#: ``X-Error-Code`` / ``code`` of a write refused in read-only mode.
READ_ONLY_CODE = "licence_read_only"
#: ``X-Error-Code`` of a user creation / re-activation refused for want of seats.
SEAT_LIMIT_CODE = "licence_seat_limit"
#: HTTP status of a refused write: 423 Locked — the records exist and can be read.
READ_ONLY_STATUS = 423

STATES = ("active", "expiring", "grace", "read_only", "unlicensed", "evaluation", "invalid")


@dataclass(frozen=True)
class LicenceState:
    state: str
    enforcing: bool
    expires: date | None = None
    grace_until: date | None = None
    #: Days until ``expires`` (0 on the last day, negative once expired).
    days_to_expiry: int | None = None
    #: Days of grace left (0 on the last day of grace), only in grace.
    grace_days_left: int | None = None
    licensed_to: str = ""
    seats_limit: int = 0
    message: str = ""

    @property
    def read_only(self) -> bool:
        """Writes are refused. Only a release build enforces it."""
        return self.enforcing and self.state == "read_only"

    @property
    def warn_admins(self) -> bool:
        return self.state in ("expiring", "grace", "read_only")

    def to_public(self, seats_used: int | None = None) -> dict:
        out = {
            "state": self.state,
            "enforcing": self.enforcing,
            "read_only": self.read_only,
            "expires": self.expires.isoformat() if self.expires else None,
            "grace_until": self.grace_until.isoformat() if self.grace_until else None,
            "days_to_expiry": self.days_to_expiry,
            "grace_days_left": self.grace_days_left,
            "licensed_to": self.licensed_to,
            "message": self.message,
            "seats_limit": self.seats_limit,
            "seats_used": seats_used,
        }
        out.update(seat_status(self.seats_limit, seats_used))
        return out


def _fmt(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def evaluate(info: lic.LicenseInfo, today: date, enforcing: bool) -> LicenceState:
    """The licence state on ``today``. Pure."""
    if info.status in ("unlicensed", "unconfigured"):
        if not enforcing:
            return LicenceState("evaluation", False, message="Unlicensed evaluation build — not for production use.")
        return LicenceState("unlicensed", True, message=info.message or "No licence is installed.")
    if not lic.signature_ok(info):
        return LicenceState("invalid", enforcing, message=info.message or "The licence could not be verified.")

    base = dict(enforcing=enforcing, licensed_to=info.licensed_to, seats_limit=max(0, int(info.seats or 0)))
    if not info.expires:
        return LicenceState("active", message="Licence verified (no expiry date).", **base)
    try:
        expires = date.fromisoformat(info.expires)
    except ValueError:
        return LicenceState("invalid", enforcing, message="The licence expiry date cannot be read.")
    grace_until = expires + timedelta(days=GRACE_DAYS)
    days = (expires - today).days
    if days >= 0:
        if days <= WARN_DAYS:
            when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
            return LicenceState(
                "expiring", expires=expires, grace_until=grace_until, days_to_expiry=days,
                message=f"The licence expires {when} ({_fmt(expires)}). Install a renewed licence to avoid interruption.",
                **base,
            )
        return LicenceState(
            "active", expires=expires, grace_until=grace_until, days_to_expiry=days,
            message=f"Licence verified; expires on {_fmt(expires)}.", **base,
        )
    if today <= grace_until:
        left = (grace_until - today).days
        return LicenceState(
            "grace", expires=expires, grace_until=grace_until, days_to_expiry=days, grace_days_left=left,
            message=(
                f"The licence expired on {_fmt(expires)}. Everything works until {_fmt(grace_until)} "
                f"({left} day{'s' if left != 1 else ''} left); after that records become read-only "
                "until a renewed licence is installed."
            ),
            **base,
        )
    return LicenceState(
        "read_only", expires=expires, grace_until=grace_until, days_to_expiry=days,
        message=read_only_detail(expires), **base,
    )


def read_only_detail(expires: date | None) -> str:
    when = _fmt(expires) if expires else "an earlier date"
    return f"The licence expired on {when}. Records are read-only until a renewed licence is installed."


def current(today: date | None = None) -> LicenceState:
    """The running installation's licence state (the file is cached; the date is not)."""
    return evaluate(lic.load_current(), today or date.today(), lic.enforcement_enabled())


# ------------------------------------------------------------------ writes in read-only ---
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Writes that stay open in read-only mode (paths below ``/api/v1``): signing in and out,
#: MFA enrolment and password changes, installing a licence, health, and POST endpoints that
#: only read (report runs and exports, import previews, score previews, rule evaluation,
#: marking notifications seen).
READ_ONLY_ALLOWLIST: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (
        r"^/auth(/.*)?$",
        r"^/system/license$",
        r"^/system/health$",
        r"^/report-builder/(run|export)$",
        r"^/notifications/seen$",
        r"^/questionnaires/[^/]+/(preview-score|validate)$",
        r"^/status-rules/evaluate/[^/]+$",
        r"^/io/[^/]+/preview$",
        r"^/content-library/[^/]+/install-controls/preview$",
    )
)
API_PREFIX = "/api/v1"


def write_allowed(method: str, path: str) -> bool:
    """Whether a request may proceed in read-only mode. Pure."""
    if (method or "").upper() in SAFE_METHODS:
        return True
    p = (path or "").split("?", 1)[0].rstrip("/")
    if not p.startswith(API_PREFIX):
        return True  # /health, /docs: not the application's records
    rest = p[len(API_PREFIX):] or "/"
    return any(rx.match(rest) for rx in READ_ONLY_ALLOWLIST)


# ------------------------------------------------------------------------------ seats ---
def seat_status(limit: int, used: int | None) -> dict:
    """``seats_warning`` at :data:`SEAT_WARN_RATIO` of the limit, ``seats_full`` at it. Pure."""
    if not limit or used is None:
        return {"seats_warning": False, "seats_full": False}
    return {"seats_warning": used >= limit * SEAT_WARN_RATIO, "seats_full": used >= limit}


def seat_refusal(*, limit: int, used: int, adding: int = 1, enforcing: bool) -> str | None:
    """The message refusing ``adding`` more active users, or ``None``. Pure.

    Dev builds and licences without a seat limit (``0``) never refuse."""
    if not enforcing or not limit or adding <= 0 or used + adding <= limit:
        return None
    return (
        f"The licence allows {limit} active user{'s' if limit != 1 else ''} and {used} "
        f"{'are' if used != 1 else 'is'} active. Deactivate a user or install a licence with more "
        "seats before adding or re-activating another. Existing users are not affected."
    )


async def seats_used() -> int:
    """Active users on this installation who are not platform operators, across every
    organisation (the licence covers the installation). Reads with the owner connection,
    because row-level security would otherwise count one organisation only."""
    from sqlalchemy import func, select

    from app.db.init_db import admin_engine
    from app.models.identity import User

    async with admin_engine.connect() as conn:
        return int(await conn.scalar(
            select(func.count()).select_from(User).where(
                User.is_active.is_(True), User.is_platform_admin.is_(False),
            )
        ) or 0)


async def ensure_seat_available(adding: int = 1) -> None:
    """Raise 403 when ``adding`` more active users would exceed the licence's seats.
    A no-op in a dev build or without a seat limit (no database call then)."""
    from fastapi import HTTPException, status

    if not lic.enforcement_enabled() or adding <= 0:
        return
    limit = max(0, int(lic.load_current().seats or 0))
    if not limit:
        return
    problem = seat_refusal(limit=limit, used=await seats_used(), adding=adding, enforcing=True)
    if problem:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=problem, headers={"X-Error-Code": SEAT_LIMIT_CODE},
        )


# ------------------------------------------------------------------ admin notices ---
def notice_stage(state: LicenceState) -> str | None:
    """The notice due for this state, or ``None``. Pure.

    ``expiry-60/30/7/1`` once ``days_to_expiry`` is at or below the threshold (the smallest
    one reached), ``grace`` and ``read_only`` on entering those states. Each stage is sent
    once per licence (the key carries the expiry date, so a renewal starts afresh)."""
    if state.state == "expiring" and state.days_to_expiry is not None:
        due = [t for t in NOTICE_DAYS if state.days_to_expiry <= t]
        return f"expiry-{min(due)}" if due else None
    if state.state in ("grace", "read_only"):
        return state.state
    return None


def notice_key(stage: str, state: LicenceState, role: str) -> str:
    from app.models.notification import EVENT_PREFIX

    expires = state.expires.isoformat() if state.expires else "none"
    return f"{EVENT_PREFIX}licence:{stage}:{expires}:role:{role}"[:255]


def notice_text(stage: str, state: LicenceState, seats_used: int | None = None) -> tuple[str, str, str]:
    """``(title, body, category)`` for a notice. Pure."""
    if stage.startswith("seats"):
        return (
            f"Licence seats: {seats_used} of {state.seats_limit} in use",
            f"{seats_used} of the {state.seats_limit} active users the licence allows are in use. "
            "New or re-activated users are refused once the limit is reached; ask your vendor for more seats.",
            "warning",
        )
    if stage == "read_only":
        return ("Licence expired: records are read-only", state.message, "critical")
    if stage == "grace":
        return ("Licence expired: grace period started", state.message, "critical")
    return (f"Licence expires in {state.days_to_expiry} day{'s' if state.days_to_expiry != 1 else ''}",
            state.message, "warning" if (state.days_to_expiry or 0) > 7 else "critical")


ADMIN_PERMISSION = "settings:manage"

_last_check: date | None = None


def reset_daily_check() -> None:
    """Make the next scheduler sweep re-read the licence and re-send due notices."""
    global _last_check
    _last_check = None


async def notify_admins(db, tenant_id: uuid.UUID, stage: str, state: LicenceState, seats_used: int | None = None) -> int:
    """Raise the notice for every role holding :data:`ADMIN_PERMISSION` in one organisation,
    once per stage (dedup key). The e-mail digest delivers it to those roles' members.
    Returns the notices created."""
    from sqlalchemy import select

    from app.models.enums import NotificationCategory
    from app.models.notification import Notification
    from app.services import audit, notifications

    directory = await notifications.load_directory(db)
    roles = directory.roles_granting(ADMIN_PERMISSION) or ["Admin"]
    title, body, category = notice_text(stage, state, seats_used)
    created = 0
    for role in roles:
        key = notice_key(stage, state, role)
        if await db.scalar(select(Notification.id).where(Notification.dedup_key == key).limit(1)):
            continue
        db.add(Notification(
            tenant_id=tenant_id, user_id=None, role_name=role, title=title[:255], body=body,
            category=getattr(NotificationCategory, category, NotificationCategory.warning),
            entity_type="licence", entity_id=None, link="/settings#system", dedup_key=key,
        ))
        created += 1
    if created:
        await audit.record_system(
            db, tenant_id=tenant_id, action="licence_notice", entity_type="licence", entity_id=None,
            summary=f"{title}"[:500],
            changes={"stage": stage, "state": state.state, "expires": state.expires.isoformat() if state.expires else None,
                     "seats_used": seats_used, "seats_limit": state.seats_limit, "roles": roles},
        )
        await db.flush()
    return created


async def run_daily(tenants: list[tuple[uuid.UUID, Any]], today: date | None = None) -> int:
    """Scheduler step: once a day re-read the licence file, then send each organisation's
    administrators the notices now due (expiry stages, grace, read-only, seats at 90%).
    Returns the notices created; 0 when already run today."""
    global _last_check
    from app.core.database import tenant_session

    today = today or date.today()
    if _last_check == today:
        return 0
    lic.load_current(refresh=True)
    state = current(today)
    _last_check = today
    logger.info("Licence re-check: %s (%s)", state.state, state.message)

    stages: list[str] = []
    stage = notice_stage(state)
    if stage:
        stages.append(stage)
    used: int | None = None
    if state.enforcing and state.seats_limit:
        try:
            used = await seats_used()
        except Exception:  # noqa: BLE001 - a count failure must not stop the notices
            logger.exception("Could not count licence seats")
        if seat_status(state.seats_limit, used)["seats_warning"]:
            stages.append(f"seats-{state.seats_limit}")
    if not stages:
        return 0
    created = 0
    for tenant_id, _name in tenants:
        for s in stages:
            try:
                async with tenant_session(tenant_id) as db:
                    created += await notify_admins(db, tenant_id, s, state, used)
            except Exception:  # noqa: BLE001 - isolate per-tenant failures
                logger.exception("Licence notice %s failed for tenant %s", s, tenant_id)
    return created
