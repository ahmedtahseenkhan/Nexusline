"""Version Audit API — structured per-record change history with field diffs and
one-click restore to a prior version."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.version import RecordVersion
from app.services import audit, versioning

router = APIRouter(prefix="/versions", tags=["versions"])


class VersionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    version_no: int
    action: str
    actor_email: str
    summary: str
    created_at: datetime


class VersionDetail(VersionRow):
    snapshot: dict
    diff: dict = {}


@router.get("/record/{entity_type}/{entity_id}", response_model=list[VersionRow], dependencies=[Depends(require("audit:read"))])
async def list_versions(entity_type: str, entity_id: uuid.UUID, db: DbSession) -> list[VersionRow]:
    rows = (
        await db.scalars(
            select(RecordVersion)
            .where(RecordVersion.entity_type == entity_type, RecordVersion.entity_id == entity_id)
            .order_by(RecordVersion.version_no.desc())
        )
    ).all()
    return [VersionRow.model_validate(r) for r in rows]


@router.get("/detail/{version_id}", response_model=VersionDetail, dependencies=[Depends(require("audit:read"))])
async def get_version(version_id: uuid.UUID, db: DbSession) -> VersionDetail:
    ver = await db.scalar(select(RecordVersion).where(RecordVersion.id == version_id))
    if ver is None:
        raise HTTPException(status_code=404, detail="Version not found")
    # diff against the immediately previous version
    prev = await db.scalar(
        select(RecordVersion)
        .where(
            RecordVersion.entity_type == ver.entity_type,
            RecordVersion.entity_id == ver.entity_id,
            RecordVersion.version_no < ver.version_no,
        )
        .order_by(RecordVersion.version_no.desc())
    )
    diff = {}
    if prev:
        for k, v in ver.snapshot.items():
            old = prev.snapshot.get(k)
            if old != v:
                diff[k] = {"from": old, "to": v}
    out = VersionDetail.model_validate(ver)
    out.diff = diff
    return out


@router.post("/detail/{version_id}/restore", response_model=VersionDetail, dependencies=[Depends(require("role:write"))])
async def restore_version(version_id: uuid.UUID, db: DbSession, user: CurrentUser) -> VersionDetail:
    ver = await db.scalar(select(RecordVersion).where(RecordVersion.id == version_id))
    if ver is None:
        raise HTTPException(status_code=404, detail="Version not found")
    entity = await versioning.restore(db, ver)
    if entity is None:
        raise HTTPException(status_code=422, detail="Cannot restore this entity type")
    await audit.record(
        db, actor=user, action="restore", entity_type=ver.entity_type, entity_id=ver.entity_id,
        summary=f"Restored {ver.entity_type} to version {ver.version_no}",
    )
    return VersionDetail.model_validate(ver)
