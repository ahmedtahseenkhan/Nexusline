"""Risk-scenario library and asset-driven risk generation.

The register a bank is asked to produce starts from the asset inventory it already has.
This module closes that gap the ISO 27005 way — threat exploits vulnerability against an
asset — by pairing selected assets with the applicable scenario templates and proposing
pre-scored risks.

Two endpoints do the work, deliberately split:

* ``POST /risk-scenarios/generate`` returns **proposals and writes nothing.** The user
  sees exactly what would be created, edits the scores, and unticks what does not apply.
* ``POST /risk-scenarios/commit`` creates the reviewed subset through the risk module's
  own ``create_risk``, so references, links, versioning and audit logging behave exactly
  as they do for a hand-made risk.

Generation is de-duplicated against the existing register by title, so re-running it
after adding fifty assets proposes fifty assets' worth of new risks rather than a second
copy of everything.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.asset import Asset
from app.models.enums import Criticality
from app.models.risk import Risk
from app.models.risk_scenario import RiskScenarioTemplate
from app.models.threat import Threat, Vulnerability
from app.schemas.common import Page
from app.schemas.risk import RiskCreate
from app.schemas.risk_scenario import (
    CommitError,
    CommitRequest,
    CommitResult,
    GenerateRequest,
    GenerateResponse,
    LibraryInstallResult,
    RiskProposal,
    ScenarioCreate,
    ScenarioRead,
    ScenarioUpdate,
)
from app.services import audit as audit_log
from app.services.refs import next_reference
from app.services.risk_scenarios import (
    CATALOGUE,
    AssetFacts,
    ScenarioSpec,
    applies_to_asset,
    impact_for,
    likelihood_for,
    title_for,
)
from app.services.risk_settings import get_matrix_size

router = APIRouter(tags=["risk scenarios"])

_READ = Depends(require("risk:read"))
_WRITE = Depends(require("risk:write"))

_CRIT_RANK = {
    Criticality.low: 1, Criticality.medium: 2, Criticality.high: 3, Criticality.critical: 4,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _facts(asset: Asset) -> AssetFacts:
    return AssetFacts(
        name=asset.name,
        asset_class=asset.asset_class.value,
        criticality=asset.criticality,
        business_value=asset.business_value,
        confidentiality=asset.confidentiality,
        integrity=asset.integrity,
        availability=asset.availability,
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
        threat=row.threat,
        vulnerability=row.vulnerability,
        likelihood=row.likelihood,
        impact_rule=row.impact_rule,
        impact_property=row.impact_property,
        fixed_impact=row.fixed_impact,
        treatment_hint=row.treatment_hint,
    )


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
    existing = set((await db.scalars(select(RiskScenarioTemplate.reference))).all())
    installed = 0
    for spec in CATALOGUE:
        if spec.reference in existing:
            continue
        db.add(
            RiskScenarioTemplate(
                tenant_id=user.tenant_id,
                reference=spec.reference,
                title=spec.title,
                description=spec.description,
                category=spec.category,
                asset_classes=",".join(spec.asset_classes),
                threat=spec.threat,
                vulnerability=spec.vulnerability,
                likelihood=spec.likelihood,
                impact_rule=spec.impact_rule,
                impact_property=spec.impact_property,
                fixed_impact=spec.fixed_impact,
                treatment_hint=spec.treatment_hint,
            )
        )
        installed += 1

    await _seed_catalog_entries(db, user)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="risk_scenario", entity_id=None,
        summary=f"Installed {installed} risk scenario(s) from the built-in library",
        changes={"installed": installed, "total": len(CATALOGUE)},
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
# Generation
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

    # De-duplicate against the register by title. Titles are deterministic per
    # (scenario, asset), so re-running after adding assets proposes only the new pairs.
    existing_titles = {
        (t or "").strip().lower()
        for t in (
            await db.scalars(select(Risk.title).where(Risk.deleted.is_(False)))
        ).all()
    }

    matrix_size = await get_matrix_size(db, user.tenant_id)
    proposals: list[RiskProposal] = []
    duplicates = 0
    truncated = False

    for asset in assets:
        facts = _facts(asset)
        # Controls already protecting this asset travel with the proposal, so the
        # residual suggestion has evidence to work with as soon as the risk exists.
        control_ids = [c.id for c in asset.controls]
        control_labels = [c.reference or c.name for c in asset.controls]
        for row in scenarios:
            spec = _spec(row)
            if not applies_to_asset(spec, facts):
                continue
            title = title_for(spec, facts)
            if title.strip().lower() in existing_titles:
                duplicates += 1
                continue
            if len(proposals) >= body.limit:
                truncated = True
                break
            likelihood = likelihood_for(spec, facts, matrix_size)
            impact = impact_for(spec, facts, matrix_size)
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
                    control_ids=control_ids,
                    control_labels=control_labels,
                )
            )
        if truncated:
            break

    _disambiguate(proposals, {a.id: a for a in assets})
    proposals.sort(key=lambda p: (-p.inherent_score, p.asset_name, p.scenario_reference))
    return GenerateResponse(
        proposals=proposals,
        assets_considered=len(assets),
        scenarios_considered=len(scenarios),
        duplicates_skipped=duplicates,
        truncated=truncated,
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
    of identically-named servers, the same application in two environments. Because the
    title is the de-duplication key, leaving the collision would produce two risks nobody
    can tell apart *and* make the next run treat both as already-present. Colliding
    titles gain the asset's hostname/serial (or a short id) so they stay meaningful.
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
        floor = _CRIT_RANK[Criticality(body.min_criticality)]
        rows = [a for a in rows if _CRIT_RANK[a.criticality] >= floor]
    return rows


@router.post(
    "/risk-scenarios/commit",
    response_model=CommitResult,
    status_code=201,
    dependencies=[_WRITE],
    summary="Create the reviewed proposals as real risks",
)
async def commit(body: CommitRequest, db: DbSession, user: CurrentUser) -> CommitResult:
    """Create the reviewed subset through the risk module's own create path.

    Each proposal is written in its own savepoint, so one bad row (an asset deleted
    between review and commit, a score outside the matrix) is reported and skipped
    rather than losing the whole batch.
    """
    from app.api.v1.risks import create_risk  # local import avoids a circular module load

    threats = await _name_index(db, Threat)
    vulns = await _name_index(db, Vulnerability)

    created = 0
    references: list[str] = []
    errors: list[CommitError] = []

    for item in body.items:
        try:
            threat_ids = await _ensure_catalog(db, user, Threat, threats, item.threat, item.category)
            vuln_ids = await _ensure_catalog(
                db, user, Vulnerability, vulns, item.vulnerability, item.category
            )
            payload = RiskCreate(
                title=item.title,
                description=item.description,
                category=item.category,
                inherent_likelihood=item.inherent_likelihood,
                inherent_impact=item.inherent_impact,
                treatment_description=item.treatment_description,
                asset_ids=[item.asset_id],
                control_ids=item.control_ids,
                threat_ids=threat_ids,
                vulnerability_ids=vuln_ids,
            )
            async with db.begin_nested():
                risk = await create_risk(body=payload, db=db, user=user)
            created += 1
            references.append(risk.reference)
        except Exception as exc:  # noqa: BLE001 - per-item isolation, same as bulk import
            errors.append(CommitError(title=item.title, message=_clean(exc)))

    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="risk", entity_id=None,
        summary=f"Generated {created} risk(s) from the asset register",
        changes={"created": created, "requested": len(body.items), "failed": len(errors)},
    )
    return CommitResult(
        created=created, skipped=len(body.items) - created, references=references, errors=errors
    )


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
