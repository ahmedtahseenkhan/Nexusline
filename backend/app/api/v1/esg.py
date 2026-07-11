"""ESG / Green Banking API — SBP Green Banking Guidelines alignment, ESG metrics,
and environmental risk ratings for credit/vendor exposures."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.esg import EnvironmentalRiskRating, EnvRiskCategory, EsgAssessment, EsgPillar, EsgStatus
from app.schemas.common import Page
from app.schemas.esg import (
    EnvRatingCreate,
    EnvRatingRead,
    EnvRatingUpdate,
    EsgAssessmentCreate,
    EsgAssessmentRead,
    EsgAssessmentUpdate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["esg"])

_READ = Depends(require("esg:read"))
_WRITE = Depends(require("esg:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ======================================================= ESG assessments ===
_ESG_SORTABLE = {
    "reference": EsgAssessment.reference,
    "title": EsgAssessment.title,
    "pillar": EsgAssessment.pillar,
    "category": EsgAssessment.category,
    "status": EsgAssessment.status,
    "owner": EsgAssessment.owner,
    "period": EsgAssessment.period,
    "created_at": EsgAssessment.created_at,
}


@router.get("/esg-assessments", response_model=Page[EsgAssessmentRead], dependencies=[_READ])
async def list_esg_assessments(
    db: DbSession,
    search: str | None = None,
    pillar: Annotated[EsgPillar | None, Query()] = None,
    status_filter: Annotated[EsgStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EsgAssessmentRead]:
    stmt: Select = select(EsgAssessment).where(EsgAssessment.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            EsgAssessment.title.ilike(like),
            EsgAssessment.category.ilike(like),
            EsgAssessment.metric.ilike(like),
            EsgAssessment.owner.ilike(like),
        ))
    if pillar is not None:
        stmt = stmt.where(EsgAssessment.pillar == pillar)
    if status_filter is not None:
        stmt = stmt.where(EsgAssessment.status == status_filter)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _ESG_SORTABLE, default=EsgAssessment.created_at)
    else:
        stmt = stmt.order_by(EsgAssessment.created_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[EsgAssessmentRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/esg-assessments", response_model=EsgAssessmentRead, status_code=201, dependencies=[_WRITE])
async def create_esg_assessment(body: EsgAssessmentCreate, db: DbSession, user: CurrentUser) -> EsgAssessmentRead:
    obj = EsgAssessment(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, EsgAssessment, "ESG")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="esg_assessment",
                           entity_id=obj.id, summary=f"Opened ESG assessment {obj.reference}: {obj.title}")
    return EsgAssessmentRead.model_validate(obj)


@router.get("/esg-assessments/{aid}", response_model=EsgAssessmentRead, dependencies=[_READ])
async def get_esg_assessment(aid: uuid.UUID, db: DbSession) -> EsgAssessmentRead:
    return EsgAssessmentRead.model_validate(await _get(db, EsgAssessment, aid, "ESG assessment"))


@router.patch("/esg-assessments/{aid}", response_model=EsgAssessmentRead, dependencies=[_WRITE])
async def update_esg_assessment(aid: uuid.UUID, body: EsgAssessmentUpdate, db: DbSession) -> EsgAssessmentRead:
    obj = await _get(db, EsgAssessment, aid, "ESG assessment")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return EsgAssessmentRead.model_validate(obj)


@router.delete("/esg-assessments/{aid}", status_code=204, dependencies=[_WRITE])
async def delete_esg_assessment(aid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, EsgAssessment, aid, "ESG assessment")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ============================================== environmental risk ratings ===
_ENV_SORTABLE = {
    "reference": EnvironmentalRiskRating.reference,
    "entity_name": EnvironmentalRiskRating.entity_name,
    "sector": EnvironmentalRiskRating.sector,
    "risk_category": EnvironmentalRiskRating.risk_category,
    "assessor": EnvironmentalRiskRating.assessor,
    "rating_date": EnvironmentalRiskRating.rating_date,
    "created_at": EnvironmentalRiskRating.created_at,
}


@router.get("/environmental-risk-ratings", response_model=Page[EnvRatingRead], dependencies=[_READ])
async def list_env_ratings(
    db: DbSession,
    search: str | None = None,
    risk_category: Annotated[EnvRiskCategory | None, Query()] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EnvRatingRead]:
    stmt: Select = select(EnvironmentalRiskRating).where(EnvironmentalRiskRating.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            EnvironmentalRiskRating.entity_name.ilike(like),
            EnvironmentalRiskRating.sector.ilike(like),
        ))
    if risk_category is not None:
        stmt = stmt.where(EnvironmentalRiskRating.risk_category == risk_category)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _ENV_SORTABLE, default=EnvironmentalRiskRating.created_at)
    else:
        stmt = stmt.order_by(EnvironmentalRiskRating.created_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[EnvRatingRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/environmental-risk-ratings", response_model=EnvRatingRead, status_code=201, dependencies=[_WRITE])
async def create_env_rating(body: EnvRatingCreate, db: DbSession, user: CurrentUser) -> EnvRatingRead:
    obj = EnvironmentalRiskRating(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, EnvironmentalRiskRating, "ENV")
    db.add(obj)
    await db.flush()
    return EnvRatingRead.model_validate(obj)


@router.get("/environmental-risk-ratings/{rid}", response_model=EnvRatingRead, dependencies=[_READ])
async def get_env_rating(rid: uuid.UUID, db: DbSession) -> EnvRatingRead:
    return EnvRatingRead.model_validate(await _get(db, EnvironmentalRiskRating, rid, "Environmental risk rating"))


@router.patch("/environmental-risk-ratings/{rid}", response_model=EnvRatingRead, dependencies=[_WRITE])
async def update_env_rating(rid: uuid.UUID, body: EnvRatingUpdate, db: DbSession) -> EnvRatingRead:
    obj = await _get(db, EnvironmentalRiskRating, rid, "Environmental risk rating")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return EnvRatingRead.model_validate(obj)


@router.delete("/environmental-risk-ratings/{rid}", status_code=204, dependencies=[_WRITE])
async def delete_env_rating(rid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, EnvironmentalRiskRating, rid, "Environmental risk rating")
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ========================================================== ESG summary ===
class EsgSummary(BaseModel):
    total_assessments: int
    by_pillar: dict[str, int]
    by_status: dict[str, int]
    achieved: int
    achieved_pct: float
    env_ratings_total: int
    env_by_category: dict[str, int]
    high_env_risk: int


@router.get("/esg-summary", response_model=EsgSummary, dependencies=[_READ],
            summary="ESG / Green Banking roll-up for the dashboard")
async def esg_summary(db: DbSession) -> EsgSummary:
    assessments = (await db.scalars(
        select(EsgAssessment).where(EsgAssessment.deleted.is_(False)))).all()
    ratings = (await db.scalars(
        select(EnvironmentalRiskRating).where(EnvironmentalRiskRating.deleted.is_(False)))).all()

    by_pillar: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    for a in assessments:
        by_pillar[a.pillar.value] += 1
        by_status[a.status.value] += 1
    achieved = by_status.get(EsgStatus.achieved.value, 0)
    total = len(assessments)

    env_by_category: dict[str, int] = defaultdict(int)
    for r in ratings:
        env_by_category[r.risk_category.value] += 1

    return EsgSummary(
        total_assessments=total,
        by_pillar=dict(by_pillar),
        by_status=dict(by_status),
        achieved=achieved,
        achieved_pct=round(achieved / total * 100, 1) if total else 0.0,
        env_ratings_total=len(ratings),
        env_by_category=dict(env_by_category),
        high_env_risk=env_by_category.get(EnvRiskCategory.high.value, 0),
    )
