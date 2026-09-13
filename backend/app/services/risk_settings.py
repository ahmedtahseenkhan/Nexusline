"""Per-tenant risk methodology: appetite/tolerance, matrix scale and residual policy.

Everything here lazily creates a sensible default row on first read, so a fresh tenant
has a working 5x5 register before anyone opens the settings screen — and an existing
installation keeps the behaviour it already had.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk import ResidualPolicy, RiskAppetite, RiskMatrixLevel, RiskSetting
from app.services.residual_engine import ResidualPolicySpec
from app.services.risk_scoring import (
    DEFAULT_MATRIX_SIZE,
    AppetiteBook,
    SeverityScale,
    max_score_for,
    validate_bands,
    validate_cells,
)

#: Generic scale wording used until a bank supplies its own. Deliberately plain: these
#: are placeholders that prompt someone to write the real criteria, not a methodology.
#: Covers the full 1..``MAX_MATRIX_SIZE`` range — a bank on a 1-10 scale that has not yet
#: written its criteria should still see words rather than bare numbers on rungs 7-10.
DEFAULT_LIKELIHOOD_LABELS: dict[int, str] = {
    1: "Rare", 2: "Unlikely", 3: "Possible", 4: "Likely", 5: "Almost certain",
    6: "Expected", 7: "Frequent", 8: "Very frequent", 9: "Near-continuous",
    10: "Continuous",
}
DEFAULT_IMPACT_LABELS: dict[int, str] = {
    1: "Insignificant", 2: "Minor", 3: "Moderate", 4: "Major", 5: "Severe",
    6: "Catastrophic", 7: "Grave", 8: "Critical to solvency", 9: "Existential",
    10: "Institution-ending",
}


async def get_or_create_settings(db: AsyncSession, tenant_id) -> RiskSetting:
    settings = await db.scalar(select(RiskSetting))  # RLS scopes to current tenant
    if settings is None:
        settings = RiskSetting(tenant_id=tenant_id)
        db.add(settings)
        await db.flush()
    return settings


async def get_matrix_size(db: AsyncSession, tenant_id) -> int:
    settings = await get_or_create_settings(db, tenant_id)
    return settings.matrix_size or DEFAULT_MATRIX_SIZE


async def get_max_score(db: AsyncSession, tenant_id) -> int:
    """Highest score the tenant's matrix can produce — what severity bands scale to."""
    return max_score_for(await get_matrix_size(db, tenant_id))


def scale_for(settings: RiskSetting) -> SeverityScale:
    """The tenant's banding: matrix maximum, configured thresholds, cell overrides.

    Stored configuration that no longer fits the matrix (bands above a shrunk maximum,
    cells outside it) is ignored here rather than trusted; the matrix-config endpoint
    clears it on resize.
    """
    size = settings.matrix_size or DEFAULT_MATRIX_SIZE
    max_score = max_score_for(size)
    try:
        bands = validate_bands(settings.severity_bands or None, max_score)
    except ValueError:
        bands = None
    try:
        cells = validate_cells(settings.matrix_cells or {}, size)
    except ValueError:
        cells = {}
    return SeverityScale(max_score=max_score, bands=bands, cells=cells)


async def get_severity_scale(db: AsyncSession, tenant_id) -> SeverityScale:
    """:func:`scale_for` the tenant's settings row (created on first read)."""
    return scale_for(await get_or_create_settings(db, tenant_id))


async def load_appetite_book(
    db: AsyncSession, tenant_id, settings: RiskSetting | None = None
) -> AppetiteBook:
    """Per-category appetite (``RiskAppetite``) over the tenant default, plus the
    risk-category tree needed to find each risk's level-1 category. Two small queries;
    RLS scopes both to the current tenant."""
    from app.models.lookup import Lookup

    settings = settings or await get_or_create_settings(db, tenant_id)
    rows = (await db.scalars(select(RiskAppetite))).all()
    parents = {
        lid: parent
        for lid, parent in (
            await db.execute(
                select(Lookup.id, Lookup.parent_id).where(Lookup.key == "risk_category")
            )
        ).all()
    }
    return AppetiteBook(
        appetite=settings.appetite_score,
        tolerance=settings.tolerance_score,
        by_category={r.category_id: (r.appetite_score, r.tolerance_score) for r in rows},
        parents=parents,
    )


async def get_levels(db: AsyncSession, tenant_id) -> dict[str, dict[int, RiskMatrixLevel]]:
    """Configured scale rungs, indexed as ``{axis: {level: row}}`` (may be empty)."""
    rows = (await db.scalars(select(RiskMatrixLevel))).all()
    out: dict[str, dict[int, RiskMatrixLevel]] = {"likelihood": {}, "impact": {}}
    for row in rows:
        out.setdefault(row.axis, {})[row.level] = row
    return out


def default_label(axis: str, level: int) -> str:
    table = DEFAULT_LIKELIHOOD_LABELS if axis == "likelihood" else DEFAULT_IMPACT_LABELS
    return table.get(level, str(level))


async def get_or_create_residual_policy(db: AsyncSession, tenant_id) -> ResidualPolicy:
    policy = await db.scalar(select(ResidualPolicy))
    if policy is None:
        policy = ResidualPolicy(tenant_id=tenant_id)
        db.add(policy)
        await db.flush()
    return policy


def policy_spec(policy: ResidualPolicy) -> ResidualPolicySpec:
    """Convert the stored row into the pure engine's input dataclass."""
    return ResidualPolicySpec(
        weight_effective=policy.weight_effective,
        weight_partially_effective=policy.weight_partially_effective,
        weight_ineffective=policy.weight_ineffective,
        weight_not_assessed=policy.weight_not_assessed,
        applies_to=policy.applies_to,
        max_reduction=policy.max_reduction,
        enabled=policy.enabled,
    )
