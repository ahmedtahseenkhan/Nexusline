"""Third-Party / Vendor Risk API — vendor registry, types, service contracts, and
links to the risks/assets a third party touches. eramba record envelope (soft-delete).

Phase 2 (F-11) adds the due-diligence record: legal name and registration number, a
relationship owner, the highest data classification accessed, data-residency countries,
supported processes, sub-contractors ("fourth parties", with the reverse "is a
sub-contractor of"), annual spend in its own currency, certifications with expiry
alerts, the SBP outsourcing facts of linked arrangements (read-only), and the inherent
risk tier derived from the "Inherent risk tiering" questionnaire
(``services/vendor_tiering.py``) with an audited, reasoned criticality override."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.core.schema_loading import options_for, serialize_all
from app.models.asset import Asset
from app.models.assessment import Questionnaire
from app.models.compliance import Requirement
from app.models.control import Control
from app.models.enums import Criticality, VendorStatus
from app.models.lookup import Lookup
from app.models.organization import Process
from app.models.risk import Risk
from app.models.settings import TenantSettings
from app.models.vendor import ServiceContract, Vendor, VendorCertification, VendorType
from app.schemas.common import GraphRef, Page
from app.schemas.vendor import (
    CERT_TYPES,
    ServiceContractCreate,
    VendorCertificationCreate,
    VendorCertificationRead,
    VendorCertificationUpdate,
    VendorConcentration,
    VendorCreate,
    VendorOutsourcingFacts,
    VendorRead,
    VendorTiering,
    VendorTypeCreate,
    VendorTypeRead,
    VendorTypeUpdate,
    VendorUpdate,
)
from app.services import audit, delete_guard, drill_through, fx, master_data
from app.schemas.fx import MoneyTotalRead
from app.services import ref_fields as rf
from app.services import vendor_tiering as vt

router = APIRouter(prefix="/vendors", tags=["vendors"])

# Phase 1 picker fields (services/ref_fields). ``country_id`` has no text twin: the
# vendor's ``location`` is a city or address and stays free text.
VENDOR_REFS = (
    rf.lookup(Vendor, "category_id", "category"),
    rf.lookup(Vendor, "country_id", None),
    rf.WORKFLOW_OWNER,
)
# Phase 2 picker fields with no legacy text twin (declared here, not through
# ``rf.lookup``: the boot backfill has nothing to match for them).
DUE_DILIGENCE_REFS = (
    rf.RefField("relationship_owner_id", None, "user"),
    rf.RefField("data_classification_id", None, "lookup", "data_classification"),
)
ALL_REFS = VENDOR_REFS + DUE_DILIGENCE_REFS

#: The link-list fields a vendor write carries, popped before the scalar fields are set.
_LINK_FIELDS = (
    "risk_ids", "asset_ids", "requirement_ids", "control_ids",
    "process_ids", "subcontractor_ids", "data_residency_country_ids",
)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


async def _org_currency(db, tenant_id) -> str:
    """The organisation's currency (Settings → Organisation), PKR if never set."""
    if tenant_id is None:
        return "PKR"
    value = await db.scalar(select(TenantSettings.currency).where(TenantSettings.tenant_id == tenant_id))
    return value or "PKR"


def contract_totals(contracts, org_currency: str) -> dict[str, float]:
    """Live (unexpired) contract value per currency; a blank currency is the
    organisation's. Pure."""
    totals: dict[str, float] = {}
    for c in contracts:
        if c.is_expired or c.value is None:
            continue
        code = (c.currency or org_currency or "PKR").upper()
        totals[code] = round(totals.get(code, 0.0) + float(c.value), 2)
    return totals


def contract_total(contracts, book: fx.RateBook) -> dict:
    """Live contract value in the reporting currency at today's rate (``MoneyTotalRead``
    shape); a blank contract currency is the reporting currency, and values with no rate
    are listed in ``unconverted`` rather than added. Pure."""
    total = fx.MoneyTotal(book)
    for c in contracts:
        if c.is_expired or c.value is None:
            continue
        total.add(c.value, c.currency)
    return total.as_dict()


async def _rate_book_for(db, org_currency: str, codes) -> fx.RateBook:
    """The rate book, loaded only when some amount is in a currency other than the
    organisation's (so an all-PKR register costs no extra query)."""
    foreign = {str(c or "").strip().upper() for c in codes} - {"", org_currency}
    if not foreign:
        return fx.RateBook(org_currency)
    return await fx.load_rate_book(db, reporting=org_currency)


def outsourcing_facts(arrangements, country_labels: dict) -> list[VendorOutsourcingFacts]:
    """The live outsourcing arrangements' SBP facts, for the read-only block. Pure."""
    out = []
    for a in arrangements:
        if getattr(a, "deleted", False):
            continue
        ref = country_labels.get(getattr(a, "country_id", None))
        out.append(VendorOutsourcingFacts(
            id=a.id, reference=a.reference or "", title=a.title or "",
            status=getattr(a.status, "value", a.status) or "",
            materiality=getattr(a.materiality, "value", a.materiality) or "",
            is_cloud=bool(a.is_cloud), data_offshored=bool(a.data_offshored),
            country=(ref.label if ref is not None else "") or (a.country or ""),
            sbp_approval_status=getattr(a.sbp_approval_status, "value", a.sbp_approval_status) or "",
            contract_end=a.contract_end, exit_plan=a.exit_plan or "",
            exit_plan_tested=bool(a.exit_plan_tested),
            materiality_assessment=getattr(a, "materiality_assessment", "") or "",
            substitutability=getattr(a, "substitutability", "") or "",
            concentration_level=getattr(a, "concentration_level", "") or "",
            concentration_note=getattr(a, "concentration_note", "") or "",
        ))
    return out


#: Criticality words that make a third party (or a process it supports) critical.
_CRITICAL = ("high", "critical")
_LEVEL_RANK = {"": 0, "low": 1, "medium": 2, "high": 3}
#: Live material arrangements / high-or-critical processes at which concentration is high.
HIGH_MATERIAL_ARRANGEMENTS = 2
HIGH_CRITICAL_PROCESSES = 3


def _word(value) -> str:
    return str(getattr(value, "value", value) or "")


def concentration_view(vendor, arrangements=None, processes=None) -> VendorConcentration:
    """How much depends on this third party (F-11). Pure.

    Counts the live (not terminated) arrangements — material ones apart — and the
    supported processes rated high or critical, and takes the highest concentration
    level recorded on an arrangement. High when an arrangement says high, when two or
    more material arrangements rely on the provider, or when three or more critical
    processes do; medium when one material arrangement or one or two critical processes
    do, or an arrangement says medium."""
    on_file = [
        a for a in (arrangements if arrangements is not None else getattr(vendor, "outsourcing_arrangements", None) or [])
        if not getattr(a, "deleted", False)
    ]
    arrangements = [a for a in on_file if _word(a.status) != "terminated"]
    processes = [
        p for p in (processes if processes is not None else getattr(vendor, "processes", None) or [])
        if not getattr(p, "deleted", False)
    ]
    material = [a for a in arrangements if _word(a.materiality) == "material"]
    critical = [p for p in processes if _word(getattr(p, "criticality", None)) in _CRITICAL]
    recorded = max((_word(getattr(a, "concentration_level", "")) for a in arrangements),
                   key=lambda v: _LEVEL_RANK.get(v, 0), default="")
    reasons: list[str] = []
    if recorded == "high":
        reasons.append("An outsourcing arrangement records high concentration on this provider.")
    if len(material) >= HIGH_MATERIAL_ARRANGEMENTS:
        reasons.append(f"{len(material)} material outsourcing arrangements rely on this provider.")
    if len(critical) >= HIGH_CRITICAL_PROCESSES:
        reasons.append(f"{len(critical)} high or critical processes depend on this provider.")
    level = "high" if reasons else "medium" if (recorded == "medium" or material or critical) else "low"
    crit = _word(getattr(vendor, "criticality", None))
    tier = _word(getattr(vendor, "inherent_tier", None))
    # Any arrangement on file, even a terminated one, means the decision was made.
    expected = not on_file and (crit in _CRITICAL or tier in _CRITICAL or bool(critical))
    return VendorConcentration(
        material_arrangements=len(material), arrangements=len(arrangements),
        critical_processes=len(critical), processes=len(processes),
        recorded_level=recorded, level=level, flagged=level == "high", reasons=reasons,
        arrangement_expected=expected,
    )


def tiering_view(vendor, questionnaire_id=None) -> VendorTiering:
    """How the stored tier was derived, recomputed from the latest completed tiering
    assessment so the page can show the score and flag a stale tier. Pure."""
    tier = vendor.inherent_tier
    proposed = vt.TIER_TO_CRITICALITY.get(tier) if tier else None
    crit = getattr(vendor.criticality, "value", vendor.criticality)
    view = VendorTiering(
        tier=tier, proposed_criticality=proposed,
        overridden=bool(proposed and crit != proposed),
        override_reason=vendor.tier_override_reason or "",
        questionnaire_id=questionnaire_id,
    )
    latest = vt.latest_completed(getattr(vendor, "assessments", []) or [])
    if latest is None:
        return view
    view.assessment = GraphRef(id=latest.id, title=latest.title or "")
    view.submitted_at = latest.submitted_at
    try:
        result = vt.tier_assessment(latest)
    except vt.TieringError as exc:
        view.problem = str(exc)
        view.stale = True
        return view
    view.total_score = result.total_score
    view.max_score = result.max_score
    view.score_pct = result.score_pct
    view.band_tier = result.band_tier
    view.worst_case_answers = result.worst_case_answers
    view.floor_applied = result.floor_applied
    view.explanation = result.explanation()
    view.stale = result.tier != tier
    return view


async def _tiering_questionnaire_id(db):
    """The published tiering questionnaire (``purpose = vendor_tiering``, phase 4E): the
    newest published version, so a new tiering assessment pins it."""
    rows = (await db.execute(
        select(Questionnaire.id, Questionnaire.purpose, Questionnaire.status, Questionnaire.version)
        .order_by(Questionnaire.version.desc())
    )).all()
    for qid, purpose, q_status, _version in rows:
        if vt.is_tiering_questionnaire(SimpleNamespace(purpose=purpose)) and q_status == "published":
            return qid
    return None


async def _reads(db, rows) -> list[VendorRead]:
    items = await serialize_all(db, rows, VendorRead.model_validate)
    await rf.fill_refs(db, list(zip(rows, items)), ALL_REFS)
    if not rows:
        return items
    org_ccy = await _org_currency(db, getattr(rows[0], "tenant_id", None))
    arrangements = [a for r in rows for a in (getattr(r, "outsourcing_arrangements", None) or [])]
    labels = await master_data.lookups_by_id(db, (a.country_id for a in arrangements))
    qid = await _tiering_questionnaire_id(db)
    book = await _rate_book_for(db, org_ccy, (c.currency for r in rows for c in (r.contracts or [])))

    def fill(row, item):
        item.active_contract_totals = contract_totals(row.contracts, org_ccy)
        item.active_contract_total = MoneyTotalRead(**contract_total(row.contracts, book))
        item.outsourcing = outsourcing_facts(getattr(row, "outsourcing_arrangements", None) or [], labels)
        item.concentration = concentration_view(row)
        item.tiering = tiering_view(row, qid)
        item.due_diligence = _due_diligence_view(row)
        return item

    # The views read the assessments' questionnaires and answers (``_VIEW_READS``); run
    # them where anything a list did not load can still be lazy-loaded.
    return await serialize_all(db, list(zip(rows, items)), lambda pair: fill(*pair))


#: Relationships the tiering, due-diligence and concentration views read, beyond the
#: ones ``VendorRead`` names — loaded with a list (``schema_loading``).
_VIEW_READS = (
    "assessments.questionnaire.questions.options",
    "assessments.answers.option",
    "assessments.findings.issue",
    "outsourcing_arrangements",
    "processes",
)


async def _read(db, vendor_id: uuid.UUID) -> VendorRead:
    return (await _reads(db, [await _load(db, vendor_id)]))[0]


def _loads():
    return (
        selectinload(Vendor.type),
        selectinload(Vendor.contracts),
        selectinload(Vendor.risks),
        selectinload(Vendor.assets),
        selectinload(Vendor.processes),
        selectinload(Vendor.subcontractors),
        selectinload(Vendor.subcontractor_of),
        selectinload(Vendor.data_residency_countries),
        selectinload(Vendor.certifications),
        selectinload(Vendor.outsourcing_arrangements),
        selectinload(Vendor.assessments),
    )


async def _load(db, vendor_id: uuid.UUID) -> Vendor:
    obj = await db.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.deleted.is_(False))
        .options(*_loads()).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return obj


async def _resolve(db, model, ids):
    if not ids:
        return []
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    return list((await db.scalars(stmt)).all())


def check_subcontractors(vendor_id, ids) -> None:
    """A vendor can't be its own sub-contractor. Pure; raises a 422."""
    if vendor_id is not None and vendor_id in set(ids or []):
        raise _unprocessable("subcontractor_ids: a vendor can't be its own sub-contractor.")


async def _resolve_strict(db, model, ids, field: str, noun: str):
    """Rows for ``ids``; an unknown or archived id is a 422 naming the field."""
    ids = list(dict.fromkeys(ids or []))
    rows = await _resolve(db, model, ids)
    missing = [str(i) for i in ids if i not in {r.id for r in rows}]
    if missing:
        raise _unprocessable(f"{field}: no such {noun} (or it is archived): {', '.join(missing)}")
    return rows


async def _residency(db, ids, stored=()) -> list:
    """Country lookup rows for ``ids``. Newly added countries must be active values of
    the country list; ones already on the record are kept even if since deactivated."""
    ids = list(dict.fromkeys(ids or []))
    keep = {c.id for c in stored}
    for cid in ids:
        if cid not in keep:
            await master_data.check_lookup(db, cid, "country", "data_residency_country_ids")
    if not ids:
        return []
    rows = list((await db.scalars(select(Lookup).where(Lookup.id.in_(ids), Lookup.key == "country"))).all())
    missing = [str(i) for i in ids if i not in {r.id for r in rows}]
    if missing:
        raise _unprocessable(f"data_residency_country_ids: pick values from the country list ({', '.join(missing)}).")
    return rows


async def _apply_links(db, obj, links: dict, *, vendor_id=None) -> None:
    """Set whichever link lists were sent (None = leave as is)."""
    if links.get("risk_ids") is not None:
        obj.risks = await _resolve(db, Risk, links["risk_ids"])
    if links.get("asset_ids") is not None:
        obj.assets = await _resolve(db, Asset, links["asset_ids"])
    if links.get("requirement_ids") is not None:
        obj.requirements = await _resolve(db, Requirement, links["requirement_ids"])
    if links.get("control_ids") is not None:
        obj.controls = await _resolve(db, Control, links["control_ids"])
    if links.get("process_ids") is not None:
        obj.processes = await _resolve_strict(db, Process, links["process_ids"], "process_ids", "process")
    if links.get("subcontractor_ids") is not None:
        check_subcontractors(vendor_id, links["subcontractor_ids"])
        obj.subcontractors = await _resolve_strict(
            db, Vendor, links["subcontractor_ids"], "subcontractor_ids", "vendor"
        )
    if links.get("data_residency_country_ids") is not None:
        stored = obj.data_residency_countries if vendor_id is not None else ()
        obj.data_residency_countries = await _residency(db, links["data_residency_country_ids"], stored)


_VENDOR_SORTABLE = {
    "name": Vendor.name,
    "category": Vendor.category,
    "criticality": Vendor.criticality,
    "status": Vendor.status,
    "risk_rating": Vendor.risk_rating,
    "assessment_status": Vendor.assessment_status,
    "last_assessed_at": Vendor.last_assessed_at,
    # Ranked low → critical, not alphabetically.
    "inherent_tier": case({t: i for i, t in enumerate(vt.TIERS)}, value=Vendor.inherent_tier, else_=-1),
    "annual_spend": Vendor.annual_spend,
    "created_at": Vendor.created_at,
}


@router.get("", response_model=Page[VendorRead], dependencies=[Depends(require("vendor:read"))])
async def list_vendors(
    db: DbSession,
    search: str | None = None,
    category_id: uuid.UUID | None = None,
    country_id: uuid.UUID | None = None,
    criticality: Annotated[Criticality | None, Query(description="low | medium | high | critical")] = None,
    review: Annotated[
        drill_through.ReviewFilter | None,
        Query(description="overdue: the next review date has passed (the dashboard's reviews overdue)"),
    ] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[VendorRead]:
    stmt = select(Vendor).where(Vendor.deleted.is_(False))
    if criticality is not None:
        stmt = stmt.where(Vendor.criticality == criticality)
    if review == "overdue":
        # The dashboard's third-party line counts with this same predicate.
        stmt = stmt.where(drill_through.vendor_review_overdue(date.today()))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            Vendor.name.ilike(like) | Vendor.category.ilike(like)
            | Vendor.legal_name.ilike(like) | Vendor.registration_number.ilike(like)
        )
    if category_id is not None:
        stmt = stmt.where(Vendor.category_id == category_id)
    if country_id is not None:
        stmt = stmt.where(Vendor.country_id == country_id)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _VENDOR_SORTABLE, default=Vendor.name)
    else:
        stmt = stmt.order_by(Vendor.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    # Load what the list serialises (``schema_loading``), not every link of every link.
    loads = (*_loads(), *options_for(Vendor, VendorRead, _VIEW_READS))
    rows = (await db.scalars(stmt.options(*loads).limit(limit).offset(offset))).all()
    return Page(items=await _reads(db, rows), total=total, limit=limit, offset=offset)


@router.post("", response_model=VendorRead, status_code=201, dependencies=[Depends(require("vendor:write"))])
async def create_vendor(body: VendorCreate, db: DbSession, user: CurrentUser) -> VendorRead:
    data = body.model_dump()
    links = {k: data.pop(k, None) or [] for k in _LINK_FIELDS}
    await rf.apply_refs(db, Vendor, data, ALL_REFS)
    if not data.get("spend_currency"):
        data["spend_currency"] = await _org_currency(db, user.tenant_id)
    obj = Vendor(tenant_id=user.tenant_id, **data)
    await _apply_links(db, obj, links)
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="vendor", entity_id=obj.id,
        summary=f"Registered vendor {obj.name}",
    )
    return await _read(db, obj.id)


class VendorSpendSummary(BaseModel):
    #: Live (not archived) vendors counted.
    vendors: int
    #: Annual spend of vendors that have not been offboarded, at today's rates.
    annual_spend: MoneyTotalRead
    #: Unexpired contract value, at today's rates.
    active_contracts: MoneyTotalRead
    conversion_basis: str = (
        "Spend and contract values are stock figures: each converts at the latest exchange rate "
        "on or before today."
    )


def spend_summary(vendors, book: fx.RateBook) -> VendorSpendSummary:
    """Vendor spend and live contract value in the reporting currency. Pure.

    Spend is counted for every vendor still in the relationship (an offboarded one is no
    longer a cost); contract value counts every contract that has not expired.
    """
    spend, contracts = fx.MoneyTotal(book), fx.MoneyTotal(book)
    for v in vendors:
        offboarded = str(getattr(v.status, "value", getattr(v, "status", ""))) == VendorStatus.offboarded.value
        if getattr(v, "annual_spend", None) is not None and not offboarded:
            spend.add(v.annual_spend, v.spend_currency)
        for c in getattr(v, "contracts", None) or []:
            if not c.is_expired and c.value is not None:
                contracts.add(c.value, c.currency)
    return VendorSpendSummary(
        vendors=len(vendors),
        annual_spend=MoneyTotalRead(**spend.as_dict()),
        active_contracts=MoneyTotalRead(**contracts.as_dict()),
    )


@router.get("/spend-summary", response_model=VendorSpendSummary,
            dependencies=[Depends(require("vendor:read"))],
            summary="Vendor annual spend and live contract value, in the reporting currency")
async def vendor_spend_summary(db: DbSession, user: CurrentUser) -> VendorSpendSummary:
    # Every vendor, with its contracts and nothing else it links to.
    vendors = (await db.scalars(
        select(Vendor).where(Vendor.deleted.is_(False)).options(*options_for(Vendor, None, ("contracts",)))
    )).all()
    return spend_summary(list(vendors), await fx.load_rate_book(db, user.tenant_id))


@router.get("/{vendor_id}", response_model=VendorRead, dependencies=[Depends(require("vendor:read"))])
async def get_vendor(vendor_id: uuid.UUID, db: DbSession) -> VendorRead:
    return await _read(db, vendor_id)


@router.patch("/{vendor_id}", response_model=VendorRead, dependencies=[Depends(require("vendor:write"))])
async def update_vendor(
    vendor_id: uuid.UUID, body: VendorUpdate, db: DbSession, user: CurrentUser
) -> VendorRead:
    obj = await _load(db, vendor_id)
    data = body.model_dump(exclude_unset=True)
    links = {k: data.pop(k, None) for k in _LINK_FIELDS}
    await rf.apply_refs(db, Vendor, data, ALL_REFS, record=obj)
    if data.get("spend_currency") == "":
        data["spend_currency"] = await _org_currency(db, user.tenant_id)
    # NOT NULL columns: a null in a partial update means "unchanged".
    for name in ("criticality", "legal_name", "registration_number", "spend_currency"):
        if name in data and data[name] is None:
            data.pop(name)
    changes = criticality_changes(obj, data)
    changes.update(rating_changes(obj, data))
    for field, value in data.items():
        setattr(obj, field, value)
    await _apply_links(db, obj, links, vendor_id=obj.id)
    await db.flush()
    summary = f"Updated vendor {obj.name}"
    if obj.inherent_tier and ("criticality" in changes or "tier_override_reason" in changes):
        proposed = vt.TIER_TO_CRITICALITY.get(obj.inherent_tier or "")
        crit = getattr(obj.criticality, "value", obj.criticality)
        if proposed and crit != proposed:
            summary += (f"; criticality {crit} overrides the {proposed} proposed by its "
                        f"{obj.inherent_tier} inherent tier: {obj.tier_override_reason}")
        elif proposed:
            summary += f"; criticality follows the {proposed} proposed by its inherent tier"
    await audit.record(
        db, actor=user, action="update", entity_type="vendor", entity_id=obj.id,
        summary=summary, changes=changes or None,
    )
    return await _read(db, obj.id)


def _due_diligence_view(row):
    """Phase 4E: the vendor's latest reviewed due-diligence questionnaire (pure)."""
    from app.schemas.vendor import VendorDueDiligence
    from app.services import questionnaire_workflow as qwf

    try:
        view = qwf.due_diligence_view(row)
    except AttributeError:  # a partial record (tests, imports) without assessments loaded
        return None
    return VendorDueDiligence(**view) if view else None


def rating_changes(obj, data: dict) -> dict:
    """Phase 4E: the due-diligence override rule on an update's set fields (in place), like
    the tier rule: a risk rating different from the latest reviewed due diligence's
    proposal needs ``risk_rating_override_reason`` (a 422 otherwise)."""
    from app.services import questionnaire_workflow as qwf

    if "risk_rating" not in data and "risk_rating_override_reason" not in data:
        return {}
    latest = qwf.latest_due_diligence(getattr(obj, "assessments", None) or [])
    proposed = getattr(latest, "result_rating", None) if latest is not None else None
    try:
        reason = qwf.resolve_rating(
            proposed=proposed, band=getattr(latest, "result_band", "") if latest is not None else "",
            stored_rating=obj.risk_rating, stored_reason=getattr(obj, "risk_rating_override_reason", "") or "", sent=data,
        )
    except qwf.WorkflowError as exc:
        raise _unprocessable(str(exc)) from exc
    if reason is None:
        data.pop("risk_rating_override_reason", None)
    else:
        data["risk_rating_override_reason"] = reason
    changes: dict = {}
    old = getattr(obj.risk_rating, "value", obj.risk_rating)
    new = getattr(data.get("risk_rating"), "value", data.get("risk_rating"))
    if "risk_rating" in data and new != old:
        changes["risk_rating"] = {"from": old, "to": new}
    if "risk_rating_override_reason" in data and (data["risk_rating_override_reason"] or "") != (getattr(obj, "risk_rating_override_reason", "") or ""):
        changes["risk_rating_override_reason"] = {"from": getattr(obj, "risk_rating_override_reason", "") or "", "to": data["risk_rating_override_reason"]}
    return changes


def criticality_changes(obj, data: dict) -> dict:
    """Apply the tier-override rule to an update's set fields (in place) and return
    the criticality / reason changes for the audit trail. Raises a 422 when the
    criticality would differ from the tier's proposal with no reason on record."""
    try:
        _, reason = vt.resolve_criticality(
            tier=obj.inherent_tier, stored_criticality=obj.criticality,
            stored_reason=obj.tier_override_reason or "", sent=data,
        )
    except vt.TieringError as exc:
        raise _unprocessable(str(exc)) from exc
    if reason is None:
        data.pop("tier_override_reason", None)
    else:
        data["tier_override_reason"] = reason
    changes: dict = {}
    old_crit = getattr(obj.criticality, "value", obj.criticality)
    new_crit = getattr(data.get("criticality"), "value", data.get("criticality"))
    if new_crit is not None and new_crit != old_crit:
        changes["criticality"] = {"from": old_crit, "to": new_crit}
    if "tier_override_reason" in data and (data["tier_override_reason"] or "") != (obj.tier_override_reason or ""):
        changes["tier_override_reason"] = {"from": obj.tier_override_reason or "", "to": data["tier_override_reason"]}
    return changes


@router.delete("/{vendor_id}", status_code=204, dependencies=[Depends(require("vendor:write"))])
async def delete_vendor(vendor_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, vendor_id)
    # (vendor, delete) is a dual-control action: whoever registered the third party
    # cannot also remove it from the register.
    await delete_guard.enforce(db, entity_type="vendor", record=obj, user=user, label="vendor")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit.record(db, actor=user, action="delete", entity_type="vendor",
                       entity_id=obj.id, summary=f"Archived vendor {obj.name}")


# ----------------------------------------------------------------- contracts
@router.post(
    "/{vendor_id}/contracts", response_model=VendorRead, status_code=201,
    dependencies=[Depends(require("vendor:write"))],
)
async def add_contract(
    vendor_id: uuid.UUID, body: ServiceContractCreate, db: DbSession, user: CurrentUser
) -> VendorRead:
    obj = await _load(db, vendor_id)
    data = body.model_dump()
    if not data.get("currency"):
        data["currency"] = await _org_currency(db, obj.tenant_id)
    contract = ServiceContract(tenant_id=obj.tenant_id, vendor_id=obj.id, **data)
    db.add(contract)
    await db.flush()
    value = f" ({contract.currency} {contract.value:,.2f})" if contract.value is not None else ""
    await audit.record(
        db, actor=user, action="add_contract", entity_type="vendor", entity_id=obj.id,
        summary=f"Added contract '{contract.name}'{value} to vendor {obj.name}",
    )
    return await _read(db, obj.id)


@router.delete(
    "/contracts/{contract_id}", status_code=204, dependencies=[Depends(require("vendor:write"))],
)
async def delete_contract(contract_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    c = await db.get(ServiceContract, contract_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    await db.delete(c)
    await audit.record(
        db, actor=user, action="delete_contract", entity_type="vendor", entity_id=c.vendor_id,
        summary=f"Removed contract '{c.name}'",
    )


# ------------------------------------------------------------ certifications
async def _load_cert(db, vendor_id: uuid.UUID, cert_id: uuid.UUID) -> VendorCertification:
    cert = await db.scalar(
        select(VendorCertification).where(
            VendorCertification.id == cert_id, VendorCertification.vendor_id == vendor_id
        )
    )
    if cert is None:
        raise HTTPException(status_code=404, detail="Certification not found")
    return cert


def _cert_label(cert) -> str:
    return CERT_TYPES.get(cert.cert_type, cert.cert_type)


def check_cert_dates(issued_on, expires_on) -> None:
    """A certificate can't expire before it was issued. Pure; raises a 422."""
    if issued_on and expires_on and expires_on < issued_on:
        raise _unprocessable("expires_on: the certificate can't expire before it was issued.")


@router.get(
    "/{vendor_id}/certifications", response_model=list[VendorCertificationRead],
    dependencies=[Depends(require("vendor:read"))],
)
async def list_certifications(vendor_id: uuid.UUID, db: DbSession) -> list[VendorCertificationRead]:
    obj = await _load(db, vendor_id)
    return [VendorCertificationRead.model_validate(c) for c in obj.certifications]


@router.post(
    "/{vendor_id}/certifications", response_model=VendorCertificationRead, status_code=201,
    dependencies=[Depends(require("vendor:write"))],
)
async def add_certification(
    vendor_id: uuid.UUID, body: VendorCertificationCreate, db: DbSession, user: CurrentUser
) -> VendorCertificationRead:
    obj = await _load(db, vendor_id)
    check_cert_dates(body.issued_on, body.expires_on)
    cert = VendorCertification(id=uuid.uuid4(), tenant_id=obj.tenant_id, vendor_id=obj.id, **body.model_dump())
    db.add(cert)
    await db.flush()
    await audit.record(
        db, actor=user, action="add_certification", entity_type="vendor", entity_id=obj.id,
        summary=f"Recorded {_cert_label(cert)} certification of {obj.name}"
        + (f", expires {cert.expires_on.isoformat()}" if cert.expires_on else ""),
        changes={"certification_id": str(cert.id)},
    )
    return VendorCertificationRead.model_validate(cert)


@router.patch(
    "/{vendor_id}/certifications/{cert_id}", response_model=VendorCertificationRead,
    dependencies=[Depends(require("vendor:write"))],
)
async def update_certification(
    vendor_id: uuid.UUID, cert_id: uuid.UUID, body: VendorCertificationUpdate, db: DbSession, user: CurrentUser
) -> VendorCertificationRead:
    obj = await _load(db, vendor_id)
    cert = await _load_cert(db, vendor_id, cert_id)
    data = body.model_dump(exclude_unset=True)
    for name in ("cert_type", "issuer", "certificate_number", "scope"):
        if name in data and data[name] is None:
            data.pop(name)  # NOT NULL: a null means "unchanged"
    check_cert_dates(data.get("issued_on", cert.issued_on), data.get("expires_on", cert.expires_on))
    changes = {}
    for field, value in data.items():
        old = getattr(cert, field)
        if old != value:
            changes[field] = {"from": old.isoformat() if hasattr(old, "isoformat") else old,
                              "to": value.isoformat() if hasattr(value, "isoformat") else value}
        setattr(cert, field, value)
    await db.flush()
    await audit.record(
        db, actor=user, action="update_certification", entity_type="vendor", entity_id=obj.id,
        summary=f"Updated {_cert_label(cert)} certification of {obj.name}",
        changes={"certification_id": str(cert.id), **changes},
    )
    return VendorCertificationRead.model_validate(cert)


@router.delete(
    "/{vendor_id}/certifications/{cert_id}", status_code=204,
    dependencies=[Depends(require("vendor:write"))],
)
async def delete_certification(vendor_id: uuid.UUID, cert_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, vendor_id)
    cert = await _load_cert(db, vendor_id, cert_id)
    label = _cert_label(cert)
    await db.delete(cert)
    await db.flush()
    await audit.record(
        db, actor=user, action="delete_certification", entity_type="vendor", entity_id=obj.id,
        summary=f"Removed {label} certification of {obj.name}",
        changes={"certification_id": str(cert_id)},
    )


# ------------------------------------------------------------------- tiering
@router.post(
    "/{vendor_id}/tiering", response_model=VendorRead,
    dependencies=[Depends(require("vendor:write"))],
    summary="(Re)compute the inherent risk tier from the latest completed tiering assessment",
)
async def recompute_tiering(vendor_id: uuid.UUID, db: DbSession, user: CurrentUser) -> VendorRead:
    obj = await _load(db, vendor_id)
    latest = vt.latest_completed(obj.assessments)
    if latest is None:
        raise _unprocessable(
            f"{obj.name} has no completed '{vt.TIERING_QUESTIONNAIRE_NAME}' assessment. "
            "Start one from this vendor (or under Assessments), answer every question and submit it."
        )
    try:
        await vt.write_back(db, obj, latest, user)
    except vt.TieringError as exc:
        raise _unprocessable(str(exc)) from exc
    return await _read(db, obj.id)


# ----------------------------------------------------------------- vendor types
types_router = APIRouter(prefix="/vendor-types", tags=["vendors"])


@types_router.get("", response_model=list[VendorTypeRead], dependencies=[Depends(require("vendor:read"))])
async def list_vendor_types(db: DbSession) -> list[VendorTypeRead]:
    rows = (await db.scalars(select(VendorType).order_by(VendorType.name))).all()
    return [VendorTypeRead.model_validate(r) for r in rows]


@types_router.post("", response_model=VendorTypeRead, status_code=201, dependencies=[Depends(require("vendor:write"))])
async def create_vendor_type(body: VendorTypeCreate, db: DbSession, user: CurrentUser) -> VendorTypeRead:
    obj = VendorType(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return VendorTypeRead.model_validate(obj)


@types_router.patch("/{type_id}", response_model=VendorTypeRead, dependencies=[Depends(require("vendor:write"))])
async def update_vendor_type(type_id: uuid.UUID, body: VendorTypeUpdate, db: DbSession) -> VendorTypeRead:
    obj = await db.get(VendorType, type_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Vendor type not found")
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, name, value)
    await db.flush()
    await db.refresh(obj)
    return VendorTypeRead.model_validate(obj)


@types_router.delete("/{type_id}", status_code=204, dependencies=[Depends(require("vendor:write"))])
async def delete_vendor_type(type_id: uuid.UUID, db: DbSession) -> None:
    """Vendors referencing the type keep working — the FK sets their type to NULL."""
    obj = await db.get(VendorType, type_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Vendor type not found")
    await db.delete(obj)
