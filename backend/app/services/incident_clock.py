"""The incident clock: when things happened, what the regulator is owed, and by when.

Phase 2 (product review F-10). An incident's timeline is kept as timezone-aware
timestamps because a regulator's clock runs in hours, not days: SBP expects the initial
notification within ``settings.regulatory_initial_report_hours`` of detection, and a
date cannot say whether 23 hours or 47 have passed.

Everything here is pure except the functions marked ``async``; the API layer
(``api.v1.incidents`` / ``api.v1.regulatory``) calls them so there is one rule for:

* **Reading a value someone typed.** A bare date ("2026-09-01", an old CSV) or a
  datetime with no offset is taken as that wall-clock time in the organisation's
  timezone (Settings → Organisation); a value with an offset is kept as sent.
* **The timeline order.** Occurred ≤ detected ≤ contained ≤ resolved.
* **The regulatory deadlines.** Initial report = anchor + N hours, final report =
  anchor + M days, to the minute, where the anchor is detection (or, when detection was
  not recorded, when the incident was logged). The ``RegulatoryReport`` rows are the one
  store of those deadlines; :func:`sync_regulatory_reports` keeps them in step.
* **The notification clock read back on the incident** — deadline, when notified, the
  regulator's reference, hours left (negative when late) and whether it was on time.
* **MTTD / MTTC / MTTR** — detection, containment and resolution times in hours.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.enums import IncidentStatus, RegulatoryReportStatus, RegulatoryReportType

#: The organisation timezone used when none is configured (TenantSettings default).
DEFAULT_TIMEZONE = "Asia/Karachi"

#: Incident timeline fields, in the order they must happen.
TIMELINE_FIELDS: tuple[str, ...] = ("occurred_at", "detected_at", "contained_at", "resolved_at")

_LABELS = {
    "occurred_at": "occurred",
    "detected_at": "detected",
    "contained_at": "contained",
    "resolved_at": "resolved",
}

#: Statuses at which the response has at least contained the incident / finished it.
CONTAINED_STATUSES = frozenset({IncidentStatus.contained})
RESOLVED_STATUSES = frozenset({IncidentStatus.resolved, IncidentStatus.closed})


# ====================================================================== zones ===
def zone(name: str | None) -> ZoneInfo:
    """The IANA zone ``name``, or the default organisation zone if it is blank/unknown."""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


async def tenant_zone(db, tenant_id) -> ZoneInfo:
    """The organisation's timezone (Settings → Organisation)."""
    from app.api.v1.tenant_settings import get_or_create_settings

    row = await get_or_create_settings(db, tenant_id)
    return zone(getattr(row, "timezone", None))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def localize(value: Any, tz: ZoneInfo) -> Any:
    """A typed value as an aware datetime.

    A ``date`` is 00:00 that day in ``tz``; a naive ``datetime`` is that wall-clock time
    in ``tz``; an aware one is returned unchanged. ``None`` (and anything else) passes
    through untouched.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=tz)
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0), tzinfo=tz)
    return value


def needs_zone(values: Iterable[Any]) -> bool:
    """True when any value is a date or a naive datetime (so the tenant zone is needed)."""
    for v in values:
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return True
        elif isinstance(v, date):
            return True
    return False


async def localize_fields(db, tenant_id, data: dict, fields: Sequence[str]) -> None:
    """Rewrite ``data[field]`` in place as aware datetimes, reading the organisation's
    timezone only when some value actually needs it."""
    present = [f for f in fields if f in data]
    if not needs_zone(data[f] for f in present):
        return
    tz = await tenant_zone(db, tenant_id)
    for f in present:
        data[f] = localize(data[f], tz)


def _aware(value: datetime | None) -> datetime | None:
    """Treat a naive stored value as UTC (the database returns aware values; this is
    for callers that built one by hand)."""
    if value is None:
        return None
    if not isinstance(value, datetime):  # a legacy date that slipped through
        value = datetime.combine(value, time(0, 0))
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def to_minute(value: datetime | None) -> datetime | None:
    """The instant truncated to the minute (a form resends 14:30 for a stored 14:30:27)."""
    v = _aware(value)
    return v.replace(second=0, microsecond=0) if v is not None else None


def local_date(value: datetime | None, tz: ZoneInfo) -> date | None:
    """The calendar day ``value`` falls on in ``tz`` (for date-only records such as a
    loss event or a breach register entry)."""
    v = _aware(value)
    return v.astimezone(tz).date() if v is not None else None


def local_text(value: datetime | None, tz: ZoneInfo) -> str:
    """``YYYY-MM-DD HH:MM`` in ``tz`` — for exports and alert text."""
    v = _aware(value)
    return v.astimezone(tz).strftime("%Y-%m-%d %H:%M") if v is not None else ""


# =================================================================== timeline ===
def timeline_problems(values: dict[str, datetime | None]) -> list[str]:
    """Out-of-order timeline steps, as messages ("detected is before occurred").

    Only steps that are both recorded are compared; contained and resolved are each
    checked against detection (and resolved against containment), since either may be
    blank.
    """
    v = {k: _aware(values.get(k)) for k in TIMELINE_FIELDS}
    pairs = (
        ("occurred_at", "detected_at"),
        ("occurred_at", "contained_at"),
        ("occurred_at", "resolved_at"),
        ("detected_at", "contained_at"),
        ("detected_at", "resolved_at"),
        ("contained_at", "resolved_at"),
    )
    problems = []
    for earlier, later in pairs:
        a, b = v[earlier], v[later]
        if a is not None and b is not None and b < a:
            problems.append(f"{_LABELS[later].capitalize()} is before {_LABELS[earlier]}")
    return problems


def status_stamps(
    status: IncidentStatus | None, current: dict[str, datetime | None], now: datetime
) -> dict[str, datetime]:
    """Timeline stamps a status move implies when the step was left blank: moving to
    *contained* records containment now, moving to *resolved*/*closed* records
    resolution now. Anything already recorded is kept; the user can correct either."""
    out: dict[str, datetime] = {}
    if status in CONTAINED_STATUSES and current.get("contained_at") is None:
        out["contained_at"] = now
    if status in RESOLVED_STATUSES and current.get("resolved_at") is None:
        out["resolved_at"] = now
    return out


def creation_stamps(
    status: IncidentStatus | None, current: dict[str, datetime | None], now: datetime
) -> dict[str, datetime]:
    """The stamps a newly logged incident gets: :func:`status_stamps` for the status it
    is logged in (logged contained records containment now, logged closed records
    resolution now), and detection now when none is given — an incident being logged
    has been detected by now at the latest, and detection starts the regulator's clock.
    Anything given is kept."""
    out = {} if current.get("detected_at") is not None else {"detected_at": now}
    out.update(status_stamps(status, current, now))
    return out


def hours_between(start: datetime | None, end: datetime | None) -> float | None:
    """Elapsed hours from ``start`` to ``end`` (2 dp); ``None`` if either is missing or
    the order is impossible (legacy rows entered before the order rule)."""
    a, b = _aware(start), _aware(end)
    if a is None or b is None or b < a:
        return None
    return round((b - a).total_seconds() / 3600, 2)


@dataclass(frozen=True)
class ResponseTimes:
    mttd_hours: float | None  # detected − occurred
    mttc_hours: float | None  # contained − detected
    mttr_hours: float | None  # resolved − detected


def response_times(incident: Any) -> ResponseTimes:
    return ResponseTimes(
        mttd_hours=hours_between(incident.occurred_at, incident.detected_at),
        mttc_hours=hours_between(incident.detected_at, getattr(incident, "contained_at", None)),
        mttr_hours=hours_between(incident.detected_at, incident.resolved_at),
    )


def average(values: Iterable[float | None]) -> tuple[float | None, int]:
    """Mean of the recorded values (2 dp) and how many there were."""
    got = [v for v in values if v is not None]
    return (round(sum(got) / len(got), 2) if got else None), len(got)


# ================================================================ regulatory ===
def clock_anchor(incident: Any, now: datetime | None = None) -> datetime:
    """Where the regulator's clock starts: detection, else when the incident was logged."""
    return _aware(incident.detected_at) or _aware(getattr(incident, "created_at", None)) or (now or now_utc())


def planned_deadlines(
    anchor: datetime, initial_hours: int, final_days: int
) -> dict[RegulatoryReportType, datetime]:
    """The initial and final report deadlines, to the minute (seconds are dropped, so a
    deadline is never later than the rule allows)."""
    base = _aware(anchor).replace(second=0, microsecond=0)
    return {
        RegulatoryReportType.initial_notification: base + timedelta(hours=initial_hours),
        RegulatoryReportType.final_report: base + timedelta(days=final_days),
    }


@dataclass(frozen=True)
class SyncChange:
    report_type: RegulatoryReportType
    action: str  # created | moved | regulator
    deadline: datetime | None


def plan_sync(
    reports: Sequence[Any],
    planned: dict[RegulatoryReportType, datetime],
    *,
    recompute: bool,
    regulator: str,
    regulator_id: Any,
    create_missing: bool = True,
) -> tuple[list[RegulatoryReportType], list[SyncChange]]:
    """What :func:`sync_regulatory_reports` must do, decided without a session.

    Returns the report types to create (when ``create_missing``: a report someone
    removed on purpose is not brought back by an unrelated edit) and the in-place
    changes it made to existing ``pending`` reports: their deadline moves to the plan
    when ``recompute`` (the anchor moved, or the incident just became reportable) and
    their regulator follows the incident's. A submitted report is history and is never
    touched.
    """
    by_type: dict[RegulatoryReportType, Any] = {}
    for r in reports:
        by_type.setdefault(r.report_type, r)
    to_create: list[RegulatoryReportType] = []
    changes: list[SyncChange] = []
    for rtype, deadline in planned.items():
        existing = by_type.get(rtype)
        if existing is None:
            if not create_missing:
                continue
            to_create.append(rtype)
            changes.append(SyncChange(rtype, "created", deadline))
            continue
        if existing.status != RegulatoryReportStatus.pending:
            continue
        if recompute and _aware(existing.deadline) != deadline:
            existing.deadline = deadline
            changes.append(SyncChange(rtype, "moved", deadline))
        if regulator and (existing.regulator != regulator or existing.regulator_id != regulator_id):
            existing.regulator = regulator
            existing.regulator_id = regulator_id
            changes.append(SyncChange(rtype, "regulator", existing.deadline))
    return to_create, changes


def sync_regulatory_reports(
    incident: Any,
    *,
    tenant_id,
    initial_hours: int,
    final_days: int,
    default_regulator: str,
    recompute: bool,
    create_missing: bool = True,
    now: datetime | None = None,
) -> list[SyncChange]:
    """Make an incident's ``regulatory_reports`` carry the initial and final reports it
    owes, with deadlines from the detection anchor. New rows are appended to the
    (loaded) collection, so this works on a new incident before it is flushed."""
    from app.models.incident import RegulatoryReport

    regulator = incident.regulator or default_regulator
    planned = planned_deadlines(clock_anchor(incident, now), initial_hours, final_days)
    to_create, changes = plan_sync(
        incident.regulatory_reports, planned, recompute=recompute,
        regulator=regulator, regulator_id=incident.regulator_id, create_missing=create_missing,
    )
    for rtype in to_create:
        incident.regulatory_reports.append(RegulatoryReport(
            tenant_id=tenant_id, regulator=regulator, regulator_id=incident.regulator_id,
            report_type=rtype, deadline=planned[rtype], status=RegulatoryReportStatus.pending,
            reference="", summary="", submitted_by="",
        ))
    return changes


@dataclass(frozen=True)
class NotificationClock:
    notification_deadline: datetime | None
    notified_at: datetime | None
    regulator_reference: str | None
    hours_to_deadline: float | None
    notified_on_time: bool | None


_NO_CLOCK = NotificationClock(None, None, None, None, None)


def initial_report(reports: Sequence[Any]) -> Any | None:
    """The incident's initial notification (earliest deadline first if there are two)."""
    initial = [r for r in reports if r.report_type == RegulatoryReportType.initial_notification]
    if not initial:
        return None
    far = datetime.max.replace(tzinfo=timezone.utc)
    return min(initial, key=lambda r: _aware(r.deadline) or far)


def notification_clock(reports: Sequence[Any], now: datetime | None = None) -> NotificationClock:
    """The regulator-notification position read off the initial report.

    ``hours_to_deadline`` runs to *now* while the notification is pending and is frozen at
    the submission once made — negative either way means late. ``notified_on_time`` is
    None while a pending notification is still within its deadline.
    """
    r = initial_report(reports)
    if r is None:
        return _NO_CLOCK
    deadline = _aware(r.deadline)
    notified = _aware(r.submitted_at)
    reference = r.reference or None
    if deadline is None:
        return NotificationClock(None, notified, reference, None, None)
    ref_point = notified or _aware(now) or now_utc()
    hours = round((deadline - ref_point).total_seconds() / 3600, 2)
    if notified is not None:
        on_time: bool | None = notified <= deadline
    else:
        on_time = False if ref_point > deadline else None
    return NotificationClock(deadline, notified, reference, hours, on_time)


def apply_notification(reports: Sequence[Any], sent: dict[str, Any]) -> list[str]:
    """Record the regulator notification from the incident form on the initial report —
    the one place it is stored. ``sent`` holds only the keys the request carried:
    ``notified_at`` (a time marks the report submitted; None reopens it) and
    ``regulator_reference``. Raises ``ValueError`` when there is no initial report."""
    if not sent:
        return []
    r = initial_report(reports)
    if r is None:
        if not any(sent.values()):
            return []  # a form clearing fields that were never set: nothing to record
        raise ValueError(
            "Mark the incident reportable first: there is no initial report to record the notification on"
        )
    notes: list[str] = []
    # A form resends what it showed: only a real change (to the minute) is written.
    if "notified_at" in sent and to_minute(sent["notified_at"]) != to_minute(r.submitted_at):
        at = sent["notified_at"]
        r.submitted_at = at
        if at is None:
            r.status = RegulatoryReportStatus.pending
            notes.append("initial notification reopened")
        else:
            if r.status == RegulatoryReportStatus.pending:
                r.status = RegulatoryReportStatus.submitted
            notes.append("initial notification recorded")
    reference = (sent.get("regulator_reference") or "").strip()[:120]
    if "regulator_reference" in sent and reference != (r.reference or ""):
        r.reference = reference
        notes.append("regulator reference recorded")
    return notes


def report_overdue(report: Any, now: datetime | None = None) -> bool:
    """A pending report whose deadline has passed."""
    deadline = _aware(report.deadline)
    return (
        report.status == RegulatoryReportStatus.pending
        and deadline is not None
        and deadline < (_aware(now) or now_utc())
    )


# ================================================================== flags ===
#: Role names taken to mean the data protection officer.
_DPO_NAMES = ("dpo", "data protection officer", "data protection")


def is_dpo_role(name: str | None) -> bool:
    """Whether a role name designates the data protection officer ("DPO", "Data
    Protection Officer", "Head of Data Protection" …)."""
    n = " ".join((name or "").lower().replace("_", " ").replace("-", " ").split())
    if not n:
        return False
    words = n.split()
    return "dpo" in words or any(k in n for k in _DPO_NAMES[1:])


def near_miss_problem(near_miss: bool | None, cost: float | None) -> str | None:
    """A near miss has no loss: refuse one that carries a cost."""
    if near_miss and cost not in (None, 0, 0.0):
        return "A near miss has no loss: clear the estimated cost, or untick near miss"
    return None


def single_unit(assets: Iterable[Any], risks: Iterable[Any]) -> Any | None:
    """The one business unit an incident's linked assets (their owning unit) and risks
    point at, or None when they name none or several — a guess is worse than a blank."""
    units = {a.owner_id for a in assets if getattr(a, "owner_id", None)}
    for r in risks:
        units.update(u.id for u in (getattr(r, "business_units", None) or []))
    return next(iter(units)) if len(units) == 1 else None


def loss_total(incidents: Iterable[Any]) -> float:
    """Sum of incident costs, near misses excluded (they have no loss by definition)."""
    return round(sum(float(i.cost or 0) for i in incidents if not getattr(i, "near_miss", False)), 2)
