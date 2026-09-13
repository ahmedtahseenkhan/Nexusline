"""Picker feeds — ``/pickers``: who and where a record can point at.

Every owner, assignee, business-unit and process field on every form reads these, so
they need only a signed-in user. That is the point: a risk owner field must not require
``user:read`` (the user-administration permission), and it must not leak what user
administration shows — no permissions, no login or MFA state, no auth fields.

* ``GET /pickers/users?search=&role=&limit=&offset=&ids=`` — active users as
  ``{id, full_name, email, roles: [name], is_active}``, name order, in the standard page
  envelope. ``search`` matches name or email (every word must match); ``role`` narrows to
  holders of a role (by name, case-insensitive); ``limit`` is capped at 50. ``ids=a,b``
  instead returns exactly those users *including deactivated ones* — for labelling ids a
  record already holds.
* ``GET /pickers/business-units?search=`` — the business-unit tree flattened
  depth-first (siblings by name), each with ``depth``, ``parent_id`` and ``path``
  ("Retail › Branch Ops"). ``search`` keeps the units whose path matches, so a search for
  a parent also lists its descendants.
* ``GET /pickers/processes?business_unit_id=&search=&limit=&ids=`` — processes with
  their business unit's name, optionally within one unit.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.db.fk_backfill import norm
from app.models.identity import Role, User, user_roles
from app.models.organization import BusinessUnit, Process
from app.schemas.common import Page

router = APIRouter(prefix="/pickers", tags=["pickers"])

PATH_SEP = " › "
MAX_LIMIT = 50


# ------------------------------------------------------------------- schemas ---
class UserPick(BaseModel):
    id: uuid.UUID
    full_name: str = ""
    email: str = ""
    roles: list[str] = []
    is_active: bool = True


class UnitPick(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    depth: int = 0
    path: str = ""


class ProcessPick(BaseModel):
    id: uuid.UUID
    name: str
    business_unit_id: uuid.UUID | None = None
    business_unit_name: str = ""


# -------------------------------------------------------------- pure helpers ---
def parse_ids(raw: str | None) -> list[uuid.UUID]:
    """``"a,b"`` → UUIDs; a malformed id is a 422."""
    if not raw:
        return []
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(uuid.UUID(part))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"ids: '{part}' is not a valid id") from exc
    return out


def flatten_tree(rows: list[tuple[Any, str, Any]]) -> list[UnitPick]:
    """``(id, name, parent_id)`` rows → the tree flattened depth-first.

    Siblings are ordered by name (case-insensitive). A unit whose parent is missing (or
    archived) is shown as a root; a cycle — possible only through bad data — is cut where
    it would repeat, and anything left over is appended as roots so no unit disappears.
    """
    ids = {r[0] for r in rows}
    children: dict[Any, list[tuple[Any, str, Any]]] = {}
    roots: list[tuple[Any, str, Any]] = []
    for r in rows:
        rid, _name, parent = r
        if parent is not None and parent in ids and parent != rid:
            children.setdefault(parent, []).append(r)
        else:
            roots.append(r)

    def by_name(r: tuple[Any, str, Any]) -> str:
        return (r[1] or "").lower()

    out: list[UnitPick] = []
    seen: set[Any] = set()

    def walk(node: tuple[Any, str, Any], depth: int, prefix: str, parent_id: Any) -> None:
        rid, name, _parent = node
        if rid in seen:
            return
        seen.add(rid)
        path = f"{prefix}{PATH_SEP}{name}" if prefix else name
        out.append(UnitPick(id=rid, name=name, parent_id=parent_id, depth=depth, path=path))
        for child in sorted(children.get(rid, []), key=by_name):
            walk(child, depth + 1, path, rid)

    for root in sorted(roots, key=by_name):
        walk(root, 0, "", None)
    for r in sorted((r for r in rows if r[0] not in seen), key=by_name):
        walk(r, 0, "", None)
    return out


def filter_units(units: list[UnitPick], search: str | None) -> list[UnitPick]:
    q = norm(search)
    return [u for u in units if not q or q in norm(u.path)]


def user_search_clause(search: str | None):
    """Every word of ``search`` must appear in the name or the email."""
    words = [w for w in (search or "").split() if w]
    return [or_(User.full_name.ilike(f"%{w}%"), User.email.ilike(f"%{w}%")) for w in words]


# -------------------------------------------------------------------- routes ---
async def _role_names(db, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(user_roles.c.user_id, Role.name)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(user_roles.c.user_id.in_(user_ids))
            .order_by(Role.name)
        )
    ).all()
    out: dict[uuid.UUID, list[str]] = {}
    for uid, name in rows:
        out.setdefault(uid, []).append(name)
    return out


@router.get("/users", response_model=Page[UserPick])
async def pick_users(
    db: DbSession,
    user: CurrentUser,
    search: str | None = None,
    role: str | None = None,
    ids: str | None = None,
    limit: int = Query(default=20, ge=1),
    offset: int = Query(default=0, ge=0),
) -> Page[UserPick]:
    """People a record can be assigned to. Any signed-in user; no ``user:read`` needed."""
    limit = min(limit, MAX_LIMIT)
    wanted = parse_ids(ids)
    stmt = select(User.id, User.full_name, User.email, User.is_active)
    if wanted:
        stmt = stmt.where(User.id.in_(wanted))
    else:
        stmt = stmt.where(User.is_active.is_(True), *user_search_clause(search))
        if role and role.strip():
            holders = (
                select(user_roles.c.user_id)
                .join(Role, Role.id == user_roles.c.role_id)
                .where(func.lower(Role.name) == role.strip().lower())
            )
            stmt = stmt.where(User.id.in_(holders))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.execute(
            stmt.order_by(func.lower(func.coalesce(func.nullif(User.full_name, ""), User.email)), User.email)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    roles = await _role_names(db, [r[0] for r in rows])
    items = [
        UserPick(id=uid, full_name=name or "", email=email or "", roles=roles.get(uid, []), is_active=active)
        for uid, name, email, active in rows
    ]
    return Page[UserPick](items=items, total=total, limit=limit, offset=offset)


@router.get("/business-units", response_model=list[UnitPick])
async def pick_business_units(db: DbSession, user: CurrentUser, search: str | None = None) -> list[UnitPick]:
    """The business-unit tree, flattened depth-first with depth and path. Any signed-in user."""
    rows = (
        await db.execute(
            select(BusinessUnit.id, BusinessUnit.name, BusinessUnit.parent_id).where(
                BusinessUnit.deleted.is_(False)
            )
        )
    ).all()
    return filter_units(flatten_tree([tuple(r) for r in rows]), search)


@router.get("/processes", response_model=list[ProcessPick])
async def pick_processes(
    db: DbSession,
    user: CurrentUser,
    business_unit_id: uuid.UUID | None = None,
    search: str | None = None,
    ids: str | None = None,
    limit: int = Query(default=MAX_LIMIT, ge=1),
) -> list[ProcessPick]:
    """Processes, optionally within one business unit. Any signed-in user."""
    stmt = (
        select(Process.id, Process.name, Process.business_unit_id, BusinessUnit.name)
        .outerjoin(BusinessUnit, BusinessUnit.id == Process.business_unit_id)
        .where(Process.deleted.is_(False))
    )
    wanted = parse_ids(ids)
    if wanted:
        stmt = stmt.where(Process.id.in_(wanted))
    else:
        if business_unit_id is not None:
            stmt = stmt.where(Process.business_unit_id == business_unit_id)
        for word in (search or "").split():
            stmt = stmt.where(Process.name.ilike(f"%{word}%"))
    rows = (await db.execute(stmt.order_by(func.lower(Process.name)).limit(min(limit, MAX_LIMIT)))).all()
    return [
        ProcessPick(id=pid, name=name, business_unit_id=bu_id, business_unit_name=bu_name or "")
        for pid, name, bu_id, bu_name in rows
    ]
