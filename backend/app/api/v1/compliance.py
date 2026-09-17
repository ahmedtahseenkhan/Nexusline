"""Compliance Management API — frameworks, requirements, control mapping, gaps.

Reuses the Control model: one control can be mapped to requirements across many
frameworks ("map once, comply many").
"""
from __future__ import annotations

import uuid
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.services import control_assurance
from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.compliance import (
    ComplianceFinding,
    Framework,
    Requirement,
    requirement_controls,
    requirement_crosswalks,
)
from app.models.control import Control
from app.models.enums import ComplianceStatus, FindingStatus
from app.models.evidence import Evidence
from app.schemas.common import Page
from app.schemas.compliance import (
    ApplicabilityUpdate,
    ComplianceFindingCreate,
    ComplianceFindingRead,
    ComplianceSummary,
    ControlMapping,
    CrosswalkItem,
    CrosswalkUpdate,
    FrameworkCreate,
    FrameworkPostureRead,
    FrameworkRead,
    FrameworkSummary,
    FrameworkUpdate,
    GapAnalysis,
    GapItem,
    RequirementCreate,
    RequirementRead,
    RequirementUpdate,
    SoaControlRead,
    SoaRowRead,
    SoaSummary,
    StatementOfApplicabilityRead,
)
from app.services import audit, compliance_posture, soa_export
from app.services.framework_library import normalize_name

router = APIRouter(tags=["compliance"])


@router.get("/requirements", dependencies=[Depends(require("compliance:read"))])
async def search_requirements(db: DbSession, search: str | None = None, limit: int = 20) -> list[dict]:
    """Flat, searchable requirements list across all frameworks — powers link pickers
    (the per-framework endpoint can't be server-typeaheaded)."""
    lim = max(1, min(limit, 50))
    stmt = (
        select(Requirement)
        .where(Requirement.deleted.is_(False))
        .options(selectinload(Requirement.framework))
    )
    if search:
        stmt = stmt.where(
            Requirement.title.ilike(f"%{search}%") | Requirement.reference.ilike(f"%{search}%")
        )
    rows = (await db.scalars(
        stmt.order_by(Requirement.reference_sort_key, Requirement.reference).limit(lim)
    )).all()
    return [
        {
            "id": str(r.id),
            "reference": r.reference,
            "title": r.title,
            "framework": r.framework.name if r.framework else "",
        }
        for r in rows
    ]


# --------------------------------------------------------------------- helpers
async def _load_framework(db, framework_id: uuid.UUID) -> Framework:
    fw = await db.scalar(
        select(Framework).where(Framework.id == framework_id, Framework.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if fw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Framework not found")
    return fw


async def _load_requirement(db, requirement_id: uuid.UUID) -> Requirement:
    req = await db.scalar(
        select(Requirement).where(Requirement.id == requirement_id, Requirement.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found"
        )
    return req


async def _resolve_controls(db, ids: Sequence[uuid.UUID]) -> list[Control]:
    if not ids:
        return []
    rows = (
        await db.scalars(
            select(Control).where(Control.id.in_(ids), Control.deleted.is_(False))
        )
    ).all()
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown control id(s): {sorted(map(str, missing))}",
        )
    return list(rows)


async def _resolve_any(db, model, ids):
    if not ids:
        return []
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    return list((await db.scalars(stmt)).all())


async def _attach_counts(db, reqs: list[Requirement]) -> None:
    """Set evidence_count and crosswalk_count on each requirement (non-mapped attrs)."""
    if not reqs:
        return
    ids = [r.id for r in reqs]

    ev = await db.execute(
        select(
            requirement_controls.c.requirement_id, func.count(func.distinct(Evidence.id))
        )
        .select_from(
            requirement_controls.join(
                Evidence, Evidence.control_id == requirement_controls.c.control_id
            )
        )
        .where(requirement_controls.c.requirement_id.in_(ids))
        .group_by(requirement_controls.c.requirement_id)
    )
    ev_map = {rid: cnt for rid, cnt in ev.all()}

    cw_map: dict = {}
    out = await db.execute(
        select(requirement_crosswalks.c.requirement_id, func.count())
        .where(requirement_crosswalks.c.requirement_id.in_(ids))
        .group_by(requirement_crosswalks.c.requirement_id)
    )
    inc = await db.execute(
        select(requirement_crosswalks.c.related_requirement_id, func.count())
        .where(requirement_crosswalks.c.related_requirement_id.in_(ids))
        .group_by(requirement_crosswalks.c.related_requirement_id)
    )
    for rid, cnt in out.all():
        cw_map[rid] = cw_map.get(rid, 0) + cnt
    for rid, cnt in inc.all():
        cw_map[rid] = cw_map.get(rid, 0) + cnt

    for r in reqs:
        r.evidence_count = ev_map.get(r.id, 0)
        r.crosswalk_count = cw_map.get(r.id, 0)


# ------------------------------------------------------------------ frameworks
async def _ensure_name_free(db, name: str, *, exclude_id: uuid.UUID | None = None) -> None:
    """One live framework per name (case-insensitive): the same standard entered twice
    counts every gap twice. The ``uq_frameworks_tenant_name`` index backs this up."""
    stmt = select(Framework.name).where(
        func.lower(func.trim(Framework.name)) == normalize_name(name),
        Framework.deleted.is_(False),
    )
    if exclude_id is not None:
        stmt = stmt.where(Framework.id != exclude_id)
    clash = await db.scalar(stmt.limit(1))
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A framework named {clash} already exists.",
        )


_FRAMEWORK_SORTABLE = {
    "name": Framework.name,
    "kind": Framework.kind,
    "authority": Framework.authority,
    "regulator": Framework.regulator,
    "workflow_status": Framework.workflow_status,
    "created_at": Framework.created_at,
}


@router.get(
    "/frameworks", response_model=Page[FrameworkRead], dependencies=[Depends(require("compliance:read"))]
)
async def list_frameworks(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FrameworkRead]:
    stmt = select(Framework).where(Framework.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Framework.name.ilike(like) | Framework.authority.ilike(like))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _FRAMEWORK_SORTABLE, default=Framework.name)
    else:
        stmt = stmt.order_by(Framework.name)
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(
        items=[FrameworkRead.model_validate(f) for f in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/frameworks",
    response_model=FrameworkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("compliance:write"))],
)
async def create_framework(
    body: FrameworkCreate, db: DbSession, user: CurrentUser
) -> FrameworkRead:
    await _ensure_name_free(db, body.name)
    fw = Framework(tenant_id=user.tenant_id, **body.model_dump())
    db.add(fw)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="framework", entity_id=fw.id,
        summary=f"Created framework {fw.name}",
    )
    await db.refresh(fw)
    return FrameworkRead.model_validate(fw)


@router.get(
    "/frameworks/{framework_id}",
    response_model=FrameworkRead,
    dependencies=[Depends(require("compliance:read"))],
)
async def get_framework(framework_id: uuid.UUID, db: DbSession) -> FrameworkRead:
    return FrameworkRead.model_validate(await _load_framework(db, framework_id))


@router.patch(
    "/frameworks/{framework_id}",
    response_model=FrameworkRead,
    dependencies=[Depends(require("compliance:write"))],
)
async def update_framework(
    framework_id: uuid.UUID, body: FrameworkUpdate, db: DbSession
) -> FrameworkRead:
    fw = await _load_framework(db, framework_id)
    data = body.model_dump(exclude_unset=True)
    for required in ("name", "kind"):
        if required in data and data[required] is None:
            data.pop(required)
    if "name" in data and normalize_name(data["name"]) != normalize_name(fw.name):
        await _ensure_name_free(db, data["name"], exclude_id=fw.id)
    for field, value in data.items():
        setattr(fw, field, value)
    await db.flush()
    await db.refresh(fw)
    return FrameworkRead.model_validate(fw)


@router.delete(
    "/frameworks/{framework_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("compliance:write"))],
)
async def delete_framework(framework_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    fw = await _load_framework(db, framework_id)
    fw.deleted = True
    fw.deleted_date = datetime.now(timezone.utc)


# ------------------------------------------------------------- framework library
@router.get("/framework-templates", dependencies=[Depends(require("compliance:read"))])
async def list_framework_templates() -> list[dict]:
    """Predefined standards that can be loaded into the tenant (e.g. ISO/IEC 42001)."""
    from app.services.framework_library import TEMPLATES, template_kind

    return [
        {
            "key": key,
            "name": t["name"],
            "version": t["version"],
            "authority": t["authority"],
            "description": t.get("description", ""),
            "requirement_count": len(t["requirements"]),
            "kind": template_kind(key),
        }
        for key, t in TEMPLATES.items()
    ]


@router.post(
    "/framework-templates/{key}/load",
    response_model=FrameworkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("compliance:write"))],
)
async def load_framework_template(key: str, db: DbSession, user: CurrentUser) -> FrameworkRead:
    """Create a framework and all its requirements from a built-in template — or, when
    the standard is already there under a legacy name or with clauses missing, upgrade
    that framework in place (missing clauses added, statuses and links kept).

    Same install path as the Framework Library page (``/content-library``), so both
    surfaces agree on what is installed and a standard cannot exist twice.
    """
    from app.services.framework_library import install_template

    fw = (await install_template(db, user, key)).framework
    await db.refresh(fw)
    return FrameworkRead.model_validate(fw)


# ----------------------------------------------------------------- requirements
_REQUIREMENT_SORTABLE = {
    # Natural order (A.5.2 before A.5.10), not text order (F-16).
    "reference": Requirement.reference_sort_key,
    "title": Requirement.title,
    "status": Requirement.status,
    "domain": Requirement.domain,
    "workflow_status": Requirement.workflow_status,
    "created_at": Requirement.created_at,
}


@router.get(
    "/frameworks/{framework_id}/requirements",
    response_model=Page[RequirementRead],
    dependencies=[Depends(require("compliance:read"))],
)
async def list_requirements(
    framework_id: uuid.UUID,
    db: DbSession,
    search: str | None = None,
    coverage: Annotated[str | None, Query(pattern="^(gaps|addressed)$")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RequirementRead]:
    await _load_framework(db, framework_id)
    stmt = select(Requirement).where(
        Requirement.framework_id == framework_id, Requirement.deleted.is_(False)
    )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Requirement.title.ilike(like) | Requirement.reference.ilike(like))
    if coverage == "gaps":
        stmt = stmt.where(_gap_predicate())
    elif coverage == "addressed":
        stmt = stmt.where(~_gap_predicate())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _REQUIREMENT_SORTABLE, default=Requirement.reference_sort_key)
    else:
        stmt = stmt.order_by(Requirement.reference_sort_key, Requirement.reference)
    rows = list((await db.scalars(stmt.limit(limit).offset(offset))).all())
    await _attach_counts(db, rows)
    items = []
    for row in rows:
        read = RequirementRead.model_validate(row)
        read.gap_reason = _gap_reason(row)
        items.append(read)
    return Page(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/frameworks/{framework_id}/requirements",
    response_model=RequirementRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("compliance:write"))],
)
async def create_requirement(
    framework_id: uuid.UUID, body: RequirementCreate, db: DbSession, user: CurrentUser
) -> RequirementRead:
    from app.models.policy import Policy
    from app.models.risk import Risk

    await _load_framework(db, framework_id)
    data = body.model_dump(exclude={"control_ids", "risk_ids", "policy_ids"})
    req = Requirement(tenant_id=user.tenant_id, framework_id=framework_id, **data)
    req.controls = await _resolve_controls(db, body.control_ids)
    req.risks = await _resolve_any(db, Risk, body.risk_ids)
    req.policies = await _resolve_any(db, Policy, body.policy_ids)
    db.add(req)
    await db.flush()
    loaded = await _load_requirement(db, req.id)
    await _attach_counts(db, [loaded])
    return RequirementRead.model_validate(loaded)


@router.get(
    "/requirements/{requirement_id}",
    response_model=RequirementRead,
    dependencies=[Depends(require("compliance:read"))],
)
async def get_requirement(requirement_id: uuid.UUID, db: DbSession) -> RequirementRead:
    req = await _load_requirement(db, requirement_id)
    await _attach_counts(db, [req])
    return RequirementRead.model_validate(req)


@router.patch(
    "/requirements/{requirement_id}",
    response_model=RequirementRead,
    dependencies=[Depends(require("compliance:write"))],
)
async def update_requirement(
    requirement_id: uuid.UUID, body: RequirementUpdate, db: DbSession
) -> RequirementRead:
    from app.models.policy import Policy
    from app.models.risk import Risk

    req = await _load_requirement(db, requirement_id)
    data = body.model_dump(exclude_unset=True)
    control_ids = data.pop("control_ids", None)
    risk_ids = data.pop("risk_ids", None)
    policy_ids = data.pop("policy_ids", None)
    if data.get("applicability_justification") is None:
        data.pop("applicability_justification", None)
    # Excluding a clause here (treatment or status "not applicable") is the same
    # decision as excluding it in the Statement of Applicability, and needs the same
    # justification. Only the transition is checked, so editing a clause excluded
    # before the rule existed does not start failing.
    was_applicable = soa_export.is_applicable(req.treatment, req.status)
    now_applicable = soa_export.is_applicable(
        data.get("treatment", req.treatment), data.get("status", req.status)
    )
    if was_applicable and not now_applicable:
        error = soa_export.applicability_error(
            False, data.get("applicability_justification", req.applicability_justification)
        )
        if error:
            raise HTTPException(status_code=422, detail=error)
    if control_ids is not None:
        req.controls = await _resolve_controls(db, control_ids)
    if risk_ids is not None:
        req.risks = await _resolve_any(db, Risk, risk_ids)
    if policy_ids is not None:
        req.policies = await _resolve_any(db, Policy, policy_ids)
    for field, value in data.items():
        setattr(req, field, value)
    await db.flush()
    loaded = await _load_requirement(db, req.id)
    await _attach_counts(db, [loaded])
    return RequirementRead.model_validate(loaded)


@router.put(
    "/requirements/{requirement_id}/controls",
    response_model=RequirementRead,
    dependencies=[Depends(require("compliance:write"))],
    summary="Replace the controls mapped to a requirement",
)
async def map_controls(
    requirement_id: uuid.UUID, body: ControlMapping, db: DbSession, user: CurrentUser
) -> RequirementRead:
    req = await _load_requirement(db, requirement_id)
    req.controls = await _resolve_controls(db, body.control_ids)
    await db.flush()
    await audit.record(
        db, actor=user, action="map_controls", entity_type="requirement",
        entity_id=req.id, summary=f"Mapped {len(req.controls)} control(s) to {req.reference}",
    )
    await db.refresh(req)
    return RequirementRead.model_validate(req)


@router.delete(
    "/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("compliance:write"))],
)
async def delete_requirement(requirement_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _load_requirement(db, requirement_id))


# ------------------------------------------------------ statement of applicability
def _require_compliance_kind(fw: Framework) -> None:
    if (fw.kind or "compliance") != "compliance":
        raise HTTPException(
            status_code=422,
            detail=(
                f"{fw.name} is a {fw.kind} framework: good practice to self-assess against, "
                "not an obligation, so it has no Statement of Applicability."
            ),
        )


async def _org_name(db, user) -> str:
    from app.models.tenant import Tenant

    tenant = await db.scalar(select(Tenant).where(Tenant.id == user.tenant_id))
    return tenant.name if tenant else "Organization"


def _soa_row(row: soa_export.SoaRow) -> SoaRowRead:
    return SoaRowRead(
        requirement_id=row.requirement_id,
        reference=row.reference,
        title=row.title,
        domain=row.domain,
        applicable=row.applicable,
        justification=row.justification,
        implementation_status=row.implementation_status,
        treatment=row.treatment,
        coverage=row.coverage,
        controls=[SoaControlRead(**vars(c)) for c in row.controls],
        last_test_date=row.last_test_date,
        last_test_result=row.last_test_result,
    )


async def _soa_document(db, user, framework_id: uuid.UUID, view: str | None = None):
    fw = await _load_framework(db, framework_id)
    _require_compliance_kind(fw)
    rows = soa_export.build_rows(fw.requirements)
    return fw, soa_export.SoaDocument(
        org_name=await _org_name(db, user),
        framework_name=fw.name,
        version=fw.version or "",
        rows=soa_export.filter_rows(rows, view),
        summary=soa_export.summarize(rows),
        view=view or "all",
    )


_SOA_VIEW = Query(None, pattern="^(all|applicable|excluded|no_control)$")


@router.get(
    "/compliance/frameworks/{framework_id}/soa",
    response_model=StatementOfApplicabilityRead,
    dependencies=[Depends(require("compliance:read"))],
    summary="Statement of Applicability for a compliance framework",
)
async def statement_of_applicability(
    framework_id: uuid.UUID, db: DbSession, user: CurrentUser, view: str | None = _SOA_VIEW,
) -> StatementOfApplicabilityRead:
    """One row per clause: applicable or excluded, the justification, the implementing
    controls with effectiveness and last test, and the implementation status. The
    summary always counts the whole framework; ``view`` filters only the rows."""
    fw, doc = await _soa_document(db, user, framework_id)
    return StatementOfApplicabilityRead(
        framework_id=fw.id,
        framework_name=fw.name,
        version=fw.version or "",
        organisation=doc.org_name,
        generated_at=doc.generated_at,
        summary=SoaSummary(**doc.summary),
        rows=[_soa_row(r) for r in soa_export.filter_rows(doc.rows, view)],
    )


def _download(data: bytes, filename: str, media_type: str):
    from urllib.parse import quote

    from fastapi.responses import Response

    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def _soa_filename(fw: Framework, ext: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in fw.name.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"soa-{slug[:60] or 'framework'}.{ext}"


@router.get(
    "/compliance/frameworks/{framework_id}/soa.xlsx",
    dependencies=[Depends(require("compliance:read"))],
    summary="Statement of Applicability as Excel",
)
async def statement_of_applicability_xlsx(
    framework_id: uuid.UUID, db: DbSession, user: CurrentUser, view: str | None = _SOA_VIEW,
):
    fw, doc = await _soa_document(db, user, framework_id, view)
    return _download(
        soa_export.to_xlsx(doc), _soa_filename(fw, "xlsx"),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get(
    "/compliance/frameworks/{framework_id}/soa.pdf",
    dependencies=[Depends(require("compliance:read"))],
    summary="Statement of Applicability as PDF",
)
async def statement_of_applicability_pdf(
    framework_id: uuid.UUID, db: DbSession, user: CurrentUser, view: str | None = _SOA_VIEW,
):
    fw, doc = await _soa_document(db, user, framework_id, view)
    return _download(soa_export.to_pdf(doc), _soa_filename(fw, "pdf"), "application/pdf")


@router.patch(
    "/requirements/{requirement_id}/applicability",
    response_model=SoaRowRead,
    dependencies=[Depends(require("compliance:write"))],
    summary="Include or exclude a clause in the Statement of Applicability",
)
async def set_applicability(
    requirement_id: uuid.UUID, body: ApplicabilityUpdate, db: DbSession, user: CurrentUser,
) -> SoaRowRead:
    """Excluding needs a justification (422 without one) and sets the clause's
    treatment and status to not applicable, so the gap analysis and compliance
    percentage stop counting it. Including resets only what said not applicable."""
    from app.models.enums import ComplianceTreatment

    req = await _load_requirement(db, requirement_id)
    error = soa_export.applicability_error(body.applicable, body.justification)
    if error:
        raise HTTPException(status_code=422, detail=error)
    fw = await _load_framework(db, req.framework_id)
    _require_compliance_kind(fw)

    was_applicable = soa_export.is_applicable(req.treatment, req.status)
    before = {
        "applicable": was_applicable,
        "justification": req.applicability_justification or "",
        "treatment": getattr(req.treatment, "value", req.treatment),
        "status": req.status.value,
    }
    for field, value in soa_export.applicability_changes(body.applicable, req.treatment, req.status).items():
        if field == "treatment":
            req.treatment = ComplianceTreatment(value) if value else None
        else:
            req.status = ComplianceStatus(value)
    req.applicability_justification = soa_export.justification_after(
        body.applicable, was_applicable, req.applicability_justification or "", body.justification,
    )
    await db.flush()
    after = {
        "applicable": body.applicable,
        "justification": req.applicability_justification,
        "treatment": getattr(req.treatment, "value", req.treatment),
        "status": req.status.value,
    }
    verb = "Included" if body.applicable else "Excluded"
    reason = f": {req.applicability_justification}" if req.applicability_justification else ""
    await audit.record(
        db, actor=user, action="applicability", entity_type="requirement", entity_id=req.id,
        summary=f"{verb} {req.reference or req.title} in the Statement of Applicability{reason}"[:500],
        changes={k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]},
    )
    loaded = await _load_requirement(db, req.id)
    return _soa_row(soa_export.build_row(loaded))


# ----------------------------------------------------------------- crosswalking
@router.put(
    "/requirements/{requirement_id}/crosswalks",
    response_model=list[CrosswalkItem],
    dependencies=[Depends(require("compliance:write"))],
    summary="Map equivalent requirements across frameworks",
)
async def set_crosswalks(
    requirement_id: uuid.UUID, body: CrosswalkUpdate, db: DbSession, user: CurrentUser
) -> list[CrosswalkItem]:
    await _load_requirement(db, requirement_id)
    targets = [rid for rid in body.related_requirement_ids if rid != requirement_id]
    if targets:
        found = (
            await db.scalars(
                select(Requirement.id).where(
                    Requirement.id.in_(targets), Requirement.deleted.is_(False)
                )
            )
        ).all()
        missing = set(targets) - set(found)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown requirement id(s): {sorted(map(str, missing))}",
            )
    # Replace this requirement's outgoing crosswalks.
    await db.execute(
        delete(requirement_crosswalks).where(
            requirement_crosswalks.c.requirement_id == requirement_id
        )
    )
    for target in targets:
        await db.execute(
            requirement_crosswalks.insert().values(
                requirement_id=requirement_id, related_requirement_id=target
            )
        )
    await audit.record(
        db, actor=user, action="crosswalk", entity_type="requirement",
        entity_id=requirement_id, summary=f"Set {len(targets)} crosswalk(s)",
    )
    return await _crosswalks_for(db, requirement_id)


@router.get(
    "/requirements/{requirement_id}/crosswalks",
    response_model=list[CrosswalkItem],
    dependencies=[Depends(require("compliance:read"))],
)
async def get_crosswalks(requirement_id: uuid.UUID, db: DbSession) -> list[CrosswalkItem]:
    await _load_requirement(db, requirement_id)
    return await _crosswalks_for(db, requirement_id)


# ------------------------------------------------- crosswalks between two frameworks
# Phase 3: suggested crosswalks (``services.clause_suggestions.suggest_crosswalks``) from
# the topic synonym table and from controls two clauses share. Suggestions are never
# written on their own; ``accept`` writes the pairs a person ticked, ``remove`` takes
# pairs out, and both are in the activity trail of the clauses involved.
from pydantic import BaseModel as _Model, Field as _Field  # noqa: E402

from app.services import clause_suggestions  # noqa: E402


class CrosswalkFrameworkRef(_Model):
    id: uuid.UUID
    name: str
    #: The library template it was installed from; None for a framework built in-house
    #: (only shared-control suggestions are possible for those).
    template_key: str | None = None


class CrosswalkSuggestionRead(_Model):
    requirement_id: uuid.UUID
    reference: str
    title: str
    framework_id: uuid.UUID
    related_requirement_id: uuid.UUID
    related_reference: str
    related_title: str
    related_framework_id: uuid.UUID
    #: 0-1. "high" from 0.75 (a primary clause of the same topic in both frameworks, or a
    #: topic match a shared control confirms); "medium" below.
    confidence: float
    strength: str
    reasons: list[str] = []
    sources: list[str] = []


class CrosswalkSuggestionsRead(_Model):
    from_framework: CrosswalkFrameworkRef
    to_framework: CrosswalkFrameworkRef
    #: Whether both frameworks come from the library, so the topic table applies.
    topic_matching: bool
    existing: int
    total: int
    suggestions: list[CrosswalkSuggestionRead]


class CrosswalkPairRead(_Model):
    requirement_id: uuid.UUID
    reference: str
    title: str
    related_requirement_id: uuid.UUID
    related_reference: str
    related_title: str


class CrosswalkPairsRead(_Model):
    from_framework: CrosswalkFrameworkRef
    to_framework: CrosswalkFrameworkRef
    pairs: list[CrosswalkPairRead]


class CrosswalkPair(_Model):
    requirement_id: uuid.UUID
    related_requirement_id: uuid.UUID


class CrosswalkPairsBody(_Model):
    pairs: list[CrosswalkPair] = _Field(min_length=1, max_length=1000)


class CrosswalkWriteResult(_Model):
    #: Pairs written (accept) or removed (remove).
    changed: int
    #: Pairs that were already crosswalked (accept) or not crosswalked (remove).
    skipped: int


def _fw_ref(fw, template_key) -> CrosswalkFrameworkRef:
    return CrosswalkFrameworkRef(id=fw.id, name=fw.name, template_key=template_key)


@router.get(
    "/compliance/crosswalks/suggest",
    response_model=CrosswalkSuggestionsRead,
    dependencies=[Depends(require("compliance:read"))],
    summary="Suggested crosswalks between two installed frameworks (nothing is written)",
)
async def suggest_crosswalks(
    db: DbSession,
    from_framework: uuid.UUID,
    to_framework: uuid.UUID,
    min_confidence: Annotated[float, Query(ge=0, le=1)] = 0.0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> CrosswalkSuggestionsRead:
    ctx, found = await clause_suggestions.crosswalk_suggestions_for(db, from_framework, to_framework)
    kept = [s for s in found if s.confidence >= min_confidence]
    return CrosswalkSuggestionsRead(
        from_framework=_fw_ref(ctx.from_framework, ctx.from_template),
        to_framework=_fw_ref(ctx.to_framework, ctx.to_template),
        topic_matching=bool(ctx.from_template and ctx.to_template),
        existing=len(ctx.existing), total=len(kept),
        suggestions=[CrosswalkSuggestionRead(**s.as_dict()) for s in kept[:limit]],
    )


@router.get(
    "/compliance/crosswalks",
    response_model=CrosswalkPairsRead,
    dependencies=[Depends(require("compliance:read"))],
    summary="Crosswalks already recorded between two frameworks",
)
async def list_framework_crosswalks(db: DbSession, from_framework: uuid.UUID, to_framework: uuid.UUID) -> CrosswalkPairsRead:
    ctx = await clause_suggestions.load_crosswalk_context(db, from_framework, to_framework)
    left = {c.requirement_id: c for c in ctx.from_clauses}
    right = {c.requirement_id: c for c in ctx.to_clauses}
    pairs = []
    for pair in ctx.existing:
        x, y = tuple(pair)
        a, b = (x, y) if x in left else (y, x)
        pairs.append(CrosswalkPairRead(
            requirement_id=a, reference=left[a].reference, title=left[a].title,
            related_requirement_id=b, related_reference=right[b].reference, related_title=right[b].title,
        ))
    nk = clause_suggestions.natural_key
    pairs.sort(key=lambda p: (nk(p.reference), nk(p.related_reference)))
    return CrosswalkPairsRead(
        from_framework=_fw_ref(ctx.from_framework, ctx.from_template),
        to_framework=_fw_ref(ctx.to_framework, ctx.to_template),
        pairs=pairs,
    )


async def _crosswalk_pairs(db, pairs: list[CrosswalkPair]) -> tuple[dict, list[tuple[uuid.UUID, uuid.UUID]]]:
    """Load every requirement the pairs name (live, with its framework) and normalise the
    pairs (deduplicated, either order). 400 for an unknown id, 422 for a pair within one
    framework."""
    ids = {p.requirement_id for p in pairs} | {p.related_requirement_id for p in pairs}
    reqs = {
        r.id: r for r in (await db.scalars(
            select(Requirement).options(selectinload(Requirement.framework))
            .where(Requirement.id.in_(ids), Requirement.deleted.is_(False))
        )).all()
    }
    missing = sorted(str(i) for i in ids - set(reqs))
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Unknown or archived requirement id(s): {', '.join(missing)}")
    out: list[tuple[uuid.UUID, uuid.UUID]] = []
    seen: set[frozenset] = set()
    for p in pairs:
        a, b = reqs[p.requirement_id], reqs[p.related_requirement_id]
        if a.framework_id == b.framework_id:
            raise HTTPException(
                status_code=422,
                detail=f"{a.reference or a.title} and {b.reference or b.title} are in the same framework; "
                       "a crosswalk links clauses of two different frameworks.",
            )
        key = frozenset((a.id, b.id))
        if key not in seen:
            seen.add(key)
            out.append((a.id, b.id))
    return reqs, out


async def _existing_crosswalks(db, ids) -> set[frozenset]:
    ids = list(ids)
    rows = (await db.execute(
        select(requirement_crosswalks.c.requirement_id, requirement_crosswalks.c.related_requirement_id)
        .where(requirement_crosswalks.c.requirement_id.in_(ids),
               requirement_crosswalks.c.related_requirement_id.in_(ids))
    )).all()
    return {frozenset((x, y)) for x, y in rows}


def _clause_label(req) -> str:
    fw = req.framework.name if req.framework else ""
    return f"{req.reference or req.title}" + (f" ({fw})" if fw else "")


async def _audit_crosswalk_change(db, user, reqs: dict, pairs: list[tuple[uuid.UUID, uuid.UUID]], verb: str) -> None:
    """One activity entry per source clause, naming the clauses it was linked to."""
    by_source: dict[uuid.UUID, list[uuid.UUID]] = {}
    for a, b in pairs:
        by_source.setdefault(a, []).append(b)
    for a, targets in by_source.items():
        names = ", ".join(_clause_label(reqs[b]) for b in targets)
        await audit.record(
            db, actor=user, action="crosswalk", entity_type="requirement", entity_id=a,
            summary=f"{verb} {_clause_label(reqs[a])} and {names}"[:500],
            changes={("added" if verb.startswith("Crosswalked") else "removed"): [
                {"id": str(b), "reference": reqs[b].reference, "framework": reqs[b].framework.name if reqs[b].framework else ""}
                for b in targets
            ], "via": "crosswalk view"},
        )


@router.post(
    "/compliance/crosswalks/accept",
    response_model=CrosswalkWriteResult,
    dependencies=[Depends(require("compliance:write"))],
    summary="Record crosswalks a person accepted (from suggestions or picked by hand)",
)
async def accept_crosswalks(body: CrosswalkPairsBody, db: DbSession, user: CurrentUser) -> CrosswalkWriteResult:
    reqs, pairs = await _crosswalk_pairs(db, body.pairs)
    existing = await _existing_crosswalks(db, list(reqs))
    new = [(a, b) for a, b in pairs if frozenset((a, b)) not in existing]
    for a, b in new:
        await db.execute(requirement_crosswalks.insert().values(requirement_id=a, related_requirement_id=b))
    await db.flush()
    await _audit_crosswalk_change(db, user, reqs, new, "Crosswalked")
    return CrosswalkWriteResult(changed=len(new), skipped=len(pairs) - len(new))


@router.post(
    "/compliance/crosswalks/remove",
    response_model=CrosswalkWriteResult,
    dependencies=[Depends(require("compliance:write"))],
    summary="Remove crosswalks between pairs of clauses",
)
async def remove_crosswalks(body: CrosswalkPairsBody, db: DbSession, user: CurrentUser) -> CrosswalkWriteResult:
    reqs, pairs = await _crosswalk_pairs(db, body.pairs)
    existing = await _existing_crosswalks(db, list(reqs))
    gone = [(a, b) for a, b in pairs if frozenset((a, b)) in existing]
    for a, b in gone:
        await db.execute(delete(requirement_crosswalks).where(
            ((requirement_crosswalks.c.requirement_id == a) & (requirement_crosswalks.c.related_requirement_id == b))
            | ((requirement_crosswalks.c.requirement_id == b) & (requirement_crosswalks.c.related_requirement_id == a))
        ))
    await db.flush()
    await _audit_crosswalk_change(db, user, reqs, gone, "Removed the crosswalk between")
    return CrosswalkWriteResult(changed=len(gone), skipped=len(pairs) - len(gone))


async def _crosswalks_for(db, requirement_id: uuid.UUID) -> list[CrosswalkItem]:
    out = (
        await db.scalars(
            select(requirement_crosswalks.c.related_requirement_id).where(
                requirement_crosswalks.c.requirement_id == requirement_id
            )
        )
    ).all()
    inc = (
        await db.scalars(
            select(requirement_crosswalks.c.requirement_id).where(
                requirement_crosswalks.c.related_requirement_id == requirement_id
            )
        )
    ).all()
    related_ids = set(out) | set(inc)
    if not related_ids:
        return []
    reqs = (
        await db.scalars(
            select(Requirement)
            .options(selectinload(Requirement.framework))
            .where(Requirement.id.in_(related_ids), Requirement.deleted.is_(False))
        )
    ).all()
    return [
        CrosswalkItem(
            id=r.id,
            reference=r.reference,
            title=r.title,
            status=r.status,
            framework_id=r.framework_id,
            framework_name=r.framework.name if r.framework else "",
        )
        for r in sorted(
            reqs,
            key=lambda r: ((r.framework.name if r.framework else "").lower(), soa_export.natural_key(r.reference), r.title),
        )
    ]


# ----------------------------------------------------------------- gap analysis
def _assessed(reqs: list[Requirement]) -> int:
    """Clauses somebody has assessed — the progress measure for a self-assessment."""
    return sum(1 for r in reqs if r.status != ComplianceStatus.not_assessed)


def _compliant_pct(reqs: list[Requirement]) -> tuple[int, int, float]:
    """Assessed compliant, of the applicable clauses. Only an assessment moves it —
    mapping a control does not; the posture shows mapped and tested beside it."""
    p = compliance_posture.posture(reqs)
    return p.compliant, p.applicable, p.compliant_pct


def _posture_read(p: compliance_posture.Posture) -> FrameworkPostureRead:
    return FrameworkPostureRead(**p.as_dict(), line=p.line)


# ---------------------------------------------------------------------------
# What counts as a gap
# ---------------------------------------------------------------------------
# A requirement is a gap when its status is not settled (compliant / not applicable)
# OR when no *working* control assures it. Both halves matter: "compliant" with nothing
# behind it is an assertion nobody can support, and an assured clause against a
# non-compliant status is work still outstanding.
#
# "Working" is the part that changed. Installing a framework now maps a control to every
# clause; if mapping alone counted, a freshly installed framework — 93 planned, untested
# controls — would look covered with nothing behind it. Coverage has states (unmapped,
# unassessed, failing, assured; see services.control_assurance) and only the last is
# coverage. A not-assessed control stays a gap until somebody tests it, and a test is
# what sets effectiveness, so the two rules meet in the middle.
#
# The rule lives here once because it is applied in two places — the requirements list
# filter and the gap-analysis roll-up — and the two disagreeing would mean the count in
# the header never matched the rows on screen.
_SETTLED = (ComplianceStatus.compliant, ComplianceStatus.not_applicable)

_COVERAGE_REASON = {
    control_assurance.UNMAPPED: "No controls mapped",
    control_assurance.UNASSESSED: "Controls mapped but none assessed yet",
    control_assurance.FAILING: "Mapped controls are ineffective",
}


def _gap_reason(requirement: Requirement) -> str:
    """Why this requirement is a gap, or ``""`` when it is not one."""
    # Nothing is required for a clause that does not apply — no control, no status.
    if requirement.status == ComplianceStatus.not_applicable:
        return ""
    unsettled = requirement.status not in _SETTLED
    coverage = requirement.coverage
    parts = []
    if coverage != control_assurance.ASSURED:
        parts.append(_COVERAGE_REASON[coverage])
    if unsettled:
        status = f"status is {requirement.status.value.replace('_', ' ')}"
        parts.append(status if parts else status[0].upper() + status[1:])
    return "; ".join(parts)


def _gap_predicate():
    """The same rule expressed in SQL, so the filter pages in the database.

    Assurance is tested with an EXISTS against the join table, restricted to live
    controls whose effectiveness counts — the exact set ``control_assurance`` uses —
    rather than by loading every row.
    """
    assured = (
        select(requirement_controls.c.requirement_id)
        .join(Control, Control.id == requirement_controls.c.control_id)
        .where(
            requirement_controls.c.requirement_id == Requirement.id,
            Control.deleted.is_(False),
            Control.effectiveness.in_(control_assurance.ASSURED_EFFECTIVENESS),
        )
        .exists()
    )
    return (Requirement.status != ComplianceStatus.not_applicable) & (
        Requirement.status.not_in(_SETTLED) | ~assured
    )


@router.get(
    "/frameworks/{framework_id}/gap-analysis",
    response_model=GapAnalysis,
    dependencies=[Depends(require("compliance:read"))],
)
async def gap_analysis(framework_id: uuid.UUID, db: DbSession) -> GapAnalysis:
    fw = await _load_framework(db, framework_id)
    reqs = fw.requirements
    by_status: dict[str, int] = {}
    covered = 0
    by_coverage: dict[str, int] = {}
    gaps: list[GapItem] = []
    for r in reqs:
        by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        if r.is_covered:
            covered += 1
        coverage = r.coverage
        by_coverage[coverage] = by_coverage.get(coverage, 0) + 1
        reason = _gap_reason(r)
        if reason:
            gaps.append(
                GapItem(
                    id=r.id, reference=r.reference, title=r.title, status=r.status,
                    is_covered=r.is_covered, coverage=coverage, reason=reason,
                )
            )
    compliant, _applicable, pct = _compliant_pct(reqs)
    return GapAnalysis(
        kind=fw.kind or "compliance",
        assessed=_assessed(reqs),
        framework_id=fw.id,
        framework_name=fw.name,
        total_requirements=len(reqs),
        by_status=by_status,
        covered=covered,
        uncovered=len(reqs) - covered,
        assured=by_coverage.get(control_assurance.ASSURED, 0),
        unassessed=by_coverage.get(control_assurance.UNASSESSED, 0),
        failing=by_coverage.get(control_assurance.FAILING, 0),
        compliant_pct=pct,
        gaps=gaps,
        posture=_posture_read(compliance_posture.posture(reqs)),
    )


@router.get(
    "/compliance/summary",
    response_model=ComplianceSummary,
    dependencies=[Depends(require("compliance:read"))],
)
async def compliance_summary(db: DbSession) -> ComplianceSummary:
    frameworks = (await db.scalars(
        select(Framework).where(Framework.deleted.is_(False)).order_by(Framework.name)
    )).all()
    rows: list[FrameworkSummary] = []
    total_reqs = 0
    counted: list[compliance_posture.Posture] = []
    for fw in frameworks:
        reqs = [r for r in fw.requirements if not r.deleted]
        fw_posture = compliance_posture.posture(reqs)
        compliant, pct = fw_posture.compliant, fw_posture.compliant_pct
        total_reqs += len(reqs)
        kind = fw.kind or "compliance"
        # A maturity self-assessment is not an obligation: it has no compliance score
        # and does not move the overall percentage.
        if kind == "compliance":
            counted.append(fw_posture)
        rows.append(
            FrameworkSummary(
                framework_id=fw.id,
                name=fw.name,
                kind=kind,
                total_requirements=len(reqs),
                compliant=compliant,
                compliant_pct=pct,
                assessed=_assessed(reqs),
                posture=_posture_read(fw_posture),
            )
        )
    overall = compliance_posture.combine(counted)
    return ComplianceSummary(
        total_frameworks=len(frameworks),
        total_requirements=total_reqs,
        overall_compliant_pct=overall.compliant_pct,
        overall_mapped_pct=overall.mapped_pct,
        overall_assured_pct=overall.assured_pct,
        frameworks=rows,
    )


# ------------------------------------------------------------ compliance findings
@router.get(
    "/requirements/{requirement_id}/findings",
    response_model=list[ComplianceFindingRead],
    dependencies=[Depends(require("compliance:read"))],
)
async def list_findings(requirement_id: uuid.UUID, db: DbSession) -> list[ComplianceFindingRead]:
    req = await _load_requirement(db, requirement_id)
    return [ComplianceFindingRead.model_validate(f) for f in req.findings if not f.deleted]


@router.post(
    "/requirements/{requirement_id}/findings",
    response_model=ComplianceFindingRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("compliance:write"))],
)
async def add_finding(
    requirement_id: uuid.UUID, body: ComplianceFindingCreate, db: DbSession, user: CurrentUser
) -> ComplianceFindingRead:
    await _load_requirement(db, requirement_id)
    finding = ComplianceFinding(tenant_id=user.tenant_id, requirement_id=requirement_id, **body.model_dump())
    db.add(finding)
    await db.flush()
    await audit.record(
        db, actor=user, action="finding", entity_type="requirement", entity_id=requirement_id,
        summary=f"Raised compliance finding: {finding.title}",
    )
    await db.refresh(finding)
    return ComplianceFindingRead.model_validate(finding)


@router.post(
    "/findings/{finding_id}/close",
    response_model=ComplianceFindingRead,
    dependencies=[Depends(require("compliance:write"))],
)
async def close_finding(finding_id: uuid.UUID, db: DbSession) -> ComplianceFindingRead:
    finding = await db.scalar(
        select(ComplianceFinding).where(
            ComplianceFinding.id == finding_id, ComplianceFinding.deleted.is_(False)
        )
    )
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    finding.status = FindingStatus.closed
    await db.flush()
    await db.refresh(finding)
    return ComplianceFindingRead.model_validate(finding)
