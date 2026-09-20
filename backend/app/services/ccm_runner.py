"""Continuous control monitoring: run the tests that are due, and record every result —
pulled by a check or pushed by a monitoring tool — the same way.

**Recording a result** (:func:`record_result`, shared by the push feed and the runner):

* evidence on the control (collected that day, valid) — what an auditor sees;
* a run of the test, with population, exceptions (a capped sample), duration and error;
  the test's last result, pass rate, last run and ``failing_since`` roll up when the run
  is the latest;
* a "Continuous monitoring failed" alert, at most one per control and connector a day.

**After a result** (:func:`follow_up`):

* a *failed* run opens an Issue (source ``ccm``) linked to the control — or adds an
  update to the one this test already has open (one per test while open). The open issue
  holds the control's operating rating at partially effective by the existing rule
  (``control_assurance.cap_for_open_issue``), which a person clears by closing it;
* ``controls.monitoring_failing_since`` carries "monitoring failing since <date>" while
  an active test on the control fails, which ``control_assurance.reliance_note`` reads —
  so residual credit and control health on risks react at once;
* a pass never raises effectiveness, and never closes an issue: it adds an update saying
  monitoring passes again, for the owner to validate and close;
* a test linked to a KRI posts a reading through the KRI's own write path
  (``operational_risk.record_reading``: thresholds, escalation), audited as the connector.

**Running** (:func:`run_due_for_tenant`, a scheduler step): a test runs when it is
active, executable (not ``manual``), runnable without a person (its connector exists; a
file check needs the connector's import folder) and a full frequency has passed since its
last run. Each run has its own transaction and a transaction-scoped advisory lock on the
test, so two app processes never run one test twice; the check itself runs in a worker
thread under the connector's timeout. A check that cannot run is recorded as an *error*
run (no evidence, no issue) with an alert, and the test is not retried before its next
period. A test that has not run for twice its frequency raises an overdue alert.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import insert, select, text

from app.core.database import tenant_session
from app.models.integrations import AutomatedControlTest, CcmResult, CcmStatus, Connector, ConnectorStatus, ControlTestRun
from app.services import ccm_checks
from app.services.ccm_checks import CheckContext, CheckError, CheckOutcome, ConnectionFailure, UploadedFile
from app.services.ccm_checks import secrets as secret_box

logger = logging.getLogger("nexusline.ccm")

#: A connector's result maps onto the test-run result; "passed with exceptions" is a
#: pass whose pass rate says how much passed (the run keeps the words in its findings).
RUN_RESULT = {
    "passed": CcmResult.passed,
    "failed": CcmResult.failed,
    "passed_with_exceptions": CcmResult.passed,
    "error": CcmResult.error,
}
FAILED_FAMILY = "ccm-failed"
ERROR_FAMILY = "ccm-error"
OVERDUE_FAMILY = "ccm-overdue"
#: A run's check gets the connector's timeout plus this, then is recorded as an error.
TIMEOUT_GRACE_SECONDS = 5
#: Runs looked at for "passing (last 30 runs 97%)".
STREAK_RUNS = 30
KRI_METRICS = ("exceptions", "exception_percent", "population", "pass_rate", "value")

FREQUENCY_DAYS = {
    "daily": 1, "weekly": 7, "fortnightly": 14, "monthly": 30, "quarterly": 91, "semiannual": 182, "annual": 365,
}


def _v(x: Any) -> Any:
    return getattr(x, "value", x)


# ------------------------------------------------------------------ due logic ---
def interval_of(frequency: Any) -> timedelta | None:
    days = FREQUENCY_DAYS.get(str(_v(frequency) or ""))
    return timedelta(days=days) if days else None


def is_executable(test: Any) -> bool:
    return (getattr(test, "check_type", "manual") or "manual") != "manual" and test.check_type in ccm_checks.CHECKS


def auto_runnable(test: Any, connector: Any | None) -> bool:
    """Can this test run without a person (no upload)? Pure."""
    if not is_executable(test):
        return False
    spec = ccm_checks.CHECKS[test.check_type]
    if connector is None or getattr(connector, "deleted", False) or _v(connector.status) == "disabled":
        return False
    if spec.input == "file":
        return bool((connector.config or {}).get("import_path"))
    return True


def is_due(test: Any, now: datetime) -> bool:
    """Active, executable, and a full frequency since its last run (or never run). Pure.
    A few minutes' slack keeps a daily test on the same sweep each day."""
    if getattr(test, "deleted", False) or _v(test.status) != CcmStatus.active.value or not is_executable(test):
        return False
    interval = interval_of(test.frequency)
    if interval is None:
        return False
    last = test.last_run_at
    return last is None or now - last >= interval - timedelta(minutes=10)


def is_overdue(test: Any, now: datetime) -> bool:
    """No run (by any means) for twice the frequency. Pure. Manual tests count too: their
    runs are expected by hand or from the feed."""
    if getattr(test, "deleted", False) or _v(test.status) != CcmStatus.active.value:
        return False
    interval = interval_of(test.frequency)
    if interval is None:
        return False
    last = test.last_run_at
    if last is None and test.last_run is not None:
        last = datetime.combine(test.last_run, datetime.min.time(), tzinfo=timezone.utc)
    reference = last or test.created_at
    if reference is None:
        return False
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return now - reference > 2 * interval


def recent_pass_rate(runs, limit: int = STREAK_RUNS) -> tuple[int, float | None]:
    """(runs considered, share that passed %) over the latest conclusive runs. Pure."""
    conclusive = [r for r in runs if _v(r.result) in ("passed", "failed")]
    conclusive.sort(key=lambda r: (r.run_date or date.min, r.created_at or datetime.min), reverse=True)
    window = conclusive[:limit]
    if not window:
        return 0, None
    passed = sum(1 for r in window if _v(r.result) == "passed")
    return len(window), round(100.0 * passed / len(window), 1)


def lock_key(test_id: uuid.UUID) -> int:
    """A signed 64-bit advisory-lock key for a test."""
    n = uuid.UUID(str(test_id)).int >> 64
    return n - (1 << 64) if n >= (1 << 63) else n


# ------------------------------------------------------------------- alerts ---
def failed_alert(*, connector, control, observed_local: str, summary: str, owner: str, day: date) -> dict:
    """The event notification a failed result raises. Pure. The dedup key carries the day,
    so a check that keeps failing raises one alert per control and connector per day."""
    from app.models.enums import NotificationCategory
    from app.models.notification import EVENT_PREFIX

    label = " ".join(p for p in (control.reference or "", control.name or "") if p)
    body = (f"{connector.name} reported a failed check at {observed_local}: {summary}"[:900]
            + ". The control's effectiveness is unchanged until a person records a test and another "
              "person reviews it; the result is on the control as evidence.")
    if owner:
        body += f" Control owner: {owner}."
    return {
        "dedup_key": f"{EVENT_PREFIX}{FAILED_FAMILY}:{connector.id}:{control.id}:{day.isoformat()}",
        "title": f"Continuous monitoring failed: {label}"[:255],
        "body": body,
        "category": NotificationCategory.critical if getattr(control, "is_key", False) else NotificationCategory.warning,
        "entity_type": "control",
        "entity_id": control.id,
        "link": f"/controls?id={control.id}",
    }


def error_alert(*, test, message: str, day: date) -> dict:
    from app.models.enums import NotificationCategory
    from app.models.notification import EVENT_PREFIX

    return {
        "dedup_key": f"{EVENT_PREFIX}{ERROR_FAMILY}:{test.id}:{day.isoformat()}",
        "title": f"Continuous monitoring could not run: {test.reference} {test.name}"[:255],
        "body": (f"{test.reference} did not run: {message}"[:900]
                 + " No evidence was recorded; fix the connector or the test and use Run now."),
        "category": NotificationCategory.warning,
        "entity_type": "automated_control_test",
        "entity_id": test.id,
        "link": f"/integrations?test={test.id}",
    }


def overdue_alert(*, test, now: datetime) -> dict:
    from app.models.enums import NotificationCategory
    from app.models.notification import EVENT_PREFIX

    last = test.last_run_at or (datetime.combine(test.last_run, datetime.min.time(), tzinfo=timezone.utc)
                                if test.last_run else None)
    marker = last.date().isoformat() if last else "never"
    return {
        "dedup_key": f"{EVENT_PREFIX}{OVERDUE_FAMILY}:{test.id}:{marker}",
        "title": f"Continuous monitoring overdue: {test.reference} {test.name}"[:255],
        "body": (f"{test.reference} is set to run {str(_v(test.frequency)).replace('_', ' ')} but "
                 + (f"last ran on {marker}" if last else "has never run")
                 + ", more than twice its frequency ago. Check the connector, the import folder or the feed."),
        "category": NotificationCategory.warning,
        "entity_type": "automated_control_test",
        "entity_id": test.id,
        "link": f"/integrations?test={test.id}",
    }


# ---------------------------------------------------------- stubbable helpers ---
async def ccm_enabled(db) -> bool:
    """Licensed on the installation and switched on for the organisation."""
    from app.models.settings import TenantSettings
    from app.services import modules

    if not modules.is_enabled("integrations_ccm"):
        return False
    chosen = await db.scalar(select(TenantSettings.enabled_modules))
    return not isinstance(chosen, list) or "integrations_ccm" in chosen


async def try_lock(db, test_id) -> bool:
    return bool(await db.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key(test_id)}))


async def next_issue_reference(db) -> str:
    from app.models.issue import Issue
    from app.services.refs import next_reference

    return await next_reference(db, Issue, "ISS")


async def link_issue_to_control(db, issue_id, control_id) -> None:
    from app.models.issue import issue_controls

    await db.execute(insert(issue_controls).values(issue_id=issue_id, control_id=control_id))


async def recompute_control(db, control_id, reason: str) -> None:
    from app.services import issue_closure

    await issue_closure.recompute_controls(db, [control_id], reason=reason)


async def connector_audit(db, tenant_id, actor: str, **entry) -> None:
    """Audit a connector's write under its own name (no user is signed in)."""
    from app.models.audit import AuditLog
    from app.services import webhooks

    db.add(AuditLog(tenant_id=tenant_id, actor_id=None, actor_email=actor, **entry))
    await webhooks.dispatch(
        db, entity_type=entry["entity_type"], action=entry["action"],
        payload={"event": f"{entry['entity_type']}.{entry['action']}", "entity_type": entry["entity_type"],
                 "entity_id": str(entry["entity_id"]), "summary": entry["summary"], "actor": actor,
                 "changes": entry.get("changes", {})},
    )


def connector_actor(name: str) -> str:
    return f"Connector {name}"[:255]


# ----------------------------------------------------------- recording a result ---
@dataclass
class Recorded:
    evidence: Any | None
    run: Any | None
    alert_key: str = ""
    advanced: bool = False
    was_failing: bool = False


async def record_result(
    db, *, tenant_id, connector, control, test, result: str, observed_day: date, today: date,
    observed_text: str, summary: str, pass_rate: float, evidence=None, findings: str | None = None,
    evidence_ref: str = "", run_fields: dict | None = None,
) -> Recorded:
    """Evidence, run, roll-ups and the failure alert for one result (push or pull)."""
    from app.models.notification import Notification
    from app.services import master_data

    if evidence is not None:
        db.add(evidence)
    run = None
    advanced = False
    was_failing = bool(test is not None and getattr(test, "failing_since", None))
    if test is not None:
        fields = dict(run_fields or {})
        run = ControlTestRun(
            id=uuid.uuid4(), tenant_id=tenant_id, test_id=test.id, run_date=observed_day, result=RUN_RESULT[result],
            findings=(findings if findings is not None else summary)[:4000],
            evidence_ref=(evidence_ref or (f"Evidence: {evidence.title}" if evidence is not None else ""))[:500],
            pass_rate=pass_rate, evidence_id=evidence.id if evidence is not None else None, **fields,
        )
        db.add(run)
        if getattr(test, "control_id", None) is None and control is not None:
            test.control_id = control.id
        if test.last_run is None or observed_day >= test.last_run:
            advanced = True
            test.last_run, test.last_result = observed_day, run.result
            if result != "error":
                test.pass_rate = pass_rate
            if result == "failed":
                test.failing_since = getattr(test, "failing_since", None) or observed_day
            elif result != "error":
                test.failing_since = None
        started = fields.get("started_at")
        if started is not None and (getattr(test, "last_run_at", None) is None or started >= test.last_run_at):
            test.last_run_at = started
    if connector is not None and result != "error" and (connector.last_sync is None or connector.last_sync < observed_day):
        connector.last_sync = min(observed_day, today)

    alert_key = ""
    if result == "failed" and connector is not None and control is not None:
        owners = await master_data.users_by_id(db, [control.owner_id])
        owner = owners.get(control.owner_id)
        alert = failed_alert(
            connector=connector, control=control, observed_local=observed_text, summary=summary,
            owner=(owner.full_name or owner.email) if owner else (control.owner or ""), day=observed_day,
        )
        if not await db.scalar(select(Notification.id).where(Notification.dedup_key == alert["dedup_key"]).limit(1)):
            db.add(Notification(tenant_id=tenant_id, user_id=control.owner_id, **alert))
            alert_key = alert["dedup_key"]
    return Recorded(evidence=evidence, run=run, alert_key=alert_key, advanced=advanced, was_failing=was_failing)


@dataclass
class FollowUp:
    issue_reference: str = ""
    issue_opened: bool = False
    kri_note: str = ""
    signal: str = ""


def issue_text(test, control, *, day: date, summary: str, exceptions: int | None, population: int | None) -> tuple[str, str]:
    """(title, description) of the issue a failing test opens. Pure."""
    label = " ".join(p for p in (test.reference or "", test.name or "") if p)
    counts = (f" {exceptions} exception(s) in a population of {population}." if exceptions is not None and population is not None
              else "")
    title = f"Continuous monitoring failed: {label}"[:255]
    description = (
        f"Opened by continuous monitoring test {test.reference} on control "
        f"{control.reference or control.name}, which failed on {day.isoformat()}: {summary}.{counts}\n\n"
        f"Pass criterion: {test.pass_criterion or test.test_logic or 'not recorded'}.\n\n"
        "The issue stays open until someone closes it; a later passing run adds an update but does not "
        "close it. While it is open the control's operating rating is held at partially effective at best."
    )
    return title, description


async def open_or_update_issue(db, *, tenant_id, test, control, day: date, summary: str, actor: str,
                               exceptions: int | None, population: int | None) -> tuple[Any, bool]:
    """The test's open issue, updated — or a new one. One per test while it is open."""
    from app.models.enums import Severity, TestResult
    from app.models.issue import Issue, IssueSource, IssueStatus2, IssueUpdate
    from app.services import control_assurance

    closed = {IssueStatus2(s) for s in control_assurance.CLOSED_ISSUE_STATES}
    issue = None
    if test.issue_id is not None:
        issue = await db.scalar(select(Issue).where(Issue.id == test.issue_id))
        if issue is not None and (issue.deleted or issue.status in closed):
            issue = None
    if issue is not None:
        db.add(IssueUpdate(
            id=uuid.uuid4(), tenant_id=tenant_id, issue_id=issue.id, author=actor[:200], update_date=day,
            note=(f"{test.reference} failed again on {day.isoformat()}: {summary}"
                  + (f" ({exceptions} exception(s) of {population})." if exceptions is not None and population is not None else "."))[:4000],
        ))
        return issue, False
    title, description = issue_text(test, control, day=day, summary=summary, exceptions=exceptions, population=population)
    severity = control_assurance.issue_severity(TestResult.failed, bool(getattr(control, "is_key", False)))
    issue = Issue(
        id=uuid.uuid4(), tenant_id=tenant_id, title=title, description=description, source_type=IssueSource.ccm,
        source_reference=f"{test.reference} continuous monitoring"[:255], source_id=control.id,
        severity=severity if isinstance(severity, Severity) else Severity.medium, status=IssueStatus2.open,
        owner_id=control.owner_id, owner=control.owner or "", identified_date=day,
    )
    issue.reference = await next_issue_reference(db)
    db.add(issue)
    await db.flush()
    await link_issue_to_control(db, issue.id, control.id)
    test.issue_id = issue.id
    await connector_audit(
        db, tenant_id, actor, action="create", entity_type="issue", entity_id=issue.id,
        summary=f"Raised issue {issue.reference}: {issue.title} (continuous monitoring)"[:500],
        changes={"source": "ccm", "test_id": str(test.id), "control_id": str(control.id)},
    )
    await recompute_control(db, control.id, f"{issue.reference} opened by {test.reference}")
    return issue, True


async def refresh_control_signal(db, *, tenant_id, control, actor: str) -> str:
    """Set ``control.monitoring_failing_since`` from its active failing tests; returns
    "failing" / "cleared" when it changed, "" otherwise."""
    rows = (await db.scalars(
        select(AutomatedControlTest).where(AutomatedControlTest.control_id == control.id,
                                           AutomatedControlTest.deleted.is_(False))
    )).all()
    since = min((t.failing_since for t in rows
                 if _v(t.status) == "active" and _v(t.last_result) == "failed" and t.failing_since), default=None)
    before = getattr(control, "monitoring_failing_since", None)
    if before == since:
        return ""
    control.monitoring_failing_since = since
    label = control.reference or control.name
    summary = (f"Continuous monitoring of {label} failing since {since.isoformat()}; the control is not relied on "
               "until it passes" if since else f"Continuous monitoring of {label} passing again")
    await connector_audit(db, tenant_id, actor, action="monitoring_signal", entity_type="control", entity_id=control.id,
                          summary=summary[:500], changes={"monitoring_failing_since": {
                              "from": before.isoformat() if before else None, "to": since.isoformat() if since else None}})
    return "failing" if since else "cleared"


def kri_value(metric: str, *, exceptions: int | None, population: int | None, pass_rate: float | None,
              value: float | None) -> float | None:
    """The number of a run a linked KRI receives. Pure."""
    if metric == "exceptions":
        return float(exceptions) if exceptions is not None else None
    if metric == "exception_percent":
        return ccm_checks.exception_percent(population, exceptions) if exceptions is not None and population is not None else None
    if metric == "population":
        return float(population) if population is not None else None
    if metric == "pass_rate":
        return pass_rate
    return value


async def post_kri(db, *, tenant_id, test, run, day: date, actor: str, value: float | None) -> str:
    from fastapi import HTTPException

    from app.api.v1 import operational_risk as orisk
    from app.models.operational_risk import KeyRiskIndicator

    kri = await db.scalar(select(KeyRiskIndicator).where(KeyRiskIndicator.id == test.kri_id,
                                                         KeyRiskIndicator.deleted.is_(False)))
    if kri is None:
        return "The linked KRI is archived or gone; no reading posted."
    if value is None:
        return f"This run has no {test.kri_metric.replace('_', ' ')} to post to {kri.reference}."
    try:
        reading = await orisk.record_reading(
            db, kri, value=value, as_of=day, tenant_id=tenant_id,
            notes=f"Source: connector — {test.reference} run on {day.isoformat()} ({actor})",
        )
    except HTTPException as exc:
        return f"{kri.reference} refused the reading: {exc.detail}"
    for entry in orisk.reading_audit(kri, reading, via=actor):
        await connector_audit(db, tenant_id, actor, **entry)
    if run is not None:
        run.kri_measurement_id = reading.measurement.id
    return f"Posted {value:g} to {kri.reference}."


async def follow_up(db, *, tenant_id, test, control, run, result: str, day: date, actor: str, summary: str,
                    exceptions: int | None, population: int | None, pass_rate: float | None,
                    metric_value: float | None, was_failing: bool, advanced: bool = True) -> FollowUp:
    """Issue, reliance signal and KRI reading after a recorded result."""
    from app.models.issue import IssueUpdate

    out = FollowUp()
    if test is None:
        return out
    metric_only = bool((test.parameters or {}).get("metric_only"))
    if control is not None and advanced and not metric_only:
        if result == "failed":
            issue, opened = await open_or_update_issue(db, tenant_id=tenant_id, test=test, control=control, day=day,
                                                       summary=summary, actor=actor, exceptions=exceptions,
                                                       population=population)
            out.issue_reference, out.issue_opened = issue.reference, opened
            if run is not None:
                run.issue_id = issue.id
        elif result in ("passed", "passed_with_exceptions") and was_failing and test.issue_id is not None:
            db.add(IssueUpdate(
                id=uuid.uuid4(), tenant_id=tenant_id, issue_id=test.issue_id, author=actor[:200], update_date=day,
                note=(f"{test.reference} passed on {day.isoformat()}: {summary}. Monitoring no longer fails; "
                      "validate the remediation and close the issue.")[:4000],
            ))
        out.signal = await refresh_control_signal(db, tenant_id=tenant_id, control=control, actor=actor)
    if test.kri_id is not None and result != "error":
        out.kri_note = await post_kri(
            db, tenant_id=tenant_id, test=test, run=run, day=day, actor=actor,
            value=kri_value(test.kri_metric or "exceptions", exceptions=exceptions, population=population,
                            pass_rate=pass_rate, value=metric_value),
        )
    return out


# --------------------------------------------------------------- vulnerability ---
async def known_first_seen(db, source: str) -> dict:
    from app.models.vulnerability import VulnFinding, VulnSource
    from app.services.ccm_checks.vuln_import import finding_key

    try:
        src = VulnSource(source)
    except ValueError:
        return {}
    rows = (await db.scalars(select(VulnFinding).where(VulnFinding.source == src, VulnFinding.deleted.is_(False)))).all()
    out: dict = {}
    for r in rows:
        if r.discovered_date is None:
            continue
        for where in {r.asset_ip, r.asset_name} - {""}:
            key = finding_key(r.cve_id, r.title, where)
            out[key] = min(out.get(key, r.discovered_date), r.discovered_date)
    return out


async def upsert_vulnerabilities(db, *, tenant_id, findings, source: str, today: date, actor: str) -> dict:
    """Add scan findings the register does not have; refresh severity on the ones it has.
    Existing findings keep their status and owner; nothing is closed because a scan
    missed it. Linked to assets by hostname or IP."""
    from app.models.asset import Asset
    from app.models.vulnerability import VulnFinding, VulnSeverity, VulnSource
    from app.services.ccm_checks.vuln_import import finding_key
    from app.services.refs import next_reference

    src = VulnSource(source)
    existing = (await db.scalars(select(VulnFinding).where(VulnFinding.source == src, VulnFinding.deleted.is_(False)))).all()
    index: dict = {}
    for r in existing:
        for where in {r.asset_ip, r.asset_name} - {""}:
            index[finding_key(r.cve_id, r.title, where)] = r
    assets = (await db.scalars(select(Asset).where(Asset.deleted.is_(False)))).all()
    by_host = {}
    for a in assets:
        for k in (getattr(a, "hostname", "") or "", getattr(a, "ip_address", "") or ""):
            if k:
                by_host.setdefault(k.strip().lower(), a)
    created = updated = linked = 0
    for f in findings[:5000]:
        cve = f.cves[0] if f.cves else ""
        row = index.get(finding_key(cve, f.title, f.ip or f.host)) or index.get(finding_key(cve, f.title, f.host))
        asset = by_host.get((f.host or "").lower()) or by_host.get((f.ip or "").lower())
        if row is not None:
            if row.severity.value != f.severity:
                row.severity = VulnSeverity(f.severity)
                updated += 1
            if row.asset_id is None and asset is not None:
                row.asset_id = asset.id
                linked += 1
            continue
        row = VulnFinding(
            id=uuid.uuid4(), tenant_id=tenant_id, title=(f.title or f.plugin_id or "Scanner finding")[:255], cve_id=cve[:64],
            cvss_score=f.cvss or 0, severity=VulnSeverity(f.severity), asset_name=(f.host or f.ip)[:200],
            asset_ip=(f.ip or "")[:64], asset_id=asset.id if asset is not None else None, source=src,
            description=(f.description or "")[:4000], remediation=(f.solution or "")[:4000],
            discovered_date=f.first_seen or today,
        )
        row.due_date = (row.discovered_date or today) + timedelta(days=row.sla_days)
        row.reference = await next_reference(db, VulnFinding, "VLN")
        db.add(row)
        await db.flush()
        index[finding_key(cve, f.title, f.ip or f.host)] = row
        created += 1
        linked += 1 if asset is not None else 0
    if created or updated:
        await connector_audit(db, tenant_id, actor, action="import", entity_type="vuln_finding", entity_id=None,
                              summary=f"Scanner import: {created} finding(s) added, {updated} updated"[:500],
                              changes={"created": created, "updated": updated, "linked_to_assets": linked})
    return {"created": created, "updated": updated, "linked_to_assets": linked, "capped": len(findings) > 5000}


# ---------------------------------------------------------------- executing ---
@dataclass
class RunReport:
    run: Any | None
    result: str
    message: str
    evidence_id: uuid.UUID | None = None
    issue_reference: str = ""
    kri_note: str = ""
    details: dict = field(default_factory=dict)


def _execute_check(spec, ctx: CheckContext, connector_config: dict, needs_folder: bool) -> CheckOutcome:
    if needs_folder and ctx.file is None:
        ctx.file = ccm_checks.files.newest_file(connector_config)
    return spec.run(ctx)


def evidence_description(test, connector, *, result_words: str, outcome: CheckOutcome, threshold: str,
                         duration_ms: int, observed_text: str, run_id) -> str:
    """What the evidence says about a pulled run. Pure."""
    lines = [
        f"Continuous monitoring test {test.reference} {test.name}"
        + (f" via connector {connector.reference} {connector.name}" if connector is not None else "")
        + f": {result_words}, run {observed_text} in {duration_ms / 1000:.1f} s.",
        "",
        f"Pass criterion: {test.pass_criterion or ccm_checks.CHECKS[test.check_type].pass_criterion}",
        f"Population: {test.population_description or ccm_checks.CHECKS[test.check_type].population} "
        f"— {outcome.population} item(s).",
        f"Threshold: {threshold}. Exceptions: {outcome.exceptions_count}.",
        "",
        outcome.summary + ".",
    ]
    if outcome.exceptions:
        lines += ["", f"Exceptions (first {min(ccm_checks.EVIDENCE_LINES, outcome.exceptions_count)} of "
                      f"{outcome.exceptions_count}; up to {ccm_checks.SAMPLE_CAP} kept on run {run_id}):"]
        for row in outcome.exceptions[:ccm_checks.EVIDENCE_LINES]:
            lines.append("- " + "; ".join(f"{k}: {v}" for k, v in row.items() if v not in (None, "")))
    return "\n".join(lines)


async def execute_test(db, test, *, tenant_id, source: str = "run_now", upload: UploadedFile | None = None,
                       now: datetime | None = None, ldap_factory=None, http_get=None) -> RunReport:
    """Run one executable test now and record the result."""
    from app.models.control import Control
    from app.models.enums import EvidenceStatus, EvidenceType
    from app.models.evidence import Evidence
    from app.models.notification import Notification
    from app.services import incident_clock
    from app.services.ccm_checks.http_json import private_urls_allowed

    if not is_executable(test):
        raise CheckError("This test is recorded by hand or pushed; it has no check to run.")
    spec = ccm_checks.CHECKS[test.check_type]
    connector = None
    if test.connector_id is not None:
        connector = await db.scalar(select(Connector).where(Connector.id == test.connector_id, Connector.deleted.is_(False)))
    control = None
    if test.control_id is not None:
        control = await db.scalar(select(Control).where(Control.id == test.control_id, Control.deleted.is_(False)))
    actor = connector_actor(connector.name) if connector is not None else f"Monitoring test {test.reference}"[:255]
    tz = await incident_clock.tenant_zone(db, tenant_id)
    now = now or incident_clock.now_utc()
    today = incident_clock.local_date(now, tz)
    observed_text = f"{incident_clock.local_text(now, tz)} {getattr(tz, 'key', '')}".strip()
    params = ccm_checks.with_defaults(spec, test.parameters)
    timeout = float(getattr(connector, "timeout_seconds", None) or 30)

    started = time.monotonic()
    outcome: CheckOutcome | None = None
    error = ""
    connection_failed = False
    try:
        if spec.input in ("connector", "connector_or_file") and connector is None and upload is None:
            raise CheckError("The test has no connector.")
        if connector is not None and _v(connector.status) == ConnectorStatus.disabled.value:
            raise CheckError(f"Connector {connector.reference} is disabled.")
        config = dict(connector.config or {}) if connector is not None else {}
        kind = ccm_checks.kind_of(connector.connector_type.value if connector is not None else None)
        needs_folder = upload is None and bool(config.get("import_path")) and (
            spec.input == "file" or (spec.input == "connector_or_file" and kind.kind != "ldap" and not config.get("base_url"))
        )
        if spec.input == "file" and upload is None and not needs_folder:
            raise CheckError("No file: upload one with Run with file, or set the connector's import folder.")
        ctx = CheckContext(
            parameters=params, connector_type=connector.connector_type.value if connector is not None else None,
            config=config, secrets=secret_box.decrypt(connector.secrets_encrypted or "") if connector is not None else {},
            timeout=timeout, file=upload, now=now, ldap_factory=ldap_factory, http_get=http_get,
            allow_private_urls=private_urls_allowed(),
        )
        if spec.key == "vuln_scan_sla":
            ctx.known_first_seen = await known_first_seen(db, str(params.get("format") or "nessus"))
        outcome = await asyncio.wait_for(asyncio.to_thread(_execute_check, spec, ctx, config, needs_folder),
                                         timeout=timeout + TIMEOUT_GRACE_SECONDS)
        if ctx.file is not None:
            outcome.details.setdefault("file", ctx.file.filename)
            if ctx.file.modified_at is not None:
                outcome.details["file_written_at"] = ctx.file.modified_at.isoformat()
    except asyncio.TimeoutError:
        error = f"The check did not finish within {int(timeout + TIMEOUT_GRACE_SECONDS)} seconds."
        connection_failed = True
    except ConnectionFailure as exc:
        error, connection_failed = str(exc), True
    except (CheckError, secret_box.SecretsUnreadable) as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - a broken check is an error run, never a crash
        logger.exception("CCM check %s of test %s failed unexpectedly", spec.key, test.id)
        error = f"The check failed unexpectedly: {type(exc).__name__}: {exc}"
    duration_ms = int((time.monotonic() - started) * 1000)
    started_at = now

    if outcome is None:
        result = "error"
        summary = error
        rate = float(test.pass_rate or 0)
    else:
        metric_only = bool(params.get("metric_only"))
        ok = metric_only or ccm_checks.evaluate(outcome, test.threshold_max_failures,
                                                float(test.threshold_max_percent) if test.threshold_max_percent is not None else None)
        result = "passed" if ok else "failed"
        summary = outcome.summary
        rate = ccm_checks.pass_rate(outcome.population, outcome.exceptions_count) if outcome.passed is None else (100.0 if ok else 0.0)
    threshold = ccm_checks.threshold_text(test.threshold_max_failures, test.threshold_max_percent)
    run_id = uuid.uuid4()
    evidence = None
    if outcome is not None and control is not None:
        words = result + (" (metric only)" if params.get("metric_only") else "")
        evidence = Evidence(
            id=uuid.uuid4(), tenant_id=tenant_id, control_id=control.id,
            title=f"{test.reference} {test.name}: {words} — {summary}"[:255],
            description=evidence_description(test, connector, result_words=words, outcome=outcome, threshold=threshold,
                                             duration_ms=duration_ms, observed_text=observed_text, run_id=run_id),
            evidence_type=EvidenceType.log, reference=f"/integrations?test={test.id}&run={run_id}"[:500],
            status=EvidenceStatus.valid, collected_at=today,
        )
    findings = summary
    if outcome is not None and result == "passed" and outcome.exceptions_count and outcome.passed is None:
        findings = f"Passed within the threshold ({threshold}): {summary}"
    recorded = await record_result(
        db, tenant_id=tenant_id, connector=connector, control=control, test=test, result=result, observed_day=today,
        today=today, observed_text=observed_text, summary=summary, pass_rate=rate, evidence=evidence, findings=findings,
        evidence_ref=f"Evidence: {evidence.title}" if evidence is not None else "",
        run_fields=dict(
            source=source, started_at=started_at, duration_ms=duration_ms,
            population_size=outcome.population if outcome else None,
            exceptions_count=outcome.exceptions_count if outcome else None,
            exceptions_sample=outcome.sample if outcome else [],
            details=json.loads(json.dumps(outcome.details if outcome else {}, default=str)),
            metric_value=outcome.metric_value if outcome else None, error_message=error[:4000],
        ),
    )
    run = recorded.run
    run.id = run_id
    if evidence is not None:
        run.evidence_id = evidence.id
    test.last_error = error[:4000]
    if connector is not None:
        if connection_failed and _v(connector.status) != "disabled":
            connector.status = ConnectorStatus.error
        elif outcome is not None and _v(connector.status) in ("error", "configured"):
            connector.status = ConnectorStatus.active

    vuln = {}
    if outcome is not None and outcome.vulnerabilities and params.get("upsert_register") in (True, "true", "yes"):
        fmt = str(outcome.details.get("format") or "nessus")
        vuln = await upsert_vulnerabilities(db, tenant_id=tenant_id, findings=outcome.vulnerabilities, source=fmt,
                                            today=today, actor=actor)
        run.details = {**(run.details or {}), "register": vuln}

    await db.flush()
    await connector_audit(
        db, tenant_id, actor, action="record_run", entity_type="automated_control_test", entity_id=test.id,
        summary=f"Ran {test.reference} ({source.replace('_', ' ')}): {result} — {summary}"[:500],
        changes={"run_id": str(run.id), "result": result, "population": run.population_size,
                 "exceptions": run.exceptions_count, "duration_ms": duration_ms, "error": error[:500]},
    )
    if evidence is not None:
        await connector_audit(
            db, tenant_id, actor, action="create", entity_type="evidence", entity_id=evidence.id,
            summary=f"Collected evidence '{evidence.title}' for control {control.reference or control.name}"[:500],
            changes={"control_id": str(control.id), "collected_at": today.isoformat(), "via": actor, "run_id": str(run.id)},
        )
    if result == "error":
        alert = error_alert(test=test, message=error, day=today)
        if not await db.scalar(select(Notification.id).where(Notification.dedup_key == alert["dedup_key"]).limit(1)):
            db.add(Notification(tenant_id=tenant_id, user_id=control.owner_id if control is not None else None, **alert))
    fu = await follow_up(
        db, tenant_id=tenant_id, test=test, control=control, run=run, result=result, day=today, actor=actor,
        summary=summary, exceptions=run.exceptions_count, population=run.population_size, pass_rate=rate,
        metric_value=run.metric_value, was_failing=recorded.was_failing, advanced=recorded.advanced,
    )
    if fu.kri_note:
        run.details = {**(run.details or {}), "kri": fu.kri_note}
    await db.flush()
    return RunReport(run=run, result=result, message=summary, evidence_id=evidence.id if evidence is not None else None,
                     issue_reference=fu.issue_reference, kri_note=fu.kri_note, details=run.details or {})


# ------------------------------------------------------------------ scheduling ---
@dataclass
class SweepSummary:
    runs: int = 0
    failed: int = 0
    errors: int = 0
    overdue_alerts: int = 0


async def raise_overdue_alerts(db, tenant_id, tests, now: datetime) -> int:
    from app.models.control import Control
    from app.models.notification import Notification

    late = [t for t in tests if is_overdue(t, now)]
    if not late:
        return 0
    control_ids = {t.control_id for t in late if t.control_id}
    owners = {}
    if control_ids:
        owners = {c.id: c.owner_id for c in (await db.scalars(select(Control).where(Control.id.in_(control_ids)))).all()}
    raised = 0
    for t in late:
        alert = overdue_alert(test=t, now=now)
        if await db.scalar(select(Notification.id).where(Notification.dedup_key == alert["dedup_key"]).limit(1)):
            continue
        db.add(Notification(tenant_id=tenant_id, user_id=owners.get(t.control_id), **alert))
        raised += 1
    return raised


async def run_due_for_tenant(tenant_id, now: datetime | None = None) -> SweepSummary:
    """The scheduler step for one organisation."""
    now = now or datetime.now(timezone.utc)
    out = SweepSummary()
    async with tenant_session(tenant_id) as db:
        if not await ccm_enabled(db):
            return out
        tests = (await db.scalars(select(AutomatedControlTest).where(AutomatedControlTest.deleted.is_(False)))).all()
        connectors = {c.id: c for c in (await db.scalars(select(Connector).where(Connector.deleted.is_(False)))).all()}
        due = [t.id for t in tests if is_due(t, now) and auto_runnable(t, connectors.get(t.connector_id))]
        out.overdue_alerts = await raise_overdue_alerts(db, tenant_id, tests, now)
    for test_id in due:
        try:
            async with tenant_session(tenant_id) as db:
                if not await try_lock(db, test_id):
                    continue
                test = await db.scalar(select(AutomatedControlTest).where(AutomatedControlTest.id == test_id)
                                       .execution_options(populate_existing=True))
                if test is None or not is_due(test, now):
                    continue
                report = await execute_test(db, test, tenant_id=tenant_id, source="scheduled", now=now)
                out.runs += 1
                out.failed += report.result == "failed"
                out.errors += report.result == "error"
        except Exception:  # noqa: BLE001 - one test never stops the others
            logger.exception("Scheduled CCM run of test %s failed", test_id)
    return out
