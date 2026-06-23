"""Helper to fetch (and lazily create) per-tenant risk appetite settings."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk import RiskSetting


async def get_or_create_settings(db: AsyncSession, tenant_id) -> RiskSetting:
    settings = await db.scalar(select(RiskSetting))  # RLS scopes to current tenant
    if settings is None:
        settings = RiskSetting(tenant_id=tenant_id)
        db.add(settings)
        await db.flush()
    return settings
