"""Fraud Risk Management API — fraud risk register, fraud case management, and the
SBP digital-fraud control checklist.

SBP's digital-fraud circulars are its most active enforcement area; this module is
kept distinct from AML/CFT. Amounts are in PKR by default.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.fraud import (
    FraudCase,
    FraudCaseStatus,
    FraudChannel,
    FraudControlCategory,
    FraudControlCheck,
    FraudControlStatus,
    FraudRisk,
    FraudRiskStatus,
    FraudScheme,
    PerpetratorType,
)
from app.schemas.common import Page
from app.schemas.fraud import (
    FraudCaseCreate,
    FraudCaseRead,
    FraudCaseUpdate,
    FraudControlCheckCreate,
    FraudControlCheckRead,
    FraudControlCheckUpdate,
    FraudRiskCreate,
    FraudRiskRead,
    FraudRiskUpdate,
)
from app.services import audit as audit_log

router = APIRouter(tags=["fraud risk"])

_READ = Depends(require("fraud:read"))
_WRITE = Depends(require("fraud:write"))


async def _next_ref(db, model, prefix: str) -> str:
    count = await db.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{count + 1:03d}"


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ============================================================ fraud risks ===
@router.get("/fraud-risks", response_model=Page[FraudRiskRead], dependencies=[_READ])
async def list_fraud_risks(
    db: DbSession,
    status: FraudRiskStatus | None = None,
    scheme: FraudScheme | None = None,
    channel: FraudChannel | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FraudRiskRead]:
    stmt = select(FraudRisk).where(FraudRisk.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(FraudRisk.status == status)
    if scheme is not None:
        stmt = stmt.where(FraudRisk.scheme == scheme)
    if channel is not None:
        stmt = stmt.where(FraudRisk.channel == channel)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(FraudRisk.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[FraudRiskRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/fraud-risks", response_model=FraudRiskRead, status_code=201, dependencies=[_WRITE])
async def create_fraud_risk(body: FraudRiskCreate, db: DbSession, user: CurrentUser) -> FraudRiskRead:
    obj = FraudRisk(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, FraudRisk, "FR")
    db.add(obj)
    await db.flush()
    return FraudRiskRead.model_validate(obj)


@router.get("/fraud-risks/{rid}", response_model=FraudRiskRead, dependencies=[_READ])
async def get_fraud_risk(rid: uuid.UUID, db: DbSession) -> FraudRiskRead:
    return FraudRiskRead.model_validate(await _get(db, FraudRisk, rid, "Fraud risk"))


@router.patch("/fraud-risks/{rid}", response_model=FraudRiskRead, dependencies=[_WRITE])
async def update_fraud_risk(rid: uuid.UUID, body: FraudRiskUpdate, db: DbSession) -> FraudRiskRead:
    obj = await _get(db, FraudRisk, rid, "Fraud risk")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return FraudRiskRead.model_validate(obj)


@router.delete("/fraud-risks/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_fraud_risk(rid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, FraudRisk, rid, "Fraud risk")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================================ fraud cases ===
@router.get("/fraud-cases", response_model=Page[FraudCaseRead], dependencies=[_READ])
async def list_fraud_cases(
    db: DbSession,
    status: FraudCaseStatus | None = None,
    scheme: FraudScheme | None = None,
    perpetrator_type: PerpetratorType | None = None,
    reported_to_regulator: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FraudCaseRead]:
    stmt = select(FraudCase).where(FraudCase.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(FraudCase.status == status)
    if scheme is not None:
        stmt = stmt.where(FraudCase.scheme == scheme)
    if perpetrator_type is not None:
        stmt = stmt.where(FraudCase.perpetrator_type == perpetrator_type)
    if reported_to_regulator is not None:
        stmt = stmt.where(FraudCase.reported_to_regulator.is_(reported_to_regulator))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(FraudCase.reported_date.is_(None), FraudCase.reported_date.desc(), FraudCase.created_at.desc())
        .limit(limit).offset(offset)
    )).all()
    return Page(items=[FraudCaseRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/fraud-cases", response_model=FraudCaseRead, status_code=201, dependencies=[_WRITE])
async def create_fraud_case(body: FraudCaseCreate, db: DbSession, user: CurrentUser) -> FraudCaseRead:
    obj = FraudCase(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, FraudCase, "FC")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="fraud_case",
                           entity_id=obj.id, summary=f"Opened fraud case {obj.reference}: {obj.title}")
    return FraudCaseRead.model_validate(obj)


@router.get("/fraud-cases/{cid}", response_model=FraudCaseRead, dependencies=[_READ])
async def get_fraud_case(cid: uuid.UUID, db: DbSession) -> FraudCaseRead:
    return FraudCaseRead.model_validate(await _get(db, FraudCase, cid, "Fraud case"))


@router.patch("/fraud-cases/{cid}", response_model=FraudCaseRead, dependencies=[_WRITE])
async def update_fraud_case(cid: uuid.UUID, body: FraudCaseUpdate, db: DbSession) -> FraudCaseRead:
    obj = await _get(db, FraudCase, cid, "Fraud case")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return FraudCaseRead.model_validate(obj)


@router.delete("/fraud-cases/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_fraud_case(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, FraudCase, cid, "Fraud case")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================ SBP digital-fraud checklist ===
@router.get("/fraud-control-checks", response_model=Page[FraudControlCheckRead], dependencies=[_READ])
async def list_fraud_control_checks(
    db: DbSession,
    category: FraudControlCategory | None = None,
    status: FraudControlStatus | None = None,
    implemented: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FraudControlCheckRead]:
    stmt = select(FraudControlCheck).where(FraudControlCheck.deleted.is_(False))
    if category is not None:
        stmt = stmt.where(FraudControlCheck.category == category)
    if status is not None:
        stmt = stmt.where(FraudControlCheck.status == status)
    if implemented is not None:
        stmt = stmt.where(FraudControlCheck.implemented.is_(implemented))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(FraudControlCheck.created_at).limit(limit).offset(offset))).all()
    return Page(items=[FraudControlCheckRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/fraud-control-checks", response_model=FraudControlCheckRead, status_code=201, dependencies=[_WRITE])
async def create_fraud_control_check(body: FraudControlCheckCreate, db: DbSession, user: CurrentUser) -> FraudControlCheckRead:
    obj = FraudControlCheck(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, FraudControlCheck, "FCK")
    db.add(obj)
    await db.flush()
    return FraudControlCheckRead.model_validate(obj)


@router.get("/fraud-control-checks/{kid}", response_model=FraudControlCheckRead, dependencies=[_READ])
async def get_fraud_control_check(kid: uuid.UUID, db: DbSession) -> FraudControlCheckRead:
    return FraudControlCheckRead.model_validate(await _get(db, FraudControlCheck, kid, "Fraud control check"))


@router.patch("/fraud-control-checks/{kid}", response_model=FraudControlCheckRead, dependencies=[_WRITE])
async def update_fraud_control_check(kid: uuid.UUID, body: FraudControlCheckUpdate, db: DbSession) -> FraudControlCheckRead:
    obj = await _get(db, FraudControlCheck, kid, "Fraud control check")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return FraudControlCheckRead.model_validate(obj)


@router.delete("/fraud-control-checks/{kid}", status_code=204, dependencies=[_WRITE])
async def delete_fraud_control_check(kid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, FraudControlCheck, kid, "Fraud control check")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ================================================================ summary ===
class FraudLossRow(BaseModel):
    scheme: str
    count: int
    gross_loss: float
    net_loss: float


class FraudSummary(BaseModel):
    cases_by_status: dict[str, int]
    open_cases: int
    loss_by_scheme: list[FraudLossRow]
    total_gross_loss: float
    total_net_loss: float
    checklist_total: int
    checklist_implemented: int
    checklist_pct: float
    risks_by_band: dict[str, int]
    high_residual_risks: int


def _band(score: int) -> str:
    """Residual score band: low 1-6 / medium 8-12 / high 15-25 (5x5 matrix)."""
    if score >= 15:
        return "high"
    if score >= 8:
        return "medium"
    return "low"


@router.get("/fraud-summary", response_model=FraudSummary, dependencies=[_READ],
            summary="Fraud dashboard roll-up: cases, losses, checklist coverage and residual-risk bands")
async def fraud_summary(db: DbSession) -> FraudSummary:
    cases = (await db.scalars(select(FraudCase).where(FraudCase.deleted.is_(False)))).all()
    checks = (await db.scalars(select(FraudControlCheck).where(FraudControlCheck.deleted.is_(False)))).all()
    risks = (await db.scalars(select(FraudRisk).where(FraudRisk.deleted.is_(False)))).all()

    cases_by_status: dict[str, int] = defaultdict(int)
    loss_groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "gross": 0.0, "net": 0.0})
    open_cases = 0
    for c in cases:
        cases_by_status[c.status.value] += 1
        if c.status not in (FraudCaseStatus.closed, FraudCaseStatus.recovered):
            open_cases += 1
        g = loss_groups[c.scheme.value]
        g["count"] += 1
        g["gross"] += float(c.amount_involved or 0)
        g["net"] += c.net_loss

    loss_by_scheme = [
        FraudLossRow(scheme=k, count=v["count"], gross_loss=round(v["gross"], 2), net_loss=round(v["net"], 2))
        for k, v in sorted(loss_groups.items())
    ]

    checklist_total = len(checks)
    checklist_implemented = sum(1 for k in checks if k.implemented)
    checklist_pct = round(checklist_implemented / checklist_total * 100, 1) if checklist_total else 0.0

    risks_by_band: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    for r in risks:
        risks_by_band[_band(r.residual_score)] += 1

    return FraudSummary(
        cases_by_status=dict(cases_by_status),
        open_cases=open_cases,
        loss_by_scheme=loss_by_scheme,
        total_gross_loss=round(sum(r.gross_loss for r in loss_by_scheme), 2),
        total_net_loss=round(sum(r.net_loss for r in loss_by_scheme), 2),
        checklist_total=checklist_total,
        checklist_implemented=checklist_implemented,
        checklist_pct=checklist_pct,
        risks_by_band=risks_by_band,
        high_residual_risks=risks_by_band["high"],
    )
