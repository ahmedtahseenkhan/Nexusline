"""Risk Management API — the reference module.

Covers the full lifecycle: register CRUD, inherent/residual scoring, treatment,
control/asset linkage, a risk-acceptance approval workflow with expiry, and review
scheduling.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.asset import Asset
from app.models.control import Control
from app.models.incident import Incident
from app.models.policy import Policy
from app.models.enums import (
    AcceptanceStatus,
    RiskStatus,
    TreatmentStrategy,
)
from app.models.organization import BusinessUnit, Process
from app.models.risk import Risk, RiskAcceptance, risk_assets, risk_business_units, risk_processes
from app.models.threat import Threat, Vulnerability
from app.schemas.common import Page
from app.schemas.risk import (
    OrphanedRisk,
    OrphanedRiskPage,
    OrphanPurgeRequest,
    OrphanPurgeResult,
    ResidualAcceptance,
    RiskAcceptanceCreate,
    RiskAcceptanceDecision,
    RiskAcceptanceRead,
    RiskAssessment,
    RiskCreate,
    RiskRead,
    RiskUpdate,
    SuggestedResidual,
)
from app.services.refs import next_reference
from app.services import audit
from app.services import dual_control
from app.services.residual_engine import ControlInput, suggest_residual
from app.services.risk_scoring import next_review_date
from app.services.risk_settings import (
    get_matrix_size,
    get_max_score,
    get_or_create_residual_policy,
    policy_spec,
)

router = APIRouter(prefix="/risks", tags=["risks"])


# --------------------------------------------------------------------------- helpers
async def _load_risk(db, risk_id: uuid.UUID) -> Risk:
    risk = await db.scalar(
        select(Risk).where(Risk.id == risk_id, Risk.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if risk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    return risk


async def _resolve(db, model, ids: Sequence[uuid.UUID]) -> list:
    if not ids:
        return []
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    rows = (await db.scalars(stmt)).all()
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown {model.__name__.lower()} id(s): {sorted(map(str, missing))}",
        )
    return list(rows)


async def _next_reference(db) -> str:
    return await next_reference(db, Risk, "R")


def build_risk_query(
    *,
    status: RiskStatus | None = None,
    category: str | None = None,
    business_unit_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    search: str | None = None,
) -> Select:
    """The register's filter, in one place.

    Shared with the PDF export so "download what I am looking at" means exactly that.
    Duplicating these predicates is how a report quietly stops matching the screen it
    was launched from, which is the worst kind of reporting bug: nothing errors, the
    numbers are just wrong.

    Segment filters are ``EXISTS`` sub-queries rather than joins, because a risk in two
    business units would otherwise come back twice and inflate every count on the page.
    """
    stmt: Select = select(Risk).where(Risk.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(Risk.status == status)
    if category:
        stmt = stmt.where(Risk.category == category)
    if business_unit_id is not None:
        stmt = stmt.where(
            select(risk_business_units.c.risk_id)
            .where(
                risk_business_units.c.risk_id == Risk.id,
                risk_business_units.c.business_unit_id == business_unit_id,
            )
            .exists()
        )
    if process_id is not None:
        stmt = stmt.where(
            select(risk_processes.c.risk_id)
            .where(
                risk_processes.c.risk_id == Risk.id,
                risk_processes.c.process_id == process_id,
            )
            .exists()
        )
    if asset_id is not None:
        stmt = stmt.where(
            select(risk_assets.c.risk_id)
            .where(risk_assets.c.risk_id == Risk.id, risk_assets.c.asset_id == asset_id)
            .exists()
        )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Risk.title.ilike(like) | Risk.reference.ilike(like))
    return stmt


async def _check_scale(db, user: CurrentUser, values: dict[str, object]) -> None:
    """Reject scores outside the tenant's configured matrix.

    The schema only bounds scores to the widest scale any tenant may choose
    (``MAX_MATRIX_SIZE``) and the database check constraint does the same, because
    neither can vary per tenant.
    This is where the tenant's own ``matrix_size`` is enforced — without it, a 4x4
    organisation could store a 5 that its own heat map has no cell for.
    """
    size = await get_matrix_size(db, user.tenant_id)
    for name in (
        "inherent_likelihood", "inherent_impact", "residual_likelihood", "residual_impact",
    ):
        value = values.get(name)
        if isinstance(value, int) and value > size:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{name.replace('_', ' ')} {value} is outside this organisation's "
                    f"{size}x{size} risk matrix (1-{size})"
                ),
            )


def _control_inputs(risk: Risk) -> list[ControlInput]:
    """Describe each linked control to the residual engine, including whether it can be
    relied on today — a failed audit, an overdue test or an open finding means it cannot.
    """
    from app.models.enums import AuditFindingStatus, TestResult

    out: list[ControlInput] = []
    for control in risk.controls:
        note = ""
        if control.last_audit_result == TestResult.failed:
            note = "its last audit failed"
        elif control.is_audit_overdue:
            note = "its audit is overdue"
        elif any(
            f.status not in (AuditFindingStatus.closed, AuditFindingStatus.risk_accepted)
            for f in control.audit_findings
        ):
            note = "it has an open audit finding"
        out.append(
            ControlInput(
                label=control.reference or control.name,
                effectiveness=control.effectiveness,
                healthy=not note,
                health_note=note,
            )
        )
    return out


# --------------------------------------------------------------------------- CRUD
_RISK_SORTABLE = {
    "reference": Risk.reference,
    "title": Risk.title,
    "category": Risk.category,
    "status": Risk.status,
    "inherent_score": Risk.inherent_score,
    "residual_score": Risk.residual_score,
    "next_review_date": Risk.next_review_date,
    "created_at": Risk.created_at,
}


@router.get("", response_model=Page[RiskRead], dependencies=[Depends(require("risk:read"))])
async def list_risks(
    db: DbSession,
    user: CurrentUser,
    status_filter: Annotated[RiskStatus | None, Query(alias="status")] = None,
    category: str | None = None,
    business_unit_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RiskRead]:
    stmt: Select = build_risk_query(
        status=status_filter,
        category=category,
        business_unit_id=business_unit_id,
        process_id=process_id,
        asset_id=asset_id,
        search=search,
    )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _RISK_SORTABLE, default=Risk.inherent_score)
    else:
        stmt = stmt.order_by(Risk.inherent_score.desc(), Risk.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    context = {"max_score": await get_max_score(db, user.tenant_id)}
    return Page(
        items=[RiskRead.model_validate(r, context=context) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=RiskRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("risk:write"))],
)
async def create_risk(body: RiskCreate, db: DbSession, user: CurrentUser) -> RiskRead:
    await _check_scale(db, user, body.model_dump())
    data = body.model_dump(
        exclude={
            "business_unit_ids", "process_ids", "asset_ids", "control_ids",
            "threat_ids", "vulnerability_ids", "policy_ids", "incident_ids",
        }
    )
    risk = Risk(tenant_id=user.tenant_id, **data)
    risk.reference = await _next_reference(db)
    risk.business_units = await _resolve(db, BusinessUnit, body.business_unit_ids)
    risk.processes = await _resolve(db, Process, body.process_ids)
    risk.assets = await _resolve(db, Asset, body.asset_ids)
    risk.controls = await _resolve(db, Control, body.control_ids)
    risk.threats = await _resolve(db, Threat, body.threat_ids)
    risk.vulnerabilities = await _resolve(db, Vulnerability, body.vulnerability_ids)
    risk.policies = await _resolve(db, Policy, body.policy_ids)
    risk.incidents = await _resolve(db, Incident, body.incident_ids)
    risk.next_review_date = next_review_date(risk.review_frequency)

    db.add(risk)
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="create",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Created risk {risk.reference}: {risk.title}",
    )
    return await _read(db, risk.id, user)


# ------------------------------------------------------------------ orphan cleanup
async def _orphaned_risk_ids(db) -> list[uuid.UUID]:
    """Live risks that are linked only to deleted assets.

    A risk with no asset links at all is left alone — a hand-made register entry
    is not required to name an asset. Orphaned means: link rows exist in
    ``risk_assets``, but none of them reaches a live asset any more (assets are
    soft-deleted, so the link rows survive).
    """
    has_links = select(risk_assets.c.risk_id)
    has_live_asset = (
        select(risk_assets.c.risk_id)
        .join(Asset, Asset.id == risk_assets.c.asset_id)
        .where(Asset.deleted.is_(False))
    )
    return list(
        (
            await db.scalars(
                select(Risk.id).where(
                    Risk.deleted.is_(False),
                    Risk.id.in_(has_links),
                    Risk.id.notin_(has_live_asset),
                )
            )
        ).all()
    )


@router.get(
    "/orphaned",
    response_model=OrphanedRiskPage,
    dependencies=[Depends(require("risk:read"))],
    summary="Risks whose every linked asset has been deleted — candidates for cleanup",
)
async def list_orphaned_risks(db: DbSession) -> OrphanedRiskPage:
    ids = await _orphaned_risk_ids(db)
    if not ids:
        return OrphanedRiskPage(items=[], total=0)

    rows = (
        await db.scalars(
            select(Risk).where(Risk.id.in_(ids)).order_by(Risk.reference)
        )
    ).all()
    # Which deleted assets each risk pointed at, so the reviewer can see why it
    # is on this list before archiving anything.
    names: dict[uuid.UUID, list[str]] = {}
    for rid, name in (
        await db.execute(
            select(risk_assets.c.risk_id, Asset.name)
            .join(Asset, Asset.id == risk_assets.c.asset_id)
            .where(risk_assets.c.risk_id.in_(ids), Asset.deleted.is_(True))
        )
    ).all():
        names.setdefault(rid, []).append(name)
    return OrphanedRiskPage(
        items=[
            OrphanedRisk(
                id=r.id,
                reference=r.reference,
                title=r.title,
                category=r.category,
                status=r.status.value,
                inherent_score=r.inherent_score,
                deleted_asset_names=sorted(names.get(r.id, [])),
            )
            for r in rows
        ],
        total=len(rows),
    )


@router.post(
    "/orphaned/purge",
    response_model=OrphanPurgeResult,
    dependencies=[Depends(require("risk:delete"))],
    summary="Archive orphaned risks (soft delete, audit-logged)",
)
async def purge_orphaned_risks(
    body: OrphanPurgeRequest, db: DbSession, user: CurrentUser
) -> OrphanPurgeResult:
    from datetime import datetime, timezone

    orphaned = set(await _orphaned_risk_ids(db))
    targets = orphaned & set(body.risk_ids) if body.risk_ids else orphaned
    if not targets:
        return OrphanPurgeResult(archived=0, references=[])

    rows = (await db.scalars(select(Risk).where(Risk.id.in_(targets)))).all()
    now = datetime.now(timezone.utc)
    for risk in rows:
        risk.deleted = True
        risk.deleted_date = now
    refs = sorted(r.reference for r in rows)
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="delete",
        entity_type="risk",
        entity_id=None,
        summary=(
            f"Archived {len(rows)} orphaned risk(s) whose linked assets were deleted"
        ),
        changes={"references": ", ".join(refs[:50]) + (" …" if len(refs) > 50 else "")},
    )
    return OrphanPurgeResult(archived=len(rows), references=refs)


@router.get("/{risk_id}", response_model=RiskRead, dependencies=[Depends(require("risk:read"))])
async def get_risk(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> RiskRead:
    return await _read(db, risk_id, user)


@router.patch(
    "/{risk_id}", response_model=RiskRead, dependencies=[Depends(require("risk:write"))]
)
async def update_risk(
    risk_id: uuid.UUID, body: RiskUpdate, db: DbSession, user: CurrentUser
) -> RiskRead:
    risk = await _load_risk(db, risk_id)
    data = body.model_dump(exclude_unset=True)
    await _check_scale(db, user, data)

    business_unit_ids = data.pop("business_unit_ids", None)
    process_ids = data.pop("process_ids", None)
    asset_ids = data.pop("asset_ids", None)
    control_ids = data.pop("control_ids", None)
    threat_ids = data.pop("threat_ids", None)
    vulnerability_ids = data.pop("vulnerability_ids", None)
    policy_ids = data.pop("policy_ids", None)
    incident_ids = data.pop("incident_ids", None)
    if business_unit_ids is not None:
        risk.business_units = await _resolve(db, BusinessUnit, business_unit_ids)
    if process_ids is not None:
        risk.processes = await _resolve(db, Process, process_ids)
    if asset_ids is not None:
        risk.assets = await _resolve(db, Asset, asset_ids)
    if control_ids is not None:
        risk.controls = await _resolve(db, Control, control_ids)
    if threat_ids is not None:
        risk.threats = await _resolve(db, Threat, threat_ids)
    if vulnerability_ids is not None:
        risk.vulnerabilities = await _resolve(db, Vulnerability, vulnerability_ids)
    if policy_ids is not None:
        risk.policies = await _resolve(db, Policy, policy_ids)
    if incident_ids is not None:
        risk.incidents = await _resolve(db, Incident, incident_ids)

    for field, value in data.items():
        setattr(risk, field, value)

    if "review_frequency" in data:
        risk.next_review_date = next_review_date(
            risk.review_frequency, risk.last_review_date
        )

    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="update",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Updated risk {risk.reference}",
        changes={k: str(v) for k, v in data.items()},
    )
    return await _read(db, risk.id, user)


@router.delete(
    "/{risk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("risk:delete"))],
)
async def delete_risk(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    from datetime import datetime, timezone

    risk = await _load_risk(db, risk_id)
    ref = risk.reference
    risk.deleted = True
    risk.deleted_date = datetime.now(timezone.utc)
    await audit.record(
        db,
        actor=user,
        action="delete",
        entity_type="risk",
        entity_id=risk_id,
        summary=f"Archived risk {ref}",
    )


# --------------------------------------------------------------------------- workflow
@router.post(
    "/{risk_id}/assess",
    response_model=RiskRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Record residual scoring after controls",
)
async def assess_risk(
    risk_id: uuid.UUID, body: RiskAssessment, db: DbSession, user: CurrentUser
) -> RiskRead:
    risk = await _load_risk(db, risk_id)
    await _check_scale(db, user, body.model_dump())
    risk.residual_likelihood = body.residual_likelihood
    risk.residual_impact = body.residual_impact
    if risk.status == RiskStatus.draft:
        risk.status = RiskStatus.assessed
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="assess",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Assessed residual risk for {risk.reference}",
    )
    return await _read(db, risk.id, user)


@router.post(
    "/{risk_id}/review",
    response_model=RiskRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Mark a risk reviewed; reschedules the next review",
)
async def review_risk(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> RiskRead:
    risk = await _load_risk(db, risk_id)
    today = date.today()
    risk.last_review_date = today
    risk.next_review_date = next_review_date(risk.review_frequency, today)
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="review",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Reviewed risk {risk.reference}",
    )
    return await _read(db, risk.id, user)


# ------------------------------------------------------------- residual suggestion
@router.get(
    "/{risk_id}/suggested-residual",
    response_model=SuggestedResidual,
    dependencies=[Depends(require("risk:read"))],
    summary="Residual score proposed from the linked controls' effectiveness",
)
async def get_suggested_residual(
    risk_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> SuggestedResidual:
    """Compute — but never store — a residual proposal, with its reasoning.

    Read-only and always recomputed, so it reflects control effectiveness *as of now*:
    when a mitigating control's audit fails, the proposal rises again on the next read
    without anyone re-running anything.
    """
    risk = await _load_risk(db, risk_id)
    policy = await get_or_create_residual_policy(db, user.tenant_id)
    suggestion = suggest_residual(
        risk.inherent_likelihood,
        risk.inherent_impact,
        _control_inputs(risk),
        policy_spec(policy),
    )
    return SuggestedResidual(
        likelihood=suggestion.likelihood,
        impact=suggestion.impact,
        score=suggestion.score,
        reduction=suggestion.reduction,
        rationale=suggestion.rationale,
        inherent_score=risk.inherent_score,
        current_residual_score=risk.residual_score,
        matches_current=(
            risk.residual_likelihood == suggestion.likelihood
            and risk.residual_impact == suggestion.impact
        ),
    )


@router.post(
    "/{risk_id}/accept-residual",
    response_model=RiskRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Adopt the suggested residual, or record a different judgement with a reason",
)
async def accept_residual(
    risk_id: uuid.UUID, body: ResidualAcceptance, db: DbSession, user: CurrentUser
) -> RiskRead:
    """Sign off the residual score.

    Sending no scores accepts the suggestion as it stands. Sending different scores is
    an override and **requires a reason** — that sentence is what an auditor reads when
    they ask why the recorded residual is lower than the control evidence supports.
    """
    risk = await _load_risk(db, risk_id)
    policy = await get_or_create_residual_policy(db, user.tenant_id)
    suggestion = suggest_residual(
        risk.inherent_likelihood,
        risk.inherent_impact,
        _control_inputs(risk),
        policy_spec(policy),
    )

    likelihood = body.likelihood if body.likelihood is not None else suggestion.likelihood
    impact = body.impact if body.impact is not None else suggestion.impact
    await _check_scale(
        db, user, {"residual_likelihood": likelihood, "residual_impact": impact}
    )

    is_override = (likelihood, impact) != (suggestion.likelihood, suggestion.impact)
    if is_override and not body.override_reason.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Recording {likelihood}x{impact} instead of the suggested "
                f"{suggestion.likelihood}x{suggestion.impact} needs a written reason"
            ),
        )

    risk.residual_likelihood = likelihood
    risk.residual_impact = impact
    risk.suggested_residual_likelihood = suggestion.likelihood
    risk.suggested_residual_impact = suggestion.impact
    risk.suggested_residual_rationale = "\n".join(suggestion.rationale)
    risk.residual_override_reason = body.override_reason.strip() if is_override else ""
    risk.residual_accepted_by = user.id
    risk.residual_accepted_at = date.today()
    if risk.status == RiskStatus.draft:
        risk.status = RiskStatus.assessed

    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="assess",
        entity_type="risk",
        entity_id=risk.id,
        summary=(
            f"{'Overrode' if is_override else 'Accepted'} suggested residual for "
            f"{risk.reference}: {likelihood}x{impact}"
        ),
        changes={
            "residual_likelihood": likelihood,
            "residual_impact": impact,
            "suggested": f"{suggestion.likelihood}x{suggestion.impact}",
            "override_reason": risk.residual_override_reason,
        },
    )
    return await _read(db, risk.id, user)


@router.post(
    "/{risk_id}/acceptances",
    response_model=RiskAcceptanceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("risk:write"))],
    summary="Request formal acceptance of a risk",
)
async def request_acceptance(
    risk_id: uuid.UUID, body: RiskAcceptanceCreate, db: DbSession, user: CurrentUser
) -> RiskAcceptanceRead:
    risk = await _load_risk(db, risk_id)
    acceptance = RiskAcceptance(
        tenant_id=user.tenant_id,
        risk_id=risk.id,
        requested_by=user.id,
        rationale=body.rationale,
        expires_at=body.expires_at,
        status=AcceptanceStatus.pending,
    )
    db.add(acceptance)
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="request_acceptance",
        entity_type="risk_acceptance",
        entity_id=acceptance.id,
        summary=f"Requested acceptance for risk {risk.reference}",
    )
    await db.refresh(acceptance)
    return RiskAcceptanceRead.model_validate(acceptance)


@router.post(
    "/{risk_id}/acceptances/{acceptance_id}/decision",
    response_model=RiskAcceptanceRead,
    dependencies=[Depends(require("risk:accept"))],
    summary="Approve or reject a pending risk acceptance",
)
async def decide_acceptance(
    risk_id: uuid.UUID,
    acceptance_id: uuid.UUID,
    body: RiskAcceptanceDecision,
    db: DbSession,
    user: CurrentUser,
) -> RiskAcceptanceRead:
    acceptance = await db.scalar(
        select(RiskAcceptance).where(
            RiskAcceptance.id == acceptance_id, RiskAcceptance.risk_id == risk_id
        )
    )
    if acceptance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Acceptance not found"
        )
    if acceptance.status != AcceptanceStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Acceptance already {acceptance.status.value}",
        )

    # Maker-checker: accepting a risk is a four-eyes control — the person who requested
    # the acceptance can never approve it. Gated by the risk's exposure (ALE) so a
    # DualControlRule threshold can scope it to material risks.
    risk = await _load_risk(db, risk_id)
    await dual_control.enforce_maker_checker(
        db,
        module="risk",
        action="accept",
        maker_id=acceptance.requested_by,
        checker_id=user.id,
        amount=float(risk.annual_loss_expectancy) if risk.annual_loss_expectancy else None,
        subject="risk acceptance",
    )

    acceptance.approver_id = user.id
    acceptance.decided_at = date.today()
    if body.approve:
        acceptance.status = AcceptanceStatus.approved
        risk.status = RiskStatus.accepted
        risk.treatment_strategy = TreatmentStrategy.accept
        action, verb = "approve_acceptance", "Approved"
    else:
        acceptance.status = AcceptanceStatus.rejected
        action, verb = "reject_acceptance", "Rejected"

    await db.flush()
    await audit.record(
        db,
        actor=user,
        action=action,
        entity_type="risk_acceptance",
        entity_id=acceptance.id,
        summary=f"{verb} acceptance for risk {risk_id}",
        changes={"note": body.note} if body.note else {},
    )
    await db.refresh(acceptance)
    return RiskAcceptanceRead.model_validate(acceptance)


async def _read(db, risk_id: uuid.UUID, user: CurrentUser) -> RiskRead:
    """Reload a risk with relationships for serialization.

    The tenant's matrix size travels as validation context so severity chips are banded
    on the same scale the heat map uses — a 4x4 register must not be banded as 5x5.
    """
    max_score = await get_max_score(db, user.tenant_id)
    return RiskRead.model_validate(
        await _load_risk(db, risk_id), context={"max_score": max_score}
    )
