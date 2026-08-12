"""Annual audit plan, reusable audit programmes, and the assurance calendar.

Three things a bare engagement list cannot answer, and this module can:

* **"Did we do what we told the board we would do?"** — the plan records the commitment
  separately from what happened, so plan-vs-actual coverage is a number rather than an
  argument. Sign-off goes through the existing approvals inbox rather than a new
  mechanism, so board approval inherits maker-checker and the audit log for free.
* **"What are the test steps?"** — a programme is written once and instantiated onto an
  engagement as ordinary working papers. Generating one from an installed framework
  turns "audit against ISO 27001" into a click, because the 93 Annex A clauses are
  already loaded.
* **"What is coming up?"** — the calendar reads dates that already exist on plans,
  engagements, findings and the audit universe. It adds no new data, only a view.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.approval import ApprovalRequest
from app.models.audit_plan import (
    AuditPlan,
    AuditPlanItem,
    AuditPlanStatus,
    AuditProgram,
    AuditProgramStep,
)
from app.models.compliance import Framework, Requirement
from app.models.enums import AuditEngagementStatus, AuditFindingStatus, Criticality
from app.models.internal_audit import AuditableUnit, AuditEngagement, AuditFinding, AuditProcedure
from app.schemas.audit_plan import (
    ApplyProgramResult,
    AuditCalendar,
    CalendarEvent,
    PlanCoverage,
    PlanCreate,
    PlanGenerateRequest,
    PlanGenerateResult,
    PlanItemCreate,
    PlanItemRead,
    PlanItemUpdate,
    PlanRead,
    PlanUpdate,
    ProgramCreate,
    ProgramFromFrameworkRequest,
    ProgramRead,
    ProgramStepCreate,
    ProgramStepRead,
    ProgramStepUpdate,
    ProgramUpdate,
)
from app.schemas.common import Page
from app.services import audit as audit_log
from app.services.refs import next_reference

router = APIRouter(tags=["audit plan"])

_READ = Depends(require("internal_audit:read"))
_WRITE = Depends(require("internal_audit:write"))

_CRIT_RANK = {
    Criticality.low: 1, Criticality.medium: 2, Criticality.high: 3, Criticality.critical: 4,
}
_OPEN_FINDING = (AuditFindingStatus.closed, AuditFindingStatus.risk_accepted)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _load_plan(db: DbSession, plan_id: uuid.UUID) -> AuditPlan:
    obj = await db.scalar(
        select(AuditPlan)
        .where(AuditPlan.id == plan_id, AuditPlan.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Audit plan not found")
    return obj


async def _load_program(db: DbSession, program_id: uuid.UUID) -> AuditProgram:
    obj = await db.scalar(
        select(AuditProgram)
        .where(AuditProgram.id == program_id, AuditProgram.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Audit programme not found")
    return obj


def _plan_read(plan: AuditPlan) -> PlanRead:
    return PlanRead(
        id=plan.id, reference=plan.reference, year=plan.year, title=plan.title,
        description=plan.description, prepared_by=plan.prepared_by,
        budget_hours=plan.budget_hours, status=plan.status,
        approval_request_id=plan.approval_request_id, approved_on=plan.approved_on,
        planned_count=plan.planned_count, started_count=plan.started_count,
        coverage_pct=plan.coverage_pct, planned_hours=plan.planned_hours,
        created_at=plan.created_at,
        items=[
            PlanItemRead(
                id=i.id, title=i.title, auditable_unit_id=i.auditable_unit_id,
                rationale=i.rationale, planned_quarter=i.planned_quarter,
                planned_month=i.planned_month,
                budgeted_hours=i.budgeted_hours, lead_auditor=i.lead_auditor,
                engagement_id=i.engagement_id,
                auditable_unit_name=(i.auditable_unit.name if i.auditable_unit else ""),
            )
            for i in plan.items
        ],
    )


def _program_read(program: AuditProgram, framework_name: str = "") -> ProgramRead:
    return ProgramRead(
        id=program.id, reference=program.reference, name=program.name,
        description=program.description, category=program.category,
        framework_id=program.framework_id, framework_name=framework_name,
        step_count=program.step_count, created_at=program.created_at,
        steps=[ProgramStepRead.model_validate(s) for s in program.steps],
    )


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
@router.get("/audit-plans", response_model=Page[PlanRead], dependencies=[_READ])
async def list_plans(
    db: DbSession,
    year: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PlanRead]:
    stmt = select(AuditPlan).where(AuditPlan.deleted.is_(False))
    if year is not None:
        stmt = stmt.where(AuditPlan.year == year)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(stmt.order_by(AuditPlan.year.desc()).limit(limit).offset(offset))
    ).all()
    return Page(items=[_plan_read(p) for p in rows], total=total, limit=limit, offset=offset)


@router.post("/audit-plans", response_model=PlanRead, status_code=201, dependencies=[_WRITE])
async def create_plan(body: PlanCreate, db: DbSession, user: CurrentUser) -> PlanRead:
    plan = AuditPlan(tenant_id=user.tenant_id, **body.model_dump())
    plan.reference = await next_reference(db, AuditPlan, "AP")
    db.add(plan)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="audit_plan", entity_id=plan.id,
        summary=f"Created audit plan {plan.reference}: {plan.title} ({plan.year})",
    )
    return _plan_read(await _load_plan(db, plan.id))


@router.get("/audit-plans/{plan_id}", response_model=PlanRead, dependencies=[_READ])
async def get_plan(plan_id: uuid.UUID, db: DbSession) -> PlanRead:
    return _plan_read(await _load_plan(db, plan_id))


@router.patch("/audit-plans/{plan_id}", response_model=PlanRead, dependencies=[_WRITE])
async def update_plan(
    plan_id: uuid.UUID, body: PlanUpdate, db: DbSession, user: CurrentUser
) -> PlanRead:
    plan = await _load_plan(db, plan_id)
    data = body.model_dump(exclude_unset=True)
    for name, value in data.items():
        setattr(plan, name, value)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="audit_plan", entity_id=plan.id,
        summary=f"Updated audit plan {plan.reference}",
        changes={k: str(v) for k, v in data.items()},
    )
    return _plan_read(await _load_plan(db, plan_id))


@router.delete("/audit-plans/{plan_id}", status_code=204, dependencies=[_WRITE])
async def delete_plan(plan_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    plan = await _load_plan(db, plan_id)
    plan.deleted = True
    await audit_log.record(
        db, actor=user, action="delete", entity_type="audit_plan", entity_id=plan_id,
        summary=f"Archived audit plan {plan.reference}",
    )


@router.post(
    "/audit-plans/{plan_id}/generate-from-universe",
    response_model=PlanGenerateResult,
    dependencies=[_WRITE],
    summary="Build a risk-based draft plan from the audit universe",
)
async def generate_from_universe(
    plan_id: uuid.UUID, body: PlanGenerateRequest, db: DbSession, user: CurrentUser
) -> PlanGenerateResult:
    """Propose plan lines from the units already carrying a risk rating and a frequency.

    Quarter is derived from when each unit is next due, so a risk-based plan comes out
    roughly scheduled rather than all landing in Q1. Units already in the plan are
    skipped, so this can be re-run after the universe grows.
    """
    plan = await _load_plan(db, plan_id)
    units = (
        await db.scalars(select(AuditableUnit).where(AuditableUnit.deleted.is_(False)))
    ).all()

    if body.replace_existing:
        for item in list(plan.items):
            if item.engagement_id is None:  # never discard a line already delivered
                await db.delete(item)
        await db.flush()
        plan = await _load_plan(db, plan_id)

    existing_units = {i.auditable_unit_id for i in plan.items if i.auditable_unit_id}
    floor = _CRIT_RANK[Criticality(body.min_risk)] if body.min_risk else 0
    year_end = date(plan.year, 12, 31)

    added = skipped = 0
    for unit in units:
        if _CRIT_RANK[unit.inherent_risk] < floor:
            skipped += 1
            continue
        if body.only_due and unit.next_audit_due is not None and unit.next_audit_due > year_end:
            skipped += 1
            continue
        if unit.id in existing_units:
            skipped += 1
            continue
        due = unit.next_audit_due
        quarter = (
            min(4, max(1, (due.month - 1) // 3 + 1))
            if due is not None and due.year == plan.year
            else 1
        )
        db.add(
            AuditPlanItem(
                tenant_id=user.tenant_id,
                plan_id=plan.id,
                auditable_unit_id=unit.id,
                title=f"Audit of {unit.name}",
                rationale=(
                    f"{unit.inherent_risk.value.title()} inherent risk, "
                    f"{unit.audit_frequency.value} audit frequency"
                ),
                planned_quarter=quarter,
                planned_month=(due.month if due is not None and due.year == plan.year else None),
                budgeted_hours=body.default_hours,
                lead_auditor=unit.owner or "",
            )
        )
        added += 1

    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="audit_plan", entity_id=plan.id,
        summary=f"Generated {added} plan line(s) for {plan.reference} from the audit universe",
        changes={"added": added, "skipped": skipped, "considered": len(units)},
    )
    return PlanGenerateResult(added=added, skipped=skipped, considered=len(units))


@router.post(
    "/audit-plans/{plan_id}/submit",
    response_model=PlanRead,
    dependencies=[_WRITE],
    summary="Send the plan for board / audit-committee approval",
)
async def submit_plan(
    plan_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> PlanRead:
    """Raise the sign-off through the shared approvals inbox.

    Reusing ``ApprovalRequest`` rather than inventing a plan-specific approval means the
    plan inherits maker-checker, the approvals inbox, overdue chasing and the audit log
    without any of it being rebuilt here.
    """
    plan = await _load_plan(db, plan_id)
    if not plan.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An empty plan cannot be submitted — add the audits it commits to first",
        )
    if plan.status in (AuditPlanStatus.approved, AuditPlanStatus.active):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This plan is already approved"
        )

    approval = ApprovalRequest(
        tenant_id=user.tenant_id,
        title=f"Annual audit plan {plan.year}: {plan.title}",
        description=(
            f"{plan.planned_count} audit(s), {plan.planned_hours} budgeted hours. "
            "Board / audit-committee approval of the annual plan."
        ),
        entity_type="audit_plan",
        entity_id=plan.id,
        entity_label=plan.reference,
        link="/internal-audit",
        requested_by=user.id,
        requested_by_email=user.email,
    )
    approval.reference = await next_reference(db, ApprovalRequest, "APR")
    db.add(approval)
    await db.flush()

    plan.approval_request_id = approval.id
    plan.status = AuditPlanStatus.submitted
    await db.flush()
    await audit_log.record(
        db, actor=user, action="submit", entity_type="audit_plan", entity_id=plan.id,
        summary=f"Submitted audit plan {plan.reference} for approval",
    )
    return _plan_read(await _load_plan(db, plan_id))


@router.get(
    "/audit-plans/{plan_id}/coverage",
    response_model=PlanCoverage,
    dependencies=[_READ],
    summary="Plan-vs-actual delivery, by quarter",
)
async def plan_coverage(plan_id: uuid.UUID, db: DbSession) -> PlanCoverage:
    plan = await _load_plan(db, plan_id)
    by_quarter = []
    for quarter in (1, 2, 3, 4):
        lines = [i for i in plan.items if i.planned_quarter == quarter]
        by_quarter.append(
            {
                "quarter": quarter,
                "planned": len(lines),
                "started": sum(1 for i in lines if i.engagement_id is not None),
                "hours": sum(i.budgeted_hours for i in lines),
            }
        )
    return PlanCoverage(
        planned=plan.planned_count, started=plan.started_count,
        coverage_pct=plan.coverage_pct, planned_hours=plan.planned_hours,
        budget_hours=plan.budget_hours, by_quarter=by_quarter,
    )


# --------------------------------------------------------------- plan items ---
@router.post(
    "/audit-plans/{plan_id}/items", response_model=PlanRead, status_code=201, dependencies=[_WRITE]
)
async def add_plan_item(
    plan_id: uuid.UUID, body: PlanItemCreate, db: DbSession, user: CurrentUser
) -> PlanRead:
    await _load_plan(db, plan_id)
    db.add(AuditPlanItem(tenant_id=user.tenant_id, plan_id=plan_id, **body.model_dump()))
    await db.flush()
    return _plan_read(await _load_plan(db, plan_id))


@router.patch("/audit-plan-items/{item_id}", response_model=PlanItemRead, dependencies=[_WRITE])
async def update_plan_item(
    item_id: uuid.UUID, body: PlanItemUpdate, db: DbSession
) -> PlanItemRead:
    item = await db.scalar(select(AuditPlanItem).where(AuditPlanItem.id == item_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Plan line not found")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(item, name, value)
    await db.flush()
    return PlanItemRead(
        id=item.id, title=item.title, auditable_unit_id=item.auditable_unit_id,
        rationale=item.rationale, planned_quarter=item.planned_quarter,
        planned_month=item.planned_month,
        budgeted_hours=item.budgeted_hours, lead_auditor=item.lead_auditor,
        engagement_id=item.engagement_id,
        auditable_unit_name=(item.auditable_unit.name if item.auditable_unit else ""),
    )


@router.delete("/audit-plan-items/{item_id}", status_code=204, dependencies=[_WRITE])
async def delete_plan_item(item_id: uuid.UUID, db: DbSession) -> None:
    item = await db.scalar(select(AuditPlanItem).where(AuditPlanItem.id == item_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Plan line not found")
    await db.delete(item)


# ---------------------------------------------------------------------------
# Programmes (checklists)
# ---------------------------------------------------------------------------
@router.get("/audit-programs", response_model=Page[ProgramRead], dependencies=[_READ])
async def list_programs(
    db: DbSession,
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProgramRead]:
    stmt = select(AuditProgram).where(AuditProgram.deleted.is_(False))
    if search:
        stmt = stmt.where(AuditProgram.name.ilike(f"%{search}%"))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(AuditProgram.name).limit(limit).offset(offset))).all()
    names = {
        f.id: f.name for f in (await db.scalars(select(Framework))).all()
    }
    return Page(
        items=[_program_read(p, names.get(p.framework_id, "")) for p in rows],
        total=total, limit=limit, offset=offset,
    )


@router.post("/audit-programs", response_model=ProgramRead, status_code=201, dependencies=[_WRITE])
async def create_program(body: ProgramCreate, db: DbSession, user: CurrentUser) -> ProgramRead:
    program = AuditProgram(tenant_id=user.tenant_id, **body.model_dump())
    program.reference = await next_reference(db, AuditProgram, "APG")
    db.add(program)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="audit_program", entity_id=program.id,
        summary=f"Created audit programme {program.reference}: {program.name}",
    )
    return _program_read(await _load_program(db, program.id))


@router.patch("/audit-programs/{program_id}", response_model=ProgramRead, dependencies=[_WRITE])
async def update_program(
    program_id: uuid.UUID, body: ProgramUpdate, db: DbSession
) -> ProgramRead:
    program = await _load_program(db, program_id)
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(program, name, value)
    await db.flush()
    return _program_read(await _load_program(db, program_id))


@router.delete("/audit-programs/{program_id}", status_code=204, dependencies=[_WRITE])
async def delete_program(program_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    program = await _load_program(db, program_id)
    program.deleted = True
    await audit_log.record(
        db, actor=user, action="delete", entity_type="audit_program", entity_id=program_id,
        summary=f"Archived audit programme {program.reference}",
    )


@router.post(
    "/audit-programs/{program_id}/steps",
    response_model=ProgramRead, status_code=201, dependencies=[_WRITE],
)
async def add_step(
    program_id: uuid.UUID, body: ProgramStepCreate, db: DbSession, user: CurrentUser
) -> ProgramRead:
    program = await _load_program(db, program_id)
    payload = body.model_dump()
    if not payload.get("order_index"):
        payload["order_index"] = len(program.steps) + 1
    db.add(AuditProgramStep(tenant_id=user.tenant_id, program_id=program_id, **payload))
    await db.flush()
    return _program_read(await _load_program(db, program_id))


@router.patch("/audit-program-steps/{step_id}", response_model=ProgramStepRead, dependencies=[_WRITE])
async def update_step(
    step_id: uuid.UUID, body: ProgramStepUpdate, db: DbSession
) -> ProgramStepRead:
    step = await db.scalar(select(AuditProgramStep).where(AuditProgramStep.id == step_id))
    if step is None:
        raise HTTPException(status_code=404, detail="Programme step not found")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(step, name, value)
    await db.flush()
    return ProgramStepRead.model_validate(step)


@router.delete("/audit-program-steps/{step_id}", status_code=204, dependencies=[_WRITE])
async def delete_step(step_id: uuid.UUID, db: DbSession) -> None:
    step = await db.scalar(select(AuditProgramStep).where(AuditProgramStep.id == step_id))
    if step is None:
        raise HTTPException(status_code=404, detail="Programme step not found")
    await db.delete(step)


@router.post(
    "/audit-programs/from-framework/{framework_id}",
    response_model=ProgramRead, status_code=201, dependencies=[_WRITE],
    summary="Generate a clause-by-clause checklist from an installed framework",
)
async def program_from_framework(
    framework_id: uuid.UUID,
    body: ProgramFromFrameworkRequest,
    db: DbSession,
    user: CurrentUser,
) -> ProgramRead:
    """One step per requirement of an installed framework.

    The clause list is already loaded by the framework library, so an ISO 27001 audit
    programme is a click rather than a fortnight of authoring — and every step keeps a
    link back to the clause it tests, which is what makes the finished working papers
    defensible to a certification auditor.
    """
    framework = await db.scalar(
        select(Framework).where(Framework.id == framework_id, Framework.deleted.is_(False))
    )
    if framework is None:
        raise HTTPException(status_code=404, detail="Framework not found")

    stmt = select(Requirement).where(Requirement.framework_id == framework_id)
    if body.domain:
        stmt = stmt.where(Requirement.domain == body.domain)
    requirements = (await db.scalars(stmt.order_by(Requirement.reference))).all()
    if not requirements:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That framework has no requirements to build a checklist from",
        )

    program = AuditProgram(
        tenant_id=user.tenant_id,
        name=body.name or f"{framework.name} — audit programme",
        description=(
            f"Clause-by-clause checklist generated from {framework.name}"
            + (f" ({body.domain})" if body.domain else "")
        ),
        category=framework.authority or "Compliance",
        framework_id=framework_id,
    )
    program.reference = await next_reference(db, AuditProgram, "APG")
    db.add(program)
    await db.flush()

    for index, requirement in enumerate(requirements, start=1):
        db.add(
            AuditProgramStep(
                tenant_id=user.tenant_id,
                program_id=program.id,
                order_index=index,
                title=f"{requirement.reference} {requirement.title}".strip(),
                procedure=requirement.description or "",
                expected_evidence="",
                requirement_id=requirement.id,
            )
        )
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="audit_program", entity_id=program.id,
        summary=(
            f"Generated audit programme {program.reference} from {framework.name} "
            f"({len(requirements)} steps)"
        ),
    )
    return _program_read(await _load_program(db, program.id), framework.name)


@router.post(
    "/audit-engagements/{eid}/apply-program/{program_id}",
    response_model=ApplyProgramResult, dependencies=[_WRITE],
    summary="Instantiate a programme's steps as working papers on an engagement",
)
async def apply_program(
    eid: uuid.UUID, program_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> ApplyProgramResult:
    """Steps become ordinary ``AuditProcedure`` rows.

    No new checklist concept is introduced — the engagement's working papers are what
    they always were, just populated rather than typed. Steps whose title is already on
    the engagement are skipped, so applying a second programme (or re-applying after an
    update) tops up instead of duplicating.
    """
    engagement = await db.scalar(
        select(AuditEngagement).where(
            AuditEngagement.id == eid, AuditEngagement.deleted.is_(False)
        )
    )
    if engagement is None:
        raise HTTPException(status_code=404, detail="Audit engagement not found")
    program = await _load_program(db, program_id)

    existing = {(p.title or "").strip().lower() for p in engagement.procedures}
    added = skipped = 0
    for step in program.steps:
        if step.title.strip().lower() in existing:
            skipped += 1
            continue
        db.add(
            AuditProcedure(
                tenant_id=user.tenant_id,
                engagement_id=eid,
                title=step.title,
                description=step.procedure,
                workpaper_ref=f"{program.reference}-{step.order_index:03d}",
            )
        )
        existing.add(step.title.strip().lower())
        added += 1

    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="audit_engagement", entity_id=eid,
        summary=(
            f"Applied programme {program.reference} to {engagement.reference}: "
            f"{added} working paper(s) added"
        ),
        changes={"added": added, "skipped": skipped},
    )
    return ApplyProgramResult(
        added=added, skipped=skipped, engagement_reference=engagement.reference
    )


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
@router.get(
    "/audit-calendar",
    response_model=AuditCalendar,
    dependencies=[_READ],
    summary="Dated assurance commitments in a window",
)
async def calendar(
    db: DbSession,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> AuditCalendar:
    """Everything the assurance function has to turn up for, in one window.

    Reads dates that already exist — planned fieldwork, finding due dates, when each
    auditable unit falls due — so nothing here is a second copy of a date recorded
    elsewhere. Defaults to the current quarter either side.
    """
    today = date.today()
    start = from_date or (today - timedelta(days=45))
    end = to_date or (today + timedelta(days=135))
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="'to' is before 'from'"
        )

    events: list[CalendarEvent] = []

    engagements = (
        await db.scalars(select(AuditEngagement).where(AuditEngagement.deleted.is_(False)))
    ).all()
    for engagement in engagements:
        when = engagement.planned_start or engagement.planned_end
        if when is None or not (start <= when <= end):
            continue
        events.append(
            CalendarEvent(
                kind="fieldwork",
                date=when,
                end_date=engagement.planned_end,
                title=engagement.title,
                reference=engagement.reference,
                severity=(engagement.rating.value if engagement.rating else ""),
                link="/internal-audit",
                overdue=(
                    engagement.status
                    not in (AuditEngagementStatus.closed, AuditEngagementStatus.cancelled)
                    and engagement.planned_end is not None
                    and engagement.planned_end < today
                ),
            )
        )

    findings = (
        await db.scalars(
            select(AuditFinding).where(
                AuditFinding.due_date.is_not(None),
                AuditFinding.due_date.between(start, end),
                AuditFinding.status.not_in(_OPEN_FINDING),
            )
        )
    ).all()
    for finding in findings:
        events.append(
            CalendarEvent(
                kind="finding_due", date=finding.due_date, title=finding.title,
                reference=finding.reference, severity=finding.rating.value,
                link="/internal-audit", overdue=finding.due_date < today,
            )
        )

    units = (
        await db.scalars(
            select(AuditableUnit).where(
                AuditableUnit.deleted.is_(False),
                AuditableUnit.next_audit_due.is_not(None),
                AuditableUnit.next_audit_due.between(start, end),
            )
        )
    ).all()
    for unit in units:
        events.append(
            CalendarEvent(
                kind="unit_due", date=unit.next_audit_due, title=f"{unit.name} falls due",
                reference=unit.reference, severity=unit.inherent_risk.value,
                link="/internal-audit", overdue=unit.next_audit_due < today,
            )
        )

    # Planned lines that have not yet become engagements: show them mid-quarter so an
    # unstarted commitment is visible on the calendar rather than only in the plan.
    plan_items = (
        await db.scalars(
            select(AuditPlanItem)
            .join(AuditPlan, AuditPlan.id == AuditPlanItem.plan_id)
            .where(AuditPlan.deleted.is_(False), AuditPlanItem.engagement_id.is_(None))
        )
    ).all()
    plans = {p.id: p for p in (await db.scalars(select(AuditPlan))).all()}
    for item in plan_items:
        plan = plans.get(item.plan_id)
        if plan is None:
            continue
        # A line scheduled to a specific month lands there; otherwise it sits mid-quarter.
        month = item.planned_month or min(12, item.planned_quarter * 3 - 1)
        marker = date(plan.year, month, 15)
        if not (start <= marker <= end):
            continue
        events.append(
            CalendarEvent(
                kind="planned_audit", date=marker, title=item.title,
                reference=plan.reference, severity="", link="/internal-audit",
                overdue=marker < today,
            )
        )

    events.sort(key=lambda e: (e.date, e.title))
    return AuditCalendar(events=events, from_date=start, to_date=end)
