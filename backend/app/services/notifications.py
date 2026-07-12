"""Cross-module alert scanner — computes due/overdue/gap alerts across every module
and reconciles them into the ``notifications`` table (dedup + auto-resolve)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, or_, select
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
    DpiaStatus,
    ExceptionStatus,
    KriStatus,
    NotificationCategory,
    ProjectStatus,
    RcsaStatus,
    SarStatus,
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

    # Every scan below filters to only the rows that actually raise an alert (overdue
    # dates, breached thresholds, open-and-past-due statuses) directly in SQL, so we never
    # materialise a whole module's table into Python. Predicates mirror the model helpers
    # (`has_transfer_gap`, `is_breached`, `is_overdue`, `effective_score`) exactly.
    settings = await get_or_create_settings(db, tenant_id)
    _eff = func.coalesce(Risk.residual_score, Risk.inherent_score)
    _risk_stmt = select(Risk).where(
        Risk.deleted.is_(False),
        or_(Risk.next_review_date < today, _eff > settings.tolerance_score),
    )
    for r in (await db.scalars(_risk_stmt)).all():
        if r.next_review_date and r.next_review_date < today:
            add(f"risk-review:{r.id}", f"Risk review overdue: {r.reference}",
                f"{r.title} — review was due {r.next_review_date}", _W, "risk", r.id, "/risks")
        eff = effective_score(r.inherent_score, r.residual_score)
        if eff is not None and eff > settings.tolerance_score:
            add(f"risk-breach:{r.id}", f"Risk above tolerance: {r.reference}",
                f"{r.title} — score {eff} exceeds tolerance {settings.tolerance_score}", _C, "risk", r.id, "/risks")

    _control_stmt = select(Control).where(
        Control.deleted.is_(False),
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
    _att_stmt = (
        select(Attestation)
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

    _kri_stmt = select(KeyRiskIndicator).where(
        KeyRiskIndicator.deleted.is_(False), KeyRiskIndicator.status == KriStatus.red
    )
    for kri in (await db.scalars(_kri_stmt)).all():
        add(f"kri-breach:{kri.id}", f"KRI breach: {kri.reference}",
            f"{kri.name} — current {kri.current_value} breached its limit threshold",
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

    _rr_stmt = (
        select(RegulatoryReport)
        .join(Incident, Incident.id == RegulatoryReport.incident_id)
        .where(
            Incident.deleted.is_(False),
            RegulatoryReport.status == RegulatoryReportStatus.pending,
            RegulatoryReport.deadline < today,
        )
    )
    for rr in (await db.scalars(_rr_stmt)).all():
        add(f"regreport-overdue:{rr.id}",
            f"Regulatory report overdue: {rr.regulator} {rr.report_type.value.replace('_', ' ')}",
            f"Submission was due {rr.deadline}", _C, "regulatory_report", rr.id, "/incidents")

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
