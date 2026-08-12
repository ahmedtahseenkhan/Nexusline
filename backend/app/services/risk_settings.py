"""Per-tenant risk methodology: appetite/tolerance, matrix scale and residual policy.

Everything here lazily creates a sensible default row on first read, so a fresh tenant
has a working 5x5 register before anyone opens the settings screen — and an existing
installation keeps the behaviour it already had.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk import ResidualPolicy, RiskMatrixLevel, RiskSetting
from app.services.residual_engine import ResidualPolicySpec
from app.services.risk_scoring import DEFAULT_MATRIX_SIZE, max_score_for

#: Generic scale wording used until a bank supplies its own. Deliberately plain: these
#: are placeholders that prompt someone to write the real criteria, not a methodology.
DEFAULT_LIKELIHOOD_LABELS: dict[int, str] = {
    1: "Rare", 2: "Unlikely", 3: "Possible", 4: "Likely", 5: "Almost certain", 6: "Expected",
}
DEFAULT_IMPACT_LABELS: dict[int, str] = {
    1: "Insignificant", 2: "Minor", 3: "Moderate", 4: "Major", 5: "Severe", 6: "Catastrophic",
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
