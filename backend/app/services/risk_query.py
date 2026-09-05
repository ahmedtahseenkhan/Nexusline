"""The risk register's filter, in one place.

Three callers need to agree on what "the risks I am looking at" means: the register's
list endpoint, the PDF export launched from it, and the report builder. Duplicating the
predicates is how a report quietly stops matching the screen it was launched from —
nothing errors, the numbers are just wrong — so they live here and everyone imports them.

Segment filters are ``EXISTS`` sub-queries rather than joins, because a risk in two
business units would otherwise come back twice and inflate every count on the page.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Select, select

from app.models.enums import RiskStatus
from app.models.risk import Risk, risk_assets, risk_business_units, risk_processes


def build_risk_query(
    *,
    status: RiskStatus | None = None,
    category: str | None = None,
    business_unit_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    search: str | None = None,
) -> Select:
    """Live risks matching the given filters. See the module docstring."""
    stmt: Select = select(Risk).where(Risk.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(Risk.status == status)
    if category:
        stmt = stmt.where(Risk.category == category)
    if business_unit_id is not None:
        stmt = stmt.where(
            select(risk_business_units.c.risk_id)
            .where(
                risk_business_units.c.risk_id == Risk.id,
                risk_business_units.c.business_unit_id == business_unit_id,
            )
            .exists()
        )
    if process_id is not None:
        stmt = stmt.where(
            select(risk_processes.c.risk_id)
            .where(
                risk_processes.c.risk_id == Risk.id,
                risk_processes.c.process_id == process_id,
            )
            .exists()
        )
    if asset_id is not None:
        stmt = stmt.where(
            select(risk_assets.c.risk_id)
            .where(risk_assets.c.risk_id == Risk.id, risk_assets.c.asset_id == asset_id)
            .exists()
        )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Risk.title.ilike(like) | Risk.reference.ilike(like))
    return stmt
