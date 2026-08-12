"""Generic CSV import / export engine (JSON in, JSON out).

One set of endpoints serves every resource declared in
``app.services.import_registry.REGISTRY``. The frontend never deals with
multipart: CSV text is carried inside JSON. Importing reuses each module's own
``create_func(body, db, user)`` so all business rules (reference generation,
association writes, audit logging) run exactly as they do for a normal POST.

On top of that sits the **smart import wizard**: a client uploads the spreadsheet they
already keep, we work out which of their columns feed which of our fields
(``app.services.import_mapping``), they confirm on a preview that writes nothing, and
the confirmed mapping can be saved and reused for the next upload. A request with no
``mapping`` behaves exactly as it always did, so template-based imports are unaffected.

Endpoints (prefix ``/io``):
* ``GET  /io/resources``             menu of registered resources
* ``GET  /io/{resource}/schema``     column metadata for building an import UI
* ``GET  /io/{resource}/template``   header row + one example data row
* ``GET  /io/{resource}/export``     all non-deleted tenant rows as CSV
* ``POST /io/{resource}/inspect``    read an uploaded CSV/XLSX, suggest a mapping
* ``POST /io/{resource}/preview``    dry-run a mapping over the first N rows
* ``POST /io/{resource}/import``     ingest CSV text, row-isolated
* ``GET/POST /io/{resource}/profiles`` · ``DELETE /io/profiles/{id}``  saved mappings
"""
from __future__ import annotations

import base64
import csv
import io
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.models.custom_field import CUSTOM_FIELD_MODELS, CustomField, CustomFieldValue
from app.models.import_profile import ImportProfile
from app.schemas.dataio import (
    ImportError as RowError,
)
from app.schemas.dataio import (
    ImportProfileCreate,
    ImportProfileRead,
    ImportRequest,
    ImportResult,
    InspectRequest,
    InspectResponse,
    MappingSuggestionRead,
    PreviewRequest,
    PreviewResponse,
    PreviewRow,
)
from app.services import audit as audit_log
from app.services import csv_io, import_mapping
from app.services.import_registry import REGISTRY, Column, LinkSpec, ResourceIO

router = APIRouter(prefix="/io", tags=["data-io"])


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
    model_key = import_mapping.custom_field_model_key(res.model)
    return {
        "resource": res.resource,
        "label": res.label,
        "importable": res.importable,
        # Empty when this register has no custom fields — the wizard then omits the
        # "keep this column as a custom field" option rather than offering a dead end.
        "custom_field_model": model_key if model_key in CUSTOM_FIELD_MODELS else "",
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
    # Discriminator-backed resources export only their own register's rows.
    for attr, value in res.fixed.items():
        stmt = stmt.where(getattr(model, attr) == value)
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
    _require_importable(res)

    header_by_field = {c.header: c for c in res.columns}
    mapping = _validated_mapping(res, body.mapping)
    custom_fields = await _validated_custom_fields(db, res, body.custom_field_mapping)
    link_indexes = await _link_indexes(db, res)

    reader = csv.DictReader(io.StringIO(body.content))
    errors: list[RowError] = []
    total = 0
    created = 0

    # Data rows start at line 2 (header is line 1).
    for row_no, raw_row in enumerate(reader, start=2):
        total += 1
        try:
            source_row = dict(raw_row)
            canonical = import_mapping.apply_mapping(source_row, mapping) if mapping else source_row
            payload = _row_to_payload(canonical, header_by_field, link_indexes)
            # Discriminators are the resource's identity, not per-row data: stamp them
            # last so a stray CSV column can never route rows into the wrong register.
            payload.update(res.fixed)
            obj = res.create_schema(**payload)
            # Custom-field values are written inside the row's own savepoint, so a bad
            # value rolls the record back with it rather than leaving a half-imported row.
            async with db.begin_nested():
                record = await res.create_func(body=obj, db=db, user=user)
                if custom_fields:
                    _write_custom_values(db, user, record, source_row, custom_fields)
            created += 1
        except Exception as exc:  # noqa: BLE001 - row isolation: report & continue
            errors.append(RowError(row=row_no, message=_clean_message(exc)))

    await db.flush()
    # A bulk load is the largest single write a user can make; record it as one event so
    # the trail explains a sudden burst of created records.
    await audit_log.record(
        db, actor=user, action="import", entity_type=res.resource, entity_id=None,
        summary=f"Imported {created} of {total} {res.label} row(s) from CSV",
        changes={
            "total": total,
            "created": created,
            "failed": len(errors),
            "mapped_columns": len(mapping),
            "custom_field_columns": len(custom_fields),
        },
    )
    return ImportResult(
        total=total, created=created, skipped=total - created, errors=errors
    )


# ---------------------------------------------------------------------------
# Smart import wizard — inspect / preview
# ---------------------------------------------------------------------------
@router.post("/{resource}/inspect", response_model=InspectResponse)
async def inspect_upload(
    resource: str, body: InspectRequest, user: CurrentUser
) -> InspectResponse:
    """Read an uploaded CSV or .xlsx and propose a column mapping.

    Nothing is written and no database is touched. The response carries the
    canonicalised ``csv`` (banner rows stripped, chosen sheet flattened) which the
    wizard passes to preview and import, so a workbook is parsed exactly once.
    """
    res = _get_resource(resource)
    _require_perm(user, res.write_perm)
    _require_importable(res)

    try:
        if body.file_b64:
            table = import_mapping.load_table(
                data=base64.b64decode(body.file_b64, validate=True), sheet=body.sheet
            )
        else:
            table = import_mapping.load_table(content=body.content or "")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - malformed upload, not a server fault
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not read the file: {exc}"
        ) from exc

    if not table.headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No column headings were found in the file",
        )

    suggestions, unmapped, unfilled = import_mapping.suggest_mapping(
        table.headers, res.columns, resource=res.resource
    )
    mapped_headers = {s.target for s in suggestions}
    missing_required = [c.header for c in res.columns if c.required and c.header not in mapped_headers]

    return InspectResponse(
        csv=table.csv,
        headers=table.headers,
        row_count=table.row_count,
        header_row_index=table.header_row_index,
        sheet_names=table.sheet_names,
        sheet=table.sheet,
        sample_rows=table.rows[:3],
        suggestions=[
            MappingSuggestionRead(
                source=s.source, target=s.target, field=s.field,
                confidence=s.confidence, reason=s.reason, band=s.band,
            )
            for s in suggestions
        ],
        unmapped_source_headers=unmapped,
        unfilled_target_headers=unfilled,
        missing_required=missing_required,
    )


@router.post("/{resource}/preview", response_model=PreviewResponse)
async def preview_import(
    resource: str, body: PreviewRequest, db: DbSession, user: CurrentUser
) -> PreviewResponse:
    """Dry-run a mapping over the first N rows. **Writes nothing.**

    Runs the exact same coercion, link resolution and schema validation the real import
    runs, so an error here is an error there — including the most common one, a
    reference naming a record that does not exist yet.
    """
    res = _get_resource(resource)
    _require_perm(user, res.write_perm)
    _require_importable(res)

    header_by_field = {c.header: c for c in res.columns}
    mapping = _validated_mapping(res, body.mapping)
    await _validated_custom_fields(db, res, body.custom_field_mapping)
    link_indexes = await _link_indexes(db, res)

    all_rows = list(csv.DictReader(io.StringIO(body.content)))
    rows: list[PreviewRow] = []
    valid = 0
    for offset, raw_row in enumerate(all_rows[: body.limit]):
        source_row = dict(raw_row)
        canonical = import_mapping.apply_mapping(source_row, mapping) if mapping else source_row
        values = {k: (v or "") for k, v in canonical.items() if k in header_by_field}
        error = ""
        try:
            payload = _row_to_payload(canonical, header_by_field, link_indexes)
            payload.update(res.fixed)
            res.create_schema(**payload)  # validation only — never persisted
            valid += 1
        except Exception as exc:  # noqa: BLE001 - surface, do not raise
            error = _clean_message(exc)
        rows.append(PreviewRow(row=offset + 2, values=values, error=error))

    populated = [c.header for c in res.columns if any(c.header in r.values for r in rows)]
    return PreviewResponse(
        total=len(all_rows), previewed=len(rows), valid=valid, rows=rows, columns=populated
    )


# ---------------------------------------------------------------------------
# Saved mapping profiles
# ---------------------------------------------------------------------------
@router.get("/{resource}/profiles", response_model=list[ImportProfileRead])
async def list_profiles(resource: str, db: DbSession, user: CurrentUser) -> list[ImportProfileRead]:
    res = _get_resource(resource)
    _require_perm(user, res.read_perm)
    rows = (
        await db.scalars(
            select(ImportProfile)
            .where(ImportProfile.resource == res.resource)
            .order_by(ImportProfile.name)
        )
    ).all()
    return [_profile_read(p) for p in rows]


@router.post("/{resource}/profiles", response_model=ImportProfileRead, status_code=201)
async def create_profile(
    resource: str, body: ImportProfileCreate, db: DbSession, user: CurrentUser
) -> ImportProfileRead:
    """Save a confirmed mapping for reuse. Re-saving a name overwrites it in place, so
    correcting last quarter's profile does not leave two near-identical entries."""
    res = _get_resource(resource)
    _require_perm(user, res.write_perm)
    mapping = _validated_mapping(res, body.mapping)
    custom_fields = await _validated_custom_fields(db, res, body.custom_field_mapping)

    existing = await db.scalar(
        select(ImportProfile).where(
            ImportProfile.resource == res.resource, ImportProfile.name == body.name
        )
    )
    profile = existing or ImportProfile(
        tenant_id=user.tenant_id, resource=res.resource, name=body.name
    )
    profile.description = body.description
    profile.mapping = mapping
    profile.custom_field_mapping = {k: str(v) for k, v in custom_fields.items()}
    profile.created_by_email = user.email
    if existing is None:
        db.add(profile)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update" if existing else "create",
        entity_type="import_profile", entity_id=profile.id,
        summary=f"Saved import mapping '{profile.name}' for {res.label}",
    )
    return _profile_read(profile)


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(profile_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    profile = await db.scalar(select(ImportProfile).where(ImportProfile.id == profile_id))
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import profile not found")
    res = _get_resource(profile.resource)
    _require_perm(user, res.write_perm)
    await db.delete(profile)
    await audit_log.record(
        db, actor=user, action="delete", entity_type="import_profile", entity_id=profile_id,
        summary=f"Deleted import mapping '{profile.name}'",
    )


def _profile_read(profile: ImportProfile) -> ImportProfileRead:
    return ImportProfileRead(
        id=profile.id,
        resource=profile.resource,
        name=profile.name,
        description=profile.description,
        mapping=dict(profile.mapping or {}),
        custom_field_mapping={k: str(v) for k, v in (profile.custom_field_mapping or {}).items()},
        created_by_email=profile.created_by_email,
        created_at=profile.created_at,
    )


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------
def _require_importable(res: ResourceIO) -> None:
    if not res.importable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Resource '{res.resource}' is export-only and cannot be imported",
        )


def _validated_mapping(res: ResourceIO, mapping: dict[str, str]) -> dict[str, str]:
    """Reject a mapping that names a column we do not have, or maps two of the client's
    columns onto the same field — both would otherwise fail silently per row."""
    if not mapping:
        return {}
    known = {c.header for c in res.columns}
    cleaned = {source: target for source, target in mapping.items() if target}

    unknown = sorted(set(cleaned.values()) - known)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown target column(s) for '{res.resource}': {', '.join(unknown)}",
        )

    seen: dict[str, str] = {}
    for source, target in cleaned.items():
        if target in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"'{seen[target]}' and '{source}' both map to '{target}'. "
                    "Each field can be filled by only one column."
                ),
            )
        seen[target] = source
    return cleaned


async def _validated_custom_fields(
    db: DbSession, res: ResourceIO, mapping: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    """Check every custom field exists, is enabled and belongs to this resource's model.

    Without the model check a caller could park a risk column's data on a vendor field,
    where it would be invisible in the UI but present in the database.
    """
    if not mapping:
        return {}
    model_key = import_mapping.custom_field_model_key(res.model)
    if model_key not in CUSTOM_FIELD_MODELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{res.label}' does not support custom fields",
        )

    ids = list(dict.fromkeys(mapping.values()))
    rows = (await db.scalars(select(CustomField).where(CustomField.id.in_(ids)))).all()
    by_id = {row.id: row for row in rows}
    for source, field_id in mapping.items():
        field = by_id.get(field_id)
        if field is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Custom field for column '{source}' does not exist",
            )
        if field.model != model_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Custom field '{field.label}' belongs to '{field.model}', "
                    f"not '{model_key}'"
                ),
            )
        if not field.enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Custom field '{field.label}' is disabled",
            )
    return dict(mapping)


async def _link_indexes(db: DbSession, res: ResourceIO) -> dict[str, dict[str, object]]:
    """One reference index per distinct link target (avoids per-row queries)."""
    indexes: dict[str, dict[str, object]] = {}
    for col in res.columns:
        if col.link is not None:
            key = col.link.target_model.__name__
            if key not in indexes:
                indexes[key] = await _build_ref_index(db, col.link)
    return indexes


def _write_custom_values(
    db: DbSession,
    user: CurrentUser,
    record: object,
    source_row: dict[str, str | None],
    custom_fields: dict[str, uuid.UUID],
) -> None:
    """Persist the mapped-to-custom-field cells for one freshly created record.

    ``record`` is whatever the module's create function returned — every one of them
    returns a Read schema carrying the new ``id``.
    """
    entity_id = getattr(record, "id", None)
    if entity_id is None:
        raise ValueError("Could not resolve the created record's id for custom fields")
    for source, field_id in custom_fields.items():
        value = (source_row.get(source) or "").strip()
        if not value:
            continue
        db.add(
            CustomFieldValue(
                tenant_id=user.tenant_id,
                custom_field_id=field_id,
                entity_id=entity_id,
                value=value,
            )
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
