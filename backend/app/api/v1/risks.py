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
from app.models.risk import Risk, RiskAcceptance
from app.models.threat import Threat, Vulnerability
from app.schemas.common import Page
from app.schemas.risk import (
    RiskAcceptanceCreate,
    RiskAcceptanceDecision,
    RiskAcceptanceRead,
    RiskAssessment,
    RiskCreate,
    RiskRead,
    RiskUpdate,
)
from app.services.refs import next_reference
from app.services import audit
from app.services.risk_scoring import next_review_date

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
    rows = (await db.scalars(select(model).where(model.id.in_(ids)))).all()
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown {model.__name__.lower()} id(s): {sorted(map(str, missing))}",
        )
    return list(rows)


async def _next_reference(db) -> str:
    return await next_reference(db, Risk, "R")


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
    status_filter: Annotated[RiskStatus | None, Query(alias="status")] = None,
    category: str | None = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RiskRead]:
    stmt: Select = select(Risk).where(Risk.deleted.is_(False))
    if status_filter is not None:
        stmt = stmt.where(Risk.status == status_filter)
    if category:
        stmt = stmt.where(Risk.category == category)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Risk.title.ilike(like) | Risk.reference.ilike(like))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _RISK_SORTABLE, default=Risk.inherent_score)
    else:
        stmt = stmt.order_by(Risk.inherent_score.desc(), Risk.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(
        items=[RiskRead.model_validate(r) for r in rows],
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
    data = body.model_dump(
        exclude={"asset_ids", "control_ids", "threat_ids", "vulnerability_ids", "policy_ids", "incident_ids"}
    )
    risk = Risk(tenant_id=user.tenant_id, **data)
    risk.reference = await _next_reference(db)
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
    return await _read(db, risk.id)


@router.get("/{risk_id}", response_model=RiskRead, dependencies=[Depends(require("risk:read"))])
async def get_risk(risk_id: uuid.UUID, db: DbSession) -> RiskRead:
    return RiskRead.model_validate(await _load_risk(db, risk_id))


@router.patch(
    "/{risk_id}", response_model=RiskRead, dependencies=[Depends(require("risk:write"))]
)
async def update_risk(
    risk_id: uuid.UUID, body: RiskUpdate, db: DbSession, user: CurrentUser
) -> RiskRead:
    risk = await _load_risk(db, risk_id)
    data = body.model_dump(exclude_unset=True)

    asset_ids = data.pop("asset_ids", None)
    control_ids = data.pop("control_ids", None)
    threat_ids = data.pop("threat_ids", None)
    vulnerability_ids = data.pop("vulnerability_ids", None)
    policy_ids = data.pop("policy_ids", None)
    incident_ids = data.pop("incident_ids", None)
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
    return await _read(db, risk.id)


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
    return await _read(db, risk.id)


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
    return await _read(db, risk.id)


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

    acceptance.approver_id = user.id
    acceptance.decided_at = date.today()
    if body.approve:
        acceptance.status = AcceptanceStatus.approved
        risk = await _load_risk(db, risk_id)
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


async def _read(db, risk_id: uuid.UUID) -> RiskRead:
    """Reload a risk with relationships for serialization."""
    return RiskRead.model_validate(await _load_risk(db, risk_id))
