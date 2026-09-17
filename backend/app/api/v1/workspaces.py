"""Phase 4B: workspaces — the start page per line of defence, the board home, the
assurance workspace and period snapshots. See ``services/workspaces.py`` and
``services/snapshots.py``.

* ``GET  /my/workspace`` — the reader's line of defence, the workspaces they may open,
  their own start-page choice and where they land. Any signed-in user.
* ``PUT  /my/workspace`` — choose a start page (``null`` to follow the default).
* ``GET  /board/home`` — the board home (``board:read``).
* ``GET  /assurance/home`` — the assurance workspace (``internal_audit:read``).
* ``GET  /snapshots`` — the dates period snapshots exist for (``board:read``).
* ``POST /snapshots/capture`` — record today's snapshot now (``settings:manage``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.schemas.workspaces import (
    AssuranceHome,
    BoardHome,
    SnapshotCaptured,
    SnapshotDate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.services import audit, board_pack, snapshots, workspaces

router = APIRouter(tags=["workspaces"])


async def _workspace(db, user) -> WorkspaceRead:
    preference = await workspaces.load_preference(db, user.id)
    off = await workspaces.modules_off(db, ("internal_audit",))
    return WorkspaceRead(**workspaces.workspace_read(
        role_names=[r.name for r in user.roles], permissions=user.permission_codes or [],
        preference=preference, modules_off=off,
    ))


@router.get("/my/workspace", response_model=WorkspaceRead, summary="My start page and the workspaces I can open")
async def get_my_workspace(db: DbSession, user: CurrentUser) -> WorkspaceRead:
    return await _workspace(db, user)


@router.put("/my/workspace", response_model=WorkspaceRead, summary="Choose my start page")
async def set_my_workspace(body: WorkspaceUpdate, db: DbSession, user: CurrentUser) -> WorkspaceRead:
    from app.models.workspace import UserWorkspacePreference

    current = await _workspace(db, user)
    if body.workspace is not None and body.workspace not in {w.key for w in current.available}:
        raise HTTPException(status_code=422, detail="workspace: you can't open that workspace.")
    row = await db.scalar(select(UserWorkspacePreference).where(UserWorkspacePreference.user_id == user.id))
    if body.workspace is None:
        if row is not None:
            await db.delete(row)
    elif row is None:
        db.add(UserWorkspacePreference(tenant_id=user.tenant_id, user_id=user.id, workspace=body.workspace))
    else:
        row.workspace = body.workspace
    await db.flush()
    return await _workspace(db, user)


@router.get("/board/home", response_model=BoardHome, dependencies=[Depends(require("board:read"))],
            summary="The board home: appetite, top risks, assurance, KRIs, issues and committee decisions")
async def get_board_home(db: DbSession, user: CurrentUser) -> BoardHome:
    org = await board_pack.org_context(db, user.tenant_id)
    return BoardHome(**await workspaces.board_home(db, user, org))


@router.get("/assurance/home", response_model=AssuranceHome, dependencies=[Depends(require("internal_audit:read"))],
            summary="Engagements in progress, findings follow-up and the three-lines assurance map")
async def get_assurance_home(db: DbSession, user: CurrentUser) -> AssuranceHome:
    org = await board_pack.org_context(db, user.tenant_id)
    return AssuranceHome(**await workspaces.assurance_home(db, user, org))


@router.get("/snapshots", response_model=list[SnapshotDate], dependencies=[Depends(require("board:read"))],
            summary="Dates period snapshots exist for, newest first")
async def list_snapshots(db: DbSession) -> list[SnapshotDate]:
    from app.models.workspace import MetricSnapshot

    rows = (await db.execute(
        select(MetricSnapshot.as_of, func.array_agg(func.distinct(MetricSnapshot.source)),
               func.count(func.distinct(MetricSnapshot.key)))
        .group_by(MetricSnapshot.as_of).order_by(MetricSnapshot.as_of.desc()).limit(120)
    )).all()
    return [SnapshotDate(as_of=d, sources=sorted(s or []), keys=int(n)) for d, s, n in rows]


@router.post("/snapshots/capture", response_model=SnapshotCaptured, dependencies=[Depends(require("settings:manage"))],
             summary="Record today's period snapshot now")
async def capture_snapshot(db: DbSession, user: CurrentUser) -> SnapshotCaptured:
    org = await board_pack.org_context(db, user.tenant_id)
    rows = await snapshots.capture(db, user.tenant_id, org.today, source=snapshots.MANUAL, viewer=user)
    await audit.record(db, actor=user, action="snapshot", entity_type="metric_snapshot", entity_id=None,
                       summary=f"Recorded the period snapshot for {org.today.isoformat()}",
                       changes={"as_of": org.today.isoformat(), "rows": rows})
    return SnapshotCaptured(as_of=org.today, rows=rows)
