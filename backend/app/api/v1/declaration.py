"""Compliance Declarations API — periodic + event-driven staff declaration
campaigns (conflict of interest, gifts & entertainment, personal account dealing,
outside employment, related-party, code of conduct) and their submissions.

A campaign collects one **Declaration** per staff member; a submission that carries
a *disclosure* is reviewed by compliance and cleared or escalated. Amounts (e.g. the
value of a declared gift) are in PKR by default.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.declaration import (
    CampaignStatus,
    Declaration,
    DeclarationCampaign,
    DeclarationStatus,
    DeclarationType,
)
from app.schemas.common import Page
from app.schemas.declaration import (
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    DeclarationCreate,
    DeclarationRead,
    DeclarationUpdate,
)
from app.services import audit as audit_log

router = APIRouter(tags=["declarations"])

_READ = Depends(require("declaration:read"))
_WRITE = Depends(require("declaration:write"))


async def _next_ref(db, model, prefix: str) -> str:
    count = await db.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{count + 1:03d}"


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _load_campaign(db, cid) -> DeclarationCampaign:
    obj = await db.scalar(
        select(DeclarationCampaign)
        .where(DeclarationCampaign.id == cid)
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Declaration campaign not found")
    return obj


# =============================================================== campaigns ===
@router.get("/declaration-campaigns", response_model=Page[CampaignRead], dependencies=[_READ])
async def list_campaigns(
    db: DbSession,
    search: str | None = None,
    declaration_type: DeclarationType | None = None,
    status_filter: Annotated[CampaignStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CampaignRead]:
    stmt: Select = select(DeclarationCampaign).where(DeclarationCampaign.deleted.is_(False))
    if declaration_type is not None:
        stmt = stmt.where(DeclarationCampaign.declaration_type == declaration_type)
    if status_filter is not None:
        stmt = stmt.where(DeclarationCampaign.status == status_filter)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            DeclarationCampaign.title.ilike(like) | DeclarationCampaign.reference.ilike(like)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(DeclarationCampaign.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return Page(items=[CampaignRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/declaration-campaigns", response_model=CampaignRead, status_code=201, dependencies=[_WRITE])
async def create_campaign(body: CampaignCreate, db: DbSession, user: CurrentUser) -> CampaignRead:
    obj = DeclarationCampaign(tenant_id=user.tenant_id, **body.model_dump())
    obj.reference = await _next_ref(db, DeclarationCampaign, "DEC")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="declaration_campaign",
                           entity_id=obj.id, summary=f"Opened declaration campaign {obj.reference}: {obj.title}")
    return CampaignRead.model_validate(await _load_campaign(db, obj.id))


@router.get("/declaration-campaigns/{cid}", response_model=CampaignRead, dependencies=[_READ])
async def get_campaign(cid: uuid.UUID, db: DbSession) -> CampaignRead:
    return CampaignRead.model_validate(await _load_campaign(db, cid))


@router.patch("/declaration-campaigns/{cid}", response_model=CampaignRead, dependencies=[_WRITE])
async def update_campaign(cid: uuid.UUID, body: CampaignUpdate, db: DbSession) -> CampaignRead:
    obj = await _load_campaign(db, cid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return CampaignRead.model_validate(await _load_campaign(db, cid))


@router.delete("/declaration-campaigns/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_campaign(cid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_campaign(db, cid)
    obj.deleted = True
    obj.deleted_date = date.today()
    await db.flush()


# ------------------------------------------------- nested declaration lines ---
@router.post("/declaration-campaigns/{cid}/declarations", response_model=CampaignRead,
             status_code=201, dependencies=[_WRITE])
async def add_declaration(cid: uuid.UUID, body: DeclarationCreate, db: DbSession, user: CurrentUser) -> CampaignRead:
    await _load_campaign(db, cid)
    obj = Declaration(tenant_id=user.tenant_id, campaign_id=cid, **body.model_dump())
    obj.reference = await _next_ref(db, Declaration, "DCL")
    db.add(obj)
    await db.flush()
    return CampaignRead.model_validate(await _load_campaign(db, cid))


@router.patch("/declarations/{did}", response_model=DeclarationRead, dependencies=[_WRITE])
async def update_declaration(did: uuid.UUID, body: DeclarationUpdate, db: DbSession) -> DeclarationRead:
    obj = await _get(db, Declaration, did, "Declaration")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return DeclarationRead.model_validate(obj)


@router.delete("/declarations/{did}", status_code=204, dependencies=[_WRITE])
async def delete_declaration(did: uuid.UUID, db: DbSession) -> None:
    obj = await db.scalar(select(Declaration).where(Declaration.id == did))
    if obj is not None:
        await db.delete(obj)


# =============================================== standalone declarations list ===
@router.get("/declarations", response_model=Page[DeclarationRead], dependencies=[_READ])
async def list_declarations(
    db: DbSession,
    has_disclosure: bool | None = None,
    status_filter: Annotated[DeclarationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DeclarationRead]:
    stmt: Select = (
        select(Declaration)
        .join(DeclarationCampaign, Declaration.campaign_id == DeclarationCampaign.id)
        .where(DeclarationCampaign.deleted.is_(False))
    )
    if has_disclosure is not None:
        stmt = stmt.where(Declaration.has_disclosure.is_(has_disclosure))
    if status_filter is not None:
        stmt = stmt.where(Declaration.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(Declaration.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return Page(items=[DeclarationRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


# ==================================================================== summary ===
class DeclarationTypeRow(BaseModel):
    declaration_type: str
    campaigns: int
    declarations: int
    disclosures: int


class DeclarationSummary(BaseModel):
    campaigns_open: int
    declarations_submitted: int
    declarations_pending: int
    disclosures_flagged: int
    by_declaration_type: list[DeclarationTypeRow]


@router.get("/declarations-summary", response_model=DeclarationSummary, dependencies=[_READ],
            summary="Compliance declaration roll-up (open campaigns, submissions, flagged disclosures)")
async def declarations_summary(db: DbSession) -> DeclarationSummary:
    campaigns = (await db.scalars(
        select(DeclarationCampaign).where(DeclarationCampaign.deleted.is_(False))
    )).all()
    campaigns_open = submitted = pending = disclosures = 0
    groups: dict[str, dict] = defaultdict(lambda: {"campaigns": 0, "declarations": 0, "disclosures": 0})
    for c in campaigns:
        if c.status == CampaignStatus.open:
            campaigns_open += 1
        g = groups[c.declaration_type.value]
        g["campaigns"] += 1
        for d in c.declarations:
            g["declarations"] += 1
            if d.status == DeclarationStatus.pending:
                pending += 1
            else:
                submitted += 1
            if d.has_disclosure:
                disclosures += 1
                g["disclosures"] += 1
    rows = [
        DeclarationTypeRow(declaration_type=k, campaigns=v["campaigns"],
                           declarations=v["declarations"], disclosures=v["disclosures"])
        for k, v in sorted(groups.items())
    ]
    return DeclarationSummary(
        campaigns_open=campaigns_open,
        declarations_submitted=submitted,
        declarations_pending=pending,
        disclosures_flagged=disclosures,
        by_declaration_type=rows,
    )
