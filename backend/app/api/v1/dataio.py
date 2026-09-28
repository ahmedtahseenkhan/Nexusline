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

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import selectinload

from app.core import db_errors

from app.core.deps import CurrentUser, DbSession
from app.core.schema_loading import options_for, serialize_all
from app.models.custom_field import CUSTOM_FIELD_MODELS, CustomField, CustomFieldValue
from app.models.import_profile import ImportProfile
from app.schemas.dataio import (
    ImportError as RowError,
)
from app.schemas.dataio import (
    CustomFieldSuggestionRead,
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
from app.services import modules as module_service
from app.services import csv_io, custom_field_values, import_mapping, lifecycle_gates, ref_fields, webhooks, xlsx_io
from app.services.import_registry import (
    REGISTRY,
    VIA_COLUMN,
    VIA_JOIN,
    Column,
    ImportGate,
    LinkSpec,
    ResourceIO,
    import_gate,
)

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


def _ref_label(obj: object, match_field: str, link: LinkSpec | None = None,
               shared: frozenset[str] = frozenset()) -> str:
    """Render a linked object as a human reference for export.

    Prefer the link's own ``label`` renderer, then the object's ``reference`` (when
    present, non-empty and not ``shared`` by another live record — a shared reference
    would resolve to the wrong one on re-import), else the configured ``match_field``
    (``name``/``title``).
    """
    if link is not None and link.label is not None:
        return link.label(obj)
    ref = getattr(obj, "reference", "") or ""
    if ref and ref.strip().lower() not in shared:
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


#: Index value for a key that names more than one record.
_AMBIGUOUS = object()


def _index_key(key: str) -> str:
    return " ".join(key.split()).lower()


def _scoped(stmt, model: type, link: LinkSpec):
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    for attr, value in link.scope:
        stmt = stmt.where(getattr(model, attr) == value)
    return stmt


async def _build_ref_index(db: DbSession, link: LinkSpec) -> dict[str, object]:
    """Preload one ``reference/name/title`` -> id map for a link target.

    Built once per import (per distinct target and scope) to avoid per-row queries.
    Keys are lower-cased with whitespace collapsed, for case-insensitive matching. The
    ``reference`` (if the model has one) wins over every other key; then the
    ``match_field``, the link's ``label`` and any ``also_match`` attributes. A key two
    different records answer to maps to ``_AMBIGUOUS``: guessing one of them would link
    the wrong record without anyone noticing.
    """
    model = link.target_model
    attrs = [a for a in dict.fromkeys(("reference", link.match_field, *link.also_match)) if hasattr(model, a)]
    if link.label is None and all(a in sa_inspect(model).column_attrs for a in attrs):
        # Only the columns matched on: loading the records would load their links too,
        # and a register's links' links — seconds of queries for a list of names.
        result = await db.execute(
            _scoped(select(model.id, *(getattr(model, a) for a in attrs)), model, link)
        )
        rows = [{"id": row[0], **dict(zip(attrs, row[1:])), "_label": None} for row in result.all()]
    else:
        # A label (or a matched property) may read the record's links: load the records,
        # none of their links, and render where a link it reads can still be loaded.
        objects = (await db.scalars(
            _scoped(select(model), model, link).options(*options_for(model, None))
        )).all()
        rows = await serialize_all(db, objects, lambda o: {
            "id": o.id, **{a: getattr(o, a, None) for a in attrs},
            "_label": link.label(o) if link.label is not None else None,
        })

    def add(index: dict[str, object], key: object, obj_id: object) -> None:
        text = _index_key(str(key or ""))
        if not text:
            return
        seen = index.get(text)
        index[text] = obj_id if seen is None or seen == obj_id else _AMBIGUOUS

    refs: dict[str, object] = {}
    names: dict[str, object] = {}
    for row in rows:
        add(refs, row.get("reference"), row["id"])
        for attr in (link.match_field, *link.also_match, "_label"):
            add(names, row.get(attr), row["id"])
    return {**names, **refs}


def _index_name(link: LinkSpec) -> str:
    """One index per target model and scope (a country list is not the regulator list)."""
    scope = ",".join(f"{attr}={getattr(value, 'value', value)}" for attr, value in link.scope)
    return f"{link.target_model.__name__}[{scope}]" if scope else link.target_model.__name__


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
    resource-specific endpoints. A register whose module is not licensed, or that the
    organisation has switched off, is left out of the menu (its endpoints refuse it).
    """
    usable = await module_service.usable_modules(user.tenant_id)
    return [
        {
            "resource": res.resource,
            "label": res.label,
            "importable": res.importable,
            "write_perm": res.write_perm,
            "read_perm": res.read_perm,
        }
        for res in REGISTRY.values()
        if (module := module_service.module_for_permission(res.read_perm)) is None or module in usable
    ]


@router.get("/{resource}/schema")
async def get_schema(resource: str, user: CurrentUser) -> dict:
    res = _get_resource(resource)
    _require_perm(user, res.read_perm)
    model_key = import_mapping.custom_field_model_key(res.model, res.resource)
    return {
        "resource": res.resource,
        "label": res.label,
        "importable": res.importable,
        # Empty when this register has no custom fields — the wizard then omits the
        # "keep this column as a custom field" option rather than offering a dead end.
        "custom_field_model": model_key if model_key in CUSTOM_FIELD_MODELS else "",
        "columns": [_column_payload(c) for c in res.all_columns],
    }


_FORMAT = Query(default="csv", pattern="^(csv|xlsx)$")


def _file_payload(
    res: ResourceIO, kind: str, fmt: str, columns: list[Column], rows: list[dict],
    examples: dict[str, str] | None = None,
) -> dict:
    """``{filename, csv}`` or ``{filename, xlsx_b64}`` — the shape the page downloads."""
    if fmt == "xlsx":
        data = xlsx_io.build_workbook(columns, rows, title=res.label, examples=examples)
        return {
            "filename": f"{res.resource}_{kind}.xlsx",
            "xlsx_b64": base64.b64encode(data).decode("ascii"),
        }
    return {
        "filename": f"{res.resource}_{kind}.csv",
        "csv": csv_io.export_csv(rows, [c.header for c in columns]),
    }


@router.get("/{resource}/template")
async def get_template(
    resource: str, db: DbSession, user: CurrentUser, format: str = _FORMAT
) -> dict:
    res = _get_resource(resource)
    _require_perm(user, res.read_perm)
    custom = await _custom_columns(db, res)
    columns = [*res.all_columns, *(col for col, _ in custom)]
    examples = csv_io.example_row(columns)
    # A required link has no sensible placeholder, so its example names a real record
    # (the first one, alphabetically) when the organisation has one: the template's own
    # example row then previews clean, as the wizard's first check of the file.
    for col in columns:
        if col.required and col.link is not None and not examples.get(col.header):
            examples[col.header] = await _example_reference(db, col.link)
    # The CSV template carries its example as a row; the workbook keeps the data sheet
    # clean (a forgotten example row would import) and shows examples on its Guide.
    rows = [] if format == "xlsx" else [examples]
    return _file_payload(res, "template", format, columns, rows, examples)


async def _example_reference(db: DbSession, link: LinkSpec) -> str:
    model = link.target_model
    stmt = _scoped(select(model), model, link).order_by(getattr(model, link.match_field)).limit(1)
    first = await db.scalar(stmt)
    return _ref_label(first, link.match_field, link) if first is not None else ""


@router.get("/{resource}/export")
async def export_resource(
    resource: str, db: DbSession, user: CurrentUser, request: Request, format: str = _FORMAT,
) -> dict:
    """Every row of the register — or, given the register's own list filters in the
    query string (``search``, ``environment`` …) or ``ids`` (comma-separated), only the
    rows the user is looking at."""
    res = _get_resource(resource)
    _require_perm(user, res.read_perm)
    params = dict(request.query_params)

    model = res.model
    stmt = select(model)
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    # Discriminator-backed resources export only their own register's rows.
    for attr, value in res.fixed.items():
        stmt = stmt.where(getattr(model, attr) == value)
    if res.export_where is not None:
        stmt = stmt.where(*res.export_where())
    if res.export_filters is not None:
        stmt = stmt.where(*res.export_filters(params))
    if params.get("ids"):
        try:
            wanted = [uuid.UUID(v.strip()) for v in params["ids"].split(",") if v.strip()]
        except ValueError:
            raise HTTPException(status_code=422, detail="ids must be comma-separated record ids.") from None
        stmt = stmt.where(model.id.in_(wanted))
    # Load the relationships the link columns read — each one's whole dotted path, so
    # ``hosted_dependencies.information_asset`` brings the information assets and not
    # just the dependencies — and nothing else: a register's rows map twenty-odd eager
    # relationships, and loading all of them for every exported row made a 6,000-asset
    # export take over a minute. Anything a column reads beyond these paths is
    # lazy-loaded while the rows are built (below), never a failed request.
    paths = tuple(sorted({
        col.link.export_attr for col in res.all_columns
        if col.link is not None and col.link.exportable and col.export_batch is None
        and _is_relationship(model, col.link.export_attr.split(".")[0])
    }))
    stmt = stmt.options(*options_for(model, None, paths))

    records = (await db.scalars(stmt)).all()
    linked = await _prefetch_links(db, res, records)
    shared = await _shared_references(db, res)
    batches = {
        col.header: await col.export_batch(db, list(records))
        for col in res.all_columns if col.export_batch is not None
    }
    custom = await _custom_columns(db, res)
    values = await _custom_values(db, custom, [obj.id for obj in records])

    def build_rows(_session) -> list[dict]:
        rows: list[dict] = []
        for obj in records:
            row: dict[str, object] = {}
            for col in res.all_columns:
                if col.export_batch is not None:
                    row[col.header] = batches[col.header].get(obj.id, "")
                elif col.export_value is not None:
                    row[col.header] = col.export_value(obj)
                elif col.link is not None:
                    row[col.header] = _export_link(
                        obj, col.link, linked.get(col.header), shared.get(col.link.target_model, frozenset())
                    )
                else:
                    row[col.header] = getattr(obj, col.field, None)
            for col, cf in custom:
                raw = values.get((cf.id, obj.id), "")
                row[col.header] = _typed_custom(col, raw) if format == "xlsx" else raw
            rows.append(row)
        return rows

    # Built where a relationship the options left unloaded can still be lazy-loaded.
    rows = await db.run_sync(build_rows)

    columns = [*res.all_columns, *(col for col, _ in custom)]
    return _file_payload(res, "export", format, columns, rows)


async def _prefetch_links(
    db: DbSession, res: ResourceIO, records: list
) -> dict[str, dict[object, list]]:
    """Linked targets of every ``column`` / ``join`` link, per record id, in one query per
    link — for links the model has no relationship to read."""
    out: dict[str, dict[object, list]] = {}
    ids = [obj.id for obj in records]
    for col in res.all_columns:
        link = col.link
        if link is None or link.exportable or col.export_batch is not None or not ids:
            continue
        target = link.target_model
        pairs: list[tuple[object, object]] = []
        if link.via == VIA_COLUMN:
            pairs = [(obj.id, getattr(obj, link.create_field, None)) for obj in records]
            pairs = [(rid, tid) for rid, tid in pairs if tid is not None]
        elif link.via == VIA_JOIN:
            table, own, other = _join_columns(res.model, target)
            pairs = list((await db.execute(select(own, other).where(own.in_(ids)))).all())
        target_ids = {tid for _, tid in pairs}
        found = {}
        if target_ids:
            # The targets are rendered by one column (``match_field``), so load none of
            # their relationships: a control's protected assets arrived with every one of
            # each asset's twenty-eight links, and ninety controls exported in eighty
            # seconds. Anything a label reads beyond the row lazy-loads while rows build.
            stmt = (
                _scoped(select(target), target, link)
                .where(target.id.in_(target_ids))
                .options(*options_for(target, None, ()))
            )
            rows = (await db.scalars(stmt)).all()
            found = {t.id: t for t in rows}
        per_record: dict[object, list] = {}
        for rid, tid in pairs:
            if tid in found:
                per_record.setdefault(rid, []).append(found[tid])
        out[col.header] = per_record
    return out


def _join_columns(model: type, target: type):
    """(table, column naming ``model``, column naming ``target``) of the join table behind
    ``target``'s relationship back to ``model`` (``Asset.legals`` for Legal's assets)."""
    for rel in target.__mapper__.relationships:
        if rel.mapper.class_ is model and rel.secondary is not None:
            table = rel.secondary
            own = next(c for c in table.c if any(fk.column.table is model.__table__ for fk in c.foreign_keys))
            other = next(c for c in table.c if any(fk.column.table is target.__table__ for fk in c.foreign_keys))
            return table, own, other
    raise LookupError(f"No join table links {target.__name__} back to {model.__name__}")


async def _shared_references(db: DbSession, res: ResourceIO) -> dict[type, frozenset[str]]:
    """Per linked model, the references more than one live record carries. An export
    names those records by name/title instead, so the cell resolves back to the same
    record on import."""
    from sqlalchemy import func

    out: dict[type, frozenset[str]] = {}
    for col in res.all_columns:
        target = col.link.target_model if col.link is not None else None
        if target is None or target in out or not hasattr(target, "reference"):
            continue
        stmt = select(func.lower(func.trim(target.reference))).where(target.reference != "")
        if hasattr(target, "deleted"):
            stmt = stmt.where(target.deleted.is_(False))
        stmt = stmt.group_by(func.lower(func.trim(target.reference))).having(func.count() > 1)
        out[target] = frozenset((await db.scalars(stmt)).all())
    return out


# ---------------------------------------------------------------------------
# Custom fields as spreadsheet columns
# ---------------------------------------------------------------------------
#: Custom-field type -> column kind: the record form's own rule set.
_CF_KIND = custom_field_values.KIND


def _norm_header(text: str) -> str:
    return " ".join(text.split()).casefold()


async def _custom_columns(db: DbSession, res: ResourceIO) -> list[tuple[Column, CustomField]]:
    """The register's enabled custom fields as extra spreadsheet columns.

    Each is headed by its label; a label that repeats a built-in heading (or another
    custom field) becomes "Label (custom)" so every heading stays unique and an
    exported file maps back to the same fields on import.
    """
    model_key = import_mapping.custom_field_model_key(res.model, res.resource)
    if model_key not in CUSTOM_FIELD_MODELS:
        return []
    fields = (
        await db.scalars(
            select(CustomField)
            .where(CustomField.model == model_key, CustomField.enabled.is_(True))
            .order_by(CustomField.order_index, CustomField.label)
        )
    ).all()
    taken = {_norm_header(c.header) for c in res.all_columns}
    out: list[tuple[Column, CustomField]] = []
    for cf in fields:
        label = cf.label.strip()
        header = label
        n = 1
        while _norm_header(header) in taken:
            header = f"{label} (custom)" if n == 1 else f"{label} (custom {n})"
            n += 1
        taken.add(_norm_header(header))
        options = custom_field_values.options_of(cf)
        kind = _CF_KIND.get(cf.field_type, "text")
        out.append((
            Column(
                header=header,
                field=f"cf:{cf.id}",
                required=cf.required,
                kind=kind,
                enum_values=options if kind == "enum" else None,
                help=cf.help_text or "Custom field",
            ),
            cf,
        ))
    return out


async def _custom_values(
    db: DbSession, custom: list[tuple[Column, CustomField]], entity_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], str]:
    """(field id, record id) -> stored value, for the exported records."""
    if not custom or not entity_ids:
        return {}
    rows = (
        await db.scalars(
            select(CustomFieldValue).where(
                CustomFieldValue.custom_field_id.in_([cf.id for _, cf in custom]),
                CustomFieldValue.entity_id.in_(entity_ids),
            )
        )
    ).all()
    return {(v.custom_field_id, v.entity_id): v.value for v in rows}


def _typed_custom(col: Column, raw: str) -> object:
    """A stored custom value as a typed cell (real dates / numbers / booleans in Excel)."""
    try:
        return csv_io.coerce(raw, col.kind if col.kind != "enum" else "text")
    except ValueError:
        return raw  # stored before validation existed — export what is there


def _custom_cell(col: Column, raw: str | None) -> str:
    """Validate one imported custom-field cell and return the value to store.

    The record form's value rules (``services.custom_field_values``): checkbox values
    normalise to ``true``/``false``, dates to ISO, select values to the option's own
    spelling (case-insensitive), numbers must be finite. A blank cell stays blank even
    for a required field: records that predate the field being made required export
    blank, and must still import (the record page asks for the value). Raises
    ``ValueError`` naming the column.
    """
    try:
        return custom_field_values.normalise(col.kind, raw, col.enum_values)
    except ValueError as exc:
        raise ValueError(f"{col.header}: {exc}") from exc


def _is_relationship(model: type, attr: str) -> bool:
    """True if ``attr`` is a genuine ORM relationship on ``model`` (loadable)."""
    try:
        return attr in model.__mapper__.relationships  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - defensive; treat as non-loadable
        return False


def _export_link(
    obj: object, link: LinkSpec, prefetched: dict[object, list] | None = None,
    shared: frozenset[str] = frozenset(),
) -> str:
    """Render a record's linked object(s) as a CSV cell.

    A relationship link reads ``export_attr`` (a dotted path steps through one more
    relationship per segment); a ``column`` / ``join`` link reads what
    :func:`_prefetch_links` loaded. Archived targets are left out: the importer cannot
    link them, so exporting them would only make the file fail on the way back in.
    """
    if link.exportable:
        related: list = [obj]
        for attr in link.export_attr.split("."):
            step: list = []
            for item in related:
                value = getattr(item, attr, None)
                if value is None:
                    continue
                step.extend(value if isinstance(value, (list, tuple, set)) else [value])
            related = step
    else:
        related = list((prefetched or {}).get(getattr(obj, "id", None), []))
    live = [item for item in related if not getattr(item, "deleted", False) and _in_scope(item, link)]
    # Sorted, so the same links always export as the same cell.
    labels = sorted(dict.fromkeys(_ref_label(item, link.match_field, link, shared) for item in live))
    return ", ".join(labels) if link.multi else (labels[0] if labels else "")


def _in_scope(item: object, link: LinkSpec) -> bool:
    return all(getattr(item, attr, None) == value for attr, value in link.scope)


@router.post("/{resource}/import")
async def import_resource(
    resource: str, body: ImportRequest, db: DbSession, user: CurrentUser
) -> ImportResult:
    res = _get_resource(resource)
    _require_perm(user, res.write_perm)
    _require_importable(res)

    header_by_field = {c.header: c for c in res.all_columns}
    mapping = _validated_mapping(res, body.mapping)
    custom_fields = await _validated_custom_fields(db, res, body.custom_field_mapping)
    link_indexes = await _link_indexes(db, res)
    gate = await import_gate(db, res, user)

    reader = csv.DictReader(io.StringIO(body.content))
    errors: list[RowError] = []
    warnings: list[RowError] = []
    total = 0
    created = 0

    # Data rows start at line 2 (header is line 1).
    for row_no, raw_row in enumerate(reader, start=2):
        total += 1
        try:
            source_row = dict(raw_row)
            payload, row_warnings = _row_payload(res, source_row, mapping, header_by_field, link_indexes, gate)
            obj = res.create_schema(**payload)
            # Custom cells are validated before anything is written, and written inside
            # the row's own savepoint, so a bad value never leaves a half-imported row.
            custom_values = _custom_cells(source_row, custom_fields)
            # The gate decided this row's state (_row_payload): the module's create
            # accepts what passed it (services.lifecycle_gates.import_decided).
            with ref_fields.collect_warnings() as ref_warnings, lifecycle_gates.import_decided():
                async with db.begin_nested():
                    record = await res.create_func(body=obj, db=db, user=user)
                    if custom_values:
                        _write_custom_values(db, user, record, custom_values)
                        await db.flush()
            created += 1
            warnings.extend(RowError(row=row_no, message=m) for m in [*row_warnings, *ref_warnings])
        except Exception as exc:  # noqa: BLE001 - row isolation: report & continue
            errors.append(RowError(row=row_no, message=_clean_message(exc, res)))
            await _reload_expired(db)

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
            "warnings": len(warnings),
            "mapped_columns": len(mapping),
            "custom_field_columns": len(custom_fields),
        },
    )
    return ImportResult(
        total=total, created=created, skipped=total - created, errors=errors, warnings=warnings
    )


async def _reload_expired(db: DbSession) -> None:
    """Reload what a rolled-back row savepoint expired.

    Rolling back a savepoint expires every record the row touched — the risks and
    controls it linked to, through their back-references. Under asyncio an expired
    attribute cannot load itself on access, so the *next* row that linked the same
    record failed with an unrelated "greenlet_spawn" error. Reloading them here keeps
    every row independent of the one before it."""
    stale = [
        (state.obj(), set(state.expired_attributes))
        for state in db.sync_session.identity_map.all_states()
        if state.expired or state.expired_attributes
    ]
    for obj, names in stale:
        if obj is None:
            continue
        try:
            # Named explicitly so lazy relationships (a role's permissions) load too.
            await db.refresh(obj, attribute_names=sorted(names) or None)
        except Exception:  # noqa: BLE001 - gone with the savepoint: forget it instead
            db.expunge(obj)


def _row_payload(
    res: ResourceIO,
    source_row: dict[str, str | None],
    mapping: dict[str, str],
    header_by_field: dict[str, Column],
    link_indexes: dict[str, dict[str, object]],
    gate: ImportGate,
) -> tuple[dict, list[str]]:
    """One row as Create-schema kwargs, plus its warnings — shared by preview and import
    so both take the same decision on every row."""
    canonical = import_mapping.apply_mapping(source_row, mapping) if mapping else source_row
    warnings: list[str] = []
    payload = _row_to_payload(canonical, header_by_field, link_indexes, warnings)
    # Discriminators are the resource's identity, not per-row data: stamp them
    # last so a stray CSV column can never route rows into the wrong register.
    payload.update(res.fixed)
    if res.prepare is not None:
        warnings.extend(res.prepare(payload))
    # A status only a workflow action reaches enters at its initial state (StateRule).
    warnings.extend(gate.apply(payload))
    return payload, warnings


# ---------------------------------------------------------------------------
# Smart import wizard — inspect / preview
# ---------------------------------------------------------------------------
@router.post("/{resource}/inspect", response_model=InspectResponse)
async def inspect_upload(
    resource: str, body: InspectRequest, db: DbSession, user: CurrentUser
) -> InspectResponse:
    """Read an uploaded CSV or .xlsx and propose a column mapping.

    Nothing is written. The response carries the
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
        table.headers, res.all_columns, resource=res.resource
    )
    # A heading that names a custom field exactly (as our template and export write
    # it) goes to that field, ahead of any fuzzy guess at a built-in one.
    custom_by_header = {_norm_header(col.header): (col, cf) for col, cf in await _custom_columns(db, res)}
    custom_suggestions: list[CustomFieldSuggestionRead] = []
    for header in table.headers:
        hit = custom_by_header.get(_norm_header(header))
        if hit is None:
            continue
        builtin = next((s for s in suggestions if s.source == header), None)
        if builtin is not None and _norm_header(builtin.target) == _norm_header(header):
            continue
        suggestions = [s for s in suggestions if s.source != header]
        unmapped = [h for h in unmapped if h != header]
        custom_suggestions.append(
            CustomFieldSuggestionRead(source=header, custom_field_id=hit[1].id, label=hit[1].label)
        )
    mapped_headers = {s.target for s in suggestions}
    unfilled = [c.header for c in res.all_columns if c.header not in mapped_headers]
    missing_required = [c.header for c in res.all_columns if c.required and c.header not in mapped_headers]

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
        custom_field_suggestions=custom_suggestions,
        unmapped_source_headers=unmapped,
        unfilled_target_headers=unfilled,
        missing_required=missing_required,
    )


#: Session key under which ``services.webhooks`` queues deliveries until commit.
_WEBHOOK_QUEUE = webhooks._PENDING


class _DryRun(Exception):
    """Raised inside a preview row's savepoint to roll back what the row wrote."""


@router.post("/{resource}/preview", response_model=PreviewResponse)
async def preview_import(
    resource: str, body: PreviewRequest, db: DbSession, user: CurrentUser
) -> PreviewResponse:
    """Dry-run a mapping over the first N rows. **Writes nothing.**

    Each row goes through exactly what the import does — coercion, link resolution,
    the workflow-state gate, schema validation *and the module's own create function*
    (so its business rules, such as a risk leaving Draft only with an owner) — inside
    a savepoint that is then rolled back. So an error or warning here is the error or
    warning the import will report for that row.
    """
    res = _get_resource(resource)
    _require_perm(user, res.write_perm)
    _require_importable(res)

    header_by_field = {c.header: c for c in res.all_columns}
    mapping = _validated_mapping(res, body.mapping)
    custom_fields = await _validated_custom_fields(db, res, body.custom_field_mapping)
    link_indexes = await _link_indexes(db, res)
    gate = await import_gate(db, res, user)
    # A create queues its webhooks for delivery on commit; the dry run's must not go out.
    queued = db.info.get(_WEBHOOK_QUEUE)
    queued_before = list(queued) if queued is not None else None

    all_rows = list(csv.DictReader(io.StringIO(body.content)))
    rows: list[PreviewRow] = []
    valid = 0
    for offset, raw_row in enumerate(all_rows[: body.limit]):
        source_row = dict(raw_row)
        canonical = import_mapping.apply_mapping(source_row, mapping) if mapping else source_row
        values = {k: (v or "") for k, v in canonical.items() if k in header_by_field}
        for source, (col, _) in custom_fields.items():
            values[col.header] = source_row.get(source) or ""
        error = ""
        row_warnings: list[str] = []
        try:
            payload, row_warnings = _row_payload(res, source_row, mapping, header_by_field, link_indexes, gate)
            obj = res.create_schema(**payload)
            custom_values = _custom_cells(source_row, custom_fields)
            with ref_fields.collect_warnings() as ref_warnings, lifecycle_gates.import_decided():
                try:
                    async with db.begin_nested():
                        record = await res.create_func(body=obj, db=db, user=user)
                        if custom_values:
                            _write_custom_values(db, user, record, custom_values)
                        await db.flush()
                        raise _DryRun
                except _DryRun:
                    pass
            row_warnings = [*row_warnings, *ref_warnings]
            valid += 1
        except Exception as exc:  # noqa: BLE001 - surface, do not raise
            error = _clean_message(exc, res)
            row_warnings = []
        await _reload_expired(db)
        rows.append(PreviewRow(row=offset + 2, values=values, error=error, warnings=row_warnings))

    if queued_before is None:
        db.info.pop(_WEBHOOK_QUEUE, None)
    else:
        db.info[_WEBHOOK_QUEUE] = queued_before

    headers = [*(c.header for c in res.all_columns), *(col.header for col, _ in custom_fields.values())]
    populated = [h for h in dict.fromkeys(headers) if any(h in r.values for r in rows)]
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
    known = {c.header for c in res.all_columns}
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
) -> dict[str, tuple[Column, uuid.UUID]]:
    """Check every custom field exists, is enabled and belongs to this resource's model.

    Without the model check a caller could park a risk column's data on a vendor field,
    where it would be invisible in the UI but present in the database. Returns each
    source column's custom field as a typed ``Column`` (for validating its cells) and id.
    """
    if not mapping:
        return {}
    model_key = import_mapping.custom_field_model_key(res.model, res.resource)
    if model_key not in CUSTOM_FIELD_MODELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{res.label}' does not support custom fields",
        )

    ids = list(dict.fromkeys(mapping.values()))
    rows = (await db.scalars(select(CustomField).where(CustomField.id.in_(ids)))).all()
    by_id = {row.id: row for row in rows}
    columns = {cf.id: col for col, cf in await _custom_columns(db, res)}
    out: dict[str, tuple[Column, uuid.UUID]] = {}
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
        if not field.enabled or field_id not in columns:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Custom field '{field.label}' is disabled",
            )
        out[source] = (columns[field_id], field_id)
    return out


def _custom_cells(
    source_row: dict[str, str | None], custom_fields: dict[str, tuple[Column, uuid.UUID]]
) -> dict[uuid.UUID, str]:
    """The row's validated custom-field values (field id -> value); blanks omitted."""
    out: dict[uuid.UUID, str] = {}
    for source, (col, field_id) in custom_fields.items():
        value = _custom_cell(col, source_row.get(source))
        if value:
            out[field_id] = value
    return out


async def _link_indexes(db: DbSession, res: ResourceIO) -> dict[str, dict[str, object]]:
    """One reference index per distinct link target and scope (avoids per-row queries)."""
    indexes: dict[str, dict[str, object]] = {}
    for col in res.all_columns:
        if col.link is not None:
            key = _index_name(col.link)
            if key not in indexes:
                indexes[key] = await _build_ref_index(db, col.link)
    return indexes


def _write_custom_values(
    db: DbSession,
    user: CurrentUser,
    record: object,
    values: dict[uuid.UUID, str],
) -> None:
    """Persist the validated custom-field cells for one freshly created record.

    ``record`` is whatever the module's create function returned — every one of them
    returns a Read schema carrying the new ``id``.
    """
    entity_id = getattr(record, "id", None)
    if entity_id is None:
        raise ValueError("Could not resolve the created record's id for custom fields")
    for field_id, value in values.items():
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
    warnings: list[str] | None = None,
) -> dict:
    """Map a CSV row dict to a Create-schema kwargs dict (typed & link-resolved).

    ``warnings`` collects what a lenient link had to skip."""
    payload: dict[str, object] = {}
    for header, raw_value in raw_row.items():
        if header is None:
            continue
        col = header_by_field.get(header.strip()) if isinstance(header, str) else None
        if col is None:
            continue  # ignore unknown/extra columns

        if col.parse is not None:
            text = (raw_value or "").strip()
            if text:
                if col.link is not None:
                    payload[col.field] = col.parse(
                        text, lambda token, c=col: _lookup_token(token, c, link_indexes)
                    )
                else:
                    payload[col.field] = col.parse(text)
            continue

        if col.link is not None:
            resolved = _resolve_link(raw_value, col, link_indexes, warnings)
            if resolved is not None:
                payload[col.field] = resolved
            continue

        value = csv_io.coerce(raw_value if raw_value is not None else "", col.kind, col.enum_values)
        if value is not None:
            payload[col.field] = value
    return payload


def _lookup_token(token: str, col: Column, link_indexes: dict[str, dict[str, object]]):
    """The id one token names; ``ValueError`` naming the column when it names none or
    several records."""
    link = col.link
    assert link is not None
    noun = link.target_model.__name__
    obj_id = link_indexes[_index_name(link)].get(_index_key(token))
    if obj_id is None:
        raise ValueError(f"{col.header}: no {noun} matching '{token.strip()}'")
    if obj_id is _AMBIGUOUS:
        raise ValueError(
            f"{col.header}: '{token.strip()}' matches more than one {noun}; use its reference "
            "or another value that names only one"
        )
    return obj_id


def _resolve_link(
    raw_value: str | None,
    col: Column,
    link_indexes: dict[str, dict[str, object]],
    warnings: list[str] | None = None,
):
    """Resolve a link cell to id(s); raise ValueError naming any unknown token.

    A token repeated in one cell is linked once. A ``lenient`` link skips a token it
    cannot resolve and says so in ``warnings`` instead of failing the row."""
    text = (raw_value or "").strip()
    if text == "":
        return None
    link = col.link
    assert link is not None
    tokens = _split_tokens(text) if link.multi else [text]
    ids: list = []
    for token in tokens:
        try:
            obj_id = _lookup_token(token, col, link_indexes)
        except ValueError as exc:
            if not link.lenient:
                raise
            if warnings is not None:
                warnings.append(f"{exc}; left blank.")
            continue
        if obj_id not in ids:
            ids.append(obj_id)
    if link.multi:
        return ids
    return ids[0] if ids else None


def _clean_message(exc: Exception, res: ResourceIO | None = None) -> str:
    """Reduce an exception to one concise sentence a user can act on.

    Never a traceback, and never the SQL of a database refusal: an ``HTTPException``
    gives its detail, a validation error its messages (under the spreadsheet heading of
    the field, when ``res`` names one), a database error the plain sentence
    ``core.db_errors`` makes of it."""
    msg = ""
    if isinstance(exc, HTTPException):
        detail = exc.detail
        msg = detail if isinstance(detail, str) else "; ".join(
            str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in (detail or [])
        )
    elif isinstance(exc, PydanticValidationError):
        parts = []
        headers = {c.field: c.header for c in res.all_columns} if res is not None else {}
        for err in exc.errors():
            text = str(err.get("msg", "")).removeprefix("Value error, ")
            loc = ".".join(str(headers.get(x, x)) for x in err.get("loc", ()) if x != "__root__")
            parts.append(f"{loc}: {text}" if loc else text)
        msg = "; ".join(parts)
    elif isinstance(exc, IntegrityError):
        msg = db_errors._describe(exc)[1]
    elif isinstance(exc, DBAPIError):
        msg = _db_error_sentence(exc)
    msg = (msg or str(exc)).strip() or exc.__class__.__name__
    return " ".join(msg.splitlines())[:500]


def _db_error_sentence(exc: DBAPIError) -> str:
    """A database refusal other than a constraint (a value too long, a bad number)."""
    cause = getattr(exc.orig, "__cause__", None) or exc.orig
    kind = type(cause).__name__
    if kind == "StringDataRightTruncationError":
        column = getattr(cause, "column_name", None)
        where = f" for '{column.replace('_', ' ')}'" if column else ""
        return f"A value is longer than allowed{where}: {str(cause).splitlines()[0]}."
    if kind in ("NumericValueOutOfRangeError", "InvalidTextRepresentationError",
                "InvalidDatetimeFormatError", "DatetimeFieldOverflowError"):
        return f"A value is not valid for its field: {str(cause).splitlines()[0]}."
    return "The database refused this row: " + (str(cause).splitlines()[0] if str(cause) else kind) + "."
