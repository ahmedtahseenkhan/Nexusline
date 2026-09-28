"""Risk-scenario library, asset-driven risk generation, and the risk candidate queue.

The register a bank is asked to produce starts from the asset inventory it already has.
This module closes that gap the ISO 27005 way — threat exploits vulnerability against an
asset — by pairing selected assets with the applicable scenario templates and proposing
pre-scored risks.

Phase 3 (F-04) puts a queue between generation and the register, because writing one
register risk per asset × scenario pair is how a reviewed register reached 1,700
near-duplicates:

* ``POST /risk-scenarios/generate`` returns **proposals and writes nothing** — one per
  asset × scenario pair, each labelled with the candidate it would join.
* ``POST /risk-scenarios/commit`` sends the reviewed pairs to the **queue**: pairs are
  grouped by a de-duplication key (scenario + process + business unit, see
  ``services.risk_scenarios.dedupe_key``) into ``RiskProposal`` rows, merged into a
  candidate already waiting with the same key, and skipped when the register already
  covers the key. Nothing reaches the register here.
* ``GET /risk-proposals`` lists candidates; ``POST /risk-proposals/accept`` promotes them
  through the risk module's own ``create_risk`` (draft, source *generated*, every
  Phase 0–2 rule, audit); ``/reject`` (with a reason) and ``/merge`` decide the rest.
  Each decision is audited per candidate.
"""
from __future__ import annotations

import uuid
import zlib
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import Asset, assets_processes
from app.models.compliance import requirement_controls, requirement_risks
from app.models.control import Control, control_assets
from app.models.enums import Criticality
from app.models.lookup import Lookup
from app.models.organization import BusinessUnit, Process
from app.models.risk import Risk, risk_assets
from app.models.risk_scenario import RiskProposal as ProposalRow
from app.models.risk_scenario import RiskScenarioTemplate, risk_proposal_assets
from app.models.threat import Threat, Vulnerability
from app.schemas.common import GraphRef, Page
from app.schemas.risk import RiskCreate
from app.schemas.risk_scenario import (
    AcceptRequest,
    AcceptResult,
    AssetKindRead,
    CommitError,
    CommitRequest,
    CommitResult,
    CommitSkip,
    GenerateRequest,
    GenerateResponse,
    LegacyMigrationPlan,
    LegacyMigrationResult,
    LibraryInstallResult,
    MergeRequest,
    MergeResult,
    NotFittingScenario,
    ProposalAssetRef,
    ProposalControlRef,
    ProposalError,
    ProposalPage,
    ProposalRead,
    RejectRequest,
    RejectResult,
    RiskProposal,
    ScenarioCreate,
    ScenarioRead,
    ScenarioUpdate,
    SourceRiskRef,
)
from app.services import audit as audit_log
from app.services import control_mapping, master_data, ref_fields, risk_hierarchy
from app.services.refs import next_reference
from app.services.risk_scenarios import (
    ACCEPTED,
    ASSET_KINDS,
    CATALOGUE,
    MERGED,
    PENDING,
    PROPOSAL_STATUSES,
    REJECTED,
    AssetFacts,
    KeyOwner,
    PairIn,
    Placement,
    ProposalFacts,
    ScenarioSpec,
    FITS,
    WRONG_KIND,
    candidate_title,
    classify_asset,
    dedupe_key,
    group_subject,
    group_title,
    impact_for,
    key_owners,
    kind_labels,
    likelihood_for,
    match_generated_title,
    merge_candidates,
    merge_refs,
    parse_kinds,
    place_asset,
    plan_commit,
    scenario_fit,
    scope_label,
    split_refs,
    title_for,
    title_patterns,
    worst_scores,
)
from app.services.risk_settings import get_matrix_size, get_or_create_settings, scale_for

router = APIRouter(tags=["risk scenarios"])

_READ = Depends(require("risk:read"))
_WRITE = Depends(require("risk:write"))
#: Moving register risks into the queue archives them: it needs delete as well as write.
_ARCHIVE = Depends(require("risk:delete"))

_CRIT_RANK = {
    Criticality.low: 1, Criticality.medium: 2, Criticality.high: 3, Criticality.critical: 4,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _facts(asset: Asset) -> AssetFacts:
    """The scoring facts of a loaded asset. ``criticality`` is the asset's *effective*
    criticality (``Asset.effective_criticality``: an information asset's business value;
    an IT asset's cost/availability band or what it inherits from the data it hosts) —
    the rating the asset registers show. The raw ``criticality`` column is not set by
    either asset form and stays at its default."""
    return AssetFacts(
        name=asset.name,
        asset_class=asset.asset_class.value,
        criticality=asset.effective_criticality,
        business_value=asset.business_value,
        confidentiality=asset.confidentiality,
        integrity=asset.integrity,
        availability=asset.availability,
        kinds=asset_kinds_of(asset),
    )


def asset_kinds_of(asset) -> frozenset[str]:
    """``services.risk_scenarios.classify_asset`` for a loaded ``Asset`` row (its media
    type and tags are eager-loaded relationships)."""
    media = getattr(asset, "media_type", None)
    return classify_asset(
        asset_class=_enum_value(asset.asset_class),
        name=asset.name or "",
        media_type=(media.name if media is not None else "") or "",
        tags=[t.name or "" for t in (getattr(asset, "tags", None) or [])],
        hostname=getattr(asset, "hostname", "") or "",
        os_version=getattr(asset, "os_version", "") or "",
        manufacturer=getattr(asset, "manufacturer", "") or "",
        model_number=getattr(asset, "model_number", "") or "",
        data_categories=getattr(asset, "data_categories", "") or "",
    )


def _spec(row: RiskScenarioTemplate) -> ScenarioSpec:
    """Convert a stored template into the pure engine's input."""
    classes = tuple(c.strip() for c in row.asset_classes.split(",") if c.strip())
    return ScenarioSpec(
        reference=row.reference,
        title=row.title,
        description=row.description,
        category=row.category,
        asset_classes=classes,
        asset_kinds=parse_kinds(getattr(row, "asset_kinds", "") or "")[0],
        threat=row.threat,
        vulnerability=row.vulnerability,
        likelihood=row.likelihood,
        impact_rule=row.impact_rule,
        impact_property=row.impact_property,
        fixed_impact=row.fixed_impact,
        treatment_hint=row.treatment_hint,
        control_references=_split_refs(row.control_references),
    )


def _split_refs(value: str | None) -> tuple[str, ...]:
    return tuple(r.strip() for r in (value or "").split(",") if r.strip())


async def _load(db: DbSession, scenario_id: uuid.UUID) -> RiskScenarioTemplate:
    row = await db.scalar(
        select(RiskScenarioTemplate).where(RiskScenarioTemplate.id == scenario_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return row


# ---------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------
@router.get("/risk-scenarios", response_model=Page[ScenarioRead], dependencies=[_READ])
async def list_scenarios(
    db: DbSession,
    category: str | None = None,
    enabled: bool | None = None,
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ScenarioRead]:
    stmt = select(RiskScenarioTemplate)
    if category:
        stmt = stmt.where(RiskScenarioTemplate.category == category)
    if enabled is not None:
        stmt = stmt.where(RiskScenarioTemplate.enabled.is_(enabled))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            RiskScenarioTemplate.title.ilike(like) | RiskScenarioTemplate.threat.ilike(like)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(
            stmt.order_by(RiskScenarioTemplate.reference).limit(limit).offset(offset)
        )
    ).all()
    return Page(
        items=[ScenarioRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/risk-scenarios/asset-kinds", response_model=list[AssetKindRead], dependencies=[_READ])
async def list_asset_kinds() -> list[AssetKindRead]:
    """The fixed vocabulary a scenario's ``asset_kinds`` uses, in display order."""
    return [
        AssetKindRead(value=k.value, label=k.label, description=k.description, group=k.group)
        for k in ASSET_KINDS
    ]


@router.post("/risk-scenarios", response_model=ScenarioRead, status_code=201, dependencies=[_WRITE])
async def create_scenario(
    body: ScenarioCreate, db: DbSession, user: CurrentUser
) -> ScenarioRead:
    reference = body.reference or await next_reference(db, RiskScenarioTemplate, "RS")
    existing = await db.scalar(
        select(RiskScenarioTemplate).where(RiskScenarioTemplate.reference == reference)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Scenario {reference} already exists"
        )
    row = RiskScenarioTemplate(
        tenant_id=user.tenant_id, **body.model_dump(exclude={"reference"}), reference=reference
    )
    db.add(row)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="risk_scenario", entity_id=row.id,
        summary=f"Created risk scenario {row.reference}: {row.title}",
    )
    return ScenarioRead.model_validate(row)


@router.patch("/risk-scenarios/{scenario_id}", response_model=ScenarioRead, dependencies=[_WRITE])
async def update_scenario(
    scenario_id: uuid.UUID, body: ScenarioUpdate, db: DbSession, user: CurrentUser
) -> ScenarioRead:
    row = await _load(db, scenario_id)
    data = body.model_dump(exclude_unset=True)
    for name, value in data.items():
        setattr(row, name, value)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="risk_scenario", entity_id=row.id,
        summary=f"Updated risk scenario {row.reference}",
        changes={k: str(v) for k, v in data.items()},
    )
    return ScenarioRead.model_validate(row)


@router.delete("/risk-scenarios/{scenario_id}", status_code=204, dependencies=[_WRITE])
async def delete_scenario(scenario_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    row = await _load(db, scenario_id)
    reference = row.reference
    await db.delete(row)
    await audit_log.record(
        db, actor=user, action="delete", entity_type="risk_scenario", entity_id=scenario_id,
        summary=f"Deleted risk scenario {reference}",
    )


@router.post(
    "/risk-scenarios/install-library",
    response_model=LibraryInstallResult,
    dependencies=[_WRITE],
    summary="Install the built-in ISO 27005-style scenario catalogue",
)
async def install_library(db: DbSession, user: CurrentUser) -> LibraryInstallResult:
    """Copy the built-in catalogue into this tenant's editable library.

    Idempotent by reference: a scenario already present is **left exactly as it is**, so
    running this again after a platform upgrade adds what is new without discarding local
    retuning. It also seeds the Threat Library with each scenario's threat and
    vulnerability, which is what lets a generated risk carry real graph links.
    """
    rows = {r.reference: r for r in (await db.scalars(select(RiskScenarioTemplate))).all()}
    existing = set(rows)
    installed = backfilled = 0
    for spec in CATALOGUE:
        if spec.reference in existing:
            # A row that predates the control mapping has an empty field, not a
            # decision. Filling it is not overwriting local retuning; a tenant that
            # cleared or edited the references keeps exactly what it wrote.
            row = rows[spec.reference]
            if not (row.control_references or "").strip() and control_mapping.references_for(spec.reference):
                row.control_references = ", ".join(control_mapping.references_for(spec.reference))
                backfilled += 1
            else:
                # A row still holding an earlier release's mapping verbatim is old, not
                # retuned: it takes the SBP additions. Edited rows are left alone.
                upgraded = control_mapping.upgraded_references(
                    spec.reference, (row.control_references or "").split(",")
                )
                if upgraded:
                    row.control_references = ", ".join(upgraded)
                    backfilled += 1
            continue
        db.add(
            RiskScenarioTemplate(
                tenant_id=user.tenant_id,
                reference=spec.reference,
                title=spec.title,
                description=spec.description,
                category=spec.category,
                asset_classes=",".join(spec.asset_classes),
                asset_kinds=",".join(sorted(spec.asset_kinds)),
                threat=spec.threat,
                vulnerability=spec.vulnerability,
                likelihood=spec.likelihood,
                impact_rule=spec.impact_rule,
                impact_property=spec.impact_property,
                fixed_impact=spec.fixed_impact,
                treatment_hint=spec.treatment_hint,
                control_references=", ".join(control_mapping.references_for(spec.reference)),
            )
        )
        installed += 1

    await _seed_catalog_entries(db, user)
    await db.flush()
    # Rows installed before asset kinds existed take the library's kinds when they are
    # still the library scenario (the start-up repair does the same on every boot).
    from app.db.data_repairs import backfill_scenario_kinds  # local: data_repairs is start-up code

    kinds_added = await backfill_scenario_kinds(db, user.tenant_id)
    await audit_log.record(
        db, actor=user, action="create", entity_type="risk_scenario", entity_id=None,
        summary=f"Installed {installed} risk scenario(s) from the built-in library"
        + (f"; control mapping added to {backfilled} existing" if backfilled else "")
        + (f"; asset kinds added to {kinds_added} existing" if kinds_added else ""),
        changes={
            "installed": installed, "backfilled": backfilled, "kinds_added": kinds_added,
            "total": len(CATALOGUE),
        },
    )
    return LibraryInstallResult(
        installed=installed, skipped=len(CATALOGUE) - installed, total=len(CATALOGUE)
    )


async def _seed_catalog_entries(db: DbSession, user: CurrentUser) -> None:
    """Ensure every threat/vulnerability the catalogue names exists in the Threat Library."""
    threats = {(t or "").strip().lower() for t in (await db.scalars(select(Threat.name))).all()}
    vulns = {(v or "").strip().lower() for v in (await db.scalars(select(Vulnerability.name))).all()}
    for spec in CATALOGUE:
        if spec.threat and spec.threat.strip().lower() not in threats:
            db.add(Threat(tenant_id=user.tenant_id, name=spec.threat, category=spec.category))
            threats.add(spec.threat.strip().lower())
        if spec.vulnerability and spec.vulnerability.strip().lower() not in vulns:
            db.add(
                Vulnerability(
                    tenant_id=user.tenant_id, name=spec.vulnerability, category=spec.category
                )
            )
            vulns.add(spec.vulnerability.strip().lower())




# ---------------------------------------------------------------------------
# Shared loaders (generation, commit and the queue)
# ---------------------------------------------------------------------------
def _enum_value(value) -> str:
    return getattr(value, "value", value) or ""


def _facts_from(row) -> AssetFacts:
    """``AssetFacts`` from an ``Asset`` row or a column tuple with the same names.

    Only for titles (``title_for`` reads the name alone): a column tuple cannot carry the
    effective criticality, so scoring always goes through :func:`_facts`."""
    return AssetFacts(
        name=row.name,
        asset_class=_enum_value(row.asset_class),
        criticality=row.criticality,
        business_value=row.business_value,
        confidentiality=row.confidentiality,
        integrity=row.integrity,
        availability=row.availability,
    )


def _auto_title(template: RiskScenarioTemplate, asset_name: str) -> str:
    """The title the scenario gives one asset on its own (``title_for``)."""
    medium = Criticality.medium
    facts = AssetFacts(asset_name, "", medium, medium, medium, medium, medium)
    return title_for(_spec(template), facts)


async def _templates(db) -> tuple[dict[uuid.UUID, RiskScenarioTemplate], dict[str, RiskScenarioTemplate]]:
    """The library by id and by upper-cased reference (small table: one query)."""
    rows = (await db.scalars(select(RiskScenarioTemplate))).all()
    return {r.id: r for r in rows}, {(r.reference or "").strip().upper(): r for r in rows}


async def _placements(db, asset_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Placement]:
    """Each asset's process and business unit for de-duplication
    (``services.risk_scenarios.place_asset`` states the rule). Three queries."""
    ids = list(set(asset_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(select(Asset.id, Asset.owner_id, Asset.asset_class).where(Asset.id.in_(ids)))
    ).all()
    processes: dict[uuid.UUID, list[tuple[uuid.UUID, str, uuid.UUID | None]]] = {}
    for asset_id, process_id, name, unit_id in (
        await db.execute(
            select(assets_processes.c.asset_id, Process.id, Process.name, Process.business_unit_id)
            .join(Process, Process.id == assets_processes.c.process_id)
            .where(assets_processes.c.asset_id.in_(ids), Process.deleted.is_(False))
        )
    ).all():
        processes.setdefault(asset_id, []).append((process_id, name, unit_id))
    unit_ids = {r.owner_id for r in rows if r.owner_id} | {
        p[2] for ps in processes.values() for p in ps if p[2]
    }
    units: dict[uuid.UUID, str] = {}
    if unit_ids:
        units = dict(
            (
                await db.execute(
                    select(BusinessUnit.id, BusinessUnit.name)
                    .where(BusinessUnit.id.in_(unit_ids), BusinessUnit.deleted.is_(False))
                )
            ).all()
        )
    return {
        r.id: place_asset(
            asset_class=_enum_value(r.asset_class),
            owner_unit=(r.owner_id, units[r.owner_id]) if r.owner_id in units else None,
            processes=processes.get(r.id, ()),
            unit_names=units,
        )
        for r in rows
    }


def _proposal_facts(row: ProposalRow) -> ProposalFacts:
    return ProposalFacts(
        id=row.id, dedupe_key=row.dedupe_key or "", status=row.status, title=row.title or "",
        merged_into_id=row.merged_into_id, promoted_risk_id=row.promoted_risk_id,
        decision_note=row.decision_note or "", decided_at=row.decided_at,
    )


async def _key_owners(db, keys: set[str]) -> dict[str, KeyOwner]:
    """What each key already has in the queue or the register (``key_owners``), with
    merged candidates followed to the one that absorbed them."""
    if not keys:
        return {}
    rows = list(
        (
            await db.scalars(
                select(ProposalRow)
                .where(ProposalRow.dedupe_key.in_(sorted(keys)))
                .order_by(ProposalRow.created_at)
            )
        ).all()
    )
    by_id = {r.id: r for r in rows}
    missing = {r.merged_into_id for r in rows if r.merged_into_id and r.merged_into_id not in by_id}
    for _ in range(10):  # merge chains are short; the cap only guards bad data
        if not missing:
            break
        found = (await db.scalars(select(ProposalRow).where(ProposalRow.id.in_(list(missing))))).all()
        for r in found:
            by_id[r.id] = r
        missing = {r.merged_into_id for r in found if r.merged_into_id and r.merged_into_id not in by_id}
    promoted = {r.promoted_risk_id for r in by_id.values() if r.promoted_risk_id}
    live: dict[uuid.UUID, str] = {}
    if promoted:
        live = {
            rid: ref or "a live risk"
            for rid, ref in (
                await db.execute(
                    select(Risk.id, Risk.reference).where(Risk.id.in_(promoted), Risk.deleted.is_(False))
                )
            ).all()
        }
    facts = {rid: _proposal_facts(r) for rid, r in by_id.items()}
    return key_owners([facts[r.id] for r in rows], facts, live)


async def _register_rows(db) -> list[tuple[uuid.UUID, str, str]]:
    """``(id, reference, title)`` of every live risk — read once per request."""
    return [
        (rid, ref or "", title or "")
        for rid, ref, title in (
            await db.execute(select(Risk.id, Risk.reference, Risk.title).where(Risk.deleted.is_(False)))
        ).all()
    ]


def _titles_index(register: Sequence[tuple[uuid.UUID, str, str]]) -> dict[str, str]:
    return {title.strip().lower(): ref or "a live risk" for _rid, ref, title in register if title.strip()}


async def _legacy_keys(
    db,
    register: Sequence[tuple[uuid.UUID, str, str]],
    templates: Iterable[RiskScenarioTemplate],
    keys: set[str],
) -> dict[str, str]:
    """Keys already covered by live risks the pre-queue generator wrote.

    Those risks carry no key, but their titles do: the generator titled each one from
    its scenario and asset (``title_for``). A title that matches a scenario's pattern
    *and* names an asset the risk links gives that asset's key. Returns key -> the
    covering risk's reference, for the keys asked about.

    Counted once: a risk gives at most one key (its first scenario naming a linked
    asset), and a risk that came from the queue — placed in the hierarchy, or promoted
    from a candidate — is not pre-queue at all: its key is the candidate's, which
    ``_key_owners`` already reports.
    """
    if not keys:
        return {}
    wanted = {k.split("|", 1)[0] for k in keys}
    patterns = [
        p for p in title_patterns((t.reference, t.title) for t in templates)
        if p.reference.strip().upper() in wanted
    ]
    if not patterns:
        return {}
    matched: dict[uuid.UUID, tuple[str, list[tuple[str, list[str]]]]] = {}
    for rid, ref, title in register:
        hits = match_generated_title(title, patterns)
        if hits:
            matched[rid] = (ref, hits)
    if not matched:
        return {}
    promoted = select(ProposalRow.promoted_risk_id).where(ProposalRow.promoted_risk_id.is_not(None))
    for rid in (
        await db.scalars(
            select(Risk.id).where(
                Risk.id.in_(list(matched)), or_(Risk.level.is_not(None), Risk.id.in_(promoted))
            )
        )
    ).all():
        matched.pop(rid, None)
    if not matched:
        return {}
    linked: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    for rid, aid, name in (
        await db.execute(
            select(risk_assets.c.risk_id, Asset.id, Asset.name)
            .join(Asset, Asset.id == risk_assets.c.asset_id)
            .where(risk_assets.c.risk_id.in_(list(matched)), Asset.deleted.is_(False))
        )
    ).all():
        linked.setdefault(rid, {})[(name or "").strip().lower()] = aid
    placements = await _placements(db, {aid for names in linked.values() for aid in names.values()})
    out: dict[str, str] = {}
    for rid, (ref, hits) in matched.items():
        names = linked.get(rid, {})
        key = _legacy_key_of(hits, names, placements)
        if key is not None and key in keys:
            out.setdefault(key, ref or "a live risk")
    return out


def _legacy_key_of(
    hits: Sequence[tuple[str, list[str]]],
    names: dict[str, uuid.UUID],
    placements: dict[uuid.UUID, Placement],
) -> str | None:
    """The one key a pre-queue risk covers: its first scenario reading that names a
    linked, placed asset."""
    for scenario_ref, candidates in hits:
        for name in candidates:
            aid = names.get(name.strip().lower())
            if aid is None or aid not in placements:
                continue
            where = placements[aid]
            return dedupe_key(scenario_ref, where.process_id, where.business_unit_id, where.asset_class)
    return None


async def _category_ids(db, texts: Iterable[str]) -> dict[str, uuid.UUID]:
    """Scenario categories ("Access Control") matched onto active ``risk_category``
    values by label or value, case-insensitively. Ambiguous text matches nothing."""
    wanted = {t.strip().lower() for t in texts if t and t.strip()}
    if not wanted:
        return {}
    hits: dict[str, set[uuid.UUID]] = {}
    for lid, label, value in (
        await db.execute(
            select(Lookup.id, Lookup.label, Lookup.value)
            .where(Lookup.key == "risk_category", Lookup.active.is_(True))
        )
    ).all():
        for text in {(label or "").strip().lower(), (value or "").strip().lower()}:
            if text in wanted:
                hits.setdefault(text, set()).add(lid)
    return {text: next(iter(ids)) for text, ids in hits.items() if len(ids) == 1}


async def _lock_queue(db, tenant_id: uuid.UUID) -> None:
    """Serialise writes to one organisation's queue for this transaction, so two people
    sending overlapping generations at once cannot both start a candidate for the same
    key. ``pg_advisory_xact_lock`` releases itself at commit or rollback."""
    first = zlib.crc32(b"risk_proposals") - 2**31
    second = zlib.crc32(str(tenant_id).encode()) - 2**31
    await db.execute(select(func.pg_advisory_xact_lock(cast(first, Integer), cast(second, Integer))))


async def _link_assets(db, links: Sequence[dict]) -> None:
    for i in range(0, len(links), 1000):
        chunk = links[i : i + 1000]
        if chunk:
            await db.execute(pg_insert(risk_proposal_assets).values(list(chunk)).on_conflict_do_nothing())


async def _asset_ids_by_proposal(
    db, proposal_ids: Sequence[uuid.UUID], *, live_only: bool
) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = {pid: [] for pid in proposal_ids}
    if not proposal_ids:
        return out
    stmt = (
        select(risk_proposal_assets.c.proposal_id, Asset.id)
        .join(Asset, Asset.id == risk_proposal_assets.c.asset_id)
        .where(risk_proposal_assets.c.proposal_id.in_(list(proposal_ids)))
        .order_by(Asset.name)
    )
    if live_only:
        stmt = stmt.where(Asset.deleted.is_(False))
    for pid, aid in (await db.execute(stmt)).all():
        out.setdefault(pid, []).append(aid)
    return out


async def _asset_names(db, asset_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = list(set(asset_ids))
    if not ids:
        return {}
    return dict((await db.execute(select(Asset.id, Asset.name).where(Asset.id.in_(ids)))).all())


# ---------------------------------------------------------------------------
# Generation (preview — writes nothing)
# ---------------------------------------------------------------------------
@router.post(
    "/risk-scenarios/generate",
    response_model=GenerateResponse,
    dependencies=[_READ],
    summary="Propose risks for the selected assets — writes nothing",
)
async def generate(body: GenerateRequest, db: DbSession, user: CurrentUser) -> GenerateResponse:
    assets = await _select_assets(db, body)
    if not assets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No assets matched — select assets or widen the filter",
        )

    scenario_stmt = select(RiskScenarioTemplate).where(RiskScenarioTemplate.enabled.is_(True))
    if body.scenario_ids:
        scenario_stmt = scenario_stmt.where(RiskScenarioTemplate.id.in_(body.scenario_ids))
    if body.category:
        scenario_stmt = scenario_stmt.where(RiskScenarioTemplate.category == body.category)
    scenarios = (await db.scalars(scenario_stmt.order_by(RiskScenarioTemplate.reference))).all()
    if not scenarios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No scenarios in the library. Install the built-in catalogue first "
                "(Threat Library → Scenarios → Install library)."
            ),
        )

    matrix_size = await get_matrix_size(db, user.tenant_id)
    placements = await _placements(db, [a.id for a in assets])

    # Every applicable pair with its candidate key, before anything is skipped. Pairs of
    # the right class but the wrong kind (fraud against a firewall) are counted, by
    # scenario, so the preview can say what it left out and why.
    pairs: list[tuple[Asset, RiskScenarioTemplate, ScenarioSpec, AssetFacts, Placement, str]] = []
    not_fitting: dict[str, list] = {}
    specs = [(row, _spec(row)) for row in scenarios]
    for asset in assets:
        facts = _facts(asset)
        where = placements.get(asset.id) or Placement(asset_class=asset.asset_class.value)
        for row, spec in specs:
            fit = scenario_fit(spec, facts)
            if fit == WRONG_KIND:
                not_fitting.setdefault(row.reference, [row, spec, 0])[2] += 1
            if fit != FITS:
                continue
            key = dedupe_key(row.reference, where.process_id, where.business_unit_id, where.asset_class)
            pairs.append((asset, row, spec, facts, where, key))

    # Already in the register: the pair's own title (a hand-made or pre-queue risk),
    # an accepted candidate with the key whose risk is live, or a pre-queue generated
    # risk covering the key. Re-running after adding assets proposes only what is new.
    keys = {p[5] for p in pairs}
    owners = await _key_owners(db, keys)
    register = await _register_rows(db)
    existing_titles = _titles_index(register)
    legacy = await _legacy_keys(db, register, scenarios, keys)

    # The organisation's catalogue by reference, once. A scenario names the controls
    # that address it ("A.8.5", "CIS 6.3"); what resolves depends on which frameworks
    # this organisation has installed, and what does not is reported on the proposal.
    catalogue_rows = (await db.scalars(select(Control).where(Control.deleted.is_(False)))).all()
    catalogue = {(c.reference or "").strip().lower(): c.id for c in catalogue_rows if c.reference}
    labels = {c.id: (c.reference or c.name) for c in catalogue_rows}

    proposals: list[RiskProposal] = []
    duplicates = 0
    truncated = False
    for asset, row, spec, facts, where, key in pairs:
        title = title_for(spec, facts)
        owner = owners.get(key)
        if (
            title.strip().lower() in existing_titles
            or key in legacy
            or (owner is not None and owner.status == ACCEPTED)
        ):
            duplicates += 1
            continue
        if len(proposals) >= body.limit:
            truncated = True
            break
        likelihood = likelihood_for(spec, facts, matrix_size)
        impact = impact_for(spec, facts, matrix_size)
        # Live controls already protecting this asset travel with the proposal, so the
        # residual suggestion has evidence to work with as soon as the risk exists.
        asset_controls = [c.id for c in asset.controls if not c.deleted]
        mapped_ids, unmapped = control_mapping.resolve_controls(spec.control_references, catalogue)
        all_ids = control_mapping.merge_controls(asset_controls, mapped_ids)
        queued = owner if owner is not None and owner.status == PENDING else None
        rejected = owner if owner is not None and owner.status == REJECTED else None
        proposals.append(
            RiskProposal(
                scenario_id=row.id,
                scenario_reference=row.reference,
                asset_id=asset.id,
                asset_name=asset.name,
                title=title,
                description=spec.description,
                category=spec.category,
                inherent_likelihood=likelihood,
                inherent_impact=impact,
                inherent_score=likelihood * impact,
                threat=spec.threat,
                vulnerability=spec.vulnerability,
                treatment_description=spec.treatment_hint,
                control_ids=all_ids,
                control_labels=[labels.get(i, str(i)) for i in all_ids],
                unmapped_references=unmapped,
                dedupe_key=key,
                scope_label=scope_label(where),
                group_title=group_title(row.title, group_subject(where)),
                queued_proposal_id=queued.proposal_id if queued else None,
                queued_title=queued.title if queued else "",
                rejected_note=rejected.note if rejected else "",
                rejected_at=rejected.decided_at if rejected else None,
                asset_kinds=kind_labels(facts.kinds),
            )
        )

    _disambiguate(proposals, {a.id: a for a in assets})
    proposals.sort(key=lambda p: (-p.inherent_score, p.asset_name, p.scenario_reference))
    return GenerateResponse(
        proposals=proposals,
        assets_considered=len(assets),
        scenarios_considered=len(scenarios),
        duplicates_skipped=duplicates,
        truncated=truncated,
        candidates=len({p.dedupe_key for p in proposals}),
        queued=sum(1 for p in proposals if p.queued_proposal_id),
        not_fitting=sum(n for _row, _spec_, n in not_fitting.values()),
        not_fitting_scenarios=[
            NotFittingScenario(
                reference=row.reference, title=(row.title or "").replace("{asset}", "…"), pairs=n,
                fits=kind_labels(spec.asset_kinds),
            )
            for row, spec, n in sorted(not_fitting.values(), key=lambda v: (-v[2], v[0].reference))
        ],
    )


def _asset_discriminator(asset: Asset) -> str:
    """Something that tells two same-named assets apart, preferring what a person reads."""
    for attr in ("hostname", "serial_number", "external_id", "ip_address", "location"):
        value = (getattr(asset, attr, "") or "").strip()
        if value:
            return value
    return str(asset.id)[:8]


def _disambiguate(proposals: list[RiskProposal], assets: dict[uuid.UUID, Asset]) -> None:
    """Make every proposed title unique, in place.

    Asset registers really do contain two distinct records with the same name — a pair
    of identically-named servers, the same application in two environments. Leaving
    the collision would produce two proposals nobody can tell apart, so colliding titles
    gain the asset's hostname/serial (or a short id) so they stay meaningful.
    """
    counts: dict[str, int] = {}
    for proposal in proposals:
        counts[proposal.title] = counts.get(proposal.title, 0) + 1
    for proposal in proposals:
        if counts.get(proposal.title, 0) < 2:
            continue
        asset = assets.get(proposal.asset_id)
        if asset is None:
            continue
        proposal.title = f"{proposal.title} ({_asset_discriminator(asset)})"


async def _select_assets(db: DbSession, body: GenerateRequest) -> list[Asset]:
    stmt = select(Asset).where(Asset.deleted.is_(False))
    if body.asset_ids:
        stmt = stmt.where(Asset.id.in_(body.asset_ids))
    if body.asset_class:
        stmt = stmt.where(Asset.asset_class == body.asset_class)
    rows = list((await db.scalars(stmt.order_by(Asset.name))).all())
    if body.min_criticality:
        # The effective criticality (see ``_facts``), computed per row: it depends on the
        # hosted information assets, so it has no column to filter on in SQL.
        floor = _CRIT_RANK[Criticality(body.min_criticality)]
        rows = [a for a in rows if _CRIT_RANK[a.effective_criticality] >= floor]
    return rows


# ---------------------------------------------------------------------------
# Commit — to the candidate queue, not the register
# ---------------------------------------------------------------------------
_SKIP_LIST_CAP = 200


@router.post(
    "/risk-scenarios/commit",
    response_model=CommitResult,
    status_code=201,
    dependencies=[_WRITE],
    summary="Send reviewed proposals to the risk candidate queue",
)
async def commit(body: CommitRequest, db: DbSession, user: CurrentUser) -> CommitResult:
    """Queue the reviewed pairs as candidates (``RiskProposal``, status *pending*).

    Pairs are grouped by their candidate key; a key with a pending candidate gains the
    pair's asset; a key the register already covers is skipped. One ``run_id`` marks the
    candidates this call created. Pairs that cannot be queued (the asset was deleted
    since the preview, the scenario removed, a score outside the matrix) are reported
    in ``errors`` and the rest go ahead. See ``services.risk_scenarios.plan_commit``.
    """
    await _lock_queue(db, user.tenant_id)
    run_id = uuid.uuid4()
    by_id, by_ref = await _templates(db)
    size = await get_matrix_size(db, user.tenant_id)

    asset_ids = {item.asset_id for item in body.items}
    assets = {
        r.id: r
        for r in (
            await db.execute(
                select(
                    Asset.id, Asset.name, Asset.asset_class, Asset.criticality, Asset.business_value,
                    Asset.confidentiality, Asset.integrity, Asset.availability,
                ).where(Asset.id.in_(list(asset_ids)), Asset.deleted.is_(False))
            )
        ).all()
    }
    placements = await _placements(db, assets)
    control_ids = {c for item in body.items for c in item.control_ids}
    control_refs: dict[uuid.UUID, str] = {}
    if control_ids:
        control_refs = {
            cid: ref
            for cid, ref in (
                await db.execute(
                    select(Control.id, Control.reference)
                    .where(Control.id.in_(list(control_ids)), Control.deleted.is_(False))
                )
            ).all()
            if ref
        }

    pairs: list[PairIn] = []
    errors: list[CommitError] = []
    used: dict[str, RiskScenarioTemplate] = {}
    for index, item in enumerate(body.items):
        template = by_id.get(item.scenario_id) if item.scenario_id else None
        if template is None and item.scenario_reference:
            template = by_ref.get(item.scenario_reference.upper())
        if template is None:
            errors.append(CommitError(title=item.title, message="Its scenario is no longer in the library"))
            continue
        asset = assets.get(item.asset_id)
        if asset is None:
            errors.append(CommitError(title=item.title, message="Its asset was deleted after the proposals were generated"))
            continue
        if item.inherent_likelihood > size or item.inherent_impact > size:
            errors.append(CommitError(
                title=item.title, message=f"Scores must be on this organisation's {size}x{size} matrix (1-{size})",
            ))
            continue
        where = placements.get(asset.id) or Placement(asset_class=_enum_value(asset.asset_class))
        used[template.reference.strip().upper()] = template
        pairs.append(PairIn(
            index=index,
            asset_id=asset.id,
            key=dedupe_key(template.reference, where.process_id, where.business_unit_id, where.asset_class),
            title=item.title.strip(),
            likelihood=item.inherent_likelihood,
            impact=item.inherent_impact,
            scenario_reference=template.reference,
            asset_name=asset.name,
            auto_title=title_for(_spec(template), _facts_from(asset)),
            group_title=group_title(template.title, group_subject(where)),
            refs=tuple(merge_refs(
                split_refs(template.control_references),
                [control_refs[c] for c in item.control_ids if c in control_refs],
            )),
            description=(item.description or template.description or "").strip(),
            business_unit_id=where.business_unit_id,
            process_id=where.process_id,
        ))

    keys = {p.key for p in pairs}
    owners = await _key_owners(db, keys)
    register = await _register_rows(db)
    plan = plan_commit(
        pairs,
        owners=owners,
        legacy_keys=await _legacy_keys(db, register, used.values(), keys),
        register_titles=_titles_index(register),
    )
    categories = await _category_ids(db, (t.category for t in used.values()))

    links: list[dict] = []
    touched: list[uuid.UUID] = []
    created: list[tuple[ProposalRow, list[uuid.UUID]]] = []
    for candidate in plan.new:
        first = candidate.pairs[0]
        template = used[first.scenario_reference.strip().upper()]
        likelihood, impact = candidate.scores
        row = ProposalRow(
            tenant_id=user.tenant_id,
            run_id=run_id,
            scenario_reference=template.reference,
            title=candidate.title,
            description=first.description,
            business_unit_id=first.business_unit_id,
            process_id=first.process_id,
            category_id=categories.get((template.category or "").strip().lower()),
            inherent_likelihood=likelihood,
            inherent_impact=impact,
            control_references=", ".join(candidate.refs),
            dedupe_key=candidate.key,
            status=PENDING,
            created_by_id=user.id,
            decision_note="",
        )
        db.add(row)
        created.append((row, candidate.asset_ids))
    if created:
        await db.flush()  # one round trip for every new candidate
    for row, candidate_assets in created:
        touched.append(row.id)
        links.extend({"proposal_id": row.id, "asset_id": aid} for aid in candidate_assets)

    if plan.merges:
        existing = {
            r.id: r
            for r in (
                await db.scalars(
                    select(ProposalRow).where(ProposalRow.id.in_(list(plan.merges))).with_for_update()
                )
            ).all()
        }
        current = await _asset_ids_by_proposal(db, list(existing), live_only=False)
        names = await _asset_names(db, {aid for ids in current.values() for aid in ids})
        for proposal_id, joining in plan.merges.items():
            row = existing.get(proposal_id)
            if row is None:
                continue
            template = by_ref.get((row.scenario_reference or "").strip().upper())
            assets_after = list(dict.fromkeys([*current.get(row.id, []), *(p.asset_id for p in joining)]))
            added = [aid for aid in assets_after if aid not in set(current.get(row.id, []))]
            single = {p.auto_title.lower() for p in joining if p.auto_title}
            if template is not None:
                single |= {_auto_title(template, names[a]).lower() for a in current.get(row.id, []) if a in names}
            before = (row.inherent_likelihood, row.inherent_impact, row.title)
            row.inherent_likelihood, row.inherent_impact = worst_scores(
                [(row.inherent_likelihood, row.inherent_impact), *((p.likelihood, p.impact) for p in joining)]
            )
            row.control_references = ", ".join(
                merge_refs(split_refs(row.control_references), *(p.refs for p in joining))
            )
            row.title = candidate_title(
                [row.title, *(p.title for p in joining)],
                group=joining[0].group_title or row.title,
                asset_count=len(assets_after),
                single_asset_titles=single,
            )
            touched.append(row.id)
            links.extend({"proposal_id": row.id, "asset_id": aid} for aid in added)
            await audit_log.record(
                db, actor=user, action="update", entity_type="risk_proposal", entity_id=row.id,
                summary=f"Added {len(added)} asset(s) to risk candidate “{row.title}” from a new generation run",
                changes={
                    "run_id": str(run_id), "assets_added": len(added),
                    **({"scores": f"{before[0]}x{before[1]} -> {row.inherent_likelihood}x{row.inherent_impact}"}
                       if (before[0], before[1]) != (row.inherent_likelihood, row.inherent_impact) else {}),
                    **({"title": f"{before[2]} -> {row.title}"} if before[2] != row.title else {}),
                },
            )
    await _link_assets(db, links)
    await db.flush()

    await audit_log.record(
        db, actor=user, action="create", entity_type="risk_proposal", entity_id=None,
        summary=(
            f"Sent {len(pairs)} generated proposal(s) to the risk candidate queue: {plan.created} new "
            f"candidate(s), {plan.merged} merged, {len(plan.skipped)} already in the register"
        ),
        changes={
            "run_id": str(run_id), "created": plan.created, "merged": plan.merged,
            "merged_into_existing": plan.merged_into_existing, "skipped": len(plan.skipped),
            "failed": len(errors), "requested": len(body.items),
        },
    )
    return CommitResult(
        run_id=run_id,
        created=plan.created,
        merged=plan.merged,
        merged_into_existing=plan.merged_into_existing,
        skipped=len(plan.skipped),
        proposals=list(dict.fromkeys(touched)),
        skipped_items=[
            CommitSkip(title=pair.title, asset_name=pair.asset_name, risk_reference=ref)
            for pair, ref in plan.skipped[:_SKIP_LIST_CAP]
        ],
        errors=errors,
    )

# ---------------------------------------------------------------------------
# The candidate queue
# ---------------------------------------------------------------------------
#: A promoted candidate is a scenario-level risk (level 3 of the hierarchy): its parent,
#: when one is picked, is an enterprise or category risk.
PROMOTED_LEVEL = 3

#: The candidate's picked fields, read as ``<name>_ref`` (one query per kind per page).
PROPOSAL_REFS: tuple[ref_fields.RefField, ...] = (
    ref_fields.unit("business_unit_id", None),
    ref_fields.process("process_id", None),
    ref_fields.RefField("category_id", None, "lookup", "risk_category"),
    ref_fields.user("created_by_id", None),
    ref_fields.user("decided_by_id", None),
)


def _proposal_filters(
    stmt,
    *,
    search: str | None,
    scenario: str | None,
    business_unit_id: uuid.UUID | None,
    process_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    asset_id: uuid.UUID | None,
):
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(ProposalRow.title.ilike(like), ProposalRow.scenario_reference.ilike(like)))
    if scenario:
        stmt = stmt.where(func.upper(ProposalRow.scenario_reference) == scenario.strip().upper())
    if business_unit_id is not None:
        stmt = stmt.where(ProposalRow.business_unit_id == business_unit_id)
    if process_id is not None:
        stmt = stmt.where(ProposalRow.process_id == process_id)
    if run_id is not None:
        stmt = stmt.where(ProposalRow.run_id == run_id)
    if asset_id is not None:
        stmt = stmt.where(
            select(risk_proposal_assets.c.proposal_id)
            .where(
                risk_proposal_assets.c.proposal_id == ProposalRow.id,
                risk_proposal_assets.c.asset_id == asset_id,
            )
            .exists()
        )
    return stmt


@router.get(
    "/risk-proposals",
    response_model=ProposalPage,
    dependencies=[_READ],
    summary="Risk candidates waiting for a decision (and those decided), with counts by status",
)
async def list_proposals(
    db: DbSession,
    user: CurrentUser,
    status_filter: Annotated[str | None, Query(alias="status", pattern="^(pending|accepted|rejected|merged)$")] = None,
    search: str | None = None,
    scenario: str | None = None,
    business_unit_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProposalPage:
    base = _proposal_filters(
        select(ProposalRow), search=search, scenario=scenario, business_unit_id=business_unit_id,
        process_id=process_id, run_id=run_id, asset_id=asset_id,
    )
    sub = base.subquery()
    counts = dict((await db.execute(select(sub.c.status, func.count()).group_by(sub.c.status))).all())
    stmt = base.where(ProposalRow.status == status_filter) if status_filter else base
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    score = func.coalesce(ProposalRow.inherent_likelihood, 0) * func.coalesce(ProposalRow.inherent_impact, 0)
    rows = list(
        (
            await db.scalars(
                stmt.order_by(ProposalRow.scenario_reference, score.desc(), ProposalRow.title, ProposalRow.id)
                .limit(limit).offset(offset)
            )
        ).all()
    )
    return ProposalPage(
        items=await _proposal_reads(db, user, rows),
        total=total,
        limit=limit,
        offset=offset,
        counts={s: int(counts.get(s, 0)) for s in PROPOSAL_STATUSES},
    )


async def _proposal_reads(db, user: CurrentUser, rows: Sequence[ProposalRow]) -> list[ProposalRead]:
    """Read models for a page of candidates: live assets, controls resolved against the
    catalogue now, the scenario, the promoted risk or the survivor, and severity on the
    tenant's matrix. A fixed number of queries whatever the page size."""
    if not rows:
        return []
    ids = [r.id for r in rows]
    assets: dict[uuid.UUID, list[ProposalAssetRef]] = {pid: [] for pid in ids}
    archived: dict[uuid.UUID, int] = {pid: 0 for pid in ids}
    for pid, aid, name, asset_class, deleted in (
        await db.execute(
            select(risk_proposal_assets.c.proposal_id, Asset.id, Asset.name, Asset.asset_class, Asset.deleted)
            .join(Asset, Asset.id == risk_proposal_assets.c.asset_id)
            .where(risk_proposal_assets.c.proposal_id.in_(ids))
            .order_by(Asset.name)
        )
    ).all():
        if deleted:
            archived[pid] += 1
        else:
            assets[pid].append(ProposalAssetRef(id=aid, name=name or "", asset_class=_enum_value(asset_class)))

    wanted_refs = {ref.lower() for r in rows for ref in split_refs(r.control_references)}
    catalogue: dict[str, ProposalControlRef] = {}
    if wanted_refs:
        for cid, ref, name in (
            await db.execute(
                select(Control.id, Control.reference, Control.name)
                .where(func.lower(Control.reference).in_(sorted(wanted_refs)), Control.deleted.is_(False))
            )
        ).all():
            catalogue.setdefault((ref or "").strip().lower(), ProposalControlRef(id=cid, reference=ref or "", name=name or ""))

    scenario_refs = {(r.scenario_reference or "").strip().upper() for r in rows}
    templates = {
        (ref or "").strip().upper(): (title or "", category or "")
        for ref, title, category in (
            await db.execute(
                select(RiskScenarioTemplate.reference, RiskScenarioTemplate.title, RiskScenarioTemplate.category)
                .where(func.upper(RiskScenarioTemplate.reference).in_(sorted(scenario_refs)))
            )
        ).all()
    }
    promoted_ids = {r.promoted_risk_id for r in rows if r.promoted_risk_id}
    promoted: dict[uuid.UUID, tuple[GraphRef, bool]] = {}
    if promoted_ids:
        for rid, ref, title, deleted in (
            await db.execute(select(Risk.id, Risk.reference, Risk.title, Risk.deleted).where(Risk.id.in_(promoted_ids)))
        ).all():
            promoted[rid] = (GraphRef(id=rid, reference=ref or "", title=title or ""), bool(deleted))
    sources = await _source_risks(db, [r for r in rows if getattr(r, "source_risk_id", None)])
    survivor_ids = {r.merged_into_id for r in rows if r.merged_into_id}
    survivors: dict[uuid.UUID, GraphRef] = {}
    if survivor_ids:
        for pid, title in (
            await db.execute(select(ProposalRow.id, ProposalRow.title).where(ProposalRow.id.in_(survivor_ids)))
        ).all():
            survivors[pid] = GraphRef(id=pid, title=title or "")

    scale = scale_for(await get_or_create_settings(db, user.tenant_id))
    reads: list[ProposalRead] = []
    for row in rows:
        read = ProposalRead.model_validate(row)
        likelihood, impact = row.inherent_likelihood, row.inherent_impact
        if likelihood and impact:
            read.inherent_score = likelihood * impact
            band = scale.for_cell(likelihood, impact)
            read.inherent_severity = band.value if band else None
        read.assets = assets.get(row.id, [])
        read.archived_assets = archived.get(row.id, 0)
        found = [catalogue[ref.lower()] for ref in read.control_references if ref.lower() in catalogue]
        read.controls = list({c.id: c for c in found}.values())
        read.unmapped_references = [ref for ref in read.control_references if ref.lower() not in catalogue]
        title, category = templates.get((row.scenario_reference or "").strip().upper(), ("", ""))
        read.scenario_title = title.replace("{asset}", "…")
        read.scenario_category = category
        if row.promoted_risk_id in promoted:
            read.promoted_risk, read.promoted_risk_archived = promoted[row.promoted_risk_id]
        read.merged_into = survivors.get(row.merged_into_id) if row.merged_into_id else None
        read.source_risks = sources.get(row.id, [])
        reads.append(read)
    await ref_fields.fill_refs(db, list(zip(rows, reads)), PROPOSAL_REFS)
    return reads


async def _source_risks(db, rows: Sequence[ProposalRow]) -> dict[uuid.UUID, list[SourceRiskRef]]:
    """The pre-queue register risks each candidate was rebuilt from. ``source_risk_id``
    names the first; every one moved in carries the candidate's id on its archive entry
    in the activity trail (``services.legacy_risk_migration``). Two queries."""
    if not rows:
        return {}
    from app.models.audit import AuditLog
    from app.services.legacy_risk_migration import MIGRATION_VIA

    wanted = {str(r.id): r.id for r in rows}
    by_proposal: dict[uuid.UUID, list[uuid.UUID]] = {r.id: [r.source_risk_id] for r in rows}
    for risk_id, proposal_id in (
        await db.execute(
            select(AuditLog.entity_id, AuditLog.changes["proposal_id"].astext).where(
                AuditLog.entity_type == "risk",
                AuditLog.changes["via"].astext == MIGRATION_VIA,
                AuditLog.changes["proposal_id"].astext.in_(sorted(wanted)),
            )
        )
    ).all():
        pid = wanted.get(proposal_id or "")
        if pid is not None and risk_id is not None and risk_id not in by_proposal[pid]:
            by_proposal[pid].append(risk_id)
    risk_ids = {rid for ids in by_proposal.values() for rid in ids}
    found = {
        rid: SourceRiskRef(id=rid, reference=ref or "", title=title or "", archived=bool(deleted))
        for rid, ref, title, deleted in (
            await db.execute(select(Risk.id, Risk.reference, Risk.title, Risk.deleted).where(Risk.id.in_(risk_ids)))
        ).all()
    }
    return {
        pid: sorted((found[rid] for rid in ids if rid in found), key=lambda r: r.reference)
        for pid, ids in by_proposal.items()
    }


async def _lock_proposals(db, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, ProposalRow]:
    """The candidates, locked for this transaction so two people cannot decide the same
    one twice."""
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return {}
    rows = (
        await db.scalars(select(ProposalRow).where(ProposalRow.id.in_(wanted)).with_for_update())
    ).all()
    return {r.id: r for r in rows}


def _undecidable(proposal_id: uuid.UUID, row: ProposalRow | None) -> ProposalError | None:
    """Why a candidate cannot be decided now, or None when it is pending."""
    if row is None:
        return ProposalError(id=proposal_id, message="Candidate not found")
    if row.status != PENDING:
        return ProposalError(id=proposal_id, title=row.title, message=f"Already {row.status}")
    return None


def _promotion_payload(
    proposal,
    template,
    *,
    asset_ids: Sequence[uuid.UUID],
    control_ids: Sequence[uuid.UUID],
    threat_ids: Sequence[uuid.UUID],
    vulnerability_ids: Sequence[uuid.UUID],
    category_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
) -> RiskCreate:
    """The register risk a candidate becomes: a **draft** (provisional scores, no
    rationale yet), source *generated*, a scenario-level (3) risk under the picked
    parent, linked to the candidate's live assets, unit and process, controls and the
    scenario's threat and vulnerability. The picked category wins over the candidate's;
    without either, the scenario's category text is matched onto the list by the risk
    module (``ref_fields``)."""
    chosen = category_id or proposal.category_id
    return RiskCreate(
        title=proposal.title,
        description=proposal.description or (template.description if template else ""),
        category_id=chosen,
        category="" if chosen else ((template.category or "") if template else ""),
        inherent_likelihood=proposal.inherent_likelihood,
        inherent_impact=proposal.inherent_impact,
        treatment_description=(template.treatment_hint or "") if template else "",
        source="generated",
        owner_id=owner_id,
        parent_id=parent_id,
        level=PROMOTED_LEVEL,
        asset_ids=list(asset_ids),
        business_unit_ids=[proposal.business_unit_id] if proposal.business_unit_id else [],
        process_ids=[proposal.process_id] if proposal.process_id else [],
        control_ids=list(control_ids),
        threat_ids=list(threat_ids),
        vulnerability_ids=list(vulnerability_ids),
    )


async def _check_accept_choices(db, body: AcceptRequest) -> None:
    """Validate the category, owner and parent once, so a bad pick refuses the request
    instead of failing every candidate in it."""
    from app.api.v1.risks import _hierarchy_node  # local import avoids a circular module load

    await master_data.check_lookup(db, body.category_id, "risk_category", "category_id")
    await master_data.check_user(db, body.owner_id, "owner_id")
    if body.parent_id is not None:
        try:
            risk_hierarchy.place(
                risk_id=None, parent_id=body.parent_id, parent=await _hierarchy_node(db, body.parent_id),
                level=PROMOTED_LEVEL, level_given=True,
            )
        except risk_hierarchy.HierarchyError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/risk-proposals/accept",
    response_model=AcceptResult,
    dependencies=[_WRITE],
    summary="Promote candidates to draft register risks through the risk module's create path",
)
async def accept_proposals(body: AcceptRequest, db: DbSession, user: CurrentUser) -> AcceptResult:
    """Each pending candidate becomes a risk via ``risks.create_risk`` — so references,
    the Phase 0–2 rules, links, versioning and the risk's own audit entry behave exactly
    as for a hand-made risk — in its own savepoint: one failure is reported and the
    rest go ahead. Controls are resolved from the candidate's references against the
    catalogue as generation does, plus the assets' own live controls; the risk is linked
    to the clauses those controls satisfy. The candidate records the risk, who decided
    and when, with one audit entry per candidate."""
    from app.api.v1.risks import create_risk  # local import avoids a circular module load

    await _check_accept_choices(db, body)
    rows = await _lock_proposals(db, body.ids)
    _, by_ref = await _templates(db)
    catalogue = {
        (ref or "").strip().lower(): cid
        for cid, ref in (
            await db.execute(select(Control.id, Control.reference).where(Control.deleted.is_(False)))
        ).all()
        if ref
    }
    live_assets = await _asset_ids_by_proposal(db, list(rows), live_only=True)
    asset_controls: dict[uuid.UUID, list[uuid.UUID]] = {}
    every_asset = {aid for ids in live_assets.values() for aid in ids}
    if every_asset:
        for aid, cid in (
            await db.execute(
                select(control_assets.c.asset_id, Control.id)
                .join(Control, Control.id == control_assets.c.control_id)
                .where(control_assets.c.asset_id.in_(list(every_asset)), Control.deleted.is_(False))
                .order_by(Control.reference)
            )
        ).all():
            asset_controls.setdefault(aid, []).append(cid)
    threats = await _name_index(db, Threat)
    vulns = await _name_index(db, Vulnerability)

    now = datetime.now(timezone.utc)
    note = body.note.strip()
    accepted: list[GraphRef] = []
    errors: list[ProposalError] = []
    for proposal_id in dict.fromkeys(body.ids):
        row = rows.get(proposal_id)
        problem = _undecidable(proposal_id, row)
        if problem is not None:
            errors.append(problem)
            continue
        title = row.title
        asset_ids = live_assets.get(row.id, [])
        if not asset_ids:
            errors.append(ProposalError(
                id=row.id, title=title,
                message="Every asset it was generated for has been deleted since; reject it instead",
            ))
            continue
        template = by_ref.get((row.scenario_reference or "").strip().upper())
        mapped, _unmapped = control_mapping.resolve_controls(split_refs(row.control_references), catalogue)
        own = list(dict.fromkeys(c for aid in asset_ids for c in asset_controls.get(aid, [])))
        control_ids = control_mapping.merge_controls(own, mapped)
        category = (template.category or "") if template else ""
        try:
            # Catalogue entries are harmless and shared: created outside the savepoint so
            # a later rollback cannot leave a cached id pointing at nothing.
            threat_ids = await _ensure_catalog(db, user, Threat, threats, template.threat if template else "", category)
            vuln_ids = await _ensure_catalog(
                db, user, Vulnerability, vulns, template.vulnerability if template else "", category
            )
            payload = _promotion_payload(
                row, template, asset_ids=asset_ids, control_ids=control_ids, threat_ids=threat_ids,
                vulnerability_ids=vuln_ids, category_id=body.category_id, owner_id=body.owner_id,
                parent_id=body.parent_id,
            )
            async with db.begin_nested():
                risk = await create_risk(body=payload, db=db, user=user)
                await _link_clauses(db, risk.id, control_ids)
                row.status = ACCEPTED
                row.promoted_risk_id = risk.id
                row.decided_by_id = user.id
                row.decided_at = now
                row.decision_note = note
                await db.flush()
                await audit_log.record(
                    db, actor=user, action="accept", entity_type="risk_proposal", entity_id=row.id,
                    summary=f"Accepted risk candidate “{title}” into the register as {risk.reference}",
                    changes={
                        "risk_id": str(risk.id), "risk_reference": risk.reference, "assets": len(asset_ids),
                        "controls": len(control_ids), **({"note": note} if note else {}),
                        **({"parent_id": str(body.parent_id)} if body.parent_id else {}),
                    },
                )
            accepted.append(GraphRef(id=risk.id, reference=risk.reference, title=risk.title))
        except HTTPException as exc:
            errors.append(ProposalError(id=proposal_id, title=title, message=_clean_detail(exc.detail)))
        except Exception as exc:  # noqa: BLE001 - per-candidate isolation, as in bulk import
            errors.append(ProposalError(id=proposal_id, title=title, message=_clean(exc)))
    return AcceptResult(accepted=len(accepted), risks=accepted, errors=errors)


@router.post(
    "/risk-proposals/reject",
    response_model=RejectResult,
    dependencies=[_WRITE],
    summary="Reject candidates, with the reason",
)
async def reject_proposals(body: RejectRequest, db: DbSession, user: CurrentUser) -> RejectResult:
    """Pending candidates become *rejected* with the reason kept on each; the next
    generation run shows the reason and leaves such pairs unticked. Candidates already
    decided are listed in ``skipped``, not changed."""
    rows = await _lock_proposals(db, body.ids)
    now = datetime.now(timezone.utc)
    decided: list[ProposalRow] = []
    skipped: list[ProposalError] = []
    for proposal_id in dict.fromkeys(body.ids):
        row = rows.get(proposal_id)
        problem = _undecidable(proposal_id, row)
        if problem is not None:
            skipped.append(problem)
            continue
        row.status = REJECTED
        row.decided_by_id = user.id
        row.decided_at = now
        row.decision_note = body.note
        decided.append(row)
    await db.flush()
    for row in decided:
        await audit_log.record(
            db, actor=user, action="reject", entity_type="risk_proposal", entity_id=row.id,
            summary=f"Rejected risk candidate “{row.title}”: {body.note}",
            changes={"note": body.note, "scenario": row.scenario_reference},
        )
    return RejectResult(rejected=len(decided), skipped=skipped)


@router.post(
    "/risk-proposals/merge",
    response_model=MergeResult,
    dependencies=[_WRITE],
    summary="Fold candidates into one: assets and control references move to the survivor",
)
async def merge_proposals(body: MergeRequest, db: DbSession, user: CurrentUser) -> MergeResult:
    """The survivor gains every asset and control reference of the others and the worst
    of their scores; the others become *merged* (``merged_into_id``). Their key follows
    the survivor from then on, so a later generation run adds to the survivor — or skips,
    once it is in the register. All candidates must be pending."""
    others_ids = [i for i in dict.fromkeys(body.ids) if i != body.into_id]
    if not others_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pick at least one other candidate to merge into the one you keep",
        )
    rows = await _lock_proposals(db, [body.into_id, *others_ids])
    survivor = rows.get(body.into_id)
    if survivor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The candidate to keep was not found")
    if survivor.status != PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"“{survivor.title}” is already {survivor.status}; only a pending candidate can absorb others",
        )
    missing = [i for i in others_ids if i not in rows]
    if missing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{len(missing)} candidate(s) not found")
    decided = [rows[i] for i in others_ids if rows[i].status != PENDING]
    if decided:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending candidates can be merged: " + ", ".join(
                f"“{r.title}” is {r.status}" for r in decided[:3]
            ),
        )
    others = [rows[i] for i in others_ids]
    held = await _asset_ids_by_proposal(db, [survivor.id, *others_ids], live_only=False)
    outcome = merge_candidates(
        (survivor.inherent_likelihood, survivor.inherent_impact),
        survivor.control_references,
        held.get(survivor.id, []),
        [((o.inherent_likelihood, o.inherent_impact), o.control_references, held.get(o.id, [])) for o in others],
    )
    before = survivor.title
    added = [aid for aid in outcome.asset_ids if aid not in set(held.get(survivor.id, []))]
    survivor.inherent_likelihood, survivor.inherent_impact = outcome.likelihood, outcome.impact
    survivor.control_references = outcome.control_references
    survivor.title = await _survivor_title(db, survivor, outcome.asset_ids)
    await _link_assets(db, [{"proposal_id": survivor.id, "asset_id": aid} for aid in added])

    now = datetime.now(timezone.utc)
    note = body.note.strip()
    for other in others:
        other.status = MERGED
        other.merged_into_id = survivor.id
        other.decided_by_id = user.id
        other.decided_at = now
        other.decision_note = note or f"Merged into “{survivor.title}”"
    await db.flush()
    for other in others:
        await audit_log.record(
            db, actor=user, action="merge", entity_type="risk_proposal", entity_id=other.id,
            summary=f"Merged risk candidate “{other.title}” into “{survivor.title}”",
            changes={"merged_into_id": str(survivor.id), **({"note": note} if note else {})},
        )
    await audit_log.record(
        db, actor=user, action="update", entity_type="risk_proposal", entity_id=survivor.id,
        summary=f"Risk candidate “{survivor.title}” absorbed {len(others)} candidate(s)",
        changes={
            "absorbed": ", ".join(str(o.id) for o in others), "assets_added": len(added),
            **({"title": f"{before} -> {survivor.title}"} if before != survivor.title else {}),
        },
    )
    return MergeResult(merged=len(others), survivor=(await _proposal_reads(db, user, [survivor]))[0])


# ---------------------------------------------------------------------------
# Generated risks made before the queue (re-check F-24)
# ---------------------------------------------------------------------------
@router.get(
    "/risk-proposals/legacy-migration",
    response_model=LegacyMigrationPlan,
    dependencies=[_READ],
    summary="What moving generated risks made before the candidate queue into it would do — writes nothing",
)
async def legacy_migration_plan(db: DbSession) -> LegacyMigrationPlan:
    """Register risks the old one-risk-per-asset generator wrote, and what would happen
    to each: moved into a new or waiting candidate, dropped (archived without a
    candidate), or kept in the register with the reason. Rules:
    ``services.legacy_risk_migration``."""
    from app.services import legacy_risk_migration

    plan, _ctx = await legacy_risk_migration.load_plan(db)
    return legacy_risk_migration.plan_read(plan)


@router.post(
    "/risk-proposals/legacy-migration",
    response_model=LegacyMigrationResult,
    dependencies=[_WRITE, _ARCHIVE],
    summary="Move generated risks made before the candidate queue into it",
)
async def apply_legacy_migration(db: DbSession, user: CurrentUser) -> LegacyMigrationResult:
    """Carry out the plan as it stands now: moved and dropped risks are archived (each
    restorable, each with an activity-trail entry saying where it went), candidates are
    created or added to, and one summary entry is written. Needs ``risk:write`` and
    ``risk:delete``. Running it again only picks up what is new."""
    from app.services import legacy_risk_migration

    return await legacy_risk_migration.apply(db, user)


async def _survivor_title(db, row: ProposalRow, asset_ids: Sequence[uuid.UUID]) -> str:
    """A candidate covering several assets never keeps a title that names only one of
    them (``candidate_title``); its group title comes from its own unit and process."""
    if len(asset_ids) <= 1:
        return row.title
    _, by_ref = await _templates(db)
    template = by_ref.get((row.scenario_reference or "").strip().upper())
    if template is None:
        return row.title
    names = await _asset_names(db, asset_ids)
    unit = await db.get(BusinessUnit, row.business_unit_id) if row.business_unit_id else None
    process = await db.get(Process, row.process_id) if row.process_id else None
    asset_class = (row.dedupe_key or "").split("|")[3] if (row.dedupe_key or "").count("|") >= 3 else ""
    where = Placement(
        asset_class=asset_class,
        process_id=row.process_id, process_name=(process.name if process and not process.deleted else ""),
        business_unit_id=row.business_unit_id, business_unit_name=(unit.name if unit and not unit.deleted else ""),
    )
    return candidate_title(
        [row.title],
        group=group_title(template.title, group_subject(where)),
        asset_count=len(asset_ids),
        single_asset_titles={_auto_title(template, n).lower() for n in names.values()},
    )


# ---------------------------------------------------------------------------
# Promotion helpers (shared with the pre-queue commit path)
# ---------------------------------------------------------------------------
def _clauses_for_controls_stmt(control_ids: list[uuid.UUID]):
    """The framework clauses the given controls satisfy — one row per clause."""
    return (
        select(requirement_controls.c.requirement_id)
        .where(requirement_controls.c.control_id.in_(control_ids))
        .distinct()
    )


async def _link_clauses(db: DbSession, risk_id: uuid.UUID, control_ids: list[uuid.UUID]) -> int:
    """Link a generated risk to every clause its controls satisfy.

    Scenario -> controls -> clauses is now known, so the risk-to-requirement edge is
    free: the compliance module can show the risks behind each clause, and the register
    can be cut by framework domain — the "assess by control objective" the client asked
    for. Only generated risks are linked this way; a hand-made risk's clause links are
    the author's choice.
    """
    if not control_ids:
        return 0
    clause_ids = list((await db.scalars(_clauses_for_controls_stmt(control_ids))).all())
    if not clause_ids:
        return 0
    await db.execute(
        pg_insert(requirement_risks)
        .values([{"requirement_id": rid, "risk_id": risk_id} for rid in clause_ids])
        .on_conflict_do_nothing()
    )
    return len(clause_ids)


async def _name_index(db: DbSession, model: type) -> dict[str, uuid.UUID]:
    rows = (await db.scalars(select(model))).all()
    return {(r.name or "").strip().lower(): r.id for r in rows if r.name}


async def _ensure_catalog(
    db: DbSession,
    user: CurrentUser,
    model: type,
    index: dict[str, uuid.UUID],
    name: str,
    category: str,
) -> list[uuid.UUID]:
    """Resolve a threat/vulnerability name to an id, creating the entry if it is new.

    Creating on demand keeps the generated risk's graph links real even when the library
    was edited to name something the catalogue never seeded.
    """
    label = (name or "").strip()
    if not label:
        return []
    key = label.lower()
    found = index.get(key)
    if found is None:
        row = model(tenant_id=user.tenant_id, name=label, category=category)
        db.add(row)
        await db.flush()
        index[key] = row.id
        found = row.id
    return [found]


def _clean(exc: Exception) -> str:
    message = " ".join(str(exc).strip().splitlines()) or exc.__class__.__name__
    return message[:300]


def _clean_detail(detail) -> str:
    """An HTTPException's detail as one sentence (validation details are lists)."""
    if isinstance(detail, list):
        parts = [str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail]
        return "; ".join(parts)[:300]
    return " ".join(str(detail).split())[:300]
