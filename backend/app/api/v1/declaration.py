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
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
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
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["declarations"])

_READ = Depends(require("declaration:read"))
_WRITE = Depends(require("declaration:write"))


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _load_campaign(db, cid) -> DeclarationCampaign:
    obj = await db.scalar(
        select(DeclarationCampaign)
        .where(DeclarationCampaign.id == cid, DeclarationCampaign.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Declaration campaign not found")
    return obj


# =============================================================== campaigns ===
_CAMPAIGN_SORTABLE = {
    "reference": DeclarationCampaign.reference,
    "title": DeclarationCampaign.title,
    "declaration_type": DeclarationCampaign.declaration_type,
    "period": DeclarationCampaign.period,
    "owner": DeclarationCampaign.owner,
    "status": DeclarationCampaign.status,
    "due_date": DeclarationCampaign.due_date,
    "created_at": DeclarationCampaign.created_at,
}


@router.get("/declaration-campaigns", response_model=Page[CampaignRead], dependencies=[_READ])
async def list_campaigns(
    db: DbSession,
    search: str | None = None,
    declaration_type: DeclarationType | None = None,
    status_filter: Annotated[CampaignStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
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
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _CAMPAIGN_SORTABLE, default=DeclarationCampaign.created_at)
    else:
        stmt = stmt.order_by(DeclarationCampaign.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
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


def _plain(value):
    return getattr(value, "value", value)


def _changes(obj, data: dict) -> dict:
    """``{field: {"from", "to"}}`` for the fields ``data`` actually changes."""
    out = {}
    for k, v in data.items():
        before = getattr(obj, k)
        if before is not None and v is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
            same = float(before) == float(v)
        else:
            same = before == v
        if not same:
            out[k] = {"from": _plain(before), "to": _plain(v)}
    return out


@router.patch("/declaration-campaigns/{cid}", response_model=CampaignRead, dependencies=[_WRITE])
async def update_campaign(cid: uuid.UUID, body: CampaignUpdate, db: DbSession, user: CurrentUser) -> CampaignRead:
    obj = await _load_campaign(db, cid)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "due_date"}
    changes = _changes(obj, data)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if changes:
        status_change = changes.get("status")
        verb = ({"closed": "Closed", "open": "Opened"}.get(status_change["to"], "Updated")
                if status_change else "Updated")
        await audit_log.record(
            db, actor=user, action="update", entity_type="declaration_campaign", entity_id=obj.id,
            summary=f"{verb} declaration campaign {obj.reference}: {', '.join(changes)}"[:500], changes=changes,
        )
    return CampaignRead.model_validate(await _load_campaign(db, cid))


@router.delete("/declaration-campaigns/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_campaign(cid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_campaign(db, cid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="delete", entity_type="declaration_campaign", entity_id=obj.id,
        summary=f"Archived declaration campaign {obj.reference}: {obj.title} "
                f"({len(obj.declarations)} declaration(s))"[:500],
    )


def declaration_edit_refusal(campaign) -> str | None:
    """Why a declaration in ``campaign`` may not be added, changed or removed, or None.
    A closed campaign is the record of what staff declared for that period (and what
    compliance concluded); an archived one is out of the register. Reopen the campaign
    — itself on the trail — to correct it."""
    if campaign is None or getattr(campaign, "deleted", False):
        return "This declaration's campaign has been archived; restore the campaign before changing its declarations."
    if campaign.status == CampaignStatus.closed:
        return "The campaign is closed; reopen it before changing its declarations."
    return None


async def _editable_declaration(db, did) -> Declaration:
    obj = await db.scalar(select(Declaration).where(Declaration.id == did))
    if obj is None:
        raise HTTPException(status_code=404, detail="Declaration not found")
    campaign = await db.scalar(select(DeclarationCampaign).where(DeclarationCampaign.id == obj.campaign_id))
    refusal = declaration_edit_refusal(campaign)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    return obj


# ------------------------------------------------- nested declaration lines ---
@router.post("/declaration-campaigns/{cid}/declarations", response_model=CampaignRead,
             status_code=201, dependencies=[_WRITE])
async def add_declaration(cid: uuid.UUID, body: DeclarationCreate, db: DbSession, user: CurrentUser) -> CampaignRead:
    campaign = await _load_campaign(db, cid)
    refusal = declaration_edit_refusal(campaign)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    data = body.model_dump()
    _stamp_submitted(data, None)
    obj = Declaration(tenant_id=user.tenant_id, campaign_id=cid, **data)
    obj.reference = await _next_ref(db, Declaration, "DCL")
    db.add(obj)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="declaration", entity_id=obj.id,
        summary=(f"Recorded declaration {obj.reference} by {obj.declarant_name or 'unnamed declarant'} "
                 f"in campaign {campaign.reference}"
                 + (" (with a disclosure)" if obj.has_disclosure else ""))[:500],
    )
    return CampaignRead.model_validate(await _load_campaign(db, cid))


def _stamp_submitted(data: dict, obj) -> None:
    """A declaration that leaves "pending" was submitted on some day: today, unless the
    request (or the record) already says when."""
    status_value = data.get("status")
    if status_value is None or DeclarationStatus(status_value) == DeclarationStatus.pending:
        return
    if data.get("submitted_date") is None and (obj is None or obj.submitted_date is None):
        data["submitted_date"] = date.today()


@router.patch("/declarations/{did}", response_model=DeclarationRead, dependencies=[_WRITE])
async def update_declaration(did: uuid.UUID, body: DeclarationUpdate, db: DbSession, user: CurrentUser) -> DeclarationRead:
    obj = await _editable_declaration(db, did)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items()
            if v is not None or k in ("amount", "submitted_date")}
    _stamp_submitted(data, obj)
    changes = _changes(obj, data)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if changes:
        # A compliance officer clearing or escalating a disclosure is the decision an
        # examiner samples: who, when, from what to what.
        status_change = changes.get("status")
        verb = f"Marked {status_change['to']}" if status_change else "Updated"
        await audit_log.record(
            db, actor=user, action="update", entity_type="declaration", entity_id=obj.id,
            summary=f"{verb} declaration {obj.reference} ({obj.declarant_name or 'unnamed'}): {', '.join(changes)}"[:500],
            changes=changes,
        )
    return DeclarationRead.model_validate(obj)


@router.delete("/declarations/{did}", status_code=204, dependencies=[_WRITE])
async def delete_declaration(did: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _editable_declaration(db, did)
    label = f"{obj.reference} ({obj.declarant_name or 'unnamed'}, {_plain(obj.status)})"
    await db.delete(obj)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="delete", entity_type="declaration", entity_id=did,
        summary=f"Deleted declaration {label}"[:500],
        changes={"campaign_id": str(obj.campaign_id), "has_disclosure": obj.has_disclosure},
    )


# =============================================== standalone declarations list ===
_DECLARATION_SORTABLE = {
    "reference": Declaration.reference,
    "declarant_name": Declaration.declarant_name,
    "declarant_role": Declaration.declarant_role,
    "business_unit": Declaration.business_unit,
    "status": Declaration.status,
    "submitted_date": Declaration.submitted_date,
    "created_at": Declaration.created_at,
}


@router.get("/declarations", response_model=Page[DeclarationRead], dependencies=[_READ])
async def list_declarations(
    db: DbSession,
    has_disclosure: bool | None = None,
    status_filter: Annotated[DeclarationStatus | None, Query(alias="status")] = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DeclarationRead]:
    stmt: Select = (
        select(Declaration, DeclarationCampaign.reference, DeclarationCampaign.title)
        .join(DeclarationCampaign, Declaration.campaign_id == DeclarationCampaign.id)
        .where(DeclarationCampaign.deleted.is_(False))
    )
    if has_disclosure is not None:
        stmt = stmt.where(Declaration.has_disclosure.is_(has_disclosure))
    if status_filter is not None:
        stmt = stmt.where(Declaration.status == status_filter)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            Declaration.declarant_name.ilike(like) | Declaration.reference.ilike(like)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.with_only_columns(Declaration.id).subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _DECLARATION_SORTABLE, default=Declaration.created_at)
    else:
        stmt = stmt.order_by(Declaration.created_at.desc())
    items = []
    for decl, campaign_ref, campaign_title in (await db.execute(stmt.limit(limit).offset(offset))).all():
        row = DeclarationRead.model_validate(decl)
        row.campaign_reference, row.campaign_title = campaign_ref or "", campaign_title or ""
        items.append(row)
    return Page(items=items, total=total, limit=limit, offset=offset)


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
