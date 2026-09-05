"""Aggregate stats for the risk dashboard."""
from __future__ import annotations

from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import DbSession, require
from app.models.asset import Asset
from app.models.control import Control
from app.models.enums import AcceptanceStatus
from app.models.risk import Risk, RiskAcceptance
from app.core.deps import CurrentUser
from app.schemas.dashboard import DashboardStats
from app.services.risk_scoring import appetite_status, effective_score, severity_for_score
from app.services.risk_settings import get_or_create_settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats, dependencies=[Depends(require("risk:read"))])
async def get_dashboard(db: DbSession, user: CurrentUser) -> DashboardStats:
    settings = await get_or_create_settings(db, user.tenant_id)
    today = date.today()
    live = Risk.deleted.is_(False)

    # Pure-column tallies aggregate in SQL — no ORM hydration of the whole register.
    total_risks = await db.scalar(select(func.count()).select_from(Risk).where(live)) or 0
    total_exposure = float(
        await db.scalar(
            select(func.coalesce(func.sum(Risk.annual_loss_expectancy), 0)).where(live)
        )
        or 0
    )
    overdue = (
        await db.scalar(
            select(func.count()).select_from(Risk).where(live, Risk.next_review_date < today)
        )
        or 0
    )
    by_status: Counter[str] = Counter()
    for status_val, cnt in (
        await db.execute(select(Risk.status, func.count()).where(live).group_by(Risk.status))
    ).all():
        by_status[status_val.value] = cnt

    # Severity/appetite bands keep the scoring functions as the single source of truth,
    # so fetch just the two score columns (lightweight tuples, not full ORM objects).
    by_inherent: Counter[str] = Counter()
    by_residual: Counter[str] = Counter()
    appetite_counts: Counter[str] = Counter()
    for inherent, residual in (
        await db.execute(select(Risk.inherent_score, Risk.residual_score).where(live))
    ).all():
        inh = severity_for_score(inherent)
        if inh:
            by_inherent[inh.value] += 1
        res = severity_for_score(residual)
        if res:
            by_residual[res.value] += 1
        status = appetite_status(
            effective_score(inherent, residual),
            settings.appetite_score,
            settings.tolerance_score,
        )
        if status:
            appetite_counts[status] += 1

    total_controls = await db.scalar(
        select(func.count()).select_from(Control).where(Control.deleted.is_(False))
    ) or 0
    total_assets = await db.scalar(
        select(func.count()).select_from(Asset).where(Asset.deleted.is_(False))
    ) or 0
    pending = (
        await db.scalar(
            select(func.count())
            .select_from(RiskAcceptance)
            .join(Risk, Risk.id == RiskAcceptance.risk_id)
            .where(RiskAcceptance.status == AcceptanceStatus.pending, Risk.deleted.is_(False))
        )
        or 0
    )

    return DashboardStats(
        total_risks=total_risks,
        total_controls=total_controls,
        total_assets=total_assets,
        risks_by_status=dict(by_status),
        risks_by_inherent_severity=dict(by_inherent),
        risks_by_residual_severity=dict(by_residual),
        overdue_reviews=overdue,
        pending_acceptances=pending,
        appetite_score=settings.appetite_score,
        tolerance_score=settings.tolerance_score,
        risks_within_appetite=appetite_counts["within_appetite"],
        risks_elevated=appetite_counts["elevated"],
        risks_in_breach=appetite_counts["breach"],
        total_exposure=round(total_exposure, 2),
    )


# =============================================================================== overview
# One payload for the redesigned dashboard. Every figure is an aggregate query or a pass
# over the two score columns; nothing hydrates a whole register. Where a rule exists
# elsewhere (severity bands, appetite, coverage, the gap reason) it is imported, so the
# dashboard can never disagree with the page it links to.
from datetime import timedelta  # noqa: E402

from sqlalchemy import and_, or_  # noqa: E402

from app.api.v1.compliance import _gap_reason  # noqa: E402
from app.models.compliance import Framework, Requirement  # noqa: E402
from app.models.control import ControlAudit  # noqa: E402
from app.models.enums import (  # noqa: E402
    AuditFindingStatus,
    ComplianceStatus,
    ControlEffectiveness,
    IncidentStatus,
    PolicyStatus,
    RiskStatus,
    TestResult,
)
from app.models.identity import User  # noqa: E402
from app.models.incident import Incident  # noqa: E402
from app.models.internal_audit import AuditFinding  # noqa: E402
from app.models.issue import Issue  # noqa: E402
from app.models.operational_risk import KeyRiskIndicator  # noqa: E402
from app.models.organization import BusinessUnit  # noqa: E402
from app.models.policy import Policy  # noqa: E402
from app.models.risk import risk_business_units, risk_controls  # noqa: E402
from app.models.vendor import Vendor  # noqa: E402
from app.schemas.dashboard import (  # noqa: E402
    ActionItem,
    Assurance,
    CompliancePosture,
    DashboardOverview,
    FrameworkPosture,
    Health,
    HealthComponent,
    IncidentsPosture,
    KriItem,
    KriPosture,
    Movement,
    Posture,
    SegmentRow,
    ThirdParties,
    TopRisk,
)
from app.services import control_assurance, governance_health  # noqa: E402
from app.services.risk_scoring import max_score_for  # noqa: E402

_OPEN_INCIDENT = (IncidentStatus.resolved, IncidentStatus.closed)
_CLOSED_ISSUE_WORDS = {"closed", "resolved", "risk_accepted", "withdrawn", "cancelled"}
_OPEN_FINDING = (AuditFindingStatus.open, AuditFindingStatus.in_progress)
_SETTLED_RISK = (RiskStatus.accepted, RiskStatus.closed)


async def _count(db, stmt) -> int:
    return await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


@router.get("/overview", response_model=DashboardOverview, dependencies=[Depends(require("risk:read"))])
async def get_overview(
    db: DbSession, user: CurrentUser, days: int = Query(default=30, ge=7, le=366)
) -> DashboardOverview:
    settings = await get_or_create_settings(db, user.tenant_id)
    max_score = max_score_for(settings.matrix_size)
    today = date.today()
    start = today - timedelta(days=days)
    prior_start = start - timedelta(days=days)
    soon = today + timedelta(days=30)
    live = Risk.deleted.is_(False)

    # ------------------------------------------------------------------ risks
    rows = (
        await db.execute(
            select(
                Risk.id, Risk.reference, Risk.title, Risk.inherent_score, Risk.residual_score,
                Risk.owner_id, Risk.status, Risk.treatment_strategy, Risk.next_review_date,
                Risk.treatment_deadline,
            ).where(live)
        )
    ).all()
    total_risks = len(rows)
    by_inherent: Counter[str] = Counter()
    by_residual: Counter[str] = Counter()
    appetite_counts: Counter[str] = Counter()
    scored = []
    for r in rows:
        inh = severity_for_score(r.inherent_score, max_score)
        res = severity_for_score(r.residual_score, max_score)
        if inh:
            by_inherent[inh.value] += 1
        if res:
            by_residual[res.value] += 1
        eff = effective_score(r.inherent_score, r.residual_score)
        status = appetite_status(eff, settings.appetite_score, settings.tolerance_score)
        if status:
            appetite_counts[status] += 1
        scored.append((r, eff, status, (severity_for_score(eff, max_score) or None)))
    scored.sort(key=lambda t: (-(t[1] or 0), t[0].reference))

    top = scored[:8]
    top_ids = [t[0].id for t in top]
    control_counts: dict = {}
    unit_names: dict = {}
    owner_names: dict = {}
    if top_ids:
        for rid, n in (await db.execute(
            select(risk_controls.c.risk_id, func.count()).where(risk_controls.c.risk_id.in_(top_ids))
            .group_by(risk_controls.c.risk_id)
        )).all():
            control_counts[rid] = n
        for rid, name in (await db.execute(
            select(risk_business_units.c.risk_id, BusinessUnit.name)
            .join(BusinessUnit, BusinessUnit.id == risk_business_units.c.business_unit_id)
            .where(risk_business_units.c.risk_id.in_(top_ids), BusinessUnit.deleted.is_(False))
        )).all():
            unit_names.setdefault(rid, []).append(name)
        owner_ids = {t[0].owner_id for t in top if t[0].owner_id}
        if owner_ids:
            for u in (await db.scalars(select(User).where(User.id.in_(owner_ids)))).all():
                owner_names[u.id] = u.full_name or u.email
    top_risks = [
        TopRisk(
            id=r.id, reference=r.reference, title=r.title, score=eff,
            severity=sev.value if sev else None, appetite_status=status,
            owner=owner_names.get(r.owner_id, ""), business_units=unit_names.get(r.id, []),
            status=r.status.value, treatment_strategy=r.treatment_strategy.value if r.treatment_strategy else None,
            next_review_date=r.next_review_date,
            review_overdue=bool(r.next_review_date and r.next_review_date < today),
            control_count=control_counts.get(r.id, 0),
        )
        for r, eff, status, sev in top
    ]

    # --------------------------------------------------------------- controls
    live_ctl = Control.deleted.is_(False)
    by_eff: Counter[str] = Counter()
    for eff_val, n in (await db.execute(
        select(Control.effectiveness, func.count()).where(live_ctl).group_by(Control.effectiveness)
    )).all():
        by_eff[eff_val.value] = n
    controls_total = sum(by_eff.values())
    tests_overdue = await _count(db, select(Control.id).where(live_ctl, Control.next_audit_date < today))
    tests_due = await _count(db, select(Control.id).where(
        live_ctl, Control.next_audit_date >= today, Control.next_audit_date <= soon
    ))
    # Latest test per control, in SQL: one row per control, newest first.
    latest = (
        select(ControlAudit.control_id, ControlAudit.result)
        .distinct(ControlAudit.control_id)
        .order_by(ControlAudit.control_id, ControlAudit.conducted_date.desc().nulls_last(), ControlAudit.created_at.desc())
    ).subquery()
    last_failed = await db.scalar(
        select(func.count()).select_from(latest)
        .join(Control, Control.id == latest.c.control_id)
        .where(live_ctl, latest.c.result == TestResult.failed)
    ) or 0
    tests_in_period = await _count(db, select(ControlAudit.id).where(ControlAudit.conducted_date >= start))
    assurance = Assurance(
        total=controls_total,
        effective=by_eff.get("effective", 0),
        partially_effective=by_eff.get("partially_effective", 0),
        ineffective=by_eff.get("ineffective", 0),
        not_assessed=by_eff.get("not_assessed", 0),
        tests_overdue=tests_overdue, tests_due_30d=tests_due,
        last_test_failed=last_failed, tests_in_period=tests_in_period,
    )
    controls_assured = assurance.effective + assurance.partially_effective

    # ------------------------------------------------------------- compliance
    frameworks = (await db.scalars(select(Framework).where(Framework.deleted.is_(False)))).all()
    fw_rows: list[FrameworkPosture] = []
    clauses_applicable = clauses_assured = 0
    for fw in frameworks:
        reqs = (await db.scalars(select(Requirement).where(Requirement.framework_id == fw.id))).all()
        by_cov: Counter[str] = Counter()
        applicable = [r for r in reqs if r.status != ComplianceStatus.not_applicable]
        for r in applicable:
            by_cov[r.coverage] += 1
        gaps = sum(1 for r in reqs if _gap_reason(r))
        compliant = sum(1 for r in applicable if r.status == ComplianceStatus.compliant)
        assured = by_cov.get(control_assurance.ASSURED, 0)
        clauses_applicable += len(applicable)
        clauses_assured += assured
        fw_rows.append(FrameworkPosture(
            id=fw.id, name=fw.name, total=len(reqs), applicable=len(applicable),
            assured=assured, unassessed=by_cov.get(control_assurance.UNASSESSED, 0),
            failing=by_cov.get(control_assurance.FAILING, 0), unmapped=by_cov.get(control_assurance.UNMAPPED, 0),
            compliant_pct=round(100 * compliant / len(applicable), 1) if applicable else 0.0,
            gaps=gaps,
        ))
    fw_rows.sort(key=lambda f: (f.applicable - f.assured), reverse=True)
    compliance = CompliancePosture(
        frameworks=fw_rows,
        overall_assured_pct=round(100 * clauses_assured / clauses_applicable, 1) if clauses_applicable else 0.0,
    )

    # ---------------------------------------------------------------- actions
    open_issue = Issue.deleted.is_(False) & Issue.status.not_in([s for s in Issue.status.type.enum_class if s.value in _CLOSED_ISSUE_WORDS])  # type: ignore[attr-defined]
    reviews_overdue = sum(1 for r in rows if r.next_review_date and r.next_review_date < today)
    treatments_overdue = sum(
        1 for r in rows if r.treatment_deadline and r.treatment_deadline < today and r.status not in _SETTLED_RISK
    )
    policies_overdue = await _count(db, select(Policy.id).where(
        Policy.deleted.is_(False), Policy.next_review_date < today,
        Policy.status.in_((PolicyStatus.approved, PolicyStatus.published)),
    ))
    acceptances_expiring = await _count(db, select(RiskAcceptance.id).join(Risk, Risk.id == RiskAcceptance.risk_id).where(
        live, RiskAcceptance.status == AcceptanceStatus.approved,
        RiskAcceptance.expires_at >= today, RiskAcceptance.expires_at <= soon,
    ))
    acceptances_pending = await _count(db, select(RiskAcceptance.id).join(Risk, Risk.id == RiskAcceptance.risk_id).where(
        live, RiskAcceptance.status == AcceptanceStatus.pending,
    ))
    issues_open = await _count(db, select(Issue.id).where(open_issue))
    issues_overdue = await _count(db, select(Issue.id).where(open_issue, Issue.due_date < today))
    findings_overdue = await _count(db, select(AuditFinding.id).where(
        AuditFinding.status.in_(_OPEN_FINDING), AuditFinding.due_date < today
    ))
    incidents_open_stmt = select(Incident.id).where(Incident.deleted.is_(False), Incident.status.not_in(_OPEN_INCIDENT))
    tat_breached = (
        await _count(db, select(Risk.id).where(live, Risk.tat_breached_at.is_not(None), Risk.status.not_in(_SETTLED_RISK)))
        + await _count(db, select(Issue.id).where(open_issue, Issue.tat_breached_at.is_not(None)))
        + await _count(db, incidents_open_stmt.where(Incident.tat_breached_at.is_not(None)))
        + await _count(db, select(AuditFinding.id).where(AuditFinding.status.in_(_OPEN_FINDING), AuditFinding.tat_breached_at.is_not(None)))
    )
    def n_(count: int, singular: str, plural: str | None = None) -> str:
        return f"{count} {singular if count == 1 else (plural or singular + 's')}"

    candidates = [
        ("breach", n_(appetite_counts["breach"], "risk") + " above tolerance", appetite_counts["breach"], "/risks", "critical"),
        ("tat", n_(tat_breached, "record") + " past turnaround time", tat_breached, "/sla-policies", "critical"),
        ("tests_failed", n_(last_failed, "control") + " failed the last test", last_failed, "/controls", "critical"),
        ("findings_overdue", n_(findings_overdue, "audit finding") + " past due", findings_overdue, "/internal-audit", "critical"),
        ("issues_overdue", n_(issues_overdue, "issue") + " past due", issues_overdue, "/issues", "warning"),
        ("treatments_overdue", n_(treatments_overdue, "risk treatment") + " past deadline", treatments_overdue, "/risks", "warning"),
        ("tests_overdue", n_(tests_overdue, "control test") + " overdue", tests_overdue, "/controls", "warning"),
        ("acceptances_expiring", n_(acceptances_expiring, "risk acceptance") + " expiring within 30 days", acceptances_expiring, "/risks", "warning"),
        ("reviews_overdue", n_(reviews_overdue, "risk review") + " overdue", reviews_overdue, "/risks", "warning"),
        ("policies_overdue", n_(policies_overdue, "policy review") + " overdue", policies_overdue, "/policies", "warning"),
        ("acceptances_pending", n_(acceptances_pending, "risk acceptance") + " awaiting a decision", acceptances_pending, "/approvals", "info"),
        ("not_assessed", n_(assurance.not_assessed, "control") + " never tested", assurance.not_assessed, "/controls", "info"),
    ]
    actions = [ActionItem(key=k, label=l, count=n, href=h, tone=t) for k, l, n, h, t in candidates if n > 0]

    # -------------------------------------------------------------- incidents
    open_by_sev: Counter[str] = Counter()
    for sev_val, n in (await db.execute(
        select(Incident.severity, func.count()).where(Incident.deleted.is_(False), Incident.status.not_in(_OPEN_INCIDENT))
        .group_by(Incident.severity)
    )).all():
        open_by_sev[sev_val.value] = n
    incidents = IncidentsPosture(
        open=sum(open_by_sev.values()), open_by_severity=dict(open_by_sev),
        reportable_open=await _count(db, incidents_open_stmt.where(Incident.is_reportable.is_(True))),
        opened_in_period=await _count(db, select(Incident.id).where(Incident.deleted.is_(False), func.date(Incident.created_at) >= start)),
        opened_prior_period=await _count(db, select(Incident.id).where(
            Incident.deleted.is_(False), func.date(Incident.created_at) >= prior_start, func.date(Incident.created_at) < start
        )),
        tat_breached=await _count(db, incidents_open_stmt.where(Incident.tat_breached_at.is_not(None))),
    )

    # ------------------------------------------------------------------- KRIs
    kri_counts: Counter[str] = Counter()
    red_items: list[KriItem] = []
    for k in (await db.scalars(select(KeyRiskIndicator).where(KeyRiskIndicator.deleted.is_(False)))).all():
        status_val = k.status.value if hasattr(k.status, "value") else str(k.status)
        kri_counts[status_val] += 1
        if status_val == "red" and len(red_items) < 6:
            red_items.append(KriItem(
                id=k.id, reference=k.reference or "", name=k.name, current_value=k.current_value,
                warning_threshold=k.warning_threshold, limit_threshold=k.limit_threshold,
                unit=k.unit or "", owner=k.owner or "", status=status_val,
            ))
    kris = KriPosture(
        green=kri_counts["green"], amber=kri_counts["amber"], red=kri_counts["red"],
        no_data=kri_counts["no_data"], red_items=red_items,
    )

    # ---------------------------------------------------------- third parties
    by_rating: Counter[str] = Counter()
    vendors_total = critical_vendors = vendors_overdue = 0
    for v in (await db.scalars(select(Vendor).where(Vendor.deleted.is_(False)))).all():
        vendors_total += 1
        rating = getattr(v.risk_rating, "value", v.risk_rating) or "unrated"
        by_rating[str(rating)] += 1
        if getattr(v.criticality, "value", v.criticality) == "critical":
            critical_vendors += 1
        if v.next_review_date and v.next_review_date < today:
            vendors_overdue += 1
    third_parties = ThirdParties(
        total=vendors_total, by_rating=dict(by_rating), assessments_overdue=vendors_overdue, critical=critical_vendors,
    )

    # --------------------------------------------------------------- segments
    seg: dict = {}
    for rid, bu_id, name in (await db.execute(
        select(risk_business_units.c.risk_id, BusinessUnit.id, BusinessUnit.name)
        .join(BusinessUnit, BusinessUnit.id == risk_business_units.c.business_unit_id)
        .where(BusinessUnit.deleted.is_(False))
    )).all():
        seg.setdefault(bu_id, {"name": name, "risks": set()})["risks"].add(rid)
    by_id = {r.id: (status, sev) for r, eff, status, sev in scored}
    segments = []
    for bu_id, info in seg.items():
        ids = [i for i in info["risks"] if i in by_id]
        segments.append(SegmentRow(
            id=bu_id, name=info["name"], risks=len(ids),
            breach=sum(1 for i in ids if by_id[i][0] == "breach"),
            elevated=sum(1 for i in ids if by_id[i][0] == "elevated"),
            critical=sum(1 for i in ids if by_id[i][1] and by_id[i][1].value == "critical"),
        ))
    segments.sort(key=lambda s: (-s.breach, -s.risks, s.name))

    # --------------------------------------------------------------- movement
    movement = Movement(
        period_days=days,
        risks_created=await _count(db, select(Risk.id).where(live, func.date(Risk.created_at) >= start)),
        risks_closed=await _count(db, select(Risk.id).where(live, Risk.status == RiskStatus.closed, func.date(Risk.updated_at) >= start)),
        acceptances_lapsed=await _count(db, select(RiskAcceptance.id).where(
            RiskAcceptance.status == AcceptanceStatus.expired, func.date(RiskAcceptance.updated_at) >= start
        )),
        tests_recorded=tests_in_period,
        incidents_opened=incidents.opened_in_period,
        issues_closed=await _count(db, select(Issue.id).where(Issue.deleted.is_(False), Issue.closed_date >= start)),
    )

    # ------------------------------------------------------------------ health
    deadlines_total = (
        sum(1 for r in rows if r.next_review_date)
        + sum(1 for r in rows if r.treatment_deadline and r.status not in _SETTLED_RISK)
        + await _count(db, select(Control.id).where(live_ctl, Control.next_audit_date.is_not(None)))
        + await _count(db, select(Policy.id).where(Policy.deleted.is_(False), Policy.next_review_date.is_not(None),
                                                  Policy.status.in_((PolicyStatus.approved, PolicyStatus.published))))
        + await _count(db, select(Issue.id).where(open_issue, Issue.due_date.is_not(None)))
        + await _count(db, select(AuditFinding.id).where(AuditFinding.status.in_(_OPEN_FINDING), AuditFinding.due_date.is_not(None)))
    )
    deadlines_overdue = reviews_overdue + treatments_overdue + tests_overdue + policies_overdue + issues_overdue + findings_overdue
    parts = governance_health.components(
        risks_total=total_risks, risks_within_tolerance=total_risks - appetite_counts["breach"],
        controls_total=controls_total, controls_assured=controls_assured,
        clauses_applicable=clauses_applicable, clauses_assured=clauses_assured,
        deadlines_total=deadlines_total, deadlines_overdue=deadlines_overdue,
    )
    score = governance_health.score(parts)
    scoreable = governance_health.has_data(parts)

    return DashboardOverview(
        as_of=today, period_days=days,
        health=Health(score=score, band=governance_health.band(score, data=scoreable),
                      components=[HealthComponent(**c.__dict__) for c in parts]),
        posture=Posture(
            total_risks=total_risks, appetite_score=settings.appetite_score, tolerance_score=settings.tolerance_score,
            within_appetite=appetite_counts["within_appetite"], elevated=appetite_counts["elevated"],
            breach=appetite_counts["breach"], by_inherent_severity=dict(by_inherent),
            by_residual_severity=dict(by_residual), top_risks=top_risks,
        ),
        assurance=assurance, compliance=compliance, actions=actions, incidents=incidents,
        kris=kris, third_parties=third_parties, segments=segments, movement=movement,
    )
