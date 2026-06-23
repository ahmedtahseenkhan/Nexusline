"""Compliance Management API — frameworks, requirements, control mapping, gaps.

Reuses the Control model: one control can be mapped to requirements across many
frameworks ("map once, comply many").
"""
from __future__ import annotations

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from sqlalchemy import delete, func
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
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
    ComplianceFindingCreate,
    ComplianceFindingRead,
    ComplianceSummary,
    ControlMapping,
    CrosswalkItem,
    CrosswalkUpdate,
    FrameworkCreate,
    FrameworkRead,
    FrameworkSummary,
    FrameworkUpdate,
    GapAnalysis,
    GapItem,
    RequirementCreate,
    RequirementRead,
    RequirementUpdate,
)
from app.services import audit

router = APIRouter(tags=["compliance"])


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
    rows = (await db.scalars(select(Control).where(Control.id.in_(ids)))).all()
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
    return list((await db.scalars(select(model).where(model.id.in_(ids)))).all())


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
@router.get(
    "/frameworks", response_model=Page[FrameworkRead], dependencies=[Depends(require("compliance:read"))]
)
async def list_frameworks(db: DbSession) -> Page[FrameworkRead]:
    rows = (await db.scalars(
        select(Framework).where(Framework.deleted.is_(False)).order_by(Framework.name)
    )).all()
    return Page(
        items=[FrameworkRead.model_validate(f) for f in rows],
        total=len(rows),
        limit=len(rows),
        offset=0,
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
    for field, value in body.model_dump(exclude_unset=True).items():
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


# ----------------------------------------------------------------- requirements
@router.get(
    "/frameworks/{framework_id}/requirements",
    response_model=list[RequirementRead],
    dependencies=[Depends(require("compliance:read"))],
)
async def list_requirements(framework_id: uuid.UUID, db: DbSession) -> list[RequirementRead]:
    await _load_framework(db, framework_id)
    rows = list(
        (
            await db.scalars(
                select(Requirement)
                .where(Requirement.framework_id == framework_id, Requirement.deleted.is_(False))
                .order_by(Requirement.reference)
            )
        ).all()
    )
    await _attach_counts(db, rows)
    return [RequirementRead.model_validate(r) for r in rows]


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
            await db.scalars(select(Requirement.id).where(Requirement.id.in_(targets)))
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
            .where(Requirement.id.in_(related_ids))
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
        for r in reqs
    ]


# ----------------------------------------------------------------- gap analysis
def _compliant_pct(reqs: list[Requirement]) -> tuple[int, int, float]:
    applicable = [r for r in reqs if r.status != ComplianceStatus.not_applicable]
    compliant = sum(1 for r in applicable if r.status == ComplianceStatus.compliant)
    pct = round(100 * compliant / len(applicable), 1) if applicable else 0.0
    return compliant, len(applicable), pct


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
    gaps: list[GapItem] = []
    for r in reqs:
        by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        if r.is_covered:
            covered += 1
        is_gap = r.status not in (ComplianceStatus.compliant, ComplianceStatus.not_applicable)
        if is_gap or not r.is_covered:
            if not r.is_covered and is_gap:
                reason = "No controls mapped and not compliant"
            elif not r.is_covered:
                reason = "No controls mapped"
            else:
                reason = f"Status is {r.status.value}"
            gaps.append(
                GapItem(
                    id=r.id, reference=r.reference, title=r.title, status=r.status,
                    is_covered=r.is_covered, reason=reason,
                )
            )
    compliant, _applicable, pct = _compliant_pct(reqs)
    return GapAnalysis(
        framework_id=fw.id,
        framework_name=fw.name,
        total_requirements=len(reqs),
        by_status=by_status,
        covered=covered,
        uncovered=len(reqs) - covered,
        compliant_pct=pct,
        gaps=gaps,
    )


@router.get(
    "/compliance/summary",
    response_model=ComplianceSummary,
    dependencies=[Depends(require("compliance:read"))],
)
async def compliance_summary(db: DbSession) -> ComplianceSummary:
    frameworks = (await db.scalars(select(Framework).order_by(Framework.name))).all()
    rows: list[FrameworkSummary] = []
    total_reqs = 0
    total_compliant = 0
    total_applicable = 0
    for fw in frameworks:
        compliant, applicable, pct = _compliant_pct(fw.requirements)
        total_reqs += len(fw.requirements)
        total_compliant += compliant
        total_applicable += applicable
        rows.append(
            FrameworkSummary(
                framework_id=fw.id,
                name=fw.name,
                total_requirements=len(fw.requirements),
                compliant=compliant,
                compliant_pct=pct,
            )
        )
    overall = round(100 * total_compliant / total_applicable, 1) if total_applicable else 0.0
    return ComplianceSummary(
        total_frameworks=len(frameworks),
        total_requirements=total_reqs,
        overall_compliant_pct=overall,
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
    finding = await db.scalar(select(ComplianceFinding).where(ComplianceFinding.id == finding_id))
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    finding.status = FindingStatus.closed
    await db.flush()
    await db.refresh(finding)
    return ComplianceFindingRead.model_validate(finding)
