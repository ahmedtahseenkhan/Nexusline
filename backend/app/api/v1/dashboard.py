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
from app.services import fx
from app.services.risk_query import board_register_clause, on_board_register
from app.services.risk_scoring import effective_score, is_scored
from app.services.risk_settings import get_or_create_settings, load_appetite_book, scale_for

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats, dependencies=[Depends(require("risk:read"))])
async def get_dashboard(db: DbSession, user: CurrentUser) -> DashboardStats:
    settings = await get_or_create_settings(db, user.tenant_id)
    scale = scale_for(settings)
    book = await load_appetite_book(db, user.tenant_id, settings)
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
    # Decision 4: a risk's annual loss expectancy carries no currency of its own — it is
    # entered in the organisation's reporting currency, so the total is labelled with it
    # rather than converted.
    exposure_currency = await fx.reporting_currency(db, user.tenant_id)
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
    # Board figures are taken over the board register (F-21): a draft nobody validated,
    # or a risk already accepted or closed, is not a breach the board is shown.
    by_inherent: Counter[str] = Counter()
    by_residual: Counter[str] = Counter()
    appetite_counts: Counter[str] = Counter()
    for r in (
        await db.execute(
            select(
                Risk.inherent_likelihood, Risk.inherent_impact, Risk.inherent_score,
                Risk.residual_likelihood, Risk.residual_impact, Risk.residual_score,
                Risk.category_id,
            ).where(board_register_clause())
        )
    ).all():
        inh = scale.for_cell(r.inherent_likelihood, r.inherent_impact)
        if inh:
            by_inherent[inh.value] += 1
        res = scale.for_cell(r.residual_likelihood, r.residual_impact)
        if res:
            by_residual[res.value] += 1
        status = book.status(effective_score(r.inherent_score, r.residual_score), r.category_id)
        if status:
            appetite_counts[status] += 1

    # The endpoint needs only risk:read, so the other registers' sizes are given only to
    # a reader of those registers — None ("not yours to see"), never a misleading 0.
    held = set(user.permission_codes)
    total_controls = total_assets = None
    if "control:read" in held:
        total_controls = await db.scalar(
            select(func.count()).select_from(Control).where(Control.deleted.is_(False))
        ) or 0
    if "asset:read" in held:
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
        exposure_currency=exposure_currency,
    )


# =============================================================================== overview
# One payload for the redesigned dashboard. Every figure is an aggregate query or a pass
# over the two score columns; nothing hydrates a whole register. Where a rule exists
# elsewhere (severity bands, appetite, coverage, the gap reason) it is imported, so the
# dashboard can never disagree with the page it links to.
from datetime import timedelta  # noqa: E402

from app.api.v1.compliance import _gap_reason  # noqa: E402
from app.models.compliance import Framework, Requirement  # noqa: E402
from app.models.control import ControlAudit  # noqa: E402
from app.models.enums import (  # noqa: E402
    AuditFindingStatus,
    ComplianceStatus,
    Criticality,
    RiskStatus,
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
    HealthCoverage,
    IncidentsPosture,
    KriItem,
    KriPosture,
    Movement,
    Posture,
    SegmentRow,
    ThirdParties,
    TopRisk,
)
from app.models.lookup import Lookup  # noqa: E402
from app.models.risk import RiskTreatmentAction  # noqa: E402
from app.schemas.dashboard import CategoryPosture, DataCompleteness  # noqa: E402
from app.services import control_assurance, governance_health  # noqa: E402
from app.services import modules as module_service  # noqa: E402
from app.services import drill_through as dt  # noqa: E402

# "Open" issues, incidents and in-force policies, overdue tests and reviews: every
# predicate behind a number that links to a list comes from services.drill_through, and
# the list endpoints filter with the same functions — the count and the list it opens
# cannot disagree. (Issues used to count "remediated" as open here while the register's
# overdue filter did not.)
_OPEN_FINDING = (AuditFindingStatus.open, AuditFindingStatus.in_progress)
_SETTLED_RISK = (RiskStatus.accepted, RiskStatus.closed)
#: Only compliance frameworks are obligations; maturity/guidance ones never add gaps.
_COMPLIANCE_KIND = "compliance"


async def _count(db, stmt) -> int:
    return await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


#: The "Needs a decision or is overdue" queue, in priority order:
#: (key, what is counted, the rest of the line, tone). Each key opens the list behind the
#: number (``drill_through.ACTION_LINKS``) — a register filtered to exactly those rows.
QUEUE: tuple[tuple[str, str, str, str], ...] = (
    ("breach", "risk", "above tolerance", "critical"),
    ("tat", "record", "past turnaround time", "critical"),
    ("tests_failed", "control", "failed the last test", "critical"),
    ("findings_overdue", "audit finding", "past due", "critical"),
    ("issues_overdue", "issue", "past due", "warning"),
    ("treatments_overdue", "risk", "with treatment past due", "warning"),
    ("tests_overdue", "control test", "overdue", "warning"),
    ("acceptances_expiring", "risk acceptance", "expiring within 30 days", "warning"),
    ("reviews_overdue", "risk review", "overdue", "warning"),
    ("policies_overdue", "policy review", "overdue", "warning"),
    ("acceptances_pending", "risk acceptance", "awaiting a decision", "info"),
    ("not_assessed", "control", "never tested", "info"),
)


def action_items(counts: dict[str, int]) -> list[ActionItem]:
    """One queue line per non-zero count ("98 controls never tested"), each linking to
    its filtered list. Pure."""
    out: list[ActionItem] = []
    for key, noun, rest, tone in QUEUE:
        n = int(counts.get(key, 0) or 0)
        if n > 0:
            label = f"{n} {noun if n == 1 else noun + 's'} {rest}"
            out.append(ActionItem(key=key, label=label, count=n, href=dt.ACTION_LINKS[key], tone=tone))
    return out


@router.get("/overview", response_model=DashboardOverview, dependencies=[Depends(require("risk:read"))])
async def get_overview(
    db: DbSession, user: CurrentUser, days: int = Query(default=30, ge=7, le=366)
) -> DashboardOverview:
    settings = await get_or_create_settings(db, user.tenant_id)
    # Severity follows the tenant's bands and cell overrides (the heat map's colours);
    # appetite and tolerance follow each risk's level-1 category, else the organisation's.
    scale = scale_for(settings)
    book = await load_appetite_book(db, user.tenant_id, settings)
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
                Risk.treatment_deadline, Risk.needs_review, Risk.review_reason,
                Risk.category_id, Risk.inherent_likelihood, Risk.inherent_impact,
                Risk.residual_likelihood, Risk.residual_impact, Risk.last_assessed_at,
                Risk.workflow_status,
            ).where(live)
        )
    ).all()
    # The board register (F-21): every figure below that a board reads — appetite and
    # tolerance, severities, top risks, segments, the tolerance health measure — is taken
    # over risks that are scored, out of Draft and not yet accepted or closed. Drafts are
    # reported as "pending validation" beside the figures, never silently inside them.
    board_rows = [r for r in rows if on_board_register(r.status, r.last_assessed_at)]
    total_risks = len(board_rows)
    by_inherent: Counter[str] = Counter()
    by_residual: Counter[str] = Counter()
    appetite_counts: Counter[str] = Counter()
    scored = []
    # Per-category posture: one bucket per level-1 category with its own appetite, and
    # one (None) for everything on the organisation's default.
    by_category: dict = {}
    for r in board_rows:
        inh = scale.for_cell(r.inherent_likelihood, r.inherent_impact)
        res = scale.for_cell(r.residual_likelihood, r.residual_impact)
        if inh:
            by_inherent[inh.value] += 1
        if res:
            by_residual[res.value] += 1
        eff = effective_score(r.inherent_score, r.residual_score)
        status = book.status(eff, r.category_id)
        if status:
            appetite_counts[status] += 1
            bucket = by_category.setdefault(book.source_of(r.category_id), Counter())
            bucket["risks"] += 1
            bucket[status] += 1
        sev = scale.for_risk(r.inherent_likelihood, r.inherent_impact, r.residual_likelihood, r.residual_impact)
        scored.append((r, eff, status, sev))
    scored.sort(key=lambda t: (-(t[1] or 0), t[0].reference))
    category_rows: list[CategoryPosture] = []
    if book.by_category:
        labels = {
            lid: label for lid, label in (await db.execute(
                select(Lookup.id, Lookup.label).where(Lookup.id.in_(list(book.by_category)))
            )).all()
        }
        for cid, (appetite, tolerance) in book.by_category.items():
            bucket = by_category.get(cid, Counter())
            category_rows.append(CategoryPosture(
                category_id=cid, label=labels.get(cid, "Category"), appetite_score=appetite,
                tolerance_score=tolerance, risks=bucket["risks"], within_appetite=bucket["within_appetite"],
                elevated=bucket["elevated"], breach=bucket["breach"],
            ))
        category_rows.sort(key=lambda c: (-c.breach, c.label.lower()))
        rest = by_category.get(None, Counter())
        category_rows.append(CategoryPosture(
            category_id=None, label="All other categories (organisation default)",
            appetite_score=settings.appetite_score, tolerance_score=settings.tolerance_score,
            risks=rest["risks"], within_appetite=rest["within_appetite"],
            elevated=rest["elevated"], breach=rest["breach"],
        ))

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
            needs_review=bool(r.needs_review), review_reason=r.review_reason or "",
        )
        for r, eff, status, sev in top
    ]

    # --------------------------------------------------------------- controls
    # A planned control is not operating yet and a retired one no longer is: neither has
    # anything to test, so neither counts as overdue, due, never tested or unassured.
    # They are reported once, as "not in operation", so the bar still adds up.
    live_ctl = Control.deleted.is_(False)
    testable_ctl = live_ctl & dt.operating_control()
    by_eff: Counter[str] = Counter()
    for eff_val, n in (await db.execute(
        select(Control.effectiveness, func.count()).where(testable_ctl).group_by(Control.effectiveness)
    )).all():
        by_eff[eff_val.value] = n
    controls_operating = sum(by_eff.values())
    not_operating = await _count(db, select(Control.id).where(
        live_ctl, dt.control_assurance_clause("not_operating")
    ))
    controls_total = controls_operating + not_operating
    tests_overdue = await _count(db, select(Control.id).where(live_ctl, dt.control_test_clause("overdue", today)))
    tests_due = await _count(db, select(Control.id).where(live_ctl, dt.control_test_clause("due_30d", today)))
    # Latest test per control that counts — reviewed, or recorded before reviews existed
    # (Phase 2: an unreviewed test changes nothing until a second person signs it off).
    last_failed = await _count(db, select(Control.id).where(live_ctl, dt.control_test_clause("failed", today)))
    tests_in_period = await _count(db, select(ControlAudit.id).where(ControlAudit.conducted_date >= start))
    assurance = Assurance(
        total=controls_total,
        effective=by_eff.get("effective", 0),
        partially_effective=by_eff.get("partially_effective", 0),
        ineffective=by_eff.get("ineffective", 0),
        not_assessed=by_eff.get("not_assessed", 0),
        not_operating=not_operating,
        tests_overdue=tests_overdue, tests_due_30d=tests_due,
        last_test_failed=last_failed, tests_in_period=tests_in_period,
    )
    controls_assured = assurance.effective + assurance.partially_effective

    # ------------------------------------------------------------- compliance
    # Only compliance frameworks are obligations. Maturity and guidance frameworks (ISO
    # 31000, ISO 27005) are listed separately and never add clauses or gaps: a bank is
    # not "non-compliant" with good-practice guidance.
    frameworks = (await db.scalars(select(Framework).where(Framework.deleted.is_(False)))).all()
    fw_rows: list[FrameworkPosture] = []
    other_rows: list[FrameworkPosture] = []
    clauses_applicable = clauses_assured = 0
    for fw in frameworks:
        kind = (getattr(fw, "kind", None) or _COMPLIANCE_KIND).lower()
        counts = kind == _COMPLIANCE_KIND
        reqs = (await db.scalars(select(Requirement).where(Requirement.framework_id == fw.id))).all()
        by_cov: Counter[str] = Counter()
        applicable = [r for r in reqs if r.status != ComplianceStatus.not_applicable]
        for r in applicable:
            by_cov[r.coverage] += 1
        gaps = sum(1 for r in reqs if _gap_reason(r))
        compliant = sum(1 for r in applicable if r.status == ComplianceStatus.compliant)
        assured = by_cov.get(control_assurance.ASSURED, 0)
        if counts:
            clauses_applicable += len(applicable)
            clauses_assured += assured
        (fw_rows if counts else other_rows).append(FrameworkPosture(
            id=fw.id, name=fw.name, total=len(reqs), applicable=len(applicable),
            assured=assured, unassessed=by_cov.get(control_assurance.UNASSESSED, 0),
            failing=by_cov.get(control_assurance.FAILING, 0), unmapped=by_cov.get(control_assurance.UNMAPPED, 0),
            compliant_pct=round(100 * compliant / len(applicable), 1) if applicable else 0.0,
            gaps=gaps, kind=kind,
        ))
    fw_rows.sort(key=lambda f: (f.applicable - f.assured), reverse=True)
    other_rows.sort(key=lambda f: f.name.lower())
    compliance = CompliancePosture(
        frameworks=fw_rows,
        overall_assured_pct=round(100 * clauses_assured / clauses_applicable, 1) if clauses_applicable else 0.0,
        other_frameworks=other_rows,
    )

    # ---------------------------------------------------------------- actions
    open_issue = Issue.deleted.is_(False) & dt.issue_open()
    reviews_overdue = await _count(db, select(Risk.id).where(live, dt.risk_review_overdue(today)))
    # The queue lists risks (it opens the risk register), so it counts risks whose
    # treatment is late; the health measure below counts each late action as a deadline.
    risks_treatment_overdue = await _count(db, select(Risk.id).where(live, dt.risk_treatment_overdue(today)))
    # Treatment is tracked per action: each open action past its due date is overdue.
    # A risk with no actions yet is still judged on its single treatment deadline.
    unsettled = {r.id for r in rows if r.status not in _SETTLED_RISK}
    with_actions: set = set()
    open_actions: list = []  # (risk_id, due_date) of open actions on unsettled risks
    if unsettled:
        for rid, action_status, due in (await db.execute(
            select(RiskTreatmentAction.risk_id, RiskTreatmentAction.status, RiskTreatmentAction.due_date)
        )).all():
            with_actions.add(rid)
            if rid in unsettled and action_status in ("open", "in_progress"):
                open_actions.append((rid, due))
    treatments_overdue = sum(1 for _rid, due in open_actions if due and due < today) + sum(
        1 for r in rows
        if r.id in unsettled and r.id not in with_actions and r.treatment_deadline and r.treatment_deadline < today
    )
    treatment_deadlines = sum(1 for _rid, due in open_actions if due) + sum(
        1 for r in rows if r.id in unsettled and r.id not in with_actions and r.treatment_deadline
    )
    policies_overdue = await _count(db, select(Policy.id).where(
        Policy.deleted.is_(False), dt.policy_review_overdue(today),
    ))
    acceptances_expiring = await _count(db, select(RiskAcceptance.id).join(Risk, Risk.id == RiskAcceptance.risk_id).where(
        live, RiskAcceptance.status == AcceptanceStatus.approved,
        RiskAcceptance.expires_at >= today, RiskAcceptance.expires_at <= soon,
    ))
    acceptances_pending = await _count(db, select(RiskAcceptance.id).join(Risk, Risk.id == RiskAcceptance.risk_id).where(
        live, RiskAcceptance.status == AcceptanceStatus.pending,
    ))
    issues_overdue = await _count(db, select(Issue.id).where(Issue.deleted.is_(False), dt.issue_overdue(today)))
    findings_overdue = await _count(db, select(AuditFinding.id).where(
        AuditFinding.status.in_(_OPEN_FINDING), AuditFinding.due_date < today
    ))
    incidents_open_stmt = select(Incident.id).where(Incident.deleted.is_(False), dt.incident_open())
    tat_breached = (
        await _count(db, select(Risk.id).where(live, Risk.tat_breached_at.is_not(None), Risk.status.not_in(_SETTLED_RISK)))
        + await _count(db, select(Issue.id).where(open_issue, Issue.tat_breached_at.is_not(None)))
        + await _count(db, incidents_open_stmt.where(Incident.tat_breached_at.is_not(None)))
        + await _count(db, select(AuditFinding.id).where(AuditFinding.status.in_(_OPEN_FINDING), AuditFinding.tat_breached_at.is_not(None)))
    )
    actions = action_items({
        "breach": appetite_counts["breach"], "tat": tat_breached, "tests_failed": last_failed,
        "findings_overdue": findings_overdue, "issues_overdue": issues_overdue,
        "treatments_overdue": risks_treatment_overdue, "tests_overdue": tests_overdue,
        "acceptances_expiring": acceptances_expiring, "reviews_overdue": reviews_overdue,
        "policies_overdue": policies_overdue, "acceptances_pending": acceptances_pending,
        "not_assessed": assurance.not_assessed,
    })

    # -------------------------------------------------------------- incidents
    open_by_sev: Counter[str] = Counter()
    for sev_val, n in (await db.execute(
        select(Incident.severity, func.count()).where(Incident.deleted.is_(False), dt.incident_open())
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
    # The red indicators are named records of the Operational Risk module: listed only for
    # a reader of KRIs whose organisation uses that module (the tallies stay, as posture).
    kri_detail = "oprisk:read" in set(user.permission_codes) and await module_service.module_refusal(
        "operational_risk", user.tenant_id
    ) is None
    for k in (await db.scalars(select(KeyRiskIndicator).where(KeyRiskIndicator.deleted.is_(False)))).all():
        status_val = k.status.value if hasattr(k.status, "value") else str(k.status)
        kri_counts[status_val] += 1
        if kri_detail and status_val == "red" and len(red_items) < 6:
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
    # Counted with the same predicates GET /vendors filters on (?criticality=critical,
    # ?review=overdue), so each number opens exactly its list.
    live_vendor = Vendor.deleted.is_(False)
    by_rating: Counter[str] = Counter()
    for rating, n in (await db.execute(
        select(Vendor.risk_rating, func.count()).where(live_vendor).group_by(Vendor.risk_rating)
    )).all():
        by_rating[str(getattr(rating, "value", rating) or "unrated")] += n
    vendors_total = sum(by_rating.values())
    critical_vendors = await _count(db, select(Vendor.id).where(live_vendor, Vendor.criticality == Criticality.critical))
    vendors_overdue = await _count(db, select(Vendor.id).where(live_vendor, dt.vendor_review_overdue(today)))
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

    # ----------------------------------------------------------- completeness
    live_ids = {r.id for r in rows}
    tagged_ids = {rid for info in seg.values() for rid in info["risks"]} & live_ids
    pending = [r for r in rows if r.status == RiskStatus.draft]
    completeness = DataCompleteness(
        live_risks=len(rows),
        board_risks=total_risks,
        pending_validation=len(pending),
        unscored=sum(1 for r in pending if not is_scored(r.status, r.last_assessed_at)),
        settled=sum(1 for r in rows if r.status in _SETTLED_RISK),
        pending_href=dt.PENDING_VALIDATION_LINK,
        owned=(owned := sum(1 for r in rows if r.owner_id)),
        owned_pct=governance_health.pct(owned, len(rows)),
        tagged=len(tagged_ids),
        tagged_pct=governance_health.pct(len(tagged_ids), len(rows)),
        approved=(approved := sum(
            1 for r in rows if getattr(r.workflow_status, "value", r.workflow_status) == "approved"
        )),
        approved_pct=governance_health.pct(approved, len(rows)),
    )

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
        + treatment_deadlines
        + await _count(db, select(Control.id).where(testable_ctl, Control.next_audit_date.is_not(None)))
        + await _count(db, select(Policy.id).where(Policy.deleted.is_(False), Policy.next_review_date.is_not(None),
                                                  Policy.status.in_(dt.POLICY_IN_FORCE)))
        + await _count(db, select(Issue.id).where(open_issue, Issue.due_date.is_not(None)))
        + await _count(db, select(AuditFinding.id).where(AuditFinding.status.in_(_OPEN_FINDING), AuditFinding.due_date.is_not(None)))
    )
    deadlines_overdue = reviews_overdue + treatments_overdue + tests_overdue + policies_overdue + issues_overdue + findings_overdue
    parts = governance_health.components(
        risks_total=total_risks, risks_within_tolerance=total_risks - appetite_counts["breach"],
        controls_total=controls_operating, controls_assured=controls_assured,
        clauses_applicable=clauses_applicable, clauses_assured=clauses_assured,
        deadlines_total=deadlines_total, deadlines_overdue=deadlines_overdue,
    )
    score = governance_health.score(parts)
    scoreable = governance_health.has_data(parts)
    cov = governance_health.coverage(parts)

    return DashboardOverview(
        as_of=today, period_days=days,
        health=Health(
            score=score, band=governance_health.band(score, data=scoreable),
            components=[HealthComponent(**c.__dict__) for c in parts],
            coverage=HealthCoverage(scored=cov.scored, total=cov.total, weight_pct=cov.weight_pct),
        ),
        posture=Posture(
            total_risks=total_risks, appetite_score=settings.appetite_score, tolerance_score=settings.tolerance_score,
            within_appetite=appetite_counts["within_appetite"], elevated=appetite_counts["elevated"],
            breach=appetite_counts["breach"], by_inherent_severity=dict(by_inherent),
            by_residual_severity=dict(by_residual), top_risks=top_risks,
            by_category=category_rows,
        ),
        assurance=assurance, compliance=compliance, actions=actions, incidents=incidents,
        kris=kris, third_parties=third_parties, segments=segments, movement=movement,
        completeness=completeness,
    )
