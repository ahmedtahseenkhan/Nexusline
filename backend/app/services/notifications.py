"""Cross-module alert scanner — computes due/overdue/gap alerts across every module
and reconciles them into the ``notifications`` table (dedup + auto-resolve).

Two rules keep the feed readable once real data is in it:

* **Housekeeping is grouped, decisions never are.** When one low-urgency family (tests,
  maintenance, scheduled reviews, training) raises more than :data:`GROUP_THRESHOLD`
  alerts, they collapse into one row ("36 controls have tests overdue") with a handful
  of examples and a link to the list. The families in :data:`NEVER_GROUPED` (tolerance
  breaches, turnaround-time breaches, approvals, attestations, regulator and incident
  deadlines, and the like) always stay one row per record, so they can't be buried.
* **An alert says what is true now.** ``refresh`` rewrites the text of an alert that
  already exists when the condition behind it has changed ("R-117 scores 20", not the
  15 it scored when first raised).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.control import UNTESTABLE_CONTROL_STATUSES
from app.models.access_review import AccessReview
from app.models.approval import ApprovalRequest
from app.models.attestation import Attestation
from app.models.awareness import AwarenessProgram
from app.models.continuity import ContinuityPlan
from app.models.control import Control
from app.models.enums import (
    AcceptanceStatus,
    AccessReviewStatus,
    ApprovalStatus,
    DpiaStatus,
    ExceptionStatus,
    KriDirection,
    KriStatus,
    NotificationCategory,
    ProjectStatus,
    RcsaStatus,
    SarStatus,
    VendorStatus,
)
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.internal_audit import AuditEngagement, AuditFinding
from app.models.shariah import ShariahFinding, ShariahReview
from app.models.operational_risk import KeyRiskIndicator, RcsaAssessment
from app.models.incident import Incident, RegulatoryReport
from app.models.aml import ScreeningCase, SuspiciousActivityReport
from app.models.enums import RegulatoryReportStatus, ScreeningCaseStatus
from app.models.enums import AuditEngagementStatus, AuditFindingStatus, ShariahFindingStatus
from app.models.notification import EVENT_PREFIX, Notification
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.risk import Risk, RiskAcceptance, RiskTreatmentAction
from app.models.vendor import CERT_EXPIRY_WARNING_DAYS, Vendor, VendorCertification, certification_expiry_state
from app.services.risk_acceptance import EXPIRY_WARNING_DAYS
from app.services.risk_scoring import effective_score
from app.services.risk_settings import get_or_create_settings, load_appetite_book

_W = NotificationCategory.warning
_C = NotificationCategory.critical
_I = NotificationCategory.info

# EVENT_PREFIX is defined on the model and imported above; callers that already reach
# for it through this module keep working.


#: Entity types whose own record carries the review schedule (``review_frequency`` /
#: ``next_review_date``). Attesting one of these moves that schedule (see
#: ``api.v1.attestations``), and the native review sweep below raises the overdue alert,
#: so the attestation sweep must not raise a second one for the same date.
NATIVE_REVIEW_ENTITY_TYPES: frozenset[str] = frozenset({"risk", "policy", "vendor"})

#: More than this many alerts in one groupable family collapse into a single row.
GROUP_THRESHOLD = 5
#: Examples named in a grouped alert's body.
GROUP_EXAMPLES = 5

#: Low-urgency families that may be grouped: dedup-key prefix -> (noun singular,
#: noun plural, predicate, link). Everything here is scheduled housekeeping whose
#: individual rows add nothing a filtered list doesn't show better.
GROUPABLE_FAMILIES: dict[str, tuple[str, str, str, str]] = {
    "control-audit": ("control", "controls", "tests overdue", "/controls"),
    "control-maint": ("control", "controls", "maintenance overdue", "/controls"),
    "risk-review": ("risk", "risks", "reviews overdue", "/risks"),
    # One per overdue open treatment action (phase 2), not one per risk deadline.
    "risk-treatment": ("risk treatment action", "risk treatment actions", "past due", "/risks"),
    "policy-review": ("policy", "policies", "reviews overdue", "/policies"),
    "vendor-review": ("third party", "third parties", "reviews overdue", "/vendors"),
    # Third-party certifications (phase 2), one alert per certificate: warned
    # CERT_EXPIRY_WARNING_DAYS out, then flagged once lapsed.
    "vendor-cert-expiring": ("third-party certification", "third-party certifications", "less than 60 days left", "/vendors"),
    "vendor-cert-expired": ("third-party certification", "third-party certifications", "expired", "/vendors"),
    "goal-audit": ("goal", "goals", "audits overdue", "/goals"),
    "bcp-test": ("continuity plan", "continuity plans", "tests overdue", "/continuity"),
    "ar-overdue": ("access review", "access reviews", "past due", "/access-reviews"),
    "aw-due": ("awareness programme", "awareness programmes", "training due", "/awareness"),
    "proj-overdue": ("project", "projects", "deadlines passed", "/projects"),
    "rcsa-overdue": ("RCSA", "RCSAs", "past due", "/operational-risk"),
    "iaeng-overdue": ("audit engagement", "audit engagements", "planned completion passed", "/internal-audit"),
}

#: Families that always render one row per record, however many there are. Each one is
#: either a breach, a decision somebody must take, or a clock set by a regulator:
#:
#: * ``risk-breach`` — a risk above tolerance; the board-level question.
#: * ``risk-acceptance-expiring`` — each lapse needs a named renew/let-lapse decision.
#: * ``tat-breach`` / ``tat-at-risk`` — turnaround-time (SLA) clocks, escalated by email.
#: * ``approval-pending`` — a named person's decision is waiting.
#: * ``attest-overdue`` — a sign-off owed by a named person.
#: * ``regreport-overdue`` / ``sar-overdue`` — regulator (SBP / FMU) filing deadlines.
#: * ``screening-escalated`` — a sanctions match awaiting a decision.
#: * ``exc-expired`` — an approved deviation has lapsed and is now unapproved.
#: * ``kri-breach`` — an indicator past its limit (or outside its within-range band).
#: * ``iafinding-overdue`` / ``snc-overdue`` — audit and Shariah findings past remediation date.
#: * ``ropa-transfer`` / ``ropa-dpia`` — data-protection obligations under the law.
#:
#: Anything not in :data:`GROUPABLE_FAMILIES` is never grouped, so a new family is
#: individual until someone decides otherwise; this list documents the deliberate choices.
NEVER_GROUPED: frozenset[str] = frozenset({
    "risk-breach", "risk-acceptance-expiring", "tat-breach", "tat-at-risk",
    "approval-pending", "attest-overdue", "regreport-overdue", "sar-overdue",
    "screening-escalated", "exc-expired", "kri-breach", "iafinding-overdue",
    "snc-overdue", "ropa-transfer", "ropa-dpia",
})

GROUP_PREFIX = "group:"

_CATEGORY_RANK = {NotificationCategory.critical: 0, NotificationCategory.warning: 1, NotificationCategory.info: 2}


def family_of(dedup_key: str) -> str:
    """The alert family a dedup key belongs to: everything before the first ``:``."""
    return dedup_key.split(":", 1)[0]


def _example_label(alert: Mapping[str, Any]) -> str:
    title = str(alert.get("title", ""))
    return title.split(": ", 1)[1] if ": " in title else title


def group_alerts(
    alerts: list[dict], *, threshold: int = GROUP_THRESHOLD, examples: int = GROUP_EXAMPLES
) -> list[dict]:
    """Collapse any groupable family with more than ``threshold`` alerts into one alert.

    Pure: takes and returns the scanner's alert dicts. Order is preserved; the grouped
    alert takes the position of its family's first member. Families in
    :data:`NEVER_GROUPED` (or not in :data:`GROUPABLE_FAMILIES`) pass through untouched.
    """
    by_family: dict[str, list[dict]] = {}
    for a in alerts:
        fam = family_of(a["dedup_key"])
        if fam in GROUPABLE_FAMILIES and fam not in NEVER_GROUPED:
            by_family.setdefault(fam, []).append(a)
    to_group = {fam for fam, members in by_family.items() if len(members) > threshold}
    if not to_group:
        return list(alerts)

    out: list[dict] = []
    emitted: set[str] = set()
    for a in alerts:
        fam = family_of(a["dedup_key"])
        if fam not in to_group:
            out.append(a)
            continue
        if fam in emitted:
            continue
        emitted.add(fam)
        members = by_family[fam]
        singular, plural, predicate, link = GROUPABLE_FAMILIES[fam]
        n = len(members)
        names = [_example_label(m) for m in members[:examples]]
        more = n - len(names)
        body = "Including " + ", ".join(names) + (f" and {more} more" if more > 0 else "") + "."
        category = min((m["category"] for m in members), key=lambda c: _CATEGORY_RANK.get(c, 3))
        out.append({
            "dedup_key": f"{GROUP_PREFIX}{fam}",
            "title": f"{n} {plural if n != 1 else singular} {'have' if n != 1 else 'has'} {predicate}",
            "body": body,
            "category": category,
            "entity_type": members[0]["entity_type"],
            "entity_id": None,
            "link": link,
        })
    return out


#: Notification columns an alert re-derives on every scan and ``refresh`` keeps current.
REFRESHED_FIELDS: tuple[str, ...] = ("title", "body", "category", "link", "entity_type", "entity_id")


def alert_changes(existing: Any, alert: Mapping[str, Any]) -> dict[str, Any]:
    """Fields of an existing notification that differ from the freshly computed alert.

    Pure: ``existing`` is anything with the notification attributes (the ORM row, or a
    stand-in in tests). An empty dict means the stored alert is still accurate.
    """
    changes: dict[str, Any] = {}
    for field in REFRESHED_FIELDS:
        if field not in alert:
            continue
        new = alert[field]
        old = getattr(existing, field, None)
        if field == "category":
            old_v = getattr(old, "value", old)
            new_v = getattr(new, "value", new)
            if old_v != new_v:
                changes[field] = new
        elif (old or None) != (new or None):
            changes[field] = new
    return changes


def keys_to_delete(
    existing_keys: Iterable[str], current_keys: set[str], *, keep_prefix: str = EVENT_PREFIX
) -> list[str]:
    """Stored alert keys whose condition no longer holds. Keys starting with
    ``keep_prefix`` (recorded events) are never swept."""
    return [k for k in existing_keys if not k.startswith(keep_prefix) and k not in current_keys]


def certification_alert(cert: Any, vendor: Any, today: date) -> tuple | None:
    """The ``add(...)`` arguments for one vendor certification, or None when it is
    neither expiring nor expired. Pure (see ``models.vendor.certification_expiry_state``)."""
    from app.schemas.vendor import CERT_TYPES

    state = certification_expiry_state(cert.expires_on, today)
    label = CERT_TYPES.get(cert.cert_type, cert.cert_type)
    if state == "expiring":
        days = (cert.expires_on - today).days
        return (f"vendor-cert-expiring:{cert.id}", f"Certification expiring: {vendor.name} {label}",
                f"{label} expires {cert.expires_on} ({days} day(s) left) — ask for the renewed certificate",
                _W, "vendor", vendor.id, "/vendors")
    if state == "expired":
        crit = getattr(vendor.criticality, "value", vendor.criticality)
        return (f"vendor-cert-expired:{cert.id}", f"Certification expired: {vendor.name} {label}",
                f"{label} expired on {cert.expires_on} — obtain the renewal or record the gap",
                _C if crit in ("high", "critical") else _W, "vendor", vendor.id, "/vendors")
    return None


# ------------------------------------------------------------------- KRIs ---
# Phase 2: within-range KRIs and escalation. The live ``kri-breach`` alert (scanned) says
# what is true now; the ``event:kri-escalation`` notification records the moment a
# reading moved a KRI into amber or red, naming who it goes to and what they must do.
# Notifications are organisation-wide, so the target is named in the text.
def _kri_num(value: Any) -> str:
    if value is None:
        return "—"
    v = float(value)
    return str(int(v)) if v.is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")


def kri_threshold_text(kri: Any) -> str:
    """What a KRI's reading is judged against, in words. Pure."""
    unit = f" {kri.unit}" if getattr(kri, "unit", "") else ""
    direction = getattr(kri.direction, "value", kri.direction)
    if direction == "within_range":
        band = f"range {_kri_num(kri.lower_bound)}–{_kri_num(kri.upper_bound)}{unit}"
        if kri.limit_threshold is not None:
            return f"{band}, tolerance {_kri_num(kri.limit_threshold)}"
        return band
    parts = []
    if kri.warning_threshold is not None:
        parts.append(f"warning {_kri_num(kri.warning_threshold)}")
    if kri.limit_threshold is not None:
        parts.append(f"limit {_kri_num(kri.limit_threshold)}")
    return (", ".join(parts) + unit) if parts else "no thresholds"


def escalation_target_text(escalation: Any, people: Mapping[Any, Any]) -> str:
    """"Jane Doe and the CRO role" — who an escalation goes to. Pure."""
    if escalation is None:
        return ""
    who = []
    if escalation.escalate_to_id is not None:
        person = people.get(escalation.escalate_to_id)
        who.append((person.full_name or person.email) if person else "a user no longer on file")
    if escalation.escalate_to_role:
        who.append(f"the {escalation.escalate_to_role} role")
    return " and ".join(who)


def _escalation_for(kri: Any, level: str) -> Any:
    return next((e for e in (getattr(kri, "escalations", None) or []) if e.level == level), None)


def kri_breach_body(kri: Any, people: Mapping[Any, Any]) -> str:
    """Body of the live ``kri-breach`` alert. Pure."""
    unit = f" {kri.unit}" if getattr(kri, "unit", "") else ""
    direction = getattr(kri.direction, "value", kri.direction)
    what = "is outside its" if direction == "within_range" else "breached its"
    body = f"{kri.name} — current {_kri_num(kri.current_value)}{unit} {what} {kri_threshold_text(kri)}"
    escalation = _escalation_for(kri, "red")
    target = escalation_target_text(escalation, people)
    if target:
        body += f". Escalate to {target}" + (f": {escalation.action}" if escalation.action else "")
    return body


def kri_escalation_event(
    kri: Any, level: str, *, value: Any, as_of: Any, measurement_id: Any,
    escalation: Any, target: str, owner: str,
) -> dict:
    """The event notification raised when a reading moves a KRI into amber or red. Pure.

    One per reading (the dedup key carries the measurement), and an ``event:`` key so the
    reconciler never sweeps it away once the KRI recovers."""
    unit = f" {kri.unit}" if getattr(kri, "unit", "") else ""
    label = f"{kri.reference} {kri.name}".strip()
    reading = f"{_kri_num(value)}{unit}" + (f" as of {as_of}" if as_of else "")
    if escalation is not None and target:
        step = f"Escalate to {target}" + (f": {escalation.action}" if escalation.action else ".")
    elif owner:
        step = f"No {level} escalation is set for this KRI; its owner, {owner}, should act."
    else:
        step = f"No {level} escalation or owner is set for this KRI; name one on the KRI."
    state = "red (limit breached)" if level == "red" else "amber (early warning)"
    return {
        "dedup_key": f"{EVENT_PREFIX}kri-escalation:{kri.id}:{measurement_id}",
        "title": f"KRI {state}: {label}"[:255],
        "body": f"Reading {reading} against {kri_threshold_text(kri)}. {step}",
        "category": _C if level == "red" else _W,
        "entity_type": "key_risk_indicator",
        "entity_id": kri.id,
        "link": "/operational-risk",
    }


async def _escalation_people(db: AsyncSession, kris: Iterable[Any], level: str) -> dict:
    from app.services import master_data

    ids = [e.escalate_to_id for k in kris for e in (k.escalations or []) if e.level == level]
    return await master_data.users_by_id(db, ids)


async def raise_kri_escalation(
    db: AsyncSession, kri: Any, level: str, *, value: Any, as_of: Any, measurement_id: Any,
) -> dict:
    """Add the escalation event for a KRI that a reading just moved into ``level``.

    Returns the notification fields plus ``target`` and ``action`` for the caller's audit
    entry (the caller knows whether a person or the KRI feed recorded the reading)."""
    from app.services import master_data

    escalation = _escalation_for(kri, level)
    people = await master_data.users_by_id(
        db, [getattr(escalation, "escalate_to_id", None), kri.owner_id]
    )
    owner_ref = people.get(kri.owner_id) if kri.owner_id else None
    owner = (owner_ref.full_name or owner_ref.email) if owner_ref else (kri.owner or "")
    target = escalation_target_text(escalation, people)
    fields = kri_escalation_event(
        kri, level, value=value, as_of=as_of, measurement_id=measurement_id,
        escalation=escalation, target=target, owner=owner,
    )
    db.add(Notification(tenant_id=kri.tenant_id, **fields))
    return {**fields, "target": target or owner, "action": getattr(escalation, "action", "") or ""}


async def scan_alerts(db: AsyncSession, tenant_id) -> list[dict]:
    today = date.today()
    alerts: list[dict] = []

    def add(key, title, body, category, etype, eid, link):
        alerts.append(
            {
                "dedup_key": key,
                "title": title,
                "body": body,
                "category": category,
                "entity_type": etype,
                "entity_id": eid,
                "link": link,
            }
        )

    # Every scan below filters to only the rows that actually raise an alert (overdue
    # dates, breached thresholds, open-and-past-due statuses) directly in SQL, so we never
    # materialise a whole module's table into Python. Predicates mirror the model helpers
    # (`has_transfer_gap`, `is_breached`, `is_overdue`, `effective_score`) exactly.
    settings = await get_or_create_settings(db, tenant_id)
    # Tolerance is the risk's top-level category's where one is set (RiskAppetite), else
    # the organisation's; the SQL pre-filter uses the lowest tolerance anywhere.
    book = await load_appetite_book(db, tenant_id, settings)
    _eff = func.coalesce(Risk.residual_score, Risk.inherent_score)
    _risk_stmt = select(Risk).where(
        Risk.deleted.is_(False),
        or_(Risk.next_review_date < today, _eff > book.min_tolerance),
    )
    for r in (await db.scalars(_risk_stmt)).all():
        if r.next_review_date and r.next_review_date < today:
            add(f"risk-review:{r.id}", f"Risk review overdue: {r.reference}",
                f"{r.title} — review was due {r.next_review_date}", _W, "risk", r.id, "/risks")
        eff = effective_score(r.inherent_score, r.residual_score)
        tolerance = book.tolerance_for(r.category_id)
        if eff is not None and eff > tolerance:
            add(f"risk-breach:{r.id}", f"Risk above tolerance: {r.reference}",
                f"{r.title} — score {eff} exceeds tolerance {tolerance}", _C, "risk", r.id, "/risks")

    # Risk treatment is tracked per action: each open action past its due date raises
    # its own alert (grouped with the rest of the housekeeping when there are many).
    _action_stmt = (
        select(RiskTreatmentAction, Risk)
        .join(Risk, Risk.id == RiskTreatmentAction.risk_id)
        .where(
            Risk.deleted.is_(False),
            RiskTreatmentAction.status.in_(("open", "in_progress")),
            RiskTreatmentAction.due_date < today,
        )
    )
    for action, risk in (await db.execute(_action_stmt)).all():
        add(f"risk-treatment:{action.id}", f"Treatment action overdue: {risk.reference}",
            f"{action.title} — was due {action.due_date} ({action.percent_complete}% done)",
            _W, "risk", risk.id, "/risks")

    # An acceptance that lapses unnoticed puts the risk back in the register with nobody
    # expecting it, so the chase starts a month out — the shortest notice on which an
    # owner can restate the rationale and a second person can approve it. This is a live
    # condition: renew the acceptance or let it lapse and the alert resolves itself. The
    # lapse *event* is raised separately by `services.risk_acceptance`.
    _acceptance_stmt = (
        select(RiskAcceptance, Risk)
        .join(Risk, Risk.id == RiskAcceptance.risk_id)
        .where(
            RiskAcceptance.status == AcceptanceStatus.approved,
            RiskAcceptance.expires_at.is_not(None),
            RiskAcceptance.expires_at >= today,
            RiskAcceptance.expires_at <= today + timedelta(days=EXPIRY_WARNING_DAYS),
            Risk.deleted.is_(False),
        )
    )
    for acceptance, risk in (await db.execute(_acceptance_stmt)).all():
        days_left = (acceptance.expires_at - today).days
        add(f"risk-acceptance-expiring:{acceptance.id}",
            f"Risk acceptance expiring: {risk.reference or risk.title}",
            f"The approved acceptance lapses on {acceptance.expires_at} "
            f"({days_left} day(s) left) — renew it or the risk returns to the register",
            _W, "risk", risk.id, "/risks")

    # Planned and retired controls have no test or maintenance clock (D-02): a control
    # that is not operating yet cannot be overdue for a test of how it operates.
    _control_stmt = select(Control).where(
        Control.deleted.is_(False),
        Control.status.not_in(UNTESTABLE_CONTROL_STATUSES),
        or_(Control.next_audit_date < today, Control.next_maintenance_date < today),
    )
    for c in (await db.scalars(_control_stmt)).all():
        if c.next_audit_date and c.next_audit_date < today:
            add(f"control-audit:{c.id}", f"Control audit overdue: {c.reference or c.name}",
                f"Audit was due {c.next_audit_date}", _W, "control", c.id, "/controls")
        if c.next_maintenance_date and c.next_maintenance_date < today:
            add(f"control-maint:{c.id}", f"Control maintenance overdue: {c.reference or c.name}",
                f"Maintenance was due {c.next_maintenance_date}", _W, "control", c.id, "/controls")

    _exc_stmt = select(ExceptionRecord).where(
        ExceptionRecord.deleted.is_(False),
        ExceptionRecord.status == ExceptionStatus.approved,
        ExceptionRecord.expires_at < today,
    )
    for e in (await db.scalars(_exc_stmt)).all():
        add(f"exc-expired:{e.id}", f"Exception expired: {e.reference}",
            f"{e.title} expired {e.expires_at}", _C, "exception", e.id, "/exceptions")

    _goal_stmt = select(Goal).where(Goal.deleted.is_(False), Goal.next_audit_date < today)
    for g in (await db.scalars(_goal_stmt)).all():
        add(f"goal-audit:{g.id}", f"Goal audit overdue: {g.reference}",
            f"{g.name} — audit was due {g.next_audit_date}", _W, "goal", g.id, "/goals")

    _bcp_stmt = select(ContinuityPlan).where(
        ContinuityPlan.deleted.is_(False), ContinuityPlan.next_test_date < today
    )
    for p in (await db.scalars(_bcp_stmt)).all():
        add(f"bcp-test:{p.id}", f"Continuity test overdue: {p.reference}",
            f"{p.name} — test was due {p.next_test_date}", _W, "continuity_plan", p.id, "/continuity")

    _ar_stmt = select(AccessReview).where(
        AccessReview.deleted.is_(False),
        AccessReview.due_date < today,
        AccessReview.status != AccessReviewStatus.completed,
    )
    for ar in (await db.scalars(_ar_stmt)).all():
        add(f"ar-overdue:{ar.id}", f"Access review overdue: {ar.reference}",
            f"{ar.name} — due {ar.due_date}", _W, "access_review", ar.id, "/access-reviews")

    _ropa_stmt = select(ProcessingActivity).where(
        ProcessingActivity.deleted.is_(False),
        or_(
            and_(ProcessingActivity.cross_border_transfer.is_(True),
                 func.trim(ProcessingActivity.transfer_safeguard) == ""),
            and_(ProcessingActivity.dpia_required.is_(True),
                 ProcessingActivity.dpia_status != DpiaStatus.completed),
        ),
    )
    for ra in (await db.scalars(_ropa_stmt)).all():
        if ra.has_transfer_gap:
            add(f"ropa-transfer:{ra.id}", f"Transfer gap: {ra.reference}",
                f"{ra.name} — cross-border transfer without a safeguard", _C, "processing_activity", ra.id, "/privacy")
        if ra.dpia_outstanding:
            add(f"ropa-dpia:{ra.id}", f"DPIA outstanding: {ra.reference}",
                f"{ra.name} — DPIA required but not completed", _W, "processing_activity", ra.id, "/privacy")

    _pol_stmt = select(Policy).where(Policy.deleted.is_(False), Policy.next_review_date < today)
    for pol in (await db.scalars(_pol_stmt)).all():
        add(f"policy-review:{pol.id}", f"Policy review overdue: {pol.reference}",
            f"{pol.title} — review was due {pol.next_review_date}", _W, "policy", pol.id, "/policies")

    # Third parties carry their own review cycle on the record; attesting a vendor moves
    # it, so this is the one overdue alert for a vendor review.
    _vendor_stmt = select(Vendor).where(Vendor.deleted.is_(False), Vendor.next_review_date < today)
    for v in (await db.scalars(_vendor_stmt)).all():
        add(f"vendor-review:{v.id}", f"Third-party review overdue: {v.name}",
            f"Review was due {v.next_review_date}", _W, "vendor", v.id, "/vendors")

    # Certifications of live third parties (not offboarded) expiring within the warning
    # window or already lapsed. Expired certs of high/critical vendors are critical.
    _cert_stmt = (
        select(VendorCertification, Vendor)
        .join(Vendor, Vendor.id == VendorCertification.vendor_id)
        .where(
            Vendor.deleted.is_(False),
            Vendor.status != VendorStatus.offboarded,
            VendorCertification.expires_on.is_not(None),
            VendorCertification.expires_on <= today + timedelta(days=CERT_EXPIRY_WARNING_DAYS),
        )
    )
    for cert, v in (await db.execute(_cert_stmt)).all():
        alert = certification_alert(cert, v, today)
        if alert is not None:
            add(*alert)

    _aw_stmt = select(AwarenessProgram).where(
        AwarenessProgram.deleted.is_(False), AwarenessProgram.next_due_date < today
    )
    for aw in (await db.scalars(_aw_stmt)).all():
        add(f"aw-due:{aw.id}", f"Awareness training due: {aw.reference}",
            f"{aw.name} — due {aw.next_due_date}", _I, "awareness_program", aw.id, "/awareness")

    _proj_stmt = select(Project).where(
        Project.deleted.is_(False),
        Project.deadline < today,
        Project.status != ProjectStatus.completed,
    )
    for pr in (await db.scalars(_proj_stmt)).all():
        add(f"proj-overdue:{pr.id}", f"Project overdue: {pr.reference}",
            f"{pr.title} — deadline {pr.deadline}", _W, "project", pr.id, "/projects")

    # Overdue attestations — DISTINCT ON keeps only the latest attestation per record
    # (one row each instead of the full history), then alert if that latest is past due.
    # Records with a native review schedule (risk, policy, vendor) are skipped: their
    # attestation writes the record's own next_review_date, which the sweeps above
    # already watch. One review clock per record, one alert.
    _att_stmt = (
        select(Attestation)
        .where(Attestation.entity_type.not_in(sorted(NATIVE_REVIEW_ENTITY_TYPES)))
        .distinct(Attestation.entity_type, Attestation.entity_id)
        .order_by(Attestation.entity_type, Attestation.entity_id, Attestation.attested_at.desc())
    )
    for att in (await db.scalars(_att_stmt)).all():
        if att.next_due and att.next_due < today:
            add(f"attest-overdue:{att.entity_type}:{att.entity_id}", f"Attestation overdue: {att.entity_type}",
                f"{att.entity_type} review was due {att.next_due} (last by {att.attested_by_email or 'n/a'})",
                _W, att.entity_type, att.entity_id, "")

    _closed_finding = [AuditFindingStatus.closed, AuditFindingStatus.risk_accepted]
    _fnd_stmt = (
        select(AuditFinding)
        .join(AuditEngagement, AuditEngagement.id == AuditFinding.engagement_id)
        .where(
            AuditEngagement.deleted.is_(False),
            AuditFinding.status.not_in(_closed_finding),
            AuditFinding.due_date < today,
        )
    )
    for f in (await db.scalars(_fnd_stmt)).all():
        add(f"iafinding-overdue:{f.id}", f"Audit finding overdue: {f.reference}",
            f"{f.title} — remediation due {f.due_date} (owner {f.action_owner or 'n/a'})",
            _C if f.rating.value in ("high", "critical") else _W,
            "audit_finding", f.id, "/internal-audit")

    _closed_eng = [AuditEngagementStatus.closed, AuditEngagementStatus.cancelled]
    _eng_stmt = select(AuditEngagement).where(
        AuditEngagement.deleted.is_(False),
        AuditEngagement.status.not_in(_closed_eng),
        AuditEngagement.planned_end < today,
    )
    for eng in (await db.scalars(_eng_stmt)).all():
        add(f"iaeng-overdue:{eng.id}", f"Audit engagement overdue: {eng.reference}",
            f"{eng.title} — planned completion {eng.planned_end}", _W,
            "audit_engagement", eng.id, "/internal-audit")

    _closed_snc = [ShariahFindingStatus.closed, ShariahFindingStatus.remediated]
    _snc_stmt = (
        select(ShariahFinding)
        .join(ShariahReview, ShariahReview.id == ShariahFinding.review_id)
        .where(
            ShariahReview.deleted.is_(False),
            ShariahFinding.status.not_in(_closed_snc),
            ShariahFinding.due_date < today,
        )
    )
    for sf in (await db.scalars(_snc_stmt)).all():
        add(f"snc-overdue:{sf.id}", f"Shariah non-compliance overdue: {sf.reference}",
            f"{sf.title} — remediation due {sf.due_date}"
            + (f"; SNC income {sf.snc_income_amount} to purify" if sf.snc_income_amount else ""),
            _C if sf.severity.value in ("high", "critical") else _W,
            "shariah_finding", sf.id, "/shariah")

    # ``KeyRiskIndicator.status`` is a Python property (it depends on the direction), so
    # it can't be filtered in SQL — comparing it there compiled to ``WHERE false`` and no
    # KRI breach alert ever fired. Narrow in SQL to KRIs that can breach (a limit, or a
    # within-range band, which is red outside it even without a tolerance), decide in
    # Python. The alert names who the red escalation goes to (phase 2).
    _kri_stmt = select(KeyRiskIndicator).where(
        KeyRiskIndicator.deleted.is_(False),
        KeyRiskIndicator.current_value.is_not(None),
        or_(
            KeyRiskIndicator.limit_threshold.is_not(None),
            KeyRiskIndicator.direction == KriDirection.within_range,
        ),
    )
    _kris = [k for k in (await db.scalars(_kri_stmt)).all() if k.status == KriStatus.red]
    _kri_people = await _escalation_people(db, _kris, "red") if _kris else {}
    for kri in _kris:
        add(f"kri-breach:{kri.id}", f"KRI breach: {kri.reference}",
            kri_breach_body(kri, _kri_people),
            _C, "key_risk_indicator", kri.id, "/operational-risk")

    _rcsa_stmt = select(RcsaAssessment).where(
        RcsaAssessment.deleted.is_(False),
        RcsaAssessment.status != RcsaStatus.completed,
        RcsaAssessment.due_date < today,
    )
    for rc in (await db.scalars(_rcsa_stmt)).all():
        add(f"rcsa-overdue:{rc.id}", f"RCSA overdue: {rc.reference}",
            f"{rc.title} — due {rc.due_date} ({rc.business_unit or 'n/a'})",
            _W, "rcsa_assessment", rc.id, "/operational-risk")

    # Regulator deadlines are timestamps (phase 2): overdue from the minute they pass,
    # and the alert names the time in the organisation's timezone.
    from app.services import incident_clock

    _rr_stmt = (
        select(RegulatoryReport)
        .join(Incident, Incident.id == RegulatoryReport.incident_id)
        .where(
            Incident.deleted.is_(False),
            RegulatoryReport.status == RegulatoryReportStatus.pending,
            RegulatoryReport.deadline < incident_clock.now_utc(),
        )
    )
    _rr_rows = (await db.scalars(_rr_stmt)).all()
    _rr_tz = await incident_clock.tenant_zone(db, tenant_id) if _rr_rows else None
    for rr in _rr_rows:
        add(f"regreport-overdue:{rr.id}",
            f"Regulatory report overdue: {rr.regulator} {rr.report_type.value.replace('_', ' ')}",
            f"Submission was due {incident_clock.local_text(rr.deadline, _rr_tz)}",
            _C, "regulatory_report", rr.id, "/incidents")

    _sar_stmt = select(SuspiciousActivityReport).where(
        SuspiciousActivityReport.deleted.is_(False),
        SuspiciousActivityReport.status.not_in([SarStatus.filed, SarStatus.closed]),
        SuspiciousActivityReport.deadline < today,
    )
    for sar in (await db.scalars(_sar_stmt)).all():
        add(f"sar-overdue:{sar.id}", f"STR/SAR filing overdue: {sar.reference}",
            f"{sar.subject} — filing was due {sar.deadline}", _C, "sar", sar.id, "/aml")

    _sc_stmt = select(ScreeningCase).where(
        ScreeningCase.deleted.is_(False), ScreeningCase.status == ScreeningCaseStatus.escalated
    )
    for sc in (await db.scalars(_sc_stmt)).all():
        add(f"screening-escalated:{sc.id}", f"Screening case escalated: {sc.reference}",
            f"{sc.subject_name} — {sc.match_status.value.replace('_', ' ')}", _C, "screening_case", sc.id, "/aml")

    _ap_stmt = select(ApprovalRequest).where(ApprovalRequest.status == ApprovalStatus.pending)
    for ap in (await db.scalars(_ap_stmt)).all():
        overdue = ap.due_date is not None and ap.due_date < today
        add(f"approval-pending:{ap.id}",
            f"Approval {'overdue' if overdue else 'pending'}: {ap.reference}",
            f"{ap.title} — awaiting {ap.approver or 'a decision'}",
            _W if overdue else _I, "approval", ap.id, "/approvals")

    # Turnaround-time clock. Reconciling here means the sweep both recomputes every open
    # record's window against the current policy and raises the resulting alerts in one
    # pass — an early warning while there is still time to act, and a critical alert once
    # the window has actually lapsed.
    from app.services import sla as sla_service

    for record in await sla_service.reconcile(db, tenant_id):
        if record.days_overdue > 0:
            add(
                f"tat-breach:{record.entity_type}:{record.entity_id}",
                f"TAT breached: {record.entity_label} {record.label}",
                f"{record.days_overdue} day(s) past the {record.severity} turnaround time "
                f"(due {record.due})",
                _C, record.entity_type, record.entity_id, record.link,
            )
        else:
            add(
                f"tat-at-risk:{record.entity_type}:{record.entity_id}",
                f"TAT approaching: {record.entity_label} {record.label}",
                f"Turnaround time expires {record.due}",
                _W, record.entity_type, record.entity_id, record.link,
            )

    return alerts


async def refresh(db: AsyncSession, tenant_id) -> list[Notification]:
    """Reconcile current alerts into the notifications table.

    Adds new alerts, rewrites the text of existing ones whose condition changed, and
    deletes resolved ones. Low-urgency families above the threshold arrive already
    grouped (:func:`group_alerts`); when a group shrinks back under it, the group key
    stops appearing and is deleted while the individual keys come back as new rows.

    Returns the list of newly created notifications so callers (e.g. the scheduler)
    can email a digest of only what is genuinely new — dedup prevents repeat alerts.
    An updated alert is not "new": its ``created_at`` (and so each user's seen state)
    is kept.
    """
    alerts = group_alerts(await scan_alerts(db, tenant_id))
    existing = {n.dedup_key: n for n in (await db.scalars(select(Notification))).all()}
    current_keys = {a["dedup_key"] for a in alerts}

    created: list[Notification] = []
    for a in alerts:
        stored = existing.get(a["dedup_key"])
        if stored is not None:
            for field, value in alert_changes(stored, a).items():
                setattr(stored, field, value)
            continue
        n = Notification(
            tenant_id=tenant_id,
            title=a["title"],
            body=a["body"],
            category=a["category"],
            entity_type=a["entity_type"],
            entity_id=a["entity_id"],
            link=a["link"],
            dedup_key=a["dedup_key"],
        )
        db.add(n)
        created.append(n)
    # Only reconcile what this scanner produces. Alerts describe a *condition* that is
    # either still true or has resolved, so one that no longer appears is deleted.
    # Event notifications (prefix `event:`) record something that *happened* — a
    # workflow finishing, for instance — and are written directly by the module that
    # observed it. Sweeping those away would mean the user never sees them, because
    # this reconciler runs every time the notification list is opened.
    for key in keys_to_delete(existing.keys(), current_keys, keep_prefix=EVENT_PREFIX):
        await db.delete(existing[key])
    await db.flush()
    return created
