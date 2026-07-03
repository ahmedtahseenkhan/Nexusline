"""Cross-module alert scanner — computes due/overdue/gap alerts across every module
and reconciles them into the ``notifications`` table (dedup + auto-resolve)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access_review import AccessReview
from app.models.approval import ApprovalRequest
from app.models.attestation import Attestation
from app.models.awareness import AwarenessProgram
from app.models.continuity import ContinuityPlan
from app.models.control import Control
from app.models.enums import (
    AccessReviewStatus,
    ApprovalStatus,
    ExceptionStatus,
    NotificationCategory,
    ProjectStatus,
)
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.internal_audit import AuditEngagement, AuditFinding
from app.models.shariah import ShariahFinding
from app.models.operational_risk import KeyRiskIndicator, RcsaAssessment
from app.models.incident import RegulatoryReport
from app.models.aml import ScreeningCase, SuspiciousActivityReport
from app.models.enums import RegulatoryReportStatus, ScreeningCaseStatus
from app.models.enums import AuditEngagementStatus, AuditFindingStatus, ShariahFindingStatus
from app.models.notification import Notification
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.risk import Risk
from app.services.risk_scoring import effective_score
from app.services.risk_settings import get_or_create_settings

_W = NotificationCategory.warning
_C = NotificationCategory.critical
_I = NotificationCategory.info


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

    settings = await get_or_create_settings(db, tenant_id)
    for r in (await db.scalars(select(Risk))).all():
        if r.next_review_date and r.next_review_date < today:
            add(f"risk-review:{r.id}", f"Risk review overdue: {r.reference}",
                f"{r.title} — review was due {r.next_review_date}", _W, "risk", r.id, "/risks")
        eff = effective_score(r.inherent_score, r.residual_score)
        if eff is not None and eff > settings.tolerance_score:
            add(f"risk-breach:{r.id}", f"Risk above tolerance: {r.reference}",
                f"{r.title} — score {eff} exceeds tolerance {settings.tolerance_score}", _C, "risk", r.id, "/risks")

    for c in (await db.scalars(select(Control))).all():
        if c.next_audit_date and c.next_audit_date < today:
            add(f"control-audit:{c.id}", f"Control audit overdue: {c.reference or c.name}",
                f"Audit was due {c.next_audit_date}", _W, "control", c.id, "/controls")
        if c.next_maintenance_date and c.next_maintenance_date < today:
            add(f"control-maint:{c.id}", f"Control maintenance overdue: {c.reference or c.name}",
                f"Maintenance was due {c.next_maintenance_date}", _W, "control", c.id, "/controls")

    for e in (await db.scalars(select(ExceptionRecord))).all():
        if e.status == ExceptionStatus.approved and e.expires_at and e.expires_at < today:
            add(f"exc-expired:{e.id}", f"Exception expired: {e.reference}",
                f"{e.title} expired {e.expires_at}", _C, "exception", e.id, "/exceptions")

    for g in (await db.scalars(select(Goal))).all():
        if g.next_audit_date and g.next_audit_date < today:
            add(f"goal-audit:{g.id}", f"Goal audit overdue: {g.reference}",
                f"{g.name} — audit was due {g.next_audit_date}", _W, "goal", g.id, "/goals")

    for p in (await db.scalars(select(ContinuityPlan))).all():
        if p.next_test_date and p.next_test_date < today:
            add(f"bcp-test:{p.id}", f"Continuity test overdue: {p.reference}",
                f"{p.name} — test was due {p.next_test_date}", _W, "continuity_plan", p.id, "/continuity")

    for ar in (await db.scalars(select(AccessReview))).all():
        if ar.due_date and ar.due_date < today and ar.status != AccessReviewStatus.completed:
            add(f"ar-overdue:{ar.id}", f"Access review overdue: {ar.reference}",
                f"{ar.name} — due {ar.due_date}", _W, "access_review", ar.id, "/access-reviews")

    for ra in (await db.scalars(select(ProcessingActivity))).all():
        if ra.has_transfer_gap:
            add(f"ropa-transfer:{ra.id}", f"Transfer gap: {ra.reference}",
                f"{ra.name} — cross-border transfer without a safeguard", _C, "processing_activity", ra.id, "/privacy")
        if ra.dpia_outstanding:
            add(f"ropa-dpia:{ra.id}", f"DPIA outstanding: {ra.reference}",
                f"{ra.name} — DPIA required but not completed", _W, "processing_activity", ra.id, "/privacy")

    for pol in (await db.scalars(select(Policy))).all():
        if pol.next_review_date and pol.next_review_date < today:
            add(f"policy-review:{pol.id}", f"Policy review overdue: {pol.reference}",
                f"{pol.title} — review was due {pol.next_review_date}", _W, "policy", pol.id, "/policies")

    for aw in (await db.scalars(select(AwarenessProgram))).all():
        if aw.next_due_date and aw.next_due_date < today:
            add(f"aw-due:{aw.id}", f"Awareness training due: {aw.reference}",
                f"{aw.name} — due {aw.next_due_date}", _I, "awareness_program", aw.id, "/awareness")

    for pr in (await db.scalars(select(Project))).all():
        if pr.deadline and pr.deadline < today and pr.status != ProjectStatus.completed:
            add(f"proj-overdue:{pr.id}", f"Project overdue: {pr.reference}",
                f"{pr.title} — deadline {pr.deadline}", _W, "project", pr.id, "/projects")

    # Overdue attestations — keep only the latest attestation per record, alert if past due.
    latest_att: dict[tuple[str, object], Attestation] = {}
    for att in (await db.scalars(select(Attestation).order_by(Attestation.attested_at))).all():
        latest_att[(att.entity_type, att.entity_id)] = att  # ordered asc -> ends on latest
    for (etype, eid), att in latest_att.items():
        if att.next_due and att.next_due < today:
            add(f"attest-overdue:{etype}:{eid}", f"Attestation overdue: {etype}",
                f"{etype} review was due {att.next_due} (last by {att.attested_by_email or 'n/a'})",
                _W, etype, eid, "")

    _closed_finding = {AuditFindingStatus.closed, AuditFindingStatus.risk_accepted}
    for f in (await db.scalars(select(AuditFinding))).all():
        if f.status not in _closed_finding and f.due_date and f.due_date < today:
            add(f"iafinding-overdue:{f.id}", f"Audit finding overdue: {f.reference}",
                f"{f.title} — remediation due {f.due_date} (owner {f.action_owner or 'n/a'})",
                _C if f.rating.value in ("high", "critical") else _W,
                "audit_finding", f.id, "/internal-audit")

    _closed_eng = {AuditEngagementStatus.closed, AuditEngagementStatus.cancelled}
    for eng in (await db.scalars(select(AuditEngagement))).all():
        if eng.status not in _closed_eng and eng.planned_end and eng.planned_end < today:
            add(f"iaeng-overdue:{eng.id}", f"Audit engagement overdue: {eng.reference}",
                f"{eng.title} — planned completion {eng.planned_end}", _W,
                "audit_engagement", eng.id, "/internal-audit")

    _closed_snc = {ShariahFindingStatus.closed, ShariahFindingStatus.remediated}
    for sf in (await db.scalars(select(ShariahFinding))).all():
        if sf.status not in _closed_snc and sf.due_date and sf.due_date < today:
            add(f"snc-overdue:{sf.id}", f"Shariah non-compliance overdue: {sf.reference}",
                f"{sf.title} — remediation due {sf.due_date}"
                + (f"; SNC income {sf.snc_income_amount} to purify" if sf.snc_income_amount else ""),
                _C if sf.severity.value in ("high", "critical") else _W,
                "shariah_finding", sf.id, "/shariah")

    for kri in (await db.scalars(select(KeyRiskIndicator).where(KeyRiskIndicator.deleted.is_(False)))).all():
        if kri.is_breached:
            add(f"kri-breach:{kri.id}", f"KRI breach: {kri.reference}",
                f"{kri.name} — current {kri.current_value} breached its limit threshold",
                _C, "key_risk_indicator", kri.id, "/operational-risk")

    for rc in (await db.scalars(select(RcsaAssessment).where(RcsaAssessment.deleted.is_(False)))).all():
        if rc.is_overdue:
            add(f"rcsa-overdue:{rc.id}", f"RCSA overdue: {rc.reference}",
                f"{rc.title} — due {rc.due_date} ({rc.business_unit or 'n/a'})",
                _W, "rcsa_assessment", rc.id, "/operational-risk")

    for rr in (await db.scalars(select(RegulatoryReport))).all():
        if rr.status == RegulatoryReportStatus.pending and rr.deadline and rr.deadline < today:
            add(f"regreport-overdue:{rr.id}",
                f"Regulatory report overdue: {rr.regulator} {rr.report_type.value.replace('_', ' ')}",
                f"Submission was due {rr.deadline}", _C, "regulatory_report", rr.id, "/incidents")

    for sar in (await db.scalars(select(SuspiciousActivityReport).where(SuspiciousActivityReport.deleted.is_(False)))).all():
        if sar.is_overdue:
            add(f"sar-overdue:{sar.id}", f"STR/SAR filing overdue: {sar.reference}",
                f"{sar.subject} — filing was due {sar.deadline}", _C, "sar", sar.id, "/aml")

    for sc in (await db.scalars(select(ScreeningCase).where(ScreeningCase.deleted.is_(False)))).all():
        if sc.status == ScreeningCaseStatus.escalated:
            add(f"screening-escalated:{sc.id}", f"Screening case escalated: {sc.reference}",
                f"{sc.subject_name} — {sc.match_status.value.replace('_', ' ')}", _C, "screening_case", sc.id, "/aml")

    for ap in (await db.scalars(select(ApprovalRequest))).all():
        if ap.status == ApprovalStatus.pending:
            overdue = ap.due_date is not None and ap.due_date < today
            add(f"approval-pending:{ap.id}",
                f"Approval {'overdue' if overdue else 'pending'}: {ap.reference}",
                f"{ap.title} — awaiting {ap.approver or 'a decision'}",
                _W if overdue else _I, "approval", ap.id, "/approvals")

    return alerts


async def refresh(db: AsyncSession, tenant_id) -> list[Notification]:
    """Reconcile current alerts into the notifications table (add new, delete resolved).

    Returns the list of newly created notifications so callers (e.g. the scheduler)
    can email a digest of only what is genuinely new — dedup prevents repeat alerts.
    """
    alerts = await scan_alerts(db, tenant_id)
    existing = {n.dedup_key: n for n in (await db.scalars(select(Notification))).all()}
    current_keys = {a["dedup_key"] for a in alerts}

    created: list[Notification] = []
    for a in alerts:
        if a["dedup_key"] not in existing:
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
    for key, n in existing.items():
        if key not in current_keys:
            await db.delete(n)
    await db.flush()
    return created
