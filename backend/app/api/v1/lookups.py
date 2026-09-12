"""Governed lookup lists API — ``/lookups``.

The lists themselves are fixed in code (``app.models.lookup.LOOKUP_LISTS``); their
values belong to each organisation. Reads need only a signed-in user (every form that
shows a category picker reads them); writes need ``org:write`` and are audited.

* ``GET    /lookups`` — every list with its value counts.
* ``GET    /lookups/{key}`` — the list's values, parents followed by their children,
  each ordered by ``sort_order`` then label. Query: ``active=true|false|all`` (default
  ``true``, what pickers want), ``search=`` (label, value or parent label, case-
  insensitive), ``usage=true`` to count the records using each value.
* ``GET    /lookups/{key}/{id}`` — one value (active or not), e.g. to label a saved id.
* ``POST   /lookups/{key}`` — add a value. ``value`` is derived from the label when
  omitted; a clash on value (or on label under the same parent) is a 409. A parent must
  be a top-level value of the same list (lists are at most two levels deep).
* ``PATCH  /lookups/{key}/{id}`` — rename, describe, reorder, deactivate (``active:
  false``) or re-parent. ``value`` never changes.
* ``PUT    /lookups/{key}/order`` — set ``sort_order`` from an ordered list of ids.
* ``DELETE /lookups/{key}/{id}`` — hard delete, refused with 409 while any record
  points at the value ("In use by N records; deactivate it instead.") or while it has
  child values. The referencing columns are discovered from the ORM metadata (every
  foreign key to ``lookups.id``), so a module that adds a lookup-backed field is covered
  without touching this file.

Unknown ``key`` → 404 everywhere.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import MetaData, func, select

from app.core.database import Base
from app.core.deps import CurrentUser, DbSession, require
from app.db.fk_backfill import norm, slug
from app.db.lookup_seed import BUILTIN_VALUES
from app.models.lookup import LOOKUP_LISTS, Lookup
from app.schemas.lookup import (
    LookupCreate,
    LookupListRead,
    LookupOrder,
    LookupRead,
    LookupUpdate,
)
from app.services import audit

router = APIRouter(prefix="/lookups", tags=["lookups"])

#: Separator between a parent's and a child's label in pickers and paths.
PATH_SEP = " › "

LOOKUP_WRITE = "org:write"


# ------------------------------------------------------------------ pure helpers ---
def list_name(key: str) -> str:
    """The list's display name, or 404 for a key that is not a governed list."""
    spec = LOOKUP_LISTS.get(key)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No lookup list called '{key}'")
    return spec[0]


def normalise_value(text: str) -> str:
    """Machine key for a value: lower-case, ``[a-z0-9_]`` (the same slug as fk_backfill)."""
    return slug(text)


def derive_value(
    label: str, given: str | None, taken: set[str], parent_value: str | None = None
) -> tuple[str, str | None]:
    """Pick the stored ``value`` for a new row; returns ``(value, error)``.

    An explicit ``given`` value is normalised and must be free. A derived one is the
    label's slug; for a child whose slug is taken (a second "Other"), the parent's value
    is prefixed ("credit_other") before giving up.
    """
    if given is not None and given.strip():
        value = normalise_value(given)
        return value, (f"The value '{value}' is already used in this list." if value in taken else None)
    base = normalise_value(label)
    if base not in taken:
        return base, None
    if parent_value:
        prefixed = normalise_value(f"{parent_value}_{base}")
        if prefixed not in taken:
            return prefixed, None
    return base, f"'{label.strip()}' is already in this list."


def parent_error(key: str, row_id: uuid.UUID | None, parent: Any, row_has_children: bool) -> str | None:
    """Why ``parent`` cannot be this row's parent, or ``None`` if it can.

    Lists are at most two levels deep, so a parent must be a top-level value of the same
    list, not the row itself, and a row that already has children cannot become a child.
    """
    if parent is None:
        return "The parent value does not exist."
    if parent.key != key:
        return "The parent must be a value from the same list."
    if row_id is not None and parent.id == row_id:
        return "A value cannot be its own parent."
    if parent.parent_id is not None:
        return "Lists are two levels deep: pick a top-level value as the parent."
    if row_has_children:
        return "This value has child values of its own, so it cannot be placed under another."
    return None


def referencing_columns(metadata: MetaData | None = None) -> list[tuple[str, str]]:
    """Every ``(table, column)`` with a foreign key to ``lookups.id``, other than the
    list's own ``parent_id``. Sorted, so the in-use message is stable."""
    if metadata is None:
        import app.models  # noqa: F401 - registers every mapper on Base.metadata

        metadata = Base.metadata
    out: list[tuple[str, str]] = []
    for table in metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name == "lookups" and fk.column.name == "id":
                if table.name == "lookups":
                    continue
                out.append((table.name, fk.parent.name))
    return sorted(set(out))


@dataclass
class LookupView:
    row: Any
    depth: int
    path: str
    parent_label: str


def order_rows(rows: list[Any]) -> list[LookupView]:
    """Parents in ``(sort_order, label)`` order, each followed by its children.

    A child whose parent is not among ``rows`` is shown at the top level.
    """
    def key_of(r: Any) -> tuple[int, str]:
        return (r.sort_order or 0, (r.label or "").lower())

    ids = {r.id for r in rows}
    children: dict[Any, list[Any]] = {}
    roots: list[Any] = []
    for r in rows:
        if r.parent_id is not None and r.parent_id in ids and r.parent_id != r.id:
            children.setdefault(r.parent_id, []).append(r)
        else:
            roots.append(r)
    out: list[LookupView] = []
    for root in sorted(roots, key=key_of):
        out.append(LookupView(root, 0, root.label, ""))
        for child in sorted(children.get(root.id, []), key=key_of):
            out.append(LookupView(child, 1, f"{root.label}{PATH_SEP}{child.label}", root.label))
    return out


def filter_views(views: list[LookupView], active: str = "true", search: str | None = None) -> list[LookupView]:
    """Apply ``active`` (``true``/``false``/``all``) and a case-insensitive search over
    label, value and path (so searching a parent also finds its children)."""
    q = norm(search)
    out = []
    for v in views:
        if active == "true" and not v.row.active:
            continue
        if active == "false" and v.row.active:
            continue
        if q and q not in norm(v.path) and q not in norm(v.row.value) and q not in norm(v.row.label):
            continue
        out.append(v)
    return out


def to_read(view: LookupView, usage: dict[Any, int] | None = None) -> LookupRead:
    r = view.row
    return LookupRead(
        id=r.id,
        key=r.key,
        value=r.value,
        label=r.label,
        description=r.description or "",
        sort_order=r.sort_order or 0,
        active=bool(r.active),
        parent_id=r.parent_id,
        parent_label=view.parent_label,
        path=view.path,
        depth=view.depth,
        builtin=(r.key, r.value) in BUILTIN_VALUES,
        usage=None if usage is None else usage.get(r.id, 0),
    )


# ---------------------------------------------------------------- db helpers ---
async def usage_counts(db, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many records point at each of ``ids``, across every lookup-backed column."""
    if not ids:
        return {}
    totals: dict[uuid.UUID, int] = {}
    for table_name, col_name in referencing_columns():
        table = Base.metadata.tables[table_name]
        col = table.c[col_name]
        rows = (await db.execute(select(col, func.count()).where(col.in_(ids)).group_by(col))).all()
        for target, n in rows:
            totals[target] = totals.get(target, 0) + int(n)
    return totals


async def _rows(db, key: str) -> list[Lookup]:
    return list((await db.scalars(select(Lookup).where(Lookup.key == key))).all())


async def _get(db, key: str, lookup_id: uuid.UUID) -> Lookup:
    row = await db.scalar(
        select(Lookup).where(Lookup.id == lookup_id).execution_options(populate_existing=True)
    )
    if row is None or row.key != key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lookup value not found")
    return row


def _view_of(row: Lookup, rows: list[Lookup]) -> LookupView:
    for v in order_rows(rows):
        if v.row.id == row.id:
            return v
    return LookupView(row, 0, row.label, "")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _label_clash(rows: list[Lookup], label: str, parent_id: uuid.UUID | None, exclude: uuid.UUID | None = None) -> bool:
    wanted = norm(label)
    return any(
        norm(r.label) == wanted and r.parent_id == parent_id and r.id != exclude for r in rows
    )


async def _audit(db, user, action: str, row: Lookup, summary: str, changes: dict | None = None) -> None:
    await audit.record(
        db, actor=user, action=action, entity_type="lookup", entity_id=row.id,
        summary=summary, changes={"key": row.key, "value": row.value, **(changes or {})},
    )


# -------------------------------------------------------------------- routes ---
@router.get("", response_model=list[LookupListRead])
async def list_lookup_lists(db: DbSession, user: CurrentUser) -> list[LookupListRead]:
    """Every governed list with how many values it has (and how many are active)."""
    counts = {
        (key, active): n
        for key, active, n in (
            await db.execute(
                select(Lookup.key, Lookup.active, func.count()).group_by(Lookup.key, Lookup.active)
            )
        ).all()
    }
    return [
        LookupListRead(
            key=key,
            name=name,
            seeded_from_text=from_text,
            total=counts.get((key, True), 0) + counts.get((key, False), 0),
            active=counts.get((key, True), 0),
        )
        for key, (name, from_text) in LOOKUP_LISTS.items()
    ]


@router.get("/{key}", response_model=list[LookupRead])
async def list_lookup_values(
    key: str,
    db: DbSession,
    user: CurrentUser,
    active: Literal["true", "false", "all"] = "true",
    search: str | None = None,
    usage: bool = False,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[LookupRead]:
    """The values of one list, parents followed by their children.

    ``active=true`` (default) is what pickers want; the admin page asks for ``all``.
    """
    list_name(key)
    views = filter_views(order_rows(await _rows(db, key)), active, search)[:limit]
    counts = await usage_counts(db, [v.row.id for v in views]) if usage else None
    return [to_read(v, counts) for v in views]


@router.get("/{key}/{lookup_id}", response_model=LookupRead)
async def read_lookup_value(key: str, lookup_id: uuid.UUID, db: DbSession, user: CurrentUser) -> LookupRead:
    """One value, active or not — for labelling an id a record already holds."""
    list_name(key)
    row = await _get(db, key, lookup_id)
    return to_read(_view_of(row, await _rows(db, key)))


@router.post(
    "/{key}", response_model=LookupRead, status_code=201, dependencies=[Depends(require(LOOKUP_WRITE))]
)
async def create_lookup_value(key: str, body: LookupCreate, db: DbSession, user: CurrentUser) -> LookupRead:
    """Add a value to a list. Requires ``org:write``; audited."""
    name = list_name(key)
    rows = await _rows(db, key)
    parent = None
    if body.parent_id is not None:
        parent = next((r for r in rows if r.id == body.parent_id), None)
        if parent is None:
            parent = await db.get(Lookup, body.parent_id)
        err = parent_error(key, None, parent, False)
        if err:
            raise HTTPException(status_code=422, detail=f"parent_id: {err}")
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="label: a label is required.")
    value, err = derive_value(label, body.value, {r.value for r in rows}, parent.value if parent else None)
    if err:
        raise _conflict(err)
    if _label_clash(rows, label, body.parent_id):
        raise _conflict(f"'{label}' is already in this list.")
    sort_order = body.sort_order
    if sort_order is None:
        siblings = [r.sort_order or 0 for r in rows if r.parent_id == body.parent_id]
        sort_order = (max(siblings) if siblings else 0) + 10
    row = Lookup(
        tenant_id=user.tenant_id, key=key, value=value, label=label,
        description=body.description or "", sort_order=sort_order, active=body.active,
        parent_id=body.parent_id,
    )
    db.add(row)
    await db.flush()
    await _audit(db, user, "create", row, f"Added '{label}' to {name}")
    rows.append(row)
    return to_read(_view_of(row, rows))


@router.put(
    "/{key}/order", response_model=list[LookupRead], dependencies=[Depends(require(LOOKUP_WRITE))]
)
async def reorder_lookup_values(key: str, body: LookupOrder, db: DbSession, user: CurrentUser) -> list[LookupRead]:
    """Set ``sort_order`` to 10, 20, 30 … in the order given. Ids not in the list are a
    422; values left out keep their current order. Requires ``org:write``; audited."""
    name = list_name(key)
    rows = await _rows(db, key)
    by_id = {r.id: r for r in rows}
    unknown = [str(i) for i in body.ids if i not in by_id]
    if unknown:
        raise HTTPException(status_code=422, detail=f"ids: not in the {name} list: {', '.join(unknown)}")
    for i, lid in enumerate(body.ids):
        by_id[lid].sort_order = (i + 1) * 10
    await db.flush()
    await audit.record(
        db, actor=user, action="reorder", entity_type="lookup", entity_id=None,
        summary=f"Reordered {name}", changes={"key": key, "ids": [str(i) for i in body.ids]},
    )
    return [to_read(v) for v in order_rows(rows)]


@router.patch(
    "/{key}/{lookup_id}", response_model=LookupRead, dependencies=[Depends(require(LOOKUP_WRITE))]
)
async def update_lookup_value(
    key: str, lookup_id: uuid.UUID, body: LookupUpdate, db: DbSession, user: CurrentUser
) -> LookupRead:
    """Rename, describe, reorder, (de)activate or re-parent a value. Requires ``org:write``;
    audited with before/after values. Deactivating keeps every record's link intact but
    drops the value from pickers."""
    name = list_name(key)
    row = await _get(db, key, lookup_id)
    rows = await _rows(db, key)
    data = body.model_dump(exclude_unset=True)

    if "label" in data:
        if data["label"] is None or not data["label"].strip():
            raise HTTPException(status_code=422, detail="label: a label is required.")
        data["label"] = data["label"].strip()
    if "parent_id" in data and data["parent_id"] != row.parent_id:
        if data["parent_id"] is not None:
            parent = next((r for r in rows if r.id == data["parent_id"]), None)
            if parent is None:
                parent = await db.get(Lookup, data["parent_id"])
            has_children = any(r.parent_id == row.id for r in rows)
            err = parent_error(key, row.id, parent, has_children)
            if err:
                raise HTTPException(status_code=422, detail=f"parent_id: {err}")
    for field in ("active", "sort_order", "description"):
        if field in data and data[field] is None:
            del data[field]

    new_label = data.get("label", row.label)
    new_parent = data.get("parent_id", row.parent_id)
    if ("label" in data or "parent_id" in data) and _label_clash(rows, new_label, new_parent, exclude=row.id):
        raise _conflict(f"'{new_label}' is already in this list.")

    changes = {
        f: {"from": getattr(row, f), "to": v}
        for f, v in data.items()
        if getattr(row, f) != v
    }
    if changes:
        for f, change in changes.items():
            setattr(row, f, change["to"])
        await db.flush()
        verb = "Deactivated" if changes.get("active", {}).get("to") is False else (
            "Reactivated" if changes.get("active", {}).get("to") is True else "Updated"
        )
        await _audit(
            db, user, "update", row, f"{verb} '{row.label}' in {name}",
            {k: {"from": str(v["from"]) if isinstance(v["from"], uuid.UUID) else v["from"],
                 "to": str(v["to"]) if isinstance(v["to"], uuid.UUID) else v["to"]}
             for k, v in changes.items()},
        )
    return to_read(_view_of(row, rows))


@router.delete(
    "/{key}/{lookup_id}", status_code=204, dependencies=[Depends(require(LOOKUP_WRITE))]
)
async def delete_lookup_value(key: str, lookup_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Delete a value nobody uses. 409 while records point at it or it has children.
    Requires ``org:write``; audited."""
    name = list_name(key)
    row = await _get(db, key, lookup_id)
    used = (await usage_counts(db, [row.id])).get(row.id, 0)
    if used:
        raise _conflict(
            f"In use by {used} record{'s' if used != 1 else ''}; deactivate it instead."
        )
    kids = await db.scalar(select(func.count()).select_from(Lookup).where(Lookup.parent_id == row.id))
    if kids:
        raise _conflict(
            f"Has {kids} child value{'s' if kids != 1 else ''}; delete or move them first."
        )
    await _audit(db, user, "delete", row, f"Deleted '{row.label}' from {name}")
    await db.delete(row)
    await db.flush()
