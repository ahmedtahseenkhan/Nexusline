"""Validate and label the people, units and lookup values a record points at.

Every phase-1 picker field (``owner_id``, ``business_unit_id``, ``category_id`` …) goes
through here, so each module checks the same three things the same way:

* the id exists in this organisation (row-level security already scopes the query);
* a lookup value belongs to the list the field draws from, and is active;
* a person is an active user.

A bad id is a 422 naming the field, never a foreign-key error at commit. Labels are
fetched in one query per kind for a whole page of records (``labels_for``), so a list
page doesn't issue one query per row.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User
from app.models.lookup import Lookup
from app.models.organization import BusinessUnit, Process
from app.schemas.common import LookupRef, UnitRef, UserRef


def _bad(field: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field}: {message}"
    )


async def check_user(db: AsyncSession, user_id: uuid.UUID | None, field: str = "owner_id") -> None:
    if user_id is None:
        return
    row = await db.get(User, user_id)
    if row is None:
        raise _bad(field, "that person is not a user in this organisation.")
    if not row.is_active:
        raise _bad(field, f"{row.full_name or row.email} is deactivated; pick an active user.")


async def check_lookup(
    db: AsyncSession, lookup_id: uuid.UUID | None, key: str, field: str = "category_id"
) -> None:
    if lookup_id is None:
        return
    row = await db.get(Lookup, lookup_id)
    if row is None or row.key != key:
        raise _bad(field, f"pick a value from the {key.replace('_', ' ')} list.")
    if not row.active:
        raise _bad(field, f"'{row.label}' is no longer in use; pick another value.")


async def check_unit(db: AsyncSession, unit_id: uuid.UUID | None, field: str = "business_unit_id") -> None:
    if unit_id is None:
        return
    row = await db.get(BusinessUnit, unit_id)
    if row is None or row.deleted:
        raise _bad(field, "that business unit does not exist.")


async def check_process(db: AsyncSession, process_id: uuid.UUID | None, field: str = "process_id") -> None:
    if process_id is None:
        return
    row = await db.get(Process, process_id)
    if row is None or row.deleted:
        raise _bad(field, "that process does not exist.")


async def users_by_id(db: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, UserRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await db.scalars(select(User).where(User.id.in_(wanted)))).all()
    return {u.id: UserRef.model_validate(u) for u in rows}


async def lookups_by_id(db: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, LookupRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await db.scalars(select(Lookup).where(Lookup.id.in_(wanted)))).all()
    return {r.id: LookupRef.model_validate(r) for r in rows}


async def units_by_id(db: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, UnitRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await db.scalars(select(BusinessUnit).where(BusinessUnit.id.in_(wanted)))).all()
    return {r.id: UnitRef.model_validate(r) for r in rows}


async def processes_by_id(db: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, UnitRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await db.scalars(select(Process).where(Process.id.in_(wanted)))).all()
    return {r.id: UnitRef.model_validate(r) for r in rows}


async def labels_for(db: AsyncSession, records: list, spec: dict[str, str]) -> dict[str, dict]:
    """Resolve labels for a page of records in one query per kind.

    ``spec`` maps an id attribute to its kind — ``{"owner_id": "user", "category_id":
    "lookup", "business_unit_id": "unit", "process_id": "process"}``. Returns
    ``{attr: {id: Ref}}`` for the caller to attach as ``owner``, ``category`` ….
    """
    fetch = {"user": users_by_id, "lookup": lookups_by_id, "unit": units_by_id, "process": processes_by_id}
    out: dict[str, dict] = {}
    by_kind: dict[str, set] = {}
    for attr, kind in spec.items():
        by_kind.setdefault(kind, set()).update(getattr(r, attr, None) for r in records)
    resolved = {kind: await fetch[kind](db, ids) for kind, ids in by_kind.items()}
    for attr, kind in spec.items():
        out[attr] = resolved[kind]
    return out
