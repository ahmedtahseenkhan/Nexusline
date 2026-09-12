"""Startup repairs for data written before the product-review phase-0 rules existed.

Every step is idempotent and safe to run on every boot: each one only touches rows that
still break a rule, so a clean database costs a handful of cheap queries.

Tenant-scoped work runs inside a tenant session (row-level security is forced even for
the table owner, so a bare ``UPDATE`` from a migration would silently match nothing).
The two unique indexes are created afterwards on the admin connection, once the
duplicates they forbid have been merged away; if a duplicate survives, the index is
skipped and logged rather than failing the start-up.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import or_, select, text

from app.core.database import set_session_tenant, tenant_session
from app.models.control import UNTESTABLE_CONTROL_STATUSES, Control
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.models.widget import DashboardWidget

logger = logging.getLogger(__name__)

RESIDUAL_REVIEW_REASON = (
    "Residual score is higher than inherent with no reason recorded. Controls can only "
    "reduce a risk: correct the residual, or record why it is higher."
)



@dataclass
class RepairReport:
    widgets_removed: int = 0
    frameworks_merged: int = 0
    framework_kinds_set: int = 0
    control_test_dates_cleared: int = 0
    risks_flagged: int = 0
    classification_values_regraded: int = 0
    foreign_keys_matched: int = 0
    lookups_created: int = 0
    operating_effectiveness_carried: int = 0
    indexes_skipped: list[str] = field(default_factory=list)

    def any(self) -> bool:
        return bool(
            self.widgets_removed or self.frameworks_merged or self.framework_kinds_set
            or self.control_test_dates_cleared or self.risks_flagged
            or self.classification_values_regraded or self.foreign_keys_matched
            or self.lookups_created or self.operating_effectiveness_carried
            or self.indexes_skipped
        )


async def dedupe_widgets(db) -> int:
    """Keep the oldest tile per (metric, form); delete the rest."""
    rows = (
        await db.scalars(
            select(DashboardWidget).order_by(DashboardWidget.created_at, DashboardWidget.id)
        )
    ).all()
    seen: set[tuple[str, str]] = set()
    removed = 0
    for w in rows:
        key = (w.metric_key, w.viz or "number")
        if key in seen:
            await db.delete(w)
            removed += 1
        else:
            seen.add(key)
    return removed


async def clear_untestable_control_dates(db) -> int:
    """A planned or retired control carries no test or maintenance clock; drop dates
    set before that rule. Returns controls changed."""
    rows = (
        await db.scalars(
            select(Control).where(
                Control.deleted.is_(False),
                Control.status.in_(UNTESTABLE_CONTROL_STATUSES),
                or_(Control.next_audit_date.is_not(None), Control.next_maintenance_date.is_not(None)),
            )
        )
    ).all()
    for c in rows:
        c.next_audit_date = None
        c.next_maintenance_date = None
    return len(rows)


async def flag_residual_above_inherent(db) -> int:
    """Flag risks whose residual exceeds inherent with no recorded reason."""
    rows = (
        await db.scalars(
            select(Risk).where(
                Risk.deleted.is_(False),
                Risk.needs_review.is_(False),
                Risk.residual_likelihood.is_not(None),
                Risk.residual_impact.is_not(None),
                Risk.residual_likelihood * Risk.residual_impact
                > Risk.inherent_likelihood * Risk.inherent_impact,
                or_(Risk.residual_override_reason.is_(None), Risk.residual_override_reason == ""),
            )
        )
    ).all()
    for r in rows:
        r.needs_review = True
        r.review_reason = RESIDUAL_REVIEW_REASON
    return len(rows)


def regrade_plan(
    axis: str, current: list[tuple[str, float, str]]
) -> list[tuple[str, str, str]] | None:
    """How to re-grade one classification axis, or None to leave it alone.

    Only an axis that still holds *exactly* the confidentiality defaults (same names,
    values and criteria, in any order) is re-graded; anything a tenant touched is theirs.
    Returns (old name, new name, new criteria) per value, matched on the numeric grade so
    every asset keeps the grade it had.
    """
    from app.db.reference_data import CLASSIFICATION_VALUES_BY_AXIS, CONFIDENTIALITY_VALUES

    target = CLASSIFICATION_VALUES_BY_AXIS.get(axis)
    if target is None or target == CONFIDENTIALITY_VALUES:
        return None
    if sorted(current) != sorted(CONFIDENTIALITY_VALUES):
        return None
    by_value = {value: (name, criteria) for name, value, criteria in target}
    return [(name, *by_value[value]) for name, value, _criteria in current]


async def regrade_default_cia_axes(db) -> int:
    """Give untouched Integrity / Availability axes their own grade names (see
    ``reference_data.CLASSIFICATION_VALUES_BY_AXIS``). Returns values renamed."""
    from app.models.asset import AssetClassification, AssetClassificationType

    renamed = 0
    for axis in (await db.scalars(select(AssetClassificationType))).all():
        values = (
            await db.scalars(select(AssetClassification).where(AssetClassification.type_id == axis.id))
        ).all()
        plan = regrade_plan(axis.name, [(v.name, float(v.value), v.criteria or "") for v in values])
        if plan is None:
            continue
        by_name = {v.name: v for v in values}
        for old, new, criteria in plan:
            by_name[old].name = new
            by_name[old].criteria = criteria
            renamed += 1
    return renamed


async def carry_effectiveness_to_operating(db) -> int:
    """Phase 2 splits design and operating effectiveness. A control's existing rating came
    from its tests of operation, so it becomes the operating rating where that is unset."""
    from app.models.enums import ControlEffectiveness

    rows = (
        await db.scalars(
            select(Control).where(
                Control.deleted.is_(False),
                Control.operating_effectiveness == ControlEffectiveness.not_assessed,
                Control.effectiveness != ControlEffectiveness.not_assessed,
            )
        )
    ).all()
    for c in rows:
        c.operating_effectiveness = c.effectiveness
    return len(rows)


async def repair_tenant(db, report: RepairReport, tenant_id=None) -> None:
    from app.db.fk_backfill import backfill_foreign_keys
    from app.services import framework_library
    from app.services.issue_closure import backfill_source_links

    report.widgets_removed += await dedupe_widgets(db)
    report.frameworks_merged += await framework_library.merge_duplicate_frameworks(db)
    report.framework_kinds_set += await framework_library.backfill_framework_kinds(db)
    report.control_test_dates_cleared += await clear_untestable_control_dates(db)
    report.risks_flagged += await flag_residual_above_inherent(db)
    report.classification_values_regraded += await regrade_default_cia_axes(db)
    report.operating_effectiveness_carried += await carry_effectiveness_to_operating(db)
    await backfill_source_links(db)  # issues raised from a record get the typed link (2.3)
    if tenant_id is not None:
        # Lookup seeding (reference data) runs before this, so defined values match first.
        fk = await backfill_foreign_keys(db, tenant_id)
        report.foreign_keys_matched += fk.matched
        report.lookups_created += fk.lookups_created
    await db.flush()


UNIQUE_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "uq_frameworks_tenant_name",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_frameworks_tenant_name "
        "ON frameworks (tenant_id, lower(name)) WHERE deleted = false",
    ),
    (
        "uq_dashboard_widgets_metric",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dashboard_widgets_metric "
        "ON dashboard_widgets (tenant_id, metric_key, viz)",
    ),
)


async def create_unique_indexes(report: RepairReport) -> None:
    from app.db.init_db import admin_engine

    for name, ddl in UNIQUE_INDEXES:
        try:
            async with admin_engine.begin() as conn:
                await conn.execute(text(ddl))
        except Exception:  # noqa: BLE001 - a surviving duplicate must not stop the start
            logger.exception("Could not create unique index %s; duplicates remain", name)
            report.indexes_skipped.append(name)


async def repair_data() -> RepairReport:
    """Run every repair for every tenant, then add the unique indexes."""
    report = RepairReport()
    async with tenant_session(None) as db:
        tenants = (await db.scalars(select(Tenant))).all()
        for tenant in tenants:
            await set_session_tenant(db, tenant.id)
            await repair_tenant(db, report, tenant.id)
    await create_unique_indexes(report)
    return report


__all__ = [
    "RESIDUAL_REVIEW_REASON",
    "UNTESTABLE_CONTROL_STATUSES",
    "RepairReport",
    "repair_data",
    "repair_tenant",
    "regrade_plan",
]
