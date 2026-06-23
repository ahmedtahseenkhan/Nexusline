"""Generic CSV import / export engine (JSON in, JSON out).

One set of endpoints serves every resource declared in
``app.services.import_registry.REGISTRY``. The frontend never deals with
multipart: CSV text is carried inside JSON. Importing reuses each module's own
``create_func(body, db, user)`` so all business rules (reference generation,
association writes, audit logging) run exactly as they do for a normal POST.

Endpoints (prefix ``/io``):
* ``GET  /io/resources``            menu of registered resources
* ``GET  /io/{resource}/schema``    column metadata for building an import UI
* ``GET  /io/{resource}/template``  header row + one example data row
* ``GET  /io/{resource}/export``    all non-deleted tenant rows as CSV
* ``POST /io/{resource}/import``    ingest CSV text, row-isolated
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.services import csv_io
from app.services.import_registry import REGISTRY, Column, LinkSpec, ResourceIO

router = APIRouter(prefix="/io", tags=["data-io"])


# ---------------------------------------------------------------------------
# Request / response payloads
# ---------------------------------------------------------------------------
class ImportRequest(BaseModel):
    content: str


class ImportError(BaseModel):
    row: int
    message: str


class ImportResult(BaseModel):
    total: int
    created: int
    skipped: int
    errors: list[ImportError]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_resource(resource: str) -> ResourceIO:
    res = REGISTRY.get(resource)
    if res is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown resource '{resource}'")
    return res


def _require_perm(user: CurrentUser, perm: str) -> None:
    """Enforce a single permission the same way ``deps.require`` does."""
    if perm not in set(user.permission_codes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires permission(s): {perm}",
        )


def _column_payload(col: Column) -> dict:
    return {
        "header": col.header,
        "field": col.field,
        "required": col.required,
        "kind": col.kind,
        "enum_values": col.enum_values,
        "help": col.help,
        "link": (
            {
                "target": col.link.target_model.__name__,
                "match_field": col.link.match_field,
                "multi": col.link.multi,
            }
            if col.link
            else None
        ),
    }


def _ref_label(obj: object, match_field: str) -> str:
    """Render a linked object as a human reference for export.

    Prefer the object's ``reference`` (when present and non-empty), else fall
    back to the configured ``match_field`` (``name``/``title``).
    """
    ref = getattr(obj, "reference", "") or ""
    if ref:
        return str(ref)
    value = getattr(obj, match_field, None)
    if value:
        return str(value)
    # last-resort fallbacks so an export cell is never silently blank
    for attr in ("name", "title"):
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return str(getattr(obj, "id", ""))


async def _build_ref_index(db: DbSession, link: LinkSpec) -> dict[str, object]:
    """Preload one ``reference/name/title`` -> id map for a link target.

    Built once per import (per distinct target) to avoid per-row queries. Keys
    are lower-cased and stripped for case-insensitive matching; both the
    ``reference`` (if the model has one) and the ``match_field`` are indexed.
    """
    model = link.target_model
    stmt = select(model)
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    rows = (await db.scalars(stmt)).all()

    index: dict[str, object] = {}
    has_reference = hasattr(model, "reference")
    for obj in rows:
        obj_id = getattr(obj, "id")
        if has_reference:
            ref = getattr(obj, "reference", "") or ""
            if ref:
                index.setdefault(ref.strip().lower(), obj_id)
        label = getattr(obj, link.match_field, None)
        if label:
            index.setdefault(str(label).strip().lower(), obj_id)
    return index


def _split_tokens(raw: str) -> list[str]:
    """Split a multi-link cell on commas/semicolons; trim and drop blanks."""
    parts: list[str] = []
    for chunk in raw.replace(";", ",").split(","):
        token = chunk.strip()
        if token:
            parts.append(token)
    return parts


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/resources")
async def list_resources(user: CurrentUser) -> list[dict]:
    """Menu of every registered resource (drives the import/export UI).

    Only requires authentication; per-resource access is enforced on the
    resource-specific endpoints.
    """
    return [
        {
            "resource": res.resource,
            "label": res.label,
            "importable": res.importable,
            "write_perm": res.write_perm,
            "read_perm": res.read_perm,
        }
        for res in REGISTRY.values()
    ]


@router.get("/{resource}/schema")
async def get_schema(resource: str, user: CurrentUser) -> dict:
    res = _get_resource(resource)
    _require_perm(user, res.read_perm)
    return {
        "resource": res.resource,
        "label": res.label,
        "importable": res.importable,
        "columns": [_column_payload(c) for c in res.columns],
    }


@router.get("/{resource}/template")
async def get_template(resource: str, user: CurrentUser) -> dict:
    res = _get_resource(resource)
    _require_perm(user, res.read_perm)
    return {
        "filename": f"{res.resource}_template.csv",
        "csv": csv_io.make_template(res.columns),
    }


@router.get("/{resource}/export")
async def export_resource(resource: str, db: DbSession, user: CurrentUser) -> dict:
    res = _get_resource(resource)
    _require_perm(user, res.read_perm)

    model = res.model
    stmt = select(model)
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    # Eager-load every exportable link relationship so rendering avoids lazy IO.
    options = []
    for col in res.columns:
        link = col.link
        if link is not None and link.exportable and _is_relationship(model, link.export_attr):
            options.append(selectinload(getattr(model, link.export_attr)))
    if options:
        stmt = stmt.options(*options)

    records = (await db.scalars(stmt)).all()

    headers = [c.header for c in res.columns]
    rows: list[dict] = []
    for obj in records:
        row: dict[str, object] = {}
        for col in res.columns:
            if col.link is not None:
                row[col.header] = _export_link(obj, col.link)
            else:
                row[col.header] = getattr(obj, col.field, None)
        rows.append(row)

    return {
        "filename": f"{res.resource}_export.csv",
        "csv": csv_io.export_csv(rows, headers),
    }


def _is_relationship(model: type, attr: str) -> bool:
    """True if ``attr`` is a genuine ORM relationship on ``model`` (loadable)."""
    try:
        return attr in model.__mapper__.relationships  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - defensive; treat as non-loadable
        return False


def _export_link(obj: object, link: LinkSpec) -> str:
    """Render a record's linked object(s) as a CSV cell.

    Import-only links (``exportable=False``) have no model relationship to read,
    so the cell is left blank; the header is still emitted for round-trip symmetry.
    """
    if not link.exportable:
        return ""
    related = getattr(obj, link.export_attr, None)
    if related is None:
        return ""
    if link.multi:
        return ", ".join(_ref_label(item, link.match_field) for item in related)
    return _ref_label(related, link.match_field)


@router.post("/{resource}/import")
async def import_resource(
    resource: str, body: ImportRequest, db: DbSession, user: CurrentUser
) -> ImportResult:
    res = _get_resource(resource)
    _require_perm(user, res.write_perm)
    if not res.importable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Resource '{res.resource}' is export-only and cannot be imported",
        )

    header_by_field = {c.header: c for c in res.columns}

    # Preload one reference index per distinct link target (avoids per-row queries).
    link_indexes: dict[str, dict[str, object]] = {}
    for col in res.columns:
        if col.link is not None:
            key = col.link.target_model.__name__
            if key not in link_indexes:
                link_indexes[key] = await _build_ref_index(db, col.link)

    reader = csv.DictReader(io.StringIO(body.content))
    errors: list[ImportError] = []
    total = 0
    created = 0

    # Data rows start at line 2 (header is line 1).
    for row_no, raw_row in enumerate(reader, start=2):
        total += 1
        try:
            payload = _row_to_payload(raw_row, header_by_field, link_indexes)
            obj = res.create_schema(**payload)
            async with db.begin_nested():
                await res.create_func(body=obj, db=db, user=user)
            created += 1
        except Exception as exc:  # noqa: BLE001 - row isolation: report & continue
            errors.append(ImportError(row=row_no, message=_clean_message(exc)))

    await db.flush()
    return ImportResult(
        total=total, created=created, skipped=total - created, errors=errors
    )


def _row_to_payload(
    raw_row: dict[str, str | None],
    header_by_field: dict[str, Column],
    link_indexes: dict[str, dict[str, object]],
) -> dict:
    """Map a CSV row dict to a Create-schema kwargs dict (typed & link-resolved)."""
    payload: dict[str, object] = {}
    for header, raw_value in raw_row.items():
        if header is None:
            continue
        col = header_by_field.get(header.strip()) if isinstance(header, str) else None
        if col is None:
            continue  # ignore unknown/extra columns

        if col.link is not None:
            resolved = _resolve_link(raw_value, col, link_indexes)
            if resolved is not None:
                payload[col.field] = resolved
            continue

        value = csv_io.coerce(raw_value if raw_value is not None else "", col.kind, col.enum_values)
        if value is not None:
            payload[col.field] = value
    return payload


def _resolve_link(
    raw_value: str | None, col: Column, link_indexes: dict[str, dict[str, object]]
):
    """Resolve a link cell to id(s); raise ValueError naming any unknown token."""
    text = (raw_value or "").strip()
    if text == "":
        return None
    link = col.link
    assert link is not None
    index = link_indexes[link.target_model.__name__]

    def lookup(token: str):
        obj_id = index.get(token.strip().lower())
        if obj_id is None:
            raise ValueError(
                f"{col.header}: no {link.target_model.__name__} matching '{token.strip()}'"
            )
        return obj_id

    if link.multi:
        return [lookup(tok) for tok in _split_tokens(text)]
    return lookup(text)


def _clean_message(exc: Exception) -> str:
    """Reduce an exception to one concise line (no tracebacks)."""
    msg = str(exc).strip()
    if not msg:
        msg = exc.__class__.__name__
    # Pydantic ValidationError renders multi-line; keep it terse.
    first = " ".join(msg.splitlines())
    return first[:500]
