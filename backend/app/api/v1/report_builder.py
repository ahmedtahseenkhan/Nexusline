"""Report builder endpoints: the subject catalogue, run, export, and saved reports.

The registry in ``services.report_builder`` decides what a report *can* ask; this
module turns one ask into rows. It owns the three things a pure registry cannot: the
tenant's methodology (matrix, appetite), the names behind ids on the cover page, and
the caps that keep a bank-sized register from being loaded into memory by accident.

Permissions are the subject's own — running a risk report needs ``risk:read``, so the
builder can never become a way around a module's access control — plus ``report:write``
to save a definition for others.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.saved_report import SavedReport
from app.models.tenant import Tenant
from app.schemas.common import Page
from app.services import audit, pdf_report, report_export
from app.services import report_builder as rb
from app.services.risk_scoring import max_score_for
from app.services.risk_settings import get_or_create_settings

router = APIRouter(prefix="/report-builder", tags=["reports"])

#: A run summarises the whole matching set, not just the page. Past this many rows the
#: summary is computed over the first N and flagged, rather than pulling a full register
#: into memory to count it.
SUMMARY_MAX = 5000
#: Exports are whole-set by nature. Past this the answer is "narrow the filters", said
#: plainly, rather than a multi-minute request that may time out at the proxy.
EXPORT_MAX = 10000


# ------------------------------------------------------------------ schemas ---
class ReportDefinition(BaseModel):
    subject: str
    filters: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    sort_by: str | None = None
    sort_dir: str | None = Field(default=None, pattern="^(asc|desc)$")
    #: Append a detail page per record where the subject supports it (risks).
    include_details: bool = False
    title: str = Field(default="", max_length=160)


class RunRequest(ReportDefinition):
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class RunColumn(BaseModel):
    key: str
    label: str


class RunRow(BaseModel):
    id: str
    cells: dict[str, Any]


class RunResponse(BaseModel):
    columns: list[RunColumn]
    items: list[RunRow]
    total: int
    #: {"By severity": {"Critical": 3, ...}, ...} over the matching set.
    summary: dict[str, dict[str, int]]
    summary_over: int
    #: (label, value) for every filter that was set — what the cover page prints.
    params: list[list[str]]


class SavedReportCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    subject: str
    definition: dict[str, Any] = Field(default_factory=dict)
    shared: bool = True


class SavedReportUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    definition: dict[str, Any] | None = None
    shared: bool | None = None


class SavedReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    subject: str
    definition: dict[str, Any]
    shared: bool
    owner_id: uuid.UUID | None
    owner_email: str
    created_at: Any
    updated_at: Any


# ------------------------------------------------------------------ helpers ---
def _subject(key: str) -> rb.Subject:
    try:
        return rb.get_subject(key)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown report subject '{key}'")


def _require_read(user: CurrentUser, subject: rb.Subject) -> None:
    if subject.read_perm not in user.permission_codes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires permission: {subject.read_perm}"
        )


def _is_admin(user) -> bool:
    return "Admin" in user.role_names


def _display(obj) -> str:
    for attr in ("full_name", "name", "title", "reference"):
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return getattr(obj, "email", None) or str(getattr(obj, "id", ""))


async def _context(db, user, subject: rb.Subject, filters: dict) -> rb.ReportContext:
    """Tenant methodology plus display names for every id-valued filter that is set."""
    settings = await get_or_create_settings(db, user.tenant_id)
    tenant = await db.scalar(select(Tenant).where(Tenant.id == user.tenant_id))
    ctx = rb.ReportContext(
        org_name=tenant.name if tenant else "Organization",
        appetite=settings.appetite_score,
        tolerance=settings.tolerance_score,
        max_score=max_score_for(settings.matrix_size),
        matrix_size=settings.matrix_size,
        today=date.today(),
    )
    for _key, model, ident in rb.id_filter_models(subject, filters):
        obj = await db.get(model, ident)
        if obj is not None:
            ctx.names[str(ident)] = _display(obj)
    return ctx


async def _load(db, subject: rb.Subject, d: ReportDefinition, ctx: rb.ReportContext,
                *, limit: int | None, offset: int = 0) -> tuple[list, int]:
    stmt = rb.build_statement(subject, d.filters, ctx)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = rb.apply_sort(subject, stmt, d.sort_by, d.sort_dir)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    rows = list((await db.scalars(stmt)).all())
    if subject.prefetch is not None and rows:
        await subject.prefetch(db, rows, ctx)
    return rows, total


def _pdf_filename(title: str, subject: rb.Subject, ext: str) -> str:
    base = (title or f"{subject.label} report").lower()
    slug = "".join(ch if ch.isalnum() else "-" for ch in base).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"{slug[:60] or 'report'}.{ext}"


def _file(data: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ---------------------------------------------------------------- catalogue ---
@router.get("/subjects", dependencies=[Depends(require("report:read"))])
async def subjects(user: CurrentUser) -> list[dict]:
    """Every subject the registry knows, with its filters and columns — the UI is built
    from this, so it can only offer what the server will honour. Subjects the user
    cannot read are omitted rather than shown greyed out."""
    return [s for s in rb.catalog() if rb.SUBJECTS[s["key"]].read_perm in user.permission_codes]


# ---------------------------------------------------------------------- run ---
@router.post("/run", response_model=RunResponse)
async def run(body: RunRequest, db: DbSession, user: CurrentUser) -> RunResponse:
    """One page of the report, plus a summary over the whole matching set."""
    subject = _subject(body.subject)
    _require_read(user, subject)
    ctx = await _context(db, user, subject, body.filters)
    columns = rb.selected_columns(subject, body.columns)

    page, total = await _load(db, subject, body, ctx, limit=body.limit, offset=body.offset)

    # The summary is over everything that matched — a page-only breakdown would change
    # as you paged, which is worse than none. Capped so a whole register is never pulled
    # into memory just to be counted.
    if total <= body.limit and body.offset == 0:
        universe = page
    else:
        universe, _ = await _load(db, subject, body, ctx, limit=SUMMARY_MAX)
    summary = subject.summarize(universe, ctx)

    return RunResponse(
        columns=[RunColumn(key=c.key, label=c.label) for c in columns],
        items=[RunRow(**r) for r in rb.render_rows(subject, columns, page, ctx)],
        total=total,
        summary=summary,
        summary_over=len(universe),
        params=[[k, v] for k, v in rb.describe_filters(subject, body.filters, ctx)],
    )


# ------------------------------------------------------------------- export ---
async def _export(db, user, d: ReportDefinition, fmt: str) -> Response:
    subject = _subject(d.subject)
    _require_read(user, subject)
    if fmt not in ("pdf", "xlsx", "csv"):
        raise HTTPException(status_code=422, detail="format must be pdf, xlsx or csv")

    ctx = await _context(db, user, subject, d.filters)
    columns = rb.selected_columns(subject, d.columns)
    rows, total = await _load(db, subject, d, ctx, limit=EXPORT_MAX)
    if total > EXPORT_MAX:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{total} rows match; exports are capped at {EXPORT_MAX}. Narrow the filters.",
        )

    title = d.title or f"{subject.label} report"
    params = rb.describe_filters(subject, d.filters, ctx)
    summary = subject.summarize(rows, ctx)
    headers = [c.label for c in columns]
    table = [[c.get(o, ctx) for c in columns] for o in rows]
    run_by = user.full_name or user.email

    await audit.record(
        db, actor=user, action="export", entity_type="report", entity_id=None,
        summary=f"Exported {subject.label.lower()} report '{title}' as {fmt.upper()} ({total} rows)",
        changes={"subject": subject.key, "format": fmt, "filters": d.filters, "rows": total},
    )

    if fmt == "csv":
        data = report_export.to_csv(headers, table).encode("utf-8-sig")
        return _file(data, _pdf_filename(title, subject, "csv"), "text/csv; charset=utf-8")

    if fmt == "xlsx":
        data = report_export.to_xlsx(
            title=title, org_name=ctx.org_name, subject_label=subject.label, run_by=run_by,
            params=params, summary=summary, headers=headers, rows=table,
        )
        return _file(
            data, _pdf_filename(title, subject, "xlsx"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # PDF. Wide reports go landscape; the widths are relative hints from the registry.
    widths = [c.width for c in columns]
    landscape = len(columns) > 7 or sum(widths) > 100
    detail = None
    if d.include_details and subject.has_detail:
        rctx = pdf_report.RiskReportContext(
            org_name=ctx.org_name, appetite=ctx.appetite, tolerance=ctx.tolerance,
            max_score=ctx.max_score, matrix_size=ctx.matrix_size,
            scope=" · ".join(v for _, v in params) or "Whole register",
            owner_names={uuid.UUID(k): v for k, v in ctx.names.items() if _is_uuid(k)},
        )
        detail = pdf_report.risk_detail_pages(rows, rctx)
    data = pdf_report.tabular_report_pdf(
        title=title, org_name=ctx.org_name, subject_label=subject.label, run_by=run_by,
        params=params, summary=summary, headers=headers, rows=[[_cell(v) for v in r] for r in table],
        widths=widths, landscape=landscape, detail=detail,
    )
    return _file(data, _pdf_filename(title, subject, "pdf"), "application/pdf")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _cell(value) -> str:
    return "" if value is None else str(value)


@router.post("/export")
async def export(
    body: ReportDefinition,
    db: DbSession,
    user: CurrentUser,
    format: Annotated[str, Query(pattern="^(pdf|xlsx|csv)$")] = "pdf",
) -> Response:
    """The whole matching set as a file. PDF for the pack, Excel for the analyst, CSV
    for anything else."""
    return await _export(db, user, body, format)


# ------------------------------------------------------------- saved reports ---
async def _load_saved(db, report_id: uuid.UUID, user) -> SavedReport:
    obj = await db.get(SavedReport, report_id)
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    if not (obj.shared or _is_admin(user) or obj.owner_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your report")
    return obj


def _definition(obj: SavedReport) -> ReportDefinition:
    d = dict(obj.definition or {})
    d["subject"] = obj.subject
    d.setdefault("title", obj.name)
    return ReportDefinition.model_validate(d)


@router.get("/saved", response_model=Page[SavedReportRead], dependencies=[Depends(require("report:read"))])
async def list_saved(
    db: DbSession, user: CurrentUser,
    subject: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SavedReportRead]:
    stmt = select(SavedReport)
    if not _is_admin(user):
        stmt = stmt.where((SavedReport.shared.is_(True)) | (SavedReport.owner_id == user.id))
    if subject:
        stmt = stmt.where(SavedReport.subject == subject)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(SavedReport.name).limit(limit).offset(offset))).all()
    return Page(items=[SavedReportRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/saved", response_model=SavedReportRead, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require("report:write"))])
async def create_saved(body: SavedReportCreate, db: DbSession, user: CurrentUser) -> SavedReportRead:
    subject = _subject(body.subject)
    _require_read(user, subject)
    obj = SavedReport(
        tenant_id=user.tenant_id, name=body.name, description=body.description,
        subject=subject.key, definition=body.definition, shared=body.shared,
        owner_id=user.id, owner_email=user.email,
    )
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="saved_report", entity_id=obj.id,
        summary=f"Saved {subject.label.lower()} report '{obj.name}'",
    )
    await db.refresh(obj)
    return SavedReportRead.model_validate(obj)


@router.get("/saved/{report_id}", response_model=SavedReportRead,
            dependencies=[Depends(require("report:read"))])
async def get_saved(report_id: uuid.UUID, db: DbSession, user: CurrentUser) -> SavedReportRead:
    return SavedReportRead.model_validate(await _load_saved(db, report_id, user))


@router.patch("/saved/{report_id}", response_model=SavedReportRead,
              dependencies=[Depends(require("report:write"))])
async def update_saved(
    report_id: uuid.UUID, body: SavedReportUpdate, db: DbSession, user: CurrentUser
) -> SavedReportRead:
    obj = await _load_saved(db, report_id, user)
    if obj.owner_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can edit this report")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="saved_report", entity_id=obj.id,
        summary=f"Updated saved report '{obj.name}'",
    )
    await db.refresh(obj)
    return SavedReportRead.model_validate(obj)


@router.delete("/saved/{report_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require("report:write"))])
async def delete_saved(report_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_saved(db, report_id, user)
    if obj.owner_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can delete this report")
    await audit.record(
        db, actor=user, action="delete", entity_type="saved_report", entity_id=obj.id,
        summary=f"Deleted saved report '{obj.name}'",
    )
    await db.delete(obj)


@router.get("/saved/{report_id}/export", dependencies=[Depends(require("report:read"))])
async def export_saved(
    report_id: uuid.UUID, db: DbSession, user: CurrentUser,
    format: Annotated[str, Query(pattern="^(pdf|xlsx|csv)$")] = "pdf",
) -> Response:
    """One click from the saved list to the file — the monthly pack, re-run live."""
    obj = await _load_saved(db, report_id, user)
    return await _export(db, user, _definition(obj), format)
