"""Workspaces — where each line of defence starts, and the two workspaces built for the
people who don't run registers: the board home and the internal-audit assurance view.

**Landing.** A person's line of defence comes from their role names first and their
permissions second (the same rules as the sidebar's role presets, ``frontend/lib/nav.tsx``):

* first line → **My Work** (``/my-work``);
* second line → the **risk dashboard** (``/dashboard``);
* internal audit → **Assurance** (``/assurance``);
* board and read-only viewers → the **board home** (``/board``);
* administrators (``settings:manage`` or ``user:write``) → the dashboard (the app sends
  them to first-run setup instead while it is unfinished).

A workspace is available only with the permission its page needs (My Work always). A
person may choose their own start page (``UserWorkspacePreference``); a choice that is no
longer available (a permission was removed) falls back to the default.

**Board home** — appetite by category with its trend over the last four quarter ends
(period snapshots), top risks with their movement since the quarter began, the control
assurance and compliance headlines with trends, KRIs in breach with their recent
readings, open high and critical issues past their due date, committee decisions due
and overdue (the reader's own marked), upcoming meetings with their pack's state, and the
archive of released packs. Everything comes from the dashboard overview and the period
snapshots, so the board sees the dashboard's numbers in board language.

**Assurance** — engagements in progress, audit findings by age and owner with the ones
past due for follow-up, and the three-lines assurance map: for each risk category, what
the first line (control and risk attestations, completed RCSAs), second line (reviewed
control tests, assessed compliance clauses mapped to the category's controls) and third
line (audit engagements whose findings touch the category, or whose auditable unit is
that category) have covered, when last, and where the gaps are.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

# ================================================================== landing ===
MY_WORK, DASHBOARD, ASSURANCE, BOARD = "my_work", "dashboard", "assurance", "board"

WORKSPACES: tuple[tuple[str, str, str, str], ...] = (
    (MY_WORK, "My work", "/my-work", "Everything waiting for you, most urgent first."),
    (DASHBOARD, "Risk dashboard", "/dashboard", "The organisation's risk, control and compliance position."),
    (ASSURANCE, "Assurance", "/assurance", "Audit engagements, findings follow-up and the three-lines assurance map."),
    (BOARD, "Board", "/board", "Appetite, top risks, assurance and committee decisions in board language."),
)
WORKSPACE_KEYS: tuple[str, ...] = tuple(k for k, *_ in WORKSPACES)
#: The permission each workspace's page needs (None: everyone).
REQUIRES: dict[str, str | None] = {
    MY_WORK: None, DASHBOARD: "risk:read", ASSURANCE: "internal_audit:read", BOARD: "board:read",
}
LINE_DEFAULT: dict[str, str] = {
    "first_line": MY_WORK, "second_line": DASHBOARD, "audit": ASSURANCE, "board": BOARD,
}
ADMIN_PERMISSIONS = ("settings:manage", "user:write")

_ROLE_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"audit", re.I), "audit"),
    (re.compile(r"first[\s-]?line|1st[\s-]?line|champion|\bowner\b|business|branch|operations", re.I), "first_line"),
    (re.compile(r"admin|\brisk\b|compliance|\bgrc\b|second[\s-]?line|2nd[\s-]?line|\bciso\b|\bcro\b|\bcco\b", re.I),
     "second_line"),
    (re.compile(r"board|viewer|director|executive|read[\s-]?only", re.I), "board"),
)
_SECOND_LINE_PERMISSIONS = ("risk:write", "risk:accept", "compliance:write", "control:write")


def line_of_defence(role_names: Iterable[str], permissions: Iterable[str]) -> str:
    """first_line | second_line | audit | board. Role names first (first match wins, in
    rule order), then permissions: no write permission → board; internal-audit write
    without a second-line permission → audit; a second-line permission → second line;
    anything else → first line. Mirrors ``navPreset`` in ``frontend/lib/nav.tsx``. Pure."""
    roles = [r for r in role_names if r]
    for pattern, line in _ROLE_RULES:
        if any(pattern.search(r) for r in roles):
            return line
    held = set(permissions)
    writes = [p for p in held if not p.endswith(":read")]
    if not writes:
        return "board"
    second = any(p in held for p in _SECOND_LINE_PERMISSIONS)
    if "internal_audit:write" in held and not second:
        return "audit"
    return "second_line" if second else "first_line"


def is_admin(permissions: Iterable[str]) -> bool:
    held = set(permissions)
    return any(p in held for p in ADMIN_PERMISSIONS)


def available_workspaces(permissions: Iterable[str], modules_off: Iterable[str] = ()) -> list[str]:
    """Workspace keys this person may open, in :data:`WORKSPACES` order. The assurance
    workspace also needs the internal-audit module switched on. Pure."""
    held = set(permissions)
    off = set(modules_off)
    out = []
    for key in WORKSPACE_KEYS:
        need = REQUIRES[key]
        if need is not None and need not in held:
            continue
        if key == ASSURANCE and "internal_audit" in off:
            continue
        out.append(key)
    return out


def default_workspace(line: str, available: Sequence[str], admin: bool = False) -> str:
    """The workspace a line of defence starts on; administrators start on the dashboard.
    When that is not available: the dashboard, else My Work. Pure."""
    wanted = DASHBOARD if admin else LINE_DEFAULT.get(line, MY_WORK)
    for key in (wanted, DASHBOARD, MY_WORK):
        if key in available:
            return key
    return MY_WORK


def landing_workspace(line: str, available: Sequence[str], preference: str | None, admin: bool = False) -> str:
    """The preference when it is still available, else the default. Pure."""
    if preference and preference in available:
        return preference
    return default_workspace(line, available, admin)


def href_of(key: str) -> str:
    return next((h for k, _l, h, _d in WORKSPACES if k == key), "/my-work")


def workspace_read(*, role_names, permissions, preference: str | None, modules_off=()) -> dict:
    """The ``WorkspaceRead`` payload. Pure."""
    held = list(permissions)
    line = line_of_defence(role_names, held)
    admin = is_admin(held)
    available = available_workspaces(held, modules_off)
    default = default_workspace(line, available, admin)
    landing = landing_workspace(line, available, preference, admin)
    return {
        "line": line, "is_admin": admin, "default": default,
        "preference": preference if preference in WORKSPACE_KEYS else None,
        "landing": landing, "landing_href": href_of(landing),
        "available": [
            {"key": k, "label": label, "href": href, "description": desc}
            for k, label, href, desc in WORKSPACES if k in available
        ],
    }


async def load_preference(db, user_id) -> str | None:
    from sqlalchemy import select

    from app.models.workspace import UserWorkspacePreference

    return await db.scalar(select(UserWorkspacePreference.workspace).where(UserWorkspacePreference.user_id == user_id))


async def modules_off(db, keys: Iterable[str] = ("internal_audit", "governance_meetings")) -> set[str]:
    from sqlalchemy import select

    from app.models.settings import TenantSettings
    from app.services import modules

    choice = await db.scalar(select(TenantSettings.enabled_modules))
    return {k for k in keys if not modules.is_enabled(k) or (isinstance(choice, list) and k not in choice)}


# =============================================================== board home ===
QUARTERS = 4
#: Decisions due within this many days are "due" on the board home.
DECISION_HORIZON_DAYS = 30
MEETINGS_SHOWN = 6
PACKS_SHOWN = 12
KRI_READINGS = 8
ISSUES_SHOWN = 10
BOARD_SEVERITIES = ("critical", "high")


def _v(value: Any) -> Any:
    return getattr(value, "value", value)


def decision_rows(rows: Iterable[Any], *, user_id, today: date, horizon_days: int = DECISION_HORIZON_DAYS) -> list[dict]:
    """Open decisions and actions that are overdue or due within the horizon, overdue
    first then by date; the reader's own marked. Rows need id, reference, description,
    decision_type, status, owner, owner_id, due_date, committee, meeting, meeting_date. Pure."""
    horizon = today + timedelta(days=horizon_days)
    out = []
    for r in rows:
        if str(_v(r.status)) not in ("open", "in_progress") or r.due_date is None or r.due_date > horizon:
            continue
        out.append({
            "id": r.id, "reference": r.reference or "", "description": r.description or "",
            "decision_type": str(_v(r.decision_type)), "status": str(_v(r.status)),
            "owner": r.owner or "", "owner_id": r.owner_id, "due_date": r.due_date,
            "overdue": r.due_date < today, "mine": user_id is not None and r.owner_id == user_id,
            "committee": r.committee or "", "meeting": r.meeting or "", "meeting_date": r.meeting_date,
        })
    out.sort(key=lambda d: (not d["overdue"], not d["mine"], d["due_date"], d["reference"]))
    return out


def pack_state_for_meetings(packs: Iterable[Any]) -> dict:
    """The latest ready pack's review state per meeting. Rows need meeting_id,
    review_state, status and a sortable ``at``. Pure."""
    best: dict = {}
    for p in packs:
        if p.meeting_id is None or p.status != "ready":
            continue
        cur = best.get(p.meeting_id)
        if cur is None or (p.at or datetime.min.replace(tzinfo=timezone.utc)) > (cur.at or datetime.min.replace(tzinfo=timezone.utc)):
            best[p.meeting_id] = p
    return {mid: p.review_state for mid, p in best.items()}


async def board_home(db, user, org) -> dict:
    """The board home payload (``schemas.workspaces.BoardHome``) for ``user``."""
    from sqlalchemy import func, select

    from app.models.issue import Issue, IssueStatus2
    from app.models.operational_risk import KeyRiskIndicator, KriMeasurement
    from app.services import board_pack, master_data, snapshots
    from app.services.notifications import kri_threshold_text

    today = org.today
    overview = await board_pack.dashboard_overview(db, org.tenant_id, 90, user)
    ends = snapshots.quarter_ends(today, QUARTERS, org.fiscal_start_month)
    dates = await snapshots.available_dates(db, since=ends[0] - timedelta(days=snapshots.MAX_DISTANCE_DAYS))
    points = snapshots.trend_points(dates, ends)
    index = snapshots.index_rows(await snapshots.load_rows(db, [p.as_of for p in points]))

    # ------------------------------------------------------------- appetite
    p = overview.posture
    cat_series = snapshots.category_series(index, points)
    categories = []
    for c in p.by_category or []:
        key = str(c.category_id) if c.category_id else "default"
        trend = (cat_series.get(key) or {}).get("points", [])
        trend = list(trend) + [{"date": today, "as_of": today, "risks": c.risks, "within": c.within_appetite,
                                "elevated": c.elevated, "breach": c.breach}]
        categories.append({
            "key": key, "label": c.label, "appetite": c.appetite_score, "tolerance": c.tolerance_score,
            "risks": c.risks, "within": c.within_appetite, "elevated": c.elevated, "breach": c.breach,
            "trend": trend,
        })
    org_trend = snapshots.appetite_series(index, points) + [{
        "date": today, "as_of": today, "risks": p.total_risks, "within": p.within_appetite,
        "elevated": p.elevated, "breach": p.breach,
    }]

    # ------------------------------------------------------------- top risks
    quarter_start = board_pack.fiscal_quarter_start(today, org.fiscal_start_month)
    start_at, _end_at = board_pack.period_instants(quarter_start, today, org.tz)
    top = await board_pack._top_risks(db, overview, start_at)
    top_rows = []
    for t, row in zip(p.top_risks, top["rows"]):
        top_rows.append({
            "id": t.id, "reference": t.reference, "title": t.title, "score": t.score, "severity": t.severity,
            "appetite_status": t.appetite_status, "owner": t.owner, "movement": row.get("trend") or "unknown",
            "movement_text": row.get("trend_text") or "",
        })

    # ------------------------------------------------ assurance / compliance
    a = overview.assurance
    operating = a.effective + a.partially_effective + a.ineffective + a.not_assessed
    assured = a.effective + a.partially_effective
    assurance_pct = round(100.0 * assured / operating, 1) if operating else None
    assurance = {
        "value": assurance_pct,
        "detail": f"{assured} of {operating} operating controls effective or partially effective"
                  + (f"; {a.ineffective} ineffective, {a.not_assessed} not tested" if operating else ""),
        "trend": snapshots.metric_series(index, points, snapshots.ASSURANCE, "assured_pct")
        + [{"date": today, "as_of": today, "value": assurance_pct}],
    }
    comp = overview.compliance
    compliance = {
        "value": comp.overall_assured_pct if comp.frameworks else None,
        "detail": (f"Clauses assured by a working control across {len(comp.frameworks)} framework(s)"
                   if comp.frameworks else "No compliance framework installed"),
        "trend": snapshots.metric_series(index, points, snapshots.COMPLIANCE_OVERALL, "assured_pct")
        + [{"date": today, "as_of": today, "value": comp.overall_assured_pct if comp.frameworks else None}],
    }
    frameworks = [
        {"name": f.name, "assured_pct": round(100.0 * f.assured / f.applicable, 1) if f.applicable else None,
         "gaps": f.gaps}
        for f in comp.frameworks
    ]

    # ------------------------------------------------------------------ KRIs
    red_ids = [k.id for k in overview.kris.red_items]
    kri_rows = []
    if red_ids:
        kris = {k.id: k for k in (await db.execute(
            select(KeyRiskIndicator.id, KeyRiskIndicator.unit, KeyRiskIndicator.direction,
                   KeyRiskIndicator.warning_threshold, KeyRiskIndicator.limit_threshold,
                   KeyRiskIndicator.lower_bound, KeyRiskIndicator.upper_bound)
            .where(KeyRiskIndicator.id.in_(red_ids))
        )).all()}
        readings: dict = defaultdict(list)
        for kid, as_of, value in (await db.execute(
            select(KriMeasurement.kri_id, KriMeasurement.as_of_date, KriMeasurement.value)
            .where(KriMeasurement.kri_id.in_(red_ids))
            .order_by(KriMeasurement.kri_id, KriMeasurement.as_of_date.desc().nulls_last(), KriMeasurement.created_at.desc())
        )).all():
            if len(readings[kid]) < KRI_READINGS and value is not None:
                readings[kid].append({"as_of": as_of, "value": float(value)})
        for item in overview.kris.red_items:
            meta = kris.get(item.id)
            kri_rows.append({
                "id": item.id, "reference": item.reference, "name": item.name, "status": item.status,
                "value": item.current_value, "unit": item.unit or "", "owner": item.owner or "",
                "threshold_text": kri_threshold_text(meta) if meta is not None else "",
                "readings": list(reversed(readings.get(item.id, []))),
            })

    # --------------------------------------------------------------- issues
    closed = [IssueStatus2(s) for s in board_pack.CLOSED_ISSUE_STATES]
    past_due = (Issue.deleted.is_(False), Issue.status.not_in(closed), Issue.severity.in_(BOARD_SEVERITIES),
                Issue.due_date.is_not(None), Issue.due_date < today)
    issues_count = int(await db.scalar(select(func.count()).select_from(Issue).where(*past_due)) or 0)
    issue_rows = (await db.execute(
        select(Issue.id, Issue.reference, Issue.title, Issue.severity, Issue.owner, Issue.owner_id, Issue.due_date,
               Issue.regulator_related)
        .where(*past_due).order_by(Issue.due_date).limit(ISSUES_SHOWN)
    )).all()
    people = await master_data.users_by_id(db, [r.owner_id for r in issue_rows])
    issues = [
        {"id": r.id, "reference": r.reference or "", "title": r.title, "severity": str(_v(r.severity)),
         "owner": (people[r.owner_id].full_name or people[r.owner_id].email) if r.owner_id in people else (r.owner or ""),
         "due_date": r.due_date, "days_overdue": (today - r.due_date).days, "regulator_related": bool(r.regulator_related)}
        for r in issue_rows
    ]

    out = {
        "as_of": today, "organisation": org.name, "quarter_ends": ends, "has_snapshots": bool(dates),
        "health_score": overview.health.score if overview.health.band != "no_data" else None,
        "health_band": overview.health.band,
        "appetite": {"risks": p.total_risks, "within": p.within_appetite, "elevated": p.elevated, "breach": p.breach,
                     "appetite": p.appetite_score, "tolerance": p.tolerance_score, "categories": categories,
                     "trend": org_trend},
        "top_risks": top_rows, "assurance": assurance, "compliance": compliance, "frameworks": frameworks,
        "kris_red": overview.kris.red, "kris_amber": overview.kris.amber, "kris_in_breach": kri_rows,
        "issues_past_due": issues_count, "issues": issues,
    }
    off = await modules_off(db, ("governance_meetings",))
    out["governance_enabled"] = "governance_meetings" not in off
    if out["governance_enabled"]:
        out.update(await _board_governance(db, user, today))
    return out


async def _board_governance(db, user, today: date) -> dict:
    from sqlalchemy import func, select

    from app.models.collab import StoredFile  # noqa: F401 - file presence comes from the pack row
    from app.models.governance import (
        BoardPack, Committee, CommitteeMember, DecisionStatus, Meeting, MeetingDecision, MeetingStatus,
    )
    from app.services import board_pack

    user_id = getattr(user, "id", None)
    mine = set((await db.scalars(
        select(CommitteeMember.committee_id).where(CommitteeMember.user_id == user_id)
    )).all()) if user_id else set()
    names = dict((await db.execute(
        select(Committee.id, Committee.name).where(Committee.deleted.is_(False))
    )).all())
    open_states = (DecisionStatus.open, DecisionStatus.in_progress)
    horizon = today + timedelta(days=DECISION_HORIZON_DAYS)
    rows = (await db.execute(
        select(MeetingDecision.id, MeetingDecision.reference, MeetingDecision.description,
               MeetingDecision.decision_type, MeetingDecision.status, MeetingDecision.owner,
               MeetingDecision.owner_id, MeetingDecision.due_date, Committee.name.label("committee"),
               Meeting.title.label("meeting"), Meeting.meeting_date)
        .join(Meeting, Meeting.id == MeetingDecision.meeting_id)
        .join(Committee, Committee.id == Meeting.committee_id)
        .where(Committee.deleted.is_(False), MeetingDecision.status.in_(open_states),
               MeetingDecision.due_date.is_not(None), MeetingDecision.due_date <= horizon)
        .order_by(MeetingDecision.due_date)
        .limit(200)
    )).all()
    decisions = decision_rows(rows, user_id=user_id, today=today)
    meetings = (await db.execute(
        select(Meeting.id, Meeting.reference, Meeting.title, Meeting.meeting_date, Meeting.committee_id)
        .join(Committee, Committee.id == Meeting.committee_id)
        .where(Committee.deleted.is_(False), Meeting.status == MeetingStatus.scheduled,
               Meeting.meeting_date.is_not(None), Meeting.meeting_date >= today)
        .order_by(Meeting.meeting_date).limit(MEETINGS_SHOWN)
    )).all()
    states = {}
    if meetings:
        states = pack_state_for_meetings((await db.execute(
            select(BoardPack.meeting_id, BoardPack.review_state, BoardPack.status,
                   func.coalesce(BoardPack.generated_at, BoardPack.created_at).label("at"))
            .where(BoardPack.meeting_id.in_([m.id for m in meetings]))
        )).all())
    packs = (await db.execute(
        select(BoardPack.id, BoardPack.title, BoardPack.committee_id, BoardPack.meeting_id, BoardPack.period_start,
               BoardPack.period_end, BoardPack.released_at, BoardPack.pdf_file_id, BoardPack.xlsx_file_id)
        .where(BoardPack.status == board_pack.READY, BoardPack.review_state == board_pack.RELEASED)
        .order_by(BoardPack.released_at.desc().nulls_last(), BoardPack.created_at.desc())
        .limit(PACKS_SHOWN)
    )).all()
    meeting_titles = dict((await db.execute(
        select(Meeting.id, Meeting.title).where(Meeting.id.in_([p.meeting_id for p in packs if p.meeting_id]))
    )).all()) if any(p.meeting_id for p in packs) else {}
    return {
        "my_committees": sorted(names[c] for c in mine if c in names),
        "decisions_overdue": sum(1 for d in decisions if d["overdue"]),
        "decisions_due": sum(1 for d in decisions if not d["overdue"]),
        "decisions": decisions[:50],
        "meetings": [
            {"id": m.id, "reference": m.reference or "", "title": m.title, "committee": names.get(m.committee_id, ""),
             "committee_id": m.committee_id, "meeting_date": m.meeting_date,
             "days_away": (m.meeting_date - today).days if m.meeting_date else None,
             "pack_state": states.get(m.id, "none"), "mine": m.committee_id in mine}
            for m in meetings
        ],
        "packs": [
            {"id": pk.id, "title": pk.title, "committee": names.get(pk.committee_id, ""),
             "meeting": meeting_titles.get(pk.meeting_id, ""), "period_start": pk.period_start,
             "period_end": pk.period_end, "released_at": pk.released_at,
             "has_pdf": pk.pdf_file_id is not None, "has_xlsx": pk.xlsx_file_id is not None}
            for pk in packs
        ],
    }


# =========================================================== assurance home ===
#: How recent each line's work must be to count as coverage.
FIRST_LINE_DAYS = 365
SECOND_LINE_DAYS = 365
THIRD_LINE_DAYS = 3 * 365
#: At or above this share of a category's controls a line is "covered".
COVERED_PCT = 80.0
AGE_BUCKETS: tuple[tuple[str, str, int | None], ...] = (
    ("0_30", "Up to 30 days", 30),
    ("31_90", "31–90 days", 90),
    ("91_180", "91–180 days", 180),
    ("over_180", "Over 180 days", None),
)
OPEN_FINDING_STATES = ("open", "in_progress")
UNCATEGORISED = "none"


def age_bucket(age_days: int) -> str:
    for key, _label, limit in AGE_BUCKETS:
        if limit is None or age_days <= limit:
            return key
    return AGE_BUCKETS[-1][0]


def findings_follow_up(rows: Iterable[Any], today: date) -> dict:
    """Open findings by age (since raised) and by owner, and the ones past their agreed
    date — the auditor's follow-up list, oldest overdue first. Rows need id, reference,
    title, rating, status, action_owner, engagement_id, engagement, due_date, created_at.
    Pure."""
    buckets: Counter = Counter()
    bucket_over: Counter = Counter()
    owners: dict[str, Counter] = {}
    overdue_rows = []
    total = 0
    for r in rows:
        if str(_v(r.status)) not in OPEN_FINDING_STATES:
            continue
        total += 1
        created = r.created_at.date() if isinstance(r.created_at, datetime) else (r.created_at or today)
        age = max(0, (today - created).days)
        over = r.due_date is not None and r.due_date < today
        b = age_bucket(age)
        buckets[b] += 1
        owner = (r.action_owner or "").strip() or "Unassigned"
        o = owners.setdefault(owner, Counter())
        o["open"] += 1
        o["oldest"] = max(o["oldest"], age)
        if over:
            bucket_over[b] += 1
            o["overdue"] += 1
            overdue_rows.append({
                "id": r.id, "reference": r.reference or "", "title": r.title, "rating": str(_v(r.rating)),
                "status": str(_v(r.status)), "owner": owner if owner != "Unassigned" else "",
                "engagement_id": r.engagement_id, "engagement": r.engagement or "", "due_date": r.due_date,
                "age_days": age, "days_overdue": (today - r.due_date).days,
            })
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    overdue_rows.sort(key=lambda f: (-f["days_overdue"], rank.get(f["rating"], 9), f["reference"]))
    return {
        "findings_open": total,
        "findings_overdue": len(overdue_rows),
        "age_buckets": [{"key": k, "label": label, "count": buckets.get(k, 0), "overdue": bucket_over.get(k, 0)}
                        for k, label, _l in AGE_BUCKETS],
        "by_owner": sorted(
            ({"owner": name, "open": c["open"], "overdue": c["overdue"], "oldest_days": c["oldest"]}
             for name, c in owners.items()),
            key=lambda o: (-o["overdue"], -o["open"], o["owner"].lower()),
        ),
        "overdue_findings": overdue_rows,
    }


@dataclass
class MapInputs:
    """Everything the assurance map is computed from (loaded by :func:`load_map_inputs`)."""

    #: level-1 category id (or None) -> label
    categories: Mapping[Any, str]
    #: risk id -> level-1 category id (or None)
    risk_category: Mapping[Any, Any]
    #: (risk id, control id)
    risk_controls: Sequence[tuple[Any, Any]]
    #: control id -> latest attestation date (first line)
    control_attested: Mapping[Any, date]
    #: risk id -> latest attestation / review date (first line)
    risk_attested: Mapping[Any, date]
    #: level-1 category id -> latest completed RCSA date (first line)
    rcsa_completed: Mapping[Any, date]
    #: control id -> latest reviewed test date (second line)
    control_tested: Mapping[Any, date]
    #: control id -> assessed compliance clauses mapped to it (second line)
    control_clauses: Mapping[Any, int]
    #: (engagement id, end date, risk ids, control ids, unit category label) — third line
    engagements: Sequence[tuple[Any, date | None, frozenset, frozenset, str]]


def _line(covered: int, total: int, last: date | None, *, recent: bool, detail: str,
          applicable: bool = True) -> dict:
    """One line's coverage. With a population (controls): covered at or above
    :data:`COVERED_PCT`, partial when anything is covered, else none. Without one: covered
    when there is recent work at all. Pure."""
    pct = round(100.0 * covered / total, 1) if total else None
    if not applicable:
        state = "not_applicable"
    elif total:
        state = "covered" if (pct or 0) >= COVERED_PCT else ("partial" if covered or recent else "none")
    else:
        state = "covered" if recent else "none"
    return {"state": state, "covered": covered, "total": total, "pct": pct, "last": last, "detail": detail}


def assurance_map(inputs: MapInputs, today: date) -> list[dict]:
    """One row per risk category (and one for risks with no category): risks, controls,
    and each line's coverage, last date and gaps. See the module notes. Pure."""
    first_since = today - timedelta(days=FIRST_LINE_DAYS)
    second_since = today - timedelta(days=SECOND_LINE_DAYS)
    third_since = today - timedelta(days=THIRD_LINE_DAYS)
    risks_by_cat: dict[Any, set] = defaultdict(set)
    for rid, cat in inputs.risk_category.items():
        risks_by_cat[cat].add(rid)
    controls_of_risk: dict[Any, set] = defaultdict(set)
    for rid, cid in inputs.risk_controls:
        controls_of_risk[rid].add(cid)
    keys = list(inputs.categories)
    if None in risks_by_cat and None not in keys:
        keys.append(None)
    rows = []
    for cat in keys:
        label = inputs.categories.get(cat) or "No category"
        risk_ids = risks_by_cat.get(cat, set())
        control_ids = set().union(*(controls_of_risk[r] for r in risk_ids)) if risk_ids else set()
        if not risk_ids and cat is not None:
            continue

        # First line: attested controls; risks reviewed; RCSAs completed in the category.
        attested = [inputs.control_attested[c] for c in control_ids
                    if c in inputs.control_attested and inputs.control_attested[c] >= first_since]
        risk_dates = [inputs.risk_attested[r] for r in risk_ids
                      if r in inputs.risk_attested and inputs.risk_attested[r] >= first_since]
        rcsa = inputs.rcsa_completed.get(cat)
        first_dates = attested + risk_dates + ([rcsa] if rcsa and rcsa >= first_since else [])
        all_first = [d for d in ([inputs.control_attested.get(c) for c in control_ids]
                                 + [inputs.risk_attested.get(r) for r in risk_ids] + [rcsa]) if d]
        # Without controls, the first line is judged on risk reviews and RCSAs alone.
        first_covered, first_total = (len(attested), len(control_ids)) if control_ids else (len(risk_dates), len(risk_ids))
        first = _line(
            first_covered, first_total, max(all_first) if all_first else None,
            recent=bool(first_dates),
            detail=f"{len(attested)} of {len(control_ids)} controls attested, {len(risk_dates)} of {len(risk_ids)} "
                   f"risks reviewed in the last 12 months" + (f"; RCSA completed {rcsa.isoformat()}" if rcsa else ""),
        )

        # Second line: controls with a reviewed test; assessed clauses mapped to them.
        tested = [inputs.control_tested[c] for c in control_ids
                  if c in inputs.control_tested and inputs.control_tested[c] >= second_since]
        all_tests = [inputs.control_tested[c] for c in control_ids if c in inputs.control_tested]
        clauses = sum(int(inputs.control_clauses.get(c, 0) or 0) for c in control_ids)
        second = _line(
            len(tested), len(control_ids), max(all_tests) if all_tests else None, recent=bool(tested),
            applicable=bool(control_ids),
            detail=f"{len(tested)} of {len(control_ids)} controls tested and reviewed in the last 12 months; "
                   f"{clauses} assessed compliance clause(s) rest on them",
        )

        # Third line: engagements touching the category's risks or controls, or auditing
        # a unit filed under the category.
        touching = []
        for _eid, end, e_risks, e_controls, unit_cat in inputs.engagements:
            if (e_risks & risk_ids) or (e_controls & control_ids) or (
                    cat is not None and unit_cat and unit_cat.strip().lower() == label.strip().lower()):
                touching.append(end)
        dated = [d for d in touching if d]
        recent = [d for d in dated if d >= third_since]
        third = {
            "state": "covered" if recent else ("partial" if touching else "none"),
            "covered": len(recent), "total": len(touching), "pct": None,
            "last": max(dated) if dated else None,
            "detail": (f"{len(recent)} engagement(s) in the last 3 years" if recent
                       else f"{len(touching)} older engagement(s)" if touching else "Not audited"),
        }

        gaps = []
        if not control_ids:
            gaps.append("No controls linked to the category's risks")
        if first["state"] in ("none", "partial"):
            gaps.append("First line: attestations missing or older than 12 months" if control_ids
                        else "First line: no risk review or RCSA in the last 12 months")
        if control_ids and second["state"] in ("none", "partial"):
            gaps.append("Second line: controls not independently tested in the last 12 months")
        if third["state"] != "covered":
            gaps.append("Third line: not audited in the last 3 years")
        rows.append({
            "key": str(cat) if cat is not None else UNCATEGORISED, "label": label,
            "risks": len(risk_ids), "controls": len(control_ids),
            "first_line": first, "second_line": second, "third_line": third, "gaps": gaps,
        })
    rank = {"none": 0, "partial": 1, "covered": 2, "not_applicable": 3}
    rows.sort(key=lambda r: (-len(r["gaps"]), rank.get(r["third_line"]["state"], 9), r["label"].lower()))
    return rows


def engagement_end(status: Any, actual_end: date | None, report_date: date | None, planned_end: date | None) -> date | None:
    """When an engagement's assurance dates from: the report, else fieldwork's end; an
    engagement not yet closed dates from its planned end only once that has passed. Pure."""
    return report_date or actual_end or (planned_end if str(_v(status)) == "closed" else None)


async def load_map_inputs(db, today: date) -> MapInputs:
    from sqlalchemy import func, select

    from app.models.attestation import Attestation
    from app.models.compliance import Requirement, requirement_controls
    from app.models.control import Control, ControlAudit
    from app.models.enums import AuditEngagementStatus, RcsaStatus, RiskStatus
    from app.models.internal_audit import (
        AuditableUnit, AuditEngagement, AuditFinding, audit_finding_controls, audit_finding_risks,
    )
    from app.models.lookup import Lookup
    from app.models.operational_risk import RcsaAssessment, RcsaRisk
    from app.models.risk import Risk, risk_controls
    from app.services.control_assurance import COUNTING_REVIEW_STATES
    from app.services.risk_scoring import AppetiteBook

    lookups = (await db.execute(
        select(Lookup.id, Lookup.label, Lookup.parent_id).where(Lookup.key == "risk_category")
    )).all()
    book = AppetiteBook(parents={lid: parent for lid, _label, parent in lookups})
    labels = {lid: label for lid, label, _p in lookups}
    risks = (await db.execute(
        select(Risk.id, Risk.category_id).where(Risk.deleted.is_(False), Risk.status != RiskStatus.closed)
    )).all()
    risk_category = {r.id: book.top_of(r.category_id) if r.category_id else None for r in risks}
    categories = {cid: labels.get(cid, "Category") for cid in sorted(
        {c for c in risk_category.values() if c is not None}, key=lambda c: labels.get(c, "").lower())}
    pairs = (await db.execute(
        select(risk_controls.c.risk_id, risk_controls.c.control_id)
        .join(Control, Control.id == risk_controls.c.control_id)
        .where(Control.deleted.is_(False))
    )).all()
    control_attested = dict((await db.execute(
        select(Attestation.entity_id, func.max(Attestation.attested_at))
        .where(Attestation.entity_type == "control").group_by(Attestation.entity_id)
    )).all())
    risk_attested = dict((await db.execute(
        select(Attestation.entity_id, func.max(Attestation.attested_at))
        .where(Attestation.entity_type == "risk").group_by(Attestation.entity_id)
    )).all())
    rcsa_completed: dict = {}
    for cat_id, done in (await db.execute(
        select(RcsaRisk.category_id, func.max(func.coalesce(RcsaAssessment.completed_date, RcsaAssessment.due_date)))
        .join(RcsaAssessment, RcsaAssessment.id == RcsaRisk.assessment_id)
        .where(RcsaAssessment.deleted.is_(False), RcsaAssessment.status == RcsaStatus.completed)
        .group_by(RcsaRisk.category_id)
    )).all():
        top = book.top_of(cat_id) if cat_id else None
        if done and (top not in rcsa_completed or done > rcsa_completed[top]):
            rcsa_completed[top] = done
    control_tested = dict((await db.execute(
        select(ControlAudit.control_id, func.max(ControlAudit.conducted_date))
        .where(ControlAudit.review_status.in_(COUNTING_REVIEW_STATES), ControlAudit.conducted_date.is_not(None))
        .group_by(ControlAudit.control_id)
    )).all())
    control_clauses = dict((await db.execute(
        select(requirement_controls.c.control_id, func.count(func.distinct(Requirement.id)))
        .join(Requirement, Requirement.id == requirement_controls.c.requirement_id)
        .where(Requirement.status.not_in(("not_assessed", "not_applicable")))
        .group_by(requirement_controls.c.control_id)
    )).all())
    engagements = (await db.execute(
        select(AuditEngagement.id, AuditEngagement.status, AuditEngagement.actual_end, AuditEngagement.report_date,
               AuditEngagement.planned_end, AuditableUnit.category)
        .outerjoin(AuditableUnit, AuditableUnit.id == AuditEngagement.auditable_unit_id)
        .where(AuditEngagement.deleted.is_(False), AuditEngagement.status != AuditEngagementStatus.cancelled)
    )).all()
    e_risks: dict = defaultdict(set)
    for eid, rid in (await db.execute(
        select(AuditFinding.engagement_id, audit_finding_risks.c.risk_id)
        .join(audit_finding_risks, audit_finding_risks.c.audit_finding_id == AuditFinding.id)
    )).all():
        e_risks[eid].add(rid)
    e_controls: dict = defaultdict(set)
    for eid, cid in (await db.execute(
        select(AuditFinding.engagement_id, audit_finding_controls.c.control_id)
        .join(audit_finding_controls, audit_finding_controls.c.audit_finding_id == AuditFinding.id)
    )).all():
        e_controls[eid].add(cid)
    return MapInputs(
        categories=categories, risk_category=risk_category, risk_controls=[tuple(p) for p in pairs],
        control_attested=control_attested, risk_attested=risk_attested, rcsa_completed=rcsa_completed,
        control_tested=control_tested, control_clauses=control_clauses,
        engagements=[
            (e.id, engagement_end(e.status, e.actual_end, e.report_date, e.planned_end),
             frozenset(e_risks.get(e.id, ())), frozenset(e_controls.get(e.id, ())), e.category or "")
            for e in engagements
        ],
    )


ACTIVE_ENGAGEMENT_STATES = ("fieldwork", "reporting")
#: Planned engagements starting within this many days are shown as in progress.
STARTING_SOON_DAYS = 30


async def assurance_home(db, user, org) -> dict:
    from sqlalchemy import and_, func, or_, select

    from app.models.enums import AuditEngagementStatus, AuditProcedureResult
    from app.models.internal_audit import AuditableUnit, AuditEngagement, AuditFinding, AuditProcedure

    today = org.today
    off = await modules_off(db, ("internal_audit",))
    out: dict = {"as_of": today, "internal_audit_enabled": "internal_audit" not in off,
                 "document_requests_supported": False,
                 "map_windows": {"first_line_days": FIRST_LINE_DAYS, "second_line_days": SECOND_LINE_DAYS,
                                 "third_line_days": THIRD_LINE_DAYS}}
    if out["internal_audit_enabled"]:
        soon = today + timedelta(days=STARTING_SOON_DAYS)
        engagements = (await db.execute(
            select(AuditEngagement.id, AuditEngagement.reference, AuditEngagement.title, AuditEngagement.status,
                   AuditEngagement.audit_type, AuditEngagement.lead_auditor, AuditEngagement.planned_start,
                   AuditEngagement.planned_end, AuditableUnit.name.label("unit"))
            .outerjoin(AuditableUnit, AuditableUnit.id == AuditEngagement.auditable_unit_id)
            .where(AuditEngagement.deleted.is_(False), or_(
                AuditEngagement.status.in_([AuditEngagementStatus(s) for s in ACTIVE_ENGAGEMENT_STATES]),
                and_(AuditEngagement.status == AuditEngagementStatus.planned,
                     AuditEngagement.planned_start.is_not(None), AuditEngagement.planned_start <= soon),
            ))
            .order_by(AuditEngagement.planned_end.nulls_last(), AuditEngagement.reference)
        )).all()
        ids = [e.id for e in engagements]
        procs: dict = {}
        open_findings: dict = {}
        if ids:
            for eid, total, pending in (await db.execute(
                select(AuditProcedure.engagement_id, func.count(),
                       func.count().filter(AuditProcedure.result == AuditProcedureResult.pending))
                .where(AuditProcedure.engagement_id.in_(ids)).group_by(AuditProcedure.engagement_id)
            )).all():
                procs[eid] = (int(total), int(pending))
            open_findings = dict((await db.execute(
                select(AuditFinding.engagement_id, func.count())
                .where(AuditFinding.engagement_id.in_(ids), AuditFinding.status.in_(OPEN_FINDING_STATES))
                .group_by(AuditFinding.engagement_id)
            )).all())
        rows = []
        for e in engagements:
            status = str(_v(e.status))
            rows.append({
                "id": e.id, "reference": e.reference or "", "title": e.title, "status": status,
                "audit_type": str(_v(e.audit_type) or ""), "lead_auditor": e.lead_auditor or "", "unit": e.unit or "",
                "planned_start": e.planned_start, "planned_end": e.planned_end,
                "overdue": status in ACTIVE_ENGAGEMENT_STATES and e.planned_end is not None and e.planned_end < today,
                "procedures": procs.get(e.id, (0, 0))[0], "procedures_pending": procs.get(e.id, (0, 0))[1],
                "findings_open": int(open_findings.get(e.id, 0)),
            })
        out["engagements"] = rows
        out["engagements_overdue"] = sum(1 for r in rows if r["overdue"])
        findings = (await db.execute(
            select(AuditFinding.id, AuditFinding.reference, AuditFinding.title, AuditFinding.rating,
                   AuditFinding.status, AuditFinding.action_owner, AuditFinding.engagement_id,
                   AuditEngagement.title.label("engagement"), AuditFinding.due_date, AuditFinding.created_at)
            .join(AuditEngagement, AuditEngagement.id == AuditFinding.engagement_id)
            .where(AuditEngagement.deleted.is_(False), AuditFinding.status.in_(OPEN_FINDING_STATES))
        )).all()
        follow = findings_follow_up(findings, today)
        follow["overdue_findings"] = follow["overdue_findings"][:50]
        out.update(follow)
    out["map"] = assurance_map(await load_map_inputs(db, today), today)
    return out
