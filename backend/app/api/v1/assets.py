"""Asset Management — full eramba-parity API.

Assets with media type, RACI ownership (owner/guardian/user), CIA classifications,
labels, a review cycle, workflow status, soft-delete, and links to risks, processes,
legal obligations, compliance requirements, incidents, exceptions and related assets.
Plus the per-module lookup registries (media types, classification types, labels).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Enum as SAEnum
from sqlalchemy import case, delete, func, insert, literal, select
from sqlalchemy.orm import aliased, selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.core.schema_loading import options_for, serialize_all
from app.models.enums import Criticality
from app.models.asset import (
    Asset,
    AssetClassification,
    AssetClassificationType,
    AssetDependency,
    AssetLabel,
    AssetMediaType,
    AssetReview,
    AssetTag,
)
from app.models.enums import AssetClass, AssetEnvironment, AssetReviewStatus, WorkflowStatus
from app.models.exception import ExceptionRecord
from app.models.incident import Incident
from app.models.compliance import Requirement
from app.models.organization import BusinessUnit, Legal, Process
from app.models.risk import risk_assets
from app.schemas.asset import (
    AssetClassificationCreate,
    AssetClassificationRead,
    AssetClassificationTypeCreate,
    AssetClassificationTypeRead,
    AssetClassificationTypeUpdate,
    AssetClassificationUpdate,
    AssetCreate,
    AssetDependencyCreate,
    AssetDependencyRead,
    AssetLabelCreate,
    AssetLabelRead,
    AssetLabelUpdate,
    AssetMediaTypeCreate,
    AssetMediaTypeRead,
    AssetMediaTypeUpdate,
    AssetRead,
    AssetReviewComplete,
    AssetReviewCreate,
    AssetReviewRead,
    AssetTagCreate,
    AssetTagRead,
    AssetTagUpdate,
    AssetUpdate,
    ClassificationRef,
    ExceptionLinkRef,
    InformationAssetRef,
    LinkRef,
    RiskExposureRef,
)
from app.schemas.common import GraphRef, Page, exception_status
from app.services import asset_review, audit, fx, record_workflow, risk_integrity
from app.services.risk_scoring import AppetiteBook, SeverityScale, effective_score, next_review_date
from app.services.risk_settings import get_or_create_settings, load_appetite_book, scale_for

router = APIRouter(prefix="/assets", tags=["assets"])

# Relationship name -> (model, write-field on the schema)
_REL = {
    "classifications": (AssetClassification, "classification_ids"),
    "tags": (AssetTag, "tag_ids"),
    "processes": (Process, "process_ids"),
    "legals": (Legal, "legal_ids"),
    "requirements": (Requirement, "requirement_ids"),
    "incidents": (Incident, "incident_ids"),
    "exceptions": (ExceptionRecord, "exception_ids"),
}


def _loads():
    """Eager-load everything the serializer touches (incl. nested classification.type)."""
    return (
        selectinload(Asset.media_type),
        selectinload(Asset.label),
        selectinload(Asset.owner),
        selectinload(Asset.guardian),
        selectinload(Asset.user),
        selectinload(Asset.classifications).selectinload(AssetClassification.type),
        selectinload(Asset.tags),
        selectinload(Asset.hosted_dependencies).selectinload(AssetDependency.information_asset),
        selectinload(Asset.hosting_dependencies).selectinload(AssetDependency.it_asset),
        selectinload(Asset.processes),
        selectinload(Asset.legals),
        selectinload(Asset.requirements),
        selectinload(Asset.incidents),
        selectinload(Asset.exceptions),
        selectinload(Asset.related_assets),
        selectinload(Asset.risks),
        selectinload(Asset.reviews),
        selectinload(Asset.vendors),
        selectinload(Asset.access_reviews),
        selectinload(Asset.controls),
        selectinload(Asset.threats),
        selectinload(Asset.vulnerabilities),
        selectinload(Asset.continuity_plans),
        selectinload(Asset.processing_activities),
        selectinload(Asset.bia_assessments),
        selectinload(Asset.vuln_findings),
    )


#: Relationships ``_serialize`` reads beyond the ones ``AssetRead`` names.
_SERIALIZE_ALSO = (
    "classifications.type", "hosted_dependencies.information_asset", "hosting_dependencies.it_asset",
)


def _ref(obj) -> LinkRef | None:
    if obj is None:
        return None
    reference = str(getattr(obj, "reference", None) or "")
    name = str(getattr(obj, "name", None) or getattr(obj, "title", None) or "")
    return LinkRef(id=obj.id, label=reference or name or str(obj.id)[:8], reference=reference, name=name)


def _info_ref(obj) -> InformationAssetRef | None:
    """The information asset in a dependency, with its business value (B8)."""
    ref = _ref(obj)
    if ref is None:
        return None
    return InformationAssetRef(**ref.model_dump(), business_value=getattr(obj, "business_value", None))


def _dep_ref(dep: AssetDependency) -> AssetDependencyRead:
    return AssetDependencyRead(
        id=dep.id,
        relationship_type=dep.relationship_type,
        notes=dep.notes,
        information_asset=_info_ref(dep.information_asset),
        it_asset=_ref(dep.it_asset),
    )


def _exception_ref(x) -> ExceptionLinkRef:
    """A linked exception with its state and expiry (B3)."""
    ref = _ref(x)
    return ExceptionLinkRef(
        id=ref.id, label=ref.label,
        status=exception_status(getattr(x, "status", None), getattr(x, "expires_at", None)),
        expires_at=getattr(x, "expires_at", None),
    )


#: What an asset read needs to band its risks the way the register does: the tenant's
#: scale (bands and cell overrides) and appetite book. None = not loaded (the list), or
#: the viewer may not read risks.
Exposure = tuple[SeverityScale, AppetiteBook] | None


def risk_exposure_ref(r, exposure: Exposure = None, *, scores: bool = True) -> RiskExposureRef:
    """A risk on an asset (B8). Scores are given when ``scores`` (the viewer may read
    risks); the bands and the appetite status only with the tenant's ``exposure``
    context, using the rules ``RiskRead`` and the dashboard use: bands per matrix cell,
    appetite on the effective score (residual when assessed, else inherent) against the
    risk category's thresholds. ``label`` is the risk's title (the reference only when it
    has none); ``reference`` carries the reference. Pure."""
    # The label is the risk's name and the reference stays separate, so a chip reads
    # "R-002 Ransomware encrypts production systems" like every other linked record.
    reference = getattr(r, "reference", "") or ""
    label = getattr(r, "title", None) or getattr(r, "name", None) or reference or str(r.id)[:8]
    out = RiskExposureRef(id=r.id, label=str(label), reference=reference)
    if not scores:
        return out
    out.inherent_score = getattr(r, "inherent_score", None)
    out.residual_score = getattr(r, "residual_score", None)
    if exposure is not None:
        scale, book = exposure
        out.inherent_severity = scale.for_cell(r.inherent_likelihood, r.inherent_impact)
        out.residual_severity = scale.for_cell(r.residual_likelihood, r.residual_impact)
        out.appetite_status = book.status(
            effective_score(out.inherent_score, out.residual_score), getattr(r, "category_id", None)
        )
    return out


def _can_read_risks(user) -> bool:
    return "risk:read" in set(getattr(user, "permission_codes", None) or [])


async def _exposure(db, asset: Asset, user) -> Exposure:
    """The tenant's scale and appetite for banding the asset's risks — only for a viewer
    who may read risks: an asset reader without ``risk:read`` sees which risks sit on the
    asset (as before), not their scores' judgements."""
    if not _can_read_risks(user) or not asset.risks:
        return None
    settings = await get_or_create_settings(db, asset.tenant_id)
    return scale_for(settings), await load_appetite_book(db, asset.tenant_id, settings)


async def _read(db, asset: Asset, user) -> AssetRead:
    """The single-asset read (and every write response): risks carry their exposure.
    Serialised where a link the loader left out can still be lazy-loaded."""
    exposure = await _exposure(db, asset, user)
    can_read_risks = _can_read_risks(user)
    return (await serialize_all(db, [asset], lambda a: _serialize(a, exposure, can_read_risks=can_read_risks)))[0]


def _serialize(a: Asset, exposure: Exposure = None, *, can_read_risks: bool = False) -> AssetRead:
    # An IT asset shows the info assets it hosts; an information asset shows the IT it runs on.
    deps = a.hosted_dependencies if a.asset_class == AssetClass.it_asset else a.hosting_dependencies
    return AssetRead(
        id=a.id,
        name=a.name,
        description=a.description,
        asset_class=a.asset_class,
        media_type=_ref(a.media_type),
        label=_ref(a.label),
        owner=_ref(a.owner),
        guardian=_ref(a.guardian),
        user=_ref(a.user),
        confidentiality=a.confidentiality,
        integrity=a.integrity,
        availability=a.availability,
        criticality=a.criticality,
        classification=a.classification,
        potential_liabilities=a.potential_liabilities,
        business_value=a.business_value,
        information_owner=a.information_owner,
        data_categories=a.data_categories,
        records_volume=a.records_volume,
        self_assessed=a.self_assessed,
        assessed_by=a.assessed_by,
        assessed_date=a.assessed_date,
        replacement_cost=float(a.replacement_cost or 0),
        currency=a.currency,
        rto_hours=a.rto_hours,
        rpo_hours=a.rpo_hours,
        environment=a.environment,
        location=a.location,
        hostname=a.hostname,
        ip_address=a.ip_address,
        serial_number=a.serial_number,
        manufacturer=a.manufacturer,
        model_number=a.model_number,
        os_version=a.os_version,
        discovery_source=a.discovery_source,
        external_id=a.external_id,
        auto_discovered=a.auto_discovered,
        last_seen=a.last_seen,
        cost_band=a.cost_band,
        intrinsic_criticality=a.intrinsic_criticality,
        derived_criticality=a.derived_criticality,
        effective_criticality=a.effective_criticality,
        review_frequency=a.review_frequency,
        next_review_date=a.next_review_date,
        last_review_date=a.last_review_date,
        expired_reviews=a.expired_reviews,
        review_status=a.review_status,
        workflow_status=a.workflow_status,
        classifications=[
            ClassificationRef(id=c.id, name=c.name, value=c.value, type_name=c.type.name if c.type else "")
            for c in a.classifications
        ],
        tags=[AssetTagRead.model_validate(t) for t in a.tags],
        dependencies=[_dep_ref(d) for d in deps],
        processes=[_ref(x) for x in a.processes],
        legals=[_ref(x) for x in a.legals],
        requirements=[_ref(x) for x in a.requirements],
        incidents=[_ref(x) for x in a.incidents],
        exceptions=[_exception_ref(x) for x in a.exceptions],
        related_assets=[_ref(x) for x in a.related_assets],
        risks=[risk_exposure_ref(x, exposure, scores=can_read_risks) for x in a.risks],
        vendors=[GraphRef.model_validate(x) for x in a.vendors],
        access_reviews=[GraphRef.model_validate(x) for x in a.access_reviews],
        controls=[GraphRef.model_validate(x) for x in a.controls],
        threats=[GraphRef.model_validate(x) for x in a.threats],
        vulnerabilities=[GraphRef.model_validate(x) for x in a.vulnerabilities],
        continuity_plans=[GraphRef.model_validate(x) for x in a.continuity_plans],
        processing_activities=[GraphRef.model_validate(x) for x in a.processing_activities],
        # One BIA can list the asset as several dependencies; show it once.
        bia_assessments=[GraphRef(id=b.id, reference=b.reference or "", name=b.process_name or "")
                         for b in {b.id: b for b in a.bia_assessments}.values()],
        vuln_findings=[GraphRef.model_validate(x) for x in a.vuln_findings],
        reviews=[AssetReviewRead.model_validate(r) for r in a.reviews],
        risk_count=len(a.risks),
        review_count=len(a.reviews),
        created_at=a.created_at,
    )


def _record_loads() -> tuple:
    """What one asset's read and writes load: every link the record shows (so writes can
    assign collections without a lazy load) and nothing behind those links. ``_loads()``
    alone let each linked risk bring its own assets and theirs — a single asset loaded
    thousands, and PATCH, review and delete took seconds to minutes at bank scale."""
    return (*_loads(), *options_for(Asset, AssetRead, _SERIALIZE_ALSO))


async def _get_or_404(db, asset_id: uuid.UUID) -> Asset:
    asset = await db.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.deleted.is_(False)).options(*_record_loads())
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


async def _fresh(db, asset_id: uuid.UUID) -> Asset:
    return await db.scalar(
        select(Asset).where(Asset.id == asset_id).options(*_record_loads())
        .execution_options(populate_existing=True)
    )


async def _load_many(db, model, ids):
    if not ids:
        return []
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    return list((await db.scalars(stmt)).all())


async def _set_risk_links(db, asset_id, risk_ids) -> None:
    """Replace the asset's rows in the risk_assets join table.

    Asset.risks is a viewonly reverse view (the writable side lives on Risk.assets),
    so we manage the association table directly — like policies._set_assoc.
    """
    if risk_ids is None:
        return
    await db.execute(delete(risk_assets).where(risk_assets.c.asset_id == asset_id))
    if risk_ids:
        await db.execute(
            insert(risk_assets), [{"asset_id": asset_id, "risk_id": rid} for rid in risk_ids]
        )


async def _apply_orm_relations(db, asset: Asset, data: dict) -> None:
    """Assign writable M2M relationships. Call while the asset is PENDING (pre-flush)
    or already eager-loaded, else async lazy-load fires MissingGreenlet."""
    for rel, (model, field) in _REL.items():
        if field in data and data[field] is not None:
            setattr(asset, rel, await _load_many(db, model, data[field]))
    if data.get("related_ids") is not None:
        related = await _load_many(db, Asset, [i for i in data["related_ids"] if i != asset.id])
        asset.related_assets = related


async def _apply_relations(db, asset: Asset, data: dict) -> None:
    """Update path: asset is already eager-loaded, so ORM assignment is safe here."""
    await _apply_orm_relations(db, asset, data)
    if "risk_ids" in data:
        await _set_risk_links(db, asset.id, data["risk_ids"])


def _crit(value: Criticality):
    return literal(value, SAEnum(Criticality, name="criticality", create_type=False))


def effective_criticality_expr():
    """``Asset.effective_criticality`` in SQL, so the register sorts by the badge it shows.

    Postgres orders the ``criticality`` enum low → critical, so GREATEST/MAX rank it:
    an information asset is its business value; an IT asset the highest of its cost band
    (the ``cost_band`` thresholds), its availability requirement and the business value
    of the live information assets it carries."""
    cost_band = case(
        (Asset.replacement_cost >= 10_000_000, _crit(Criticality.critical)),
        (Asset.replacement_cost >= 2_000_000, _crit(Criticality.high)),
        (Asset.replacement_cost >= 250_000, _crit(Criticality.medium)),
        else_=_crit(Criticality.low),
    )
    info = aliased(Asset)
    hosted = (
        select(func.max(info.business_value))
        .select_from(AssetDependency)
        .join(info, AssetDependency.information_asset_id == info.id)
        .where(AssetDependency.it_asset_id == Asset.id, info.deleted.is_(False))
        .correlate(Asset)
        .scalar_subquery()
    )
    it_value = func.greatest(cost_band, Asset.availability, func.coalesce(hosted, _crit(Criticality.low)))
    return case((Asset.asset_class == AssetClass.it_asset, it_value), else_=Asset.business_value)


# Columns a client may sort the asset list by (allow-list — keeps the API and any
# future index in agreement and blocks sorting by arbitrary/unindexed columns). Computed
# columns the registers show (effective criticality, owning unit) sort by the same value.
_ASSET_SORTABLE = {
    "name": Asset.name,
    "created_at": Asset.created_at,
    "business_value": Asset.business_value,
    "effective_criticality": effective_criticality_expr(),
    "owner": select(BusinessUnit.name).where(BusinessUnit.id == Asset.owner_id).correlate(Asset).scalar_subquery(),
    "availability": Asset.availability,
    "next_review_date": Asset.next_review_date,
    "self_assessed": Asset.self_assessed,
    "replacement_cost": Asset.replacement_cost,
    "environment": Asset.environment,
}


def asset_filters(
    *, search: str | None = None, asset_class: AssetClass | None = None,
    media_type_id: uuid.UUID | None = None, review_overdue: bool | None = None,
    environment: AssetEnvironment | None = None, effective_criticality: Criticality | None = None,
    workflow_status: WorkflowStatus | None = None,
) -> list:
    """The register's filters as WHERE clauses — shared by the list and the export, so
    "export what I'm looking at" exports exactly the rows on screen."""
    where: list = []
    if search:
        like = f"%{search}%"
        where.append(
            Asset.name.ilike(like) | Asset.information_owner.ilike(like)
            | Asset.hostname.ilike(like) | Asset.ip_address.ilike(like)
        )
    if asset_class:
        where.append(Asset.asset_class == asset_class)
    if media_type_id:
        where.append(Asset.media_type_id == media_type_id)
    if review_overdue:
        where.append(Asset.next_review_date < date.today())
    if environment:
        where.append(Asset.environment == environment)
    if effective_criticality:
        where.append(effective_criticality_expr() == _crit(effective_criticality))
    if workflow_status:
        where.append(Asset.workflow_status == workflow_status)
    return where


@router.get("", response_model=Page[AssetRead], dependencies=[Depends(require("asset:read"))])
async def list_assets(
    db: DbSession,
    user: CurrentUser,
    search: Annotated[str | None, Query()] = None,
    asset_class: Annotated[AssetClass | None, Query(description="Filter by IT vs Information asset")] = None,
    media_type_id: Annotated[uuid.UUID | None, Query()] = None,
    review_overdue: Annotated[bool | None, Query()] = None,
    # The narrowing a 6,000-row register needs beyond search: where it runs, how
    # critical it is (the value the register shows, not the stored input) and where it
    # is in its approval lifecycle.
    environment: Annotated[AssetEnvironment | None, Query()] = None,
    effective_criticality: Annotated[Criticality | None, Query()] = None,
    workflow_status: Annotated[WorkflowStatus | None, Query()] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AssetRead]:
    stmt = select(Asset).where(Asset.deleted.is_(False), *asset_filters(
        search=search, asset_class=asset_class, media_type_id=media_type_id,
        review_overdue=review_overdue, environment=environment,
        effective_criticality=effective_criticality, workflow_status=workflow_status,
    ))
    params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
    stmt = apply_sort(stmt, params, _ASSET_SORTABLE, default=Asset.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    # ``_serialize`` reads the links ``AssetRead`` names (``schema_loading``) and the
    # dependencies' assets and classifications' types — not the links' own links.
    loads = (*_loads(), *options_for(Asset, AssetRead, _SERIALIZE_ALSO))
    rows = (await db.scalars(stmt.options(*loads).limit(limit).offset(offset))).all()
    can_read_risks = _can_read_risks(user)
    items = await serialize_all(db, rows, lambda r: _serialize(r, can_read_risks=can_read_risks))
    return Page(items=items, total=total, limit=limit, offset=offset)


async def replacement_value(db, filters) -> dict:
    """Replacement cost of the matching assets in the reporting currency (``MoneyTotalRead``
    shape): one grouped query, converted at today's rate; currencies with no rate are listed
    in ``unconverted`` and left out of ``total``."""
    groups = (await db.execute(
        select(Asset.currency, func.coalesce(func.sum(Asset.replacement_cost), 0), func.count())
        .where(*filters, Asset.replacement_cost > 0)
        .group_by(Asset.currency)
    )).all()
    book = await fx.load_rate_book(db) if groups else fx.RateBook(await fx.reporting_currency(db))
    total = fx.MoneyTotal(book)
    for code, amount, count in groups:
        total.add(amount, code, count=int(count or 0))
    return total.as_dict()


@router.get("/summary", dependencies=[Depends(require("asset:read"))])
async def asset_summary(
    db: DbSession,
    asset_class: Annotated[AssetClass | None, Query()] = None,
) -> dict:
    """Server-computed stat-card figures (correct at any scale — never derived from a
    truncated page fetch)."""
    filters = [Asset.deleted.is_(False)]
    if asset_class:
        filters.append(Asset.asset_class == asset_class)

    def _count(extra=None):
        conds = filters + ([extra] if extra is not None else [])
        return select(func.count()).select_from(Asset).where(*conds)

    total = await db.scalar(_count()) or 0
    # --- information-asset figures ---
    high_val = await db.scalar(_count(Asset.business_value.in_([Criticality.high, Criticality.critical]))) or 0
    self_assessed = await db.scalar(_count(Asset.self_assessed.is_(True))) or 0
    with_pii = await db.scalar(_count(Asset.data_categories.ilike("%pii%"))) or 0
    # --- IT-asset figures (server-computed so the stat cards are right at any scale) ---
    production = await db.scalar(_count(Asset.environment == AssetEnvironment.production)) or 0
    # Decision 4: replacement cost is summed per currency, then converted to the reporting
    # currency at today's rate (a stock figure: what replacing the estate costs now).
    replacement = await replacement_value(db, filters)
    # The same expression the register sorts and filters by, so the tile agrees with the
    # column: an information asset is critical by its business value, an IT asset by
    # cost band, availability or the data it carries. The tile used the IT formula for
    # both classes, so on the information register it counted availability instead of
    # business value and disagreed with every row beneath it.
    effective_critical = await db.scalar(
        _count(effective_criticality_expr() == _crit(Criticality.critical))
    ) or 0
    return {
        "total": total,
        "high_or_critical_value": high_val,
        "self_assessed": self_assessed,
        "self_assessed_pct": round(self_assessed / total * 100, 1) if total else 0.0,
        "with_pii": with_pii,
        "production": production,
        "total_replacement_value": replacement["total"],
        "replacement_value": replacement,
        "effective_critical": effective_critical,
    }


@router.post("", response_model=AssetRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_asset(body: AssetCreate, db: DbSession, user: CurrentUser) -> AssetRead:
    data = body.model_dump()
    rel_data = {k: data.pop(k) for k in list(data) if k.endswith("_ids")}
    if data.get("next_review_date") is None:
        data["next_review_date"] = next_review_date(body.review_frequency, date.today())
    asset = Asset(tenant_id=user.tenant_id, **data)
    await _apply_orm_relations(db, asset, rel_data)  # assign while PENDING (no lazy-load)
    db.add(asset)
    await db.flush()
    if "risk_ids" in rel_data:  # viewonly reverse view -> direct join-table write, needs id
        await _set_risk_links(db, asset.id, rel_data["risk_ids"])
    await db.flush()
    await audit.record(db, actor=user, action="create", entity_type="asset", entity_id=asset.id,
                       summary=f"Created asset {asset.name}")
    return await _read(db, await _fresh(db, asset.id), user)


@router.get("/{asset_id}", response_model=AssetRead, dependencies=[Depends(require("asset:read"))])
async def get_asset(asset_id: uuid.UUID, db: DbSession, user: CurrentUser) -> AssetRead:
    """The asset. Its ``risks`` carry their scores, bands and appetite status (for a
    viewer who holds ``risk:read``); its information-asset dependencies carry their
    business value; its exceptions their status and expiry."""
    return await _read(db, await _get_or_404(db, asset_id), user)


#: Changes to what an approver signed off: the asset's classification, the inputs its
#: criticality is computed from, and who owns it. On an approved asset they send it back
#: for review, with the editor as its submitter — so someone else approves the new
#: classification (maker-checker; ISO/IEC 27001 A.5.9, A.5.12). Technical details
#: (hostname, IP, OS, location), links and the review schedule don't.
MATERIAL_FIELDS: frozenset[str] = frozenset({
    "asset_class", "confidentiality", "integrity", "availability", "business_value",
    "replacement_cost", "currency", "environment", "rto_hours", "rpo_hours",
    "owner_id", "guardian_id", "user_id", "information_owner", "label_id",
    "data_categories", "classification_ids",
})

#: Scalar reference fields, shown in the trail by the name they point at.
_NAMED_REFS = {
    "owner_id": BusinessUnit, "guardian_id": BusinessUnit, "user_id": BusinessUnit,
    "media_type_id": AssetMediaType, "label_id": AssetLabel,
}


def _text(value) -> str | None:
    """A value as the activity trail shows it."""
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _link_label(obj) -> str:
    return (getattr(obj, "reference", "") or getattr(obj, "name", "") or getattr(obj, "title", "") or str(obj.id))


def _link_names(asset: Asset, field: str) -> list[str]:
    """The names behind a ``*_ids`` field, as currently loaded on the asset."""
    rel = next((r for r, (_m, f) in _REL.items() if f == field), None)
    rel = rel or {"related_ids": "related_assets", "risk_ids": "risks"}.get(field)
    if rel is None:
        return []
    return sorted(_link_label(o) for o in (getattr(asset, rel, None) or []))


async def _ref_name(db, model, ref_id) -> str | None:
    if ref_id is None:
        return None
    obj = await db.get(model, ref_id)
    return getattr(obj, "name", None) or str(ref_id)


@router.patch("/{asset_id}", response_model=AssetRead, dependencies=[Depends(require("asset:write"))])
async def update_asset(asset_id: uuid.UUID, body: AssetUpdate, db: DbSession, user: CurrentUser) -> AssetRead:
    """Update the asset. The trail records each changed field's old and new value. A
    material change to an approved asset (``MATERIAL_FIELDS``) reopens it and submits
    it for review. The review date moves only within the rules of
    ``services.asset_review``: an overdue review is cleared by completing it."""
    asset = await _get_or_404(db, asset_id)
    data = body.model_dump(exclude_unset=True)
    rel_data = {k: data.pop(k) for k in list(data) if k.endswith("_ids")}
    if "next_review_date" in data:
        problem = asset_review.date_change_problem(
            asset.next_review_date, data["next_review_date"],
            data.get("review_frequency", asset.review_frequency), date.today(),
        )
        if problem:
            raise HTTPException(status_code=422, detail=f"The review date can't change: {problem}.")

    fields: dict[str, dict] = {}
    for field, value in data.items():
        old = getattr(asset, field)
        if _text(old) != _text(value):
            if field in _NAMED_REFS:
                fields[field] = {"from": await _ref_name(db, _NAMED_REFS[field], old),
                                 "to": await _ref_name(db, _NAMED_REFS[field], value)}
            else:
                fields[field] = {"from": _text(old), "to": _text(value)}
        setattr(asset, field, value)
    links_before = {f: _link_names(asset, f) for f, ids in rel_data.items() if ids is not None}
    await _apply_relations(db, asset, rel_data)
    await db.flush()
    if links_before:
        asset = await _fresh(db, asset.id)
        for f, before in links_before.items():
            after = _link_names(asset, f)
            if after != before:
                fields[f] = {"from": ", ".join(before) or None, "to": ", ".join(after) or None}
    if "next_review_date" in fields:
        await asset_review.sync_schedule(db, asset)

    changed = ", ".join(f.removesuffix("_ids").removesuffix("_id").replace("_", " ") for f in fields)
    await audit.record(db, actor=user, action="update", entity_type="asset", entity_id=asset.id,
                       summary=(f"Updated asset {asset.name}: {changed}" if changed else f"Updated asset {asset.name}")[:500],
                       changes={"fields": fields} if fields else None)

    material = [f for f in fields if f in MATERIAL_FIELDS]
    if material and record_workflow.state_value(asset.workflow_status) == record_workflow.APPROVED:
        what = ", ".join(f.removesuffix("_ids").removesuffix("_id").replace("_", " ") for f in material)
        await record_workflow.apply(
            db, user, asset, "asset", "revise", f"Changed {what} on the approved asset"[:500]
        )
        await record_workflow.apply(db, user, asset, "asset", "submit")
    return await _read(db, await _fresh(db, asset.id), user)


class AssetImpact(BaseModel):
    """Live records that link to an asset — what deleting it would touch."""

    risks: int
    controls: int


@router.get("/{asset_id}/impact", response_model=AssetImpact, dependencies=[Depends(require("asset:read"))])
async def asset_impact(asset_id: uuid.UUID, db: DbSession) -> AssetImpact:
    """Counts for the delete confirmation: linked live risks are flagged for review when
    the asset goes, so the person deleting it should know how many first."""
    await _get_or_404(db, asset_id)
    return AssetImpact(**await risk_integrity.asset_impact(db, asset_id))


@router.delete("/{asset_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_asset(asset_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Soft delete. Every live risk written against the asset is kept and flagged
    ``needs_review`` with the asset's name, so a person decides what happens to it —
    nothing is archived or relinked on its own."""
    from datetime import datetime, timezone

    asset = await _get_or_404(db, asset_id)
    risks = await risk_integrity.live_risks_for_assets(db, [asset.id])
    flagged = risk_integrity.flag_for_asset_removal(risks, asset.name)
    asset.deleted = True
    asset.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    summary = f"Archived asset {asset.name}"
    if flagged:
        summary += f"; flagged {flagged} linked risk(s) for review"
    await audit.record(db, actor=user, action="delete", entity_type="asset", entity_id=asset.id,
                       summary=summary,
                       changes={"risks_flagged": ", ".join(sorted(r.reference for r in risks))} if flagged else None)


# ----------------------------------------------------------------- review cycle
@router.get("/{asset_id}/reviews", response_model=list[AssetReviewRead], dependencies=[Depends(require("asset:read"))])
async def list_reviews(asset_id: uuid.UUID, db: DbSession) -> list[AssetReviewRead]:
    asset = await _get_or_404(db, asset_id)
    return [AssetReviewRead.model_validate(r) for r in asset.reviews]


@router.post("/{asset_id}/reviews", response_model=AssetRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def schedule_review(asset_id: uuid.UUID, body: AssetReviewCreate, db: DbSession, user: CurrentUser) -> AssetRead:
    asset = await _get_or_404(db, asset_id)
    # Scheduling sets the next review date, so it follows the same rule as editing it:
    # an overdue review is cleared by completing it, not by scheduling a later one.
    problem = asset_review.date_change_problem(
        asset.next_review_date, body.scheduled_date, asset.review_frequency, date.today()
    )
    if problem:
        raise HTTPException(status_code=422, detail=f"The review can't be scheduled then: {problem}.")
    before = asset.next_review_date
    pending = await asset_review.pending_review(db, asset.id)
    if pending is not None:
        # One pending review carries the next date; a second would leave the first
        # sitting on the old date. Reschedule it instead.
        pending.scheduled_date = body.scheduled_date
        if body.reviewer:
            pending.reviewer = body.reviewer
        if body.comments:
            pending.comments = body.comments
    else:
        db.add(AssetReview(tenant_id=asset.tenant_id, asset_id=asset.id, reviewer=body.reviewer,
                           scheduled_date=body.scheduled_date, comments=body.comments,
                           status=AssetReviewStatus.scheduled))
    asset.next_review_date = body.scheduled_date
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="asset", entity_id=asset.id,
        summary=f"Scheduled a review of asset {asset.name} for {body.scheduled_date.isoformat()}",
        changes={"next_review_date": {"from": before.isoformat() if before else None,
                                      "to": body.scheduled_date.isoformat()},
                 **({"reviewer": body.reviewer} if body.reviewer else {})},
    )
    return await _read(db, await _fresh(db, asset.id), user)


@router.post("/{asset_id}/reviews/{review_id}/complete", response_model=AssetRead, dependencies=[Depends(require("asset:write"))])
async def complete_review(asset_id: uuid.UUID, review_id: uuid.UUID, body: AssetReviewComplete, db: DbSession, user: CurrentUser) -> AssetRead:
    asset = await _get_or_404(db, asset_id)
    review = await db.scalar(select(AssetReview).where(AssetReview.id == review_id, AssetReview.asset_id == asset_id))
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status == AssetReviewStatus.completed:
        raise HTTPException(status_code=409, detail="That review is already completed.")
    today = date.today()
    review.status = AssetReviewStatus.completed
    review.actual_date = today
    review.outcome = body.outcome
    review.completed_by = asset_review.completer_name(user)
    review.completed_by_id = user.id
    if body.comments:
        review.comments = body.comments
    asset.last_review_date = today
    asset.next_review_date = next_review_date(asset.review_frequency, today)
    await db.flush()
    # The next cycle is scheduled now, for whoever was planned for this one.
    await asset_review.sync_schedule(db, asset, reviewer=review.reviewer)
    await audit.record(db, actor=user, action="review", entity_type="asset", entity_id=asset.id,
                       summary=f"Reviewed asset {asset.name} ({body.outcome})",
                       changes={"completed_by": review.completed_by,
                                "planned_reviewer": review.reviewer or None,
                                "next_review_date": _text(asset.next_review_date)})
    await db.flush()
    return await _read(db, await _fresh(db, asset.id), user)


# -------------------------------------------- information ↔ IT dependency links
@router.get("/{asset_id}/dependencies", response_model=list[AssetDependencyRead], dependencies=[Depends(require("asset:read"))])
async def list_dependencies(asset_id: uuid.UUID, db: DbSession) -> list[AssetDependencyRead]:
    asset = await _get_or_404(db, asset_id)
    deps = asset.hosted_dependencies if asset.asset_class == AssetClass.it_asset else asset.hosting_dependencies
    return [_dep_ref(d) for d in deps]


@router.post("/dependencies", response_model=AssetDependencyRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_dependency(body: AssetDependencyCreate, db: DbSession, user: CurrentUser) -> AssetDependencyRead:
    """Link an information asset to the IT asset that carries it (so criticality inherits)."""
    info = await db.scalar(select(Asset).where(Asset.id == body.information_asset_id, Asset.deleted.is_(False)))
    it = await db.scalar(select(Asset).where(Asset.id == body.it_asset_id, Asset.deleted.is_(False)))
    if info is None or it is None:
        raise HTTPException(status_code=404, detail="Both information and IT assets must exist")
    if info.asset_class != AssetClass.information_asset:
        raise HTTPException(status_code=422, detail="information_asset_id must reference an information asset")
    if it.asset_class != AssetClass.it_asset:
        raise HTTPException(status_code=422, detail="it_asset_id must reference an IT asset")
    dep = AssetDependency(
        tenant_id=user.tenant_id,
        information_asset_id=body.information_asset_id,
        it_asset_id=body.it_asset_id,
        relationship_type=body.relationship_type,
        notes=body.notes,
    )
    db.add(dep)
    await db.flush()
    dep = await db.scalar(
        select(AssetDependency).where(AssetDependency.id == dep.id).execution_options(populate_existing=True)
    )
    return _dep_ref(dep)


@router.delete("/dependencies/{dependency_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_dependency(dependency_id: uuid.UUID, db: DbSession) -> None:
    dep = await db.get(AssetDependency, dependency_id)
    if dep is not None:
        await db.delete(dep)


# ----------------------------------------------------------------- labels lookup
labels_router = APIRouter(prefix="/asset-labels", tags=["assets"])


@labels_router.get("", response_model=list[AssetLabelRead], dependencies=[Depends(require("asset:read"))])
async def list_asset_labels(db: DbSession) -> list[AssetLabelRead]:
    rows = (await db.scalars(select(AssetLabel).order_by(AssetLabel.name))).all()
    return [AssetLabelRead.model_validate(r) for r in rows]


@labels_router.post("", response_model=AssetLabelRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_asset_label(body: AssetLabelCreate, db: DbSession, user: CurrentUser) -> AssetLabelRead:
    obj = AssetLabel(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return AssetLabelRead.model_validate(obj)


@labels_router.patch("/{label_id}", response_model=AssetLabelRead, dependencies=[Depends(require("asset:write"))])
async def update_asset_label(label_id: uuid.UUID, body: AssetLabelUpdate, db: DbSession) -> AssetLabelRead:
    obj = await db.get(AssetLabel, label_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Label not found")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, name, value)
    await db.flush()
    await db.refresh(obj)
    return AssetLabelRead.model_validate(obj)


@labels_router.delete("/{label_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_asset_label(label_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.get(AssetLabel, label_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Label not found")
    await db.delete(obj)


# ------------------------------------------------------------- media types lookup
media_types_router = APIRouter(prefix="/asset-media-types", tags=["assets"])


@media_types_router.get("", response_model=list[AssetMediaTypeRead], dependencies=[Depends(require("asset:read"))])
async def list_media_types(db: DbSession) -> list[AssetMediaTypeRead]:
    rows = (await db.scalars(select(AssetMediaType).order_by(AssetMediaType.name))).all()
    return [AssetMediaTypeRead.model_validate(r) for r in rows]


@media_types_router.post("", response_model=AssetMediaTypeRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_media_type(body: AssetMediaTypeCreate, db: DbSession, user: CurrentUser) -> AssetMediaTypeRead:
    obj = AssetMediaType(tenant_id=user.tenant_id, editable=True, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return AssetMediaTypeRead.model_validate(obj)


@media_types_router.patch("/{type_id}", response_model=AssetMediaTypeRead, dependencies=[Depends(require("asset:write"))])
async def update_media_type(type_id: uuid.UUID, body: AssetMediaTypeUpdate, db: DbSession) -> AssetMediaTypeRead:
    obj = await db.get(AssetMediaType, type_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Media type not found")
    data = body.model_dump(exclude_unset=True)
    # Built-ins are the fixed taxonomy assets reference — renaming one would silently
    # reclassify every asset, so only the description may be clarified.
    if not obj.editable and "name" in data and data["name"] != obj.name:
        raise HTTPException(status_code=409, detail="Built-in media type cannot be renamed")
    for name, value in data.items():
        setattr(obj, name, value)
    await db.flush()
    await db.refresh(obj)
    return AssetMediaTypeRead.model_validate(obj)


@media_types_router.delete("/{type_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_media_type(type_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.get(AssetMediaType, type_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Media type not found")
    if not obj.editable:
        raise HTTPException(status_code=409, detail="Built-in media type cannot be deleted")
    await db.delete(obj)


# ------------------------------------------------- classification types + values
class_router = APIRouter(prefix="/asset-classification-types", tags=["assets"])


@class_router.get("", response_model=list[AssetClassificationTypeRead], dependencies=[Depends(require("asset:read"))])
async def list_classification_types(db: DbSession) -> list[AssetClassificationTypeRead]:
    rows = (await db.scalars(select(AssetClassificationType).order_by(AssetClassificationType.name))).all()
    return [AssetClassificationTypeRead.model_validate(r) for r in rows]


@class_router.post("", response_model=AssetClassificationTypeRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_classification_type(body: AssetClassificationTypeCreate, db: DbSession, user: CurrentUser) -> AssetClassificationTypeRead:
    obj = AssetClassificationType(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    return AssetClassificationTypeRead.model_validate(await db.scalar(
        select(AssetClassificationType).where(AssetClassificationType.id == obj.id).execution_options(populate_existing=True)
    ))


@class_router.patch("/{type_id}", response_model=AssetClassificationTypeRead, dependencies=[Depends(require("asset:write"))])
async def update_classification_type(type_id: uuid.UUID, body: AssetClassificationTypeUpdate, db: DbSession) -> AssetClassificationTypeRead:
    obj = await db.get(AssetClassificationType, type_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Classification type not found")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, name, value)
    await db.flush()
    return AssetClassificationTypeRead.model_validate(await db.scalar(
        select(AssetClassificationType).where(AssetClassificationType.id == type_id).execution_options(populate_existing=True)
    ))


@class_router.delete("/{type_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_classification_type(type_id: uuid.UUID, db: DbSession) -> None:
    """Deletes the axis and its values; assets keep working — their links cascade away."""
    obj = await db.get(AssetClassificationType, type_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Classification type not found")
    await db.delete(obj)


@class_router.patch("/classifications/{classification_id}", response_model=AssetClassificationRead, dependencies=[Depends(require("asset:write"))])
async def update_classification(classification_id: uuid.UUID, body: AssetClassificationUpdate, db: DbSession) -> AssetClassificationRead:
    obj = await db.get(AssetClassification, classification_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Classification not found")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, name, value)
    await db.flush()
    await db.refresh(obj)
    return AssetClassificationRead.model_validate(obj)


@class_router.post("/{type_id}/classifications", response_model=AssetClassificationRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def add_classification(type_id: uuid.UUID, body: AssetClassificationCreate, db: DbSession, user: CurrentUser) -> AssetClassificationRead:
    if await db.get(AssetClassificationType, type_id) is None:
        raise HTTPException(status_code=404, detail="Classification type not found")
    obj = AssetClassification(tenant_id=user.tenant_id, type_id=type_id, name=body.name, criteria=body.criteria, value=body.value)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return AssetClassificationRead.model_validate(obj)


@class_router.delete("/classifications/{classification_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_classification(classification_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.get(AssetClassification, classification_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Classification not found")
    await db.delete(obj)


# --------------------------------------------------------- IT asset tags lookup
tags_router = APIRouter(prefix="/asset-tags", tags=["assets"])


@tags_router.get("", response_model=list[AssetTagRead], dependencies=[Depends(require("asset:read"))])
async def list_asset_tags(db: DbSession) -> list[AssetTagRead]:
    rows = (await db.scalars(select(AssetTag).order_by(AssetTag.name))).all()
    return [AssetTagRead.model_validate(r) for r in rows]


@tags_router.post("", response_model=AssetTagRead, status_code=201, dependencies=[Depends(require("asset:write"))])
async def create_asset_tag(body: AssetTagCreate, db: DbSession, user: CurrentUser) -> AssetTagRead:
    obj = AssetTag(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return AssetTagRead.model_validate(obj)


@tags_router.patch("/{tag_id}", response_model=AssetTagRead, dependencies=[Depends(require("asset:write"))])
async def update_asset_tag(tag_id: uuid.UUID, body: AssetTagUpdate, db: DbSession) -> AssetTagRead:
    obj = await db.get(AssetTag, tag_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, name, value)
    await db.flush()
    await db.refresh(obj)
    return AssetTagRead.model_validate(obj)


@tags_router.delete("/{tag_id}", status_code=204, dependencies=[Depends(require("asset:write"))])
async def delete_asset_tag(tag_id: uuid.UUID, db: DbSession) -> None:
    obj = await db.get(AssetTag, tag_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    await db.delete(obj)
