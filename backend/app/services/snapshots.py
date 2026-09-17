"""Period snapshots — the organisation's headline figures as they stood on a date.

Without snapshots every "trend" is a guess and a board pack for June prints September's
numbers. The scheduler writes a snapshot at each month end (:func:`run_due`), and the
first time it runs for an organisation it reconstructs the last four quarter ends from
the records' own history where that history exists (:func:`backfill`).

What a snapshot holds (``MetricSnapshot`` rows, one per key and dimension):

==========================  ==============  ===========================================
key                         dimension       value
==========================  ==============  ===========================================
``health``                  —               score, band
``appetite.total``          —               risks, within, elevated, breach, appetite,
                                            tolerance
``appetite.category``       category id or  label, appetite, tolerance, risks, within,
                            ``default``     elevated, breach
``risks.severity``          —               inherent {band: n}, residual {band: n}
``risks.top``               —               rows [{id, reference, title, score,
                                            severity, appetite_status, owner}]
``risks.heatmap``           —               size, cells {"L,I": n} (current exposure)
``assurance``               —               effective … not_operating, tests_overdue,
                                            last_test_failed, operating, assured_pct
``compliance.overall``      —               assured_pct
``compliance.framework``    framework id    name, applicable, assured, assured_pct,
                                            compliant_pct, gaps, failing, unassessed,
                                            unmapped
``kri.status``              —               green, amber, red, no_data
``kri.value``               KRI id          reference, name, value, status, unit
``issues.open``             —               open, overdue, by_severity {sev: n}
==========================  ==============  ===========================================

A **captured** snapshot is taken from the dashboard's own overview (so it can never
disagree with the dashboard on the day). A **backfilled** one is reconstructed: each
risk's scores, status and category from its latest version-history entry on or before
the date, judged against *today's* appetite and severity bands; each KRI's latest
reading on or before the date against today's thresholds; and issues open on the date
from their raised and closed dates. Control assurance and compliance are not
reconstructed — there is no history to rebuild them from honestly — so a backfilled
date simply has no row for them, and every reader says "no snapshot" rather than guess.

Pure rules (when a snapshot is due, which snapshot stands for a date, the series a chart
draws) are unit-tested; the async functions load and write for one organisation.
"""
from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

HEALTH = "health"
APPETITE_TOTAL = "appetite.total"
APPETITE_CATEGORY = "appetite.category"
SEVERITY = "risks.severity"
TOP_RISKS = "risks.top"
HEATMAP = "risks.heatmap"
ASSURANCE = "assurance"
COMPLIANCE_OVERALL = "compliance.overall"
COMPLIANCE_FRAMEWORK = "compliance.framework"
KRI_STATUS = "kri.status"
KRI_VALUE = "kri.value"
ISSUES_OPEN = "issues.open"

KEYS: tuple[str, ...] = (
    HEALTH, APPETITE_TOTAL, APPETITE_CATEGORY, SEVERITY, TOP_RISKS, HEATMAP, ASSURANCE,
    COMPLIANCE_OVERALL, COMPLIANCE_FRAMEWORK, KRI_STATUS, KRI_VALUE, ISSUES_OPEN,
)

SCHEDULER, BACKFILL, MANUAL = "scheduler", "backfill", "manual"
#: A snapshot further than this from the date it is asked to stand for is not used.
MAX_DISTANCE_DAYS = 45
#: Top risks kept in a snapshot.
TOP_N = 10
SEVERITIES = ("critical", "high", "medium", "low")
BACKFILL_BASIS = (
    "Reconstructed from the records' history: risk scores and status from version history, "
    "judged against today's appetite and severity bands; KRI readings against today's thresholds."
)


def _v(value: Any) -> Any:
    return getattr(value, "value", value)


# ================================================================= pure rules ===
def month_end(day: date) -> date:
    nxt = date(day.year + (day.month // 12), day.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def snapshot_due(today: date, latest: date | None) -> bool:
    """Whether the scheduler should capture a snapshot today.

    On the last day of each month (once). Also on any day when the previous month's end
    was missed (the scheduler was down) — the catch-up is dated today, never back-dated —
    and on the first run for an organisation, so trends have a starting point."""
    if latest is not None and latest >= today:
        return False
    if today == month_end(today):
        return True
    previous_end = today.replace(day=1) - timedelta(days=1)
    return latest is None or latest < previous_end


def quarter_ends(today: date, count: int = 4, fiscal_start_month: int = 1) -> list[date]:
    """The last ``count`` completed fiscal quarter ends before ``today``, oldest first."""
    from app.services.board_pack import fiscal_quarter_start

    ends: list[date] = []
    start = fiscal_quarter_start(today, fiscal_start_month)
    for _ in range(count):
        end = start - timedelta(days=1)
        ends.append(end)
        start = fiscal_quarter_start(end, fiscal_start_month)
    return list(reversed(ends))


def nearest_date(available: Iterable[date], target: date, max_days: int = MAX_DISTANCE_DAYS) -> date | None:
    """The snapshot date that best stands for ``target``: the closest one within
    ``max_days``, preferring one on or before the target when two are equally close
    (a figure known on the day beats one from after it)."""
    best: tuple[int, int, date] | None = None
    for d in set(available):
        gap = abs((d - target).days)
        if gap > max_days:
            continue
        key = (gap, 0 if d <= target else 1, d)
        if best is None or key < best:
            best = key
    return best[2] if best else None


@dataclass(frozen=True)
class Point:
    """One point of a trend: the date it stands for and the snapshot date behind it."""

    label_date: date
    as_of: date | None


def trend_points(available: Iterable[date], targets: Sequence[date]) -> list[Point]:
    """For each target date (quarter ends), the snapshot used — or None when there is no
    snapshot near enough, which a chart shows as a gap rather than a made-up value."""
    avail = list(set(available))
    return [Point(t, nearest_date(avail, t)) for t in targets]


def index_rows(rows: Iterable[Any]) -> dict[date, dict[str, dict[str, dict]]]:
    """``{as_of: {key: {dimension: value}}}`` from snapshot rows."""
    out: dict[date, dict[str, dict[str, dict]]] = {}
    for r in rows:
        out.setdefault(r.as_of, {}).setdefault(r.key, {})[r.dimension or ""] = dict(r.value or {})
    return out


def rows_from_overview(overview: Any, *, heatmap: Mapping | None = None, kris: Iterable[Any] = (),
                       issues: Mapping | None = None) -> list[tuple[str, str, dict]]:
    """The ``(key, dimension, value)`` rows for a captured snapshot. Pure: the overview is
    the dashboard's own response; ``kris`` rows need id, reference, name, current_value,
    unit and a status; ``issues`` is ``board_pack.issue_summary`` output."""
    out: list[tuple[str, str, dict]] = []
    h = overview.health
    out.append((HEALTH, "", {"score": h.score if h.band != "no_data" else None, "band": h.band}))
    p = overview.posture
    out.append((APPETITE_TOTAL, "", {
        "risks": p.total_risks, "within": p.within_appetite, "elevated": p.elevated, "breach": p.breach,
        "appetite": p.appetite_score, "tolerance": p.tolerance_score,
    }))
    for c in p.by_category or []:
        out.append((APPETITE_CATEGORY, str(c.category_id) if c.category_id else "default", {
            "label": c.label, "appetite": c.appetite_score, "tolerance": c.tolerance_score, "risks": c.risks,
            "within": c.within_appetite, "elevated": c.elevated, "breach": c.breach,
        }))
    out.append((SEVERITY, "", {"inherent": dict(p.by_inherent_severity or {}),
                               "residual": dict(p.by_residual_severity or {})}))
    out.append((TOP_RISKS, "", {"rows": [
        {"id": str(t.id), "reference": t.reference, "title": t.title, "score": t.score, "severity": t.severity,
         "appetite_status": t.appetite_status, "owner": t.owner}
        for t in list(p.top_risks)[:TOP_N]
    ]}))
    if heatmap is not None:
        out.append((HEATMAP, "", dict(heatmap)))
    a = overview.assurance
    operating = a.effective + a.partially_effective + a.ineffective + a.not_assessed
    assured = a.effective + a.partially_effective
    out.append((ASSURANCE, "", {
        "total": a.total, "effective": a.effective, "partially_effective": a.partially_effective,
        "ineffective": a.ineffective, "not_assessed": a.not_assessed, "not_operating": a.not_operating,
        "tests_overdue": a.tests_overdue, "last_test_failed": a.last_test_failed, "operating": operating,
        "assured_pct": round(100.0 * assured / operating, 1) if operating else None,
    }))
    comp = overview.compliance
    out.append((COMPLIANCE_OVERALL, "", {"assured_pct": comp.overall_assured_pct}))
    for f in comp.frameworks:
        out.append((COMPLIANCE_FRAMEWORK, str(f.id), {
            "name": f.name, "applicable": f.applicable, "assured": f.assured,
            "assured_pct": round(100.0 * f.assured / f.applicable, 1) if f.applicable else None,
            "compliant_pct": f.compliant_pct, "gaps": f.gaps, "failing": f.failing,
            "unassessed": f.unassessed, "unmapped": f.unmapped,
        }))
    counts: Counter = Counter()
    for k in kris:
        status = str(_v(k.status))
        counts[status] += 1
        out.append((KRI_VALUE, str(k.id), {
            "reference": k.reference or "", "name": k.name, "status": status, "unit": k.unit or "",
            "value": float(k.current_value) if k.current_value is not None else None,
        }))
    out.append((KRI_STATUS, "", {s: counts.get(s, 0) for s in ("green", "amber", "red", "no_data")}))
    if issues is not None:
        out.append((ISSUES_OPEN, "", {
            "open": issues.get("open", 0), "overdue": issues.get("overdue", 0),
            "by_severity": {r["severity"]: r["open"] for r in issues.get("by_severity", [])},
        }))
    return out


def heatmap_cells(rows: Iterable[Any], size: int) -> dict:
    """Risks on the board register per heat-map cell of their current exposure (residual
    cell once assessed, else inherent). Rows need the four likelihood/impact columns,
    residual_score, status and last_assessed_at. Pure."""
    from app.services.risk_query import on_board_register

    cells: Counter = Counter()
    for r in rows:
        if not on_board_register(r.status, r.last_assessed_at):
            continue
        if r.residual_score is not None and r.residual_likelihood and r.residual_impact:
            like, imp = r.residual_likelihood, r.residual_impact
        else:
            like, imp = r.inherent_likelihood, r.inherent_impact
        if like and imp:
            cells[f"{int(like)},{int(imp)}"] += 1
    return {"size": int(size or 5), "cells": dict(cells)}


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def reconstruct_risk_rows(
    risks: Iterable[Any], history: Mapping[Any, Mapping], book: Any, scale: Any, labels: Mapping[Any, str],
    *, size: int = 5,
) -> list[tuple[str, str, dict]]:
    """Appetite, severity and heat-map rows for a past date from version snapshots.
    ``risks`` need id; ``history`` maps risk id to its latest snapshot on or before the
    date (risks with none did not exist yet, or have no history, and are left out).
    Pure."""
    from app.services.board_pack import score_from_snapshot
    from app.services.risk_query import on_board_register

    totals: Counter = Counter()
    by_cat: dict[Any, Counter] = {}
    inherent: Counter = Counter()
    residual: Counter = Counter()
    cells: Counter = Counter()
    for r in risks:
        snap = history.get(r.id)
        if not snap or snap.get("deleted"):
            continue
        if not on_board_register(snap.get("status"), _parse_dt(snap.get("last_assessed_at"))):
            continue
        score = score_from_snapshot(snap)
        raw_cat = snap.get("category_id")
        try:
            category = uuid.UUID(str(raw_cat)) if raw_cat else None
        except ValueError:
            category = None
        status = book.status(score, category)
        totals["risks"] += 1
        if status:
            totals[status] += 1
            bucket = by_cat.setdefault(book.source_of(category), Counter())
            bucket["risks"] += 1
            bucket[status] += 1
        inh = scale.for_cell(snap.get("inherent_likelihood"), snap.get("inherent_impact"))
        res = scale.for_cell(snap.get("residual_likelihood"), snap.get("residual_impact"))
        if inh:
            inherent[inh.value] += 1
        if res:
            residual[res.value] += 1
        if snap.get("residual_likelihood") and snap.get("residual_impact") and snap.get("residual_score") is not None:
            cell = (snap.get("residual_likelihood"), snap.get("residual_impact"))
        else:
            cell = (snap.get("inherent_likelihood"), snap.get("inherent_impact"))
        if cell[0] and cell[1]:
            cells[f"{int(cell[0])},{int(cell[1])}"] += 1
    rows: list[tuple[str, str, dict]] = [
        (APPETITE_TOTAL, "", {"risks": totals["risks"], "within": totals["within_appetite"],
                              "elevated": totals["elevated"], "breach": totals["breach"],
                              "appetite": book.appetite, "tolerance": book.tolerance, "basis": BACKFILL_BASIS}),
        (SEVERITY, "", {"inherent": dict(inherent), "residual": dict(residual)}),
        (HEATMAP, "", {"size": int(size or 5), "cells": dict(cells)}),
    ]
    if book.by_category:
        for cid, (appetite, tolerance) in book.by_category.items():
            b = by_cat.get(cid, Counter())
            rows.append((APPETITE_CATEGORY, str(cid), {
                "label": labels.get(cid, "Category"), "appetite": appetite, "tolerance": tolerance,
                "risks": b["risks"], "within": b["within_appetite"], "elevated": b["elevated"], "breach": b["breach"],
            }))
        rest = by_cat.get(None, Counter())
        rows.append((APPETITE_CATEGORY, "default", {
            "label": "All other categories (organisation default)", "appetite": book.appetite,
            "tolerance": book.tolerance, "risks": rest["risks"], "within": rest["within_appetite"],
            "elevated": rest["elevated"], "breach": rest["breach"],
        }))
    return rows


def reconstruct_kri_rows(kris: Iterable[Any], readings: Mapping[Any, Any]) -> list[tuple[str, str, dict]]:
    """KRI rows for a past date: each KRI's latest reading on or before it (``readings``
    maps KRI id to the value) against its current thresholds. Pure."""
    from app.models.operational_risk import kri_status

    counts: Counter = Counter()
    rows = []
    for k in kris:
        value = readings.get(k.id)
        status = _v(kri_status(k.direction, value, k.warning_threshold, k.limit_threshold,
                               getattr(k, "lower_bound", None), getattr(k, "upper_bound", None)))
        counts[status] += 1
        rows.append((KRI_VALUE, str(k.id), {
            "reference": k.reference or "", "name": k.name, "status": status, "unit": k.unit or "",
            "value": float(value) if value is not None else None,
        }))
    rows.append((KRI_STATUS, "", {s: counts.get(s, 0) for s in ("green", "amber", "red", "no_data")}))
    return rows


def reconstruct_issue_row(issues: Iterable[Any], day: date) -> tuple[str, str, dict]:
    """Issues open on ``day``: raised on or before it and not closed by then. Pure.
    Rows need created_at, closed_date, due_date and severity."""
    by: Counter = Counter()
    overdue = 0
    total = 0
    for i in issues:
        created = i.created_at.date() if isinstance(i.created_at, datetime) else i.created_at
        if created is None or created > day:
            continue
        if i.closed_date is not None and i.closed_date <= day:
            continue
        total += 1
        by[str(_v(i.severity) or "medium")] += 1
        if i.due_date is not None and i.due_date < day:
            overdue += 1
    return (ISSUES_OPEN, "", {"open": total, "overdue": overdue,
                              "by_severity": {s: by.get(s, 0) for s in SEVERITIES}})


def appetite_series(index: Mapping[date, Mapping], points: Sequence[Point]) -> list[dict]:
    """Organisation appetite position at each point: {date, as_of, within, elevated,
    breach, risks} with None counts where there is no snapshot. Pure."""
    out = []
    for pt in points:
        v = (index.get(pt.as_of, {}).get(APPETITE_TOTAL, {}).get("") if pt.as_of else None) or None
        out.append({"date": pt.label_date, "as_of": pt.as_of,
                    **{k: (v.get(k) if v else None) for k in ("risks", "within", "elevated", "breach")}})
    return out


def category_series(index: Mapping[date, Mapping], points: Sequence[Point]) -> dict[str, dict]:
    """Per category: {label, points: [{date, as_of, breach, elevated, within, risks}]}. Pure."""
    dims: dict[str, str] = {}
    for pt in points:
        for dim, v in (index.get(pt.as_of, {}).get(APPETITE_CATEGORY, {}) if pt.as_of else {}).items():
            dims.setdefault(dim, v.get("label") or "Category")
    out: dict[str, dict] = {}
    for dim, label in dims.items():
        series = []
        for pt in points:
            v = index.get(pt.as_of, {}).get(APPETITE_CATEGORY, {}).get(dim) if pt.as_of else None
            series.append({"date": pt.label_date, "as_of": pt.as_of,
                           **{k: (v.get(k) if v else None) for k in ("risks", "within", "elevated", "breach")}})
        out[dim] = {"label": label, "points": series}
    return out


def metric_series(index: Mapping[date, Mapping], points: Sequence[Point], key: str, field: str,
                  dimension: str = "") -> list[dict]:
    """One number over the points, e.g. assurance %: [{date, as_of, value}]. Pure."""
    out = []
    for pt in points:
        v = index.get(pt.as_of, {}).get(key, {}).get(dimension) if pt.as_of else None
        out.append({"date": pt.label_date, "as_of": pt.as_of, "value": v.get(field) if v else None})
    return out


# ================================================================== database ===
async def available_dates(db, since: date | None = None) -> list[date]:
    from sqlalchemy import select

    from app.models.workspace import MetricSnapshot

    stmt = select(MetricSnapshot.as_of).distinct()
    if since is not None:
        stmt = stmt.where(MetricSnapshot.as_of >= since)
    return sorted(d for d in (await db.scalars(stmt)).all() if d is not None)


async def load_rows(db, dates: Iterable[date], keys: Iterable[str] | None = None) -> list:
    from sqlalchemy import select

    from app.models.workspace import MetricSnapshot

    wanted = sorted({d for d in dates if d is not None})
    if not wanted:
        return []
    stmt = select(MetricSnapshot).where(MetricSnapshot.as_of.in_(wanted))
    if keys is not None:
        stmt = stmt.where(MetricSnapshot.key.in_(list(keys)))
    return list((await db.scalars(stmt)).all())


async def write_rows(db, tenant_id, as_of: date, rows: Sequence[tuple[str, str, dict]], source: str) -> int:
    """Replace the snapshot rows for ``as_of`` with ``rows`` (a re-capture on the same day
    supersedes the earlier one; a backfill never overwrites a captured key)."""
    from sqlalchemy import delete, select

    from app.models.workspace import MetricSnapshot

    keys = sorted({k for k, _d, _v in rows})
    if not keys:
        return 0
    if source == BACKFILL:
        present = set((await db.scalars(
            select(MetricSnapshot.key).where(MetricSnapshot.as_of == as_of, MetricSnapshot.key.in_(keys))
        )).all())
        rows = [r for r in rows if r[0] not in present]
        if not rows:
            return 0
    else:
        await db.execute(delete(MetricSnapshot).where(MetricSnapshot.as_of == as_of, MetricSnapshot.key.in_(keys)))
    for key, dimension, value in rows:
        db.add(MetricSnapshot(tenant_id=tenant_id, as_of=as_of, key=key, dimension=(dimension or "")[:255],
                              value=_jsonable(value), source=source))
    await db.flush()
    return len(rows)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return getattr(value, "value", value)


async def _matrix_size(db) -> int:
    from sqlalchemy import select

    from app.models.risk import RiskSetting

    return int(await db.scalar(select(RiskSetting.matrix_size)) or 5)


async def live_heatmap(db) -> dict:
    from sqlalchemy import select

    from app.models.risk import Risk

    rows = (await db.execute(
        select(Risk.status, Risk.last_assessed_at, Risk.inherent_likelihood, Risk.inherent_impact,
               Risk.residual_likelihood, Risk.residual_impact, Risk.residual_score)
        .where(Risk.deleted.is_(False))
    )).all()
    return heatmap_cells(rows, await _matrix_size(db))


async def live_kris(db) -> list:
    from sqlalchemy import select
    from sqlalchemy.orm import noload

    from app.models.operational_risk import KeyRiskIndicator

    return list((await db.scalars(
        select(KeyRiskIndicator).where(KeyRiskIndicator.deleted.is_(False)).options(noload("*"))
    )).all())


async def capture(db, tenant_id, as_of: date, *, source: str = SCHEDULER, viewer: Any = None) -> int:
    """Take today's figures from the dashboard overview (and the KRI, issue and heat-map
    reads beside it) and store them as the snapshot for ``as_of``."""
    from app.services import board_pack

    overview = await board_pack.dashboard_overview(db, tenant_id, 30, viewer)
    issues = await board_pack._issues(db, as_of)
    rows = rows_from_overview(overview, heatmap=await live_heatmap(db), kris=await live_kris(db), issues=issues)
    return await write_rows(db, tenant_id, as_of, rows, source)


async def backfill(db, tenant_id, today: date, fiscal_start_month: int = 1, tz: Any = None) -> int:
    """Reconstruct the last four quarter ends where the history allows (module notes).
    Returns the number of rows written."""
    from sqlalchemy import select

    from app.models.issue import Issue
    from app.models.lookup import Lookup
    from app.models.operational_risk import KriMeasurement
    from app.models.risk import Risk, RiskSetting
    from app.models.version import RecordVersion
    from app.services.risk_settings import load_appetite_book, scale_for

    settings = await db.scalar(select(RiskSetting))
    if settings is None:
        return 0
    book = await load_appetite_book(db, tenant_id, settings)
    scale = scale_for(settings)
    labels = dict((await db.execute(
        select(Lookup.id, Lookup.label).where(Lookup.id.in_(list(book.by_category)))
    )).all()) if book.by_category else {}
    risks = (await db.execute(select(Risk.id, Risk.created_at))).all()
    kris = await live_kris(db)
    issues = (await db.execute(
        select(Issue.created_at, Issue.closed_date, Issue.due_date, Issue.severity).where(Issue.deleted.is_(False))
    )).all()
    written = 0
    tz = tz or timezone.utc
    for end in quarter_ends(today, 4, fiscal_start_month):
        instant = datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=tz)
        rows: list[tuple[str, str, dict]] = []
        existed = [r for r in risks if r.created_at is not None and r.created_at < instant]
        if existed:
            history = {
                rid: snap or {}
                for rid, snap in (await db.execute(
                    select(RecordVersion.entity_id, RecordVersion.snapshot)
                    .where(RecordVersion.entity_type == "risk", RecordVersion.created_at < instant,
                           RecordVersion.entity_id.in_([r.id for r in existed]))
                    .distinct(RecordVersion.entity_id)
                    .order_by(RecordVersion.entity_id, RecordVersion.created_at.desc(), RecordVersion.version_no.desc())
                )).all()
            }
            if history:
                rows += reconstruct_risk_rows(existed, history, book, scale, labels, size=settings.matrix_size or 5)
        if kris:
            readings = {
                kid: value for kid, value in (await db.execute(
                    select(KriMeasurement.kri_id, KriMeasurement.value)
                    .where(KriMeasurement.as_of_date <= end, KriMeasurement.kri_id.in_([k.id for k in kris]))
                    .distinct(KriMeasurement.kri_id)
                    .order_by(KriMeasurement.kri_id, KriMeasurement.as_of_date.desc(), KriMeasurement.created_at.desc())
                )).all()
            }
            if readings:
                rows += reconstruct_kri_rows([k for k in kris if k.id in readings], readings)
        if any((i.created_at.date() if isinstance(i.created_at, datetime) else i.created_at) <= end
               for i in issues if i.created_at is not None):
            rows.append(reconstruct_issue_row(issues, end))
        if rows:
            written += await write_rows(db, tenant_id, end, rows, BACKFILL)
    return written


async def run_due(db, tenant_id) -> int:
    """The scheduler step: backfill once for an organisation with no snapshots, then
    capture today's snapshot when one is due. Returns rows written."""
    from sqlalchemy import func, select

    from app.models.workspace import MetricSnapshot
    from app.services import audit, board_pack

    org = await board_pack.org_context(db, tenant_id)
    latest = await db.scalar(select(func.max(MetricSnapshot.as_of)).where(MetricSnapshot.source != BACKFILL))
    any_row = await db.scalar(select(MetricSnapshot.id).limit(1))
    written = 0
    if any_row is None:
        written += await backfill(db, tenant_id, org.today, org.fiscal_start_month, org.tz)
    if snapshot_due(org.today, latest):
        written += await capture(db, tenant_id, org.today)
        await audit.record_system(
            db, tenant_id=tenant_id, action="snapshot", entity_type="metric_snapshot", entity_id=None,
            summary=f"Recorded the period snapshot for {org.today.isoformat()}",
            changes={"as_of": org.today.isoformat(), "rows": written},
        )
    return written
