"""Write and read the phase-1 picker fields beside the free text they replace.

Each module declares its picker fields once as :class:`RefField` — ``owner_id`` beside
``owner``, ``business_unit_id`` beside ``business_unit`` … — and that one declaration
drives the write path, the read path and CSV import:

**Write** (:func:`apply_refs`). An id is checked with ``services.master_data`` (a bad id
is a 422 naming the field) and its display text — the user's full name or email, the
lookup label, the unit or process name — is written into the legacy string column too,
so PDFs, exports, search, status rules and notifications that read the text keep
working this release. The id wins when a request sends both. A request that sends only
new text (an older client, or a CSV import) has the text matched the way the boot
backfill (``app.db.fk_backfill``) matches it: exactly, ignoring case and extra spaces,
against a user's email or full name, a unit or process name, or a lookup value or label
in the field's own list. Text that matches nothing — or matches more than one record,
or only a deactivated one — is kept as it was typed: nothing typed is lost.

**Read** (:func:`fill_refs`). Each ``<name>_id`` is resolved to a ``<name>_ref``
(``UserRef`` / ``LookupRef`` / ``UnitRef``) for a whole page in one query per kind.

**Import warnings** (:func:`collect_warnings`). The CSV engine opens a collector around
each row; unmatched text found while that row is written is reported back as a row
warning instead of being silently kept.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.fk_backfill import FK_LOOKUP_KEYS, norm, slug
from app.services import master_data

_KIND_NOUN = {"user": "user", "unit": "business unit", "process": "process", "lookup": "value"}


@dataclass(frozen=True)
class RefField:
    """One picker field: the new id column and the legacy text column it replaces.

    ``text_field`` is None for an id with no text twin (a vendor's ``country_id`` sits
    beside ``location``, which is a city or address and stays free text).
    ``text_input`` is False where the text is readable but no longer accepted as input
    (``workflow_owner``: requests send ``workflow_owner_id`` only).
    """

    id_field: str
    text_field: str | None
    kind: str  # user | unit | process | lookup
    lookup_key: str | None = None
    text_input: bool = True

    @property
    def ref_name(self) -> str:
        return f"{self.id_field.removesuffix('_id')}_ref"


def user(id_field: str, text_field: str | None, *, text_input: bool = True) -> RefField:
    return RefField(id_field, text_field, "user", text_input=text_input)


def unit(id_field: str, text_field: str | None) -> RefField:
    return RefField(id_field, text_field, "unit")


def process(id_field: str, text_field: str | None) -> RefField:
    return RefField(id_field, text_field, "process")


def lookup(model: type, id_field: str, text_field: str | None) -> RefField:
    """A lookup-backed field; the list comes from ``fk_backfill.FK_LOOKUP_KEYS`` so the
    write path and the boot backfill can never disagree about it."""
    return RefField(id_field, text_field, "lookup", FK_LOOKUP_KEYS[(model.__tablename__, id_field)])


#: Every WorkflowMixin record's approval owner — picked, never typed.
WORKFLOW_OWNER = user("workflow_owner_id", "workflow_owner", text_input=False)


# ==================================================================== pure rules ===
def pick(
    data: dict[str, Any], f: RefField, *, stored_id: uuid.UUID | None = None, stored_text: str = ""
) -> tuple[str, Any]:
    """Decide how one picker field is written from a request payload.

    Returns ``(decision, value)``:

    * ``("id", id)`` — a new id was sent. It wins over any text sent with it.
    * ``("same", None)`` — the stored id was sent back unchanged (a form resaving every
      field). Nothing is re-checked — a record whose owner has since left can still be
      edited — and any text sent with it is ignored, since the id wins.
    * ``("clear", text)`` — the stored id was cleared (sent as null). The legacy text,
      which was only that id's display name, is emptied — unless different text was sent
      with the null, which is kept as typed.
    * ``("text", text)`` — new text was sent without an id: match it to an id.
    * ``("keep", None)`` — nothing about this field changed.

    A null id where no id is stored clears nothing — it is what a create dumps for every
    field nobody picked — so the text rule decides.
    """
    text_sent = f.text_field is not None and f.text_input and f.text_field in data
    text = (data.get(f.text_field) or "") if text_sent else None
    if f.id_field in data:
        new_id = data[f.id_field]
        if new_id is not None:
            return ("same", None) if new_id == stored_id else ("id", new_id)
        if stored_id is not None:
            if text is not None and norm(text) != norm(stored_text):
                return ("clear", text)
            return ("clear", "")
    if text is not None and norm(text) != norm(stored_text):
        return ("text", text)
    return ("keep", None)


@dataclass(frozen=True)
class Candidate:
    """A record a piece of text might name. ``strong`` keys identify it on their own
    (an email, a lookup value); ``weak`` keys may be shared (a full name, a label)."""

    id: uuid.UUID
    label: str
    strong: tuple[str, ...] = ()
    weak: tuple[str, ...] = ()
    active: bool = True


@dataclass(frozen=True)
class Resolution:
    id: uuid.UUID | None
    label: str | None = None
    warning: str | None = None


def resolve_text(text: str, candidates: Sequence[Candidate], *, field: str = "", noun: str = "record") -> Resolution:
    """Match typed text to exactly one active candidate (the import rule, no database).

    An exact strong-key match wins (a lookup value also matches in its slug form, the
    way the backfill writes new values); otherwise a single match on any key. Several
    matches, only deactivated matches, or none leave the text unresolved with a warning
    naming why, so the caller keeps it as legacy text.
    """
    key = norm(text)
    if not key:
        return Resolution(None)
    prefix = f"{field}: " if field else ""
    shown = text.strip()
    live = [c for c in candidates if c.active]
    strong = [c for c in live if key in {norm(k) for k in c.strong} or slug(text) in c.strong]
    if len(strong) == 1:
        return Resolution(strong[0].id, strong[0].label)
    hits = strong or [c for c in live if key in {norm(k) for k in (*c.strong, *c.weak)}]
    if len(hits) == 1:
        return Resolution(hits[0].id, hits[0].label)
    if len(hits) > 1:
        return Resolution(None, warning=f"{prefix}'{shown}' matches {len(hits)} {noun}s; kept as text — pick one.")
    retired = [c for c in candidates if not c.active and key in {norm(k) for k in (*c.strong, *c.weak)}]
    if retired:
        return Resolution(None, warning=f"{prefix}'{shown}' is deactivated; kept as text — pick an active {noun}.")
    return Resolution(None, warning=f"{prefix}no {noun} matches '{shown}'; kept as text.")


def fit(model: type, column: str, value: str) -> str:
    """Trim display text to the legacy column's width (a lookup label may be longer
    than an old ``String(64)`` column)."""
    length = getattr(model.__table__.c[column].type, "length", None)
    return value[:length] if length and value else value


# ==================================================================== database ===
async def _candidates(db: AsyncSession, f: RefField, text: str) -> list[Candidate]:
    from app.models.identity import User
    from app.models.lookup import Lookup
    from app.models.organization import BusinessUnit, Process

    key = norm(text)

    def same(col):
        # SQL twin of fk_backfill.norm: trim, collapse inner whitespace, lower-case.
        return func.lower(func.regexp_replace(func.trim(col), r"\s+", " ", "g")) == key

    if f.kind == "user":
        rows = (await db.scalars(select(User).where(or_(same(User.email), same(User.full_name))))).all()
        return [Candidate(u.id, u.full_name or u.email, (u.email,), (u.full_name or "",), u.is_active) for u in rows]
    if f.kind == "lookup":
        rows = (
            await db.scalars(
                select(Lookup).where(
                    Lookup.key == f.lookup_key,
                    or_(same(Lookup.value), Lookup.value == slug(text), same(Lookup.label)),
                )
            )
        ).all()
        return [Candidate(r.id, r.label, (r.value,), (r.label,), r.active) for r in rows]
    model = BusinessUnit if f.kind == "unit" else Process
    rows = (await db.scalars(select(model).where(model.deleted.is_(False), same(model.name)))).all()
    return [Candidate(r.id, r.name, (), (r.name,)) for r in rows]


async def _label_for_id(db: AsyncSession, f: RefField, value: uuid.UUID) -> str:
    from app.models.identity import User
    from app.models.lookup import Lookup
    from app.models.organization import BusinessUnit, Process

    if f.kind == "user":
        await master_data.check_user(db, value, f.id_field)
        row = await db.get(User, value)
        return row.full_name or row.email
    if f.kind == "lookup":
        await master_data.check_lookup(db, value, f.lookup_key or "", f.id_field)
        return (await db.get(Lookup, value)).label
    if f.kind == "unit":
        await master_data.check_unit(db, value, f.id_field)
        return (await db.get(BusinessUnit, value)).name
    await master_data.check_process(db, value, f.id_field)
    return (await db.get(Process, value)).name


_warnings: ContextVar[list[str] | None] = ContextVar("ref_field_warnings", default=None)


@contextmanager
def collect_warnings() -> Iterator[list[str]]:
    """Collect the unmatched-text warnings raised while one record is written."""
    token = _warnings.set([])
    try:
        yield _warnings.get()  # type: ignore[misc]
    finally:
        _warnings.reset(token)


def _warn(message: str) -> None:
    bucket = _warnings.get()
    if bucket is not None:
        bucket.append(message)


async def apply_refs(
    db: AsyncSession,
    model: type,
    data: dict[str, Any],
    fields: Sequence[RefField],
    *,
    record: Any = None,
) -> list[str]:
    """Rewrite ``data`` (a create kwargs dict or an update's set fields) in place so
    each picker field's id and legacy text agree. Returns the warnings raised."""
    raised: list[str] = []
    for f in fields:
        if f.text_field is not None and not f.text_input:
            data.pop(f.text_field, None)  # readable, not writable
        decision, value = pick(
            data, f,
            stored_id=getattr(record, f.id_field, None) if record is not None else None,
            stored_text=(getattr(record, f.text_field, "") or "") if record is not None and f.text_field else "",
        )
        if decision == "keep":
            continue
        if decision == "same":
            data.pop(f.id_field, None)
            if f.text_field:
                data.pop(f.text_field, None)
            continue
        if decision == "id":
            label = await _label_for_id(db, f, value)
            data[f.id_field] = value
            if f.text_field:
                data[f.text_field] = fit(model, f.text_field, label)
        elif decision == "clear":
            data[f.id_field] = None
            if f.text_field:
                data[f.text_field] = value
        else:  # text only
            found = resolve_text(
                value, await _candidates(db, f, value) if norm(value) else [],
                field=f.text_field or f.id_field, noun=_KIND_NOUN[f.kind],
            )
            data[f.id_field] = found.id
            data[f.text_field] = fit(model, f.text_field, found.label) if found.id else value
            if found.warning:
                raised.append(found.warning)
                _warn(found.warning)
    return raised


async def fill_refs(db: AsyncSession, pairs: Sequence[tuple[Any, Any]], fields: Sequence[RefField]) -> None:
    """Set ``<name>_ref`` on each read model from its ORM record — one query per kind
    for the whole list (``master_data.labels_for``), however many rows and children."""
    if not pairs:
        return
    spec = {f.id_field: f.kind for f in fields}
    labels = await master_data.labels_for(db, [record for record, _ in pairs], spec)
    for record, read in pairs:
        names = type(read).model_fields
        for f in fields:
            if f.ref_name in names and hasattr(record, f.id_field):
                setattr(read, f.ref_name, labels[f.id_field].get(getattr(record, f.id_field)))
