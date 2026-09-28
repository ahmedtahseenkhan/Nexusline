"""Metric registry — named, computable KPIs across modules for the report builder.

Each metric is either a *scalar* (single number) or a *breakdown* (label -> count
series). The catalog drives the widget picker; ``compute`` evaluates one metric.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest
from app.models.asset import Asset
from app.models.compliance import Requirement
from app.models.control import UNTESTABLE_CONTROL_STATUSES, Control
from app.models.enums import (
    ApprovalStatus,
    ComplianceStatus,
    ControlStatus,
    IncidentStatus,
    PolicyStatus,
)
from app.models.incident import Incident
from app.models.policy import Policy
from app.models.project import Project
from app.models.risk import Risk, RiskSetting
from app.models.vendor import Vendor
from app.services.risk_scoring import effective_score
from app.services.risk_settings import get_or_create_settings, load_appetite_book, scale_for

# key -> (label, description, kind, category)
CATALOG: dict[str, tuple[str, str, str, str]] = {
    "risks_total": ("Total risks", "Count of risks in the register", "scalar", "Risk"),
    "risks_above_tolerance": ("Risks above tolerance", "Risks whose effective score exceeds the org tolerance", "scalar", "Risk"),
    "risks_overdue_review": ("Risk reviews overdue", "Risks past their next review date", "scalar", "Risk"),
    "risks_by_severity": ("Risks by severity", "Distribution of risks across severity bands", "breakdown", "Risk"),
    "risks_by_status": ("Risks by status", "Risk treatment lifecycle distribution", "breakdown", "Risk"),
    "controls_total": ("Total controls", "Count of controls", "scalar", "Control"),
    "controls_operational": ("Operational controls", "Controls in operational state", "scalar", "Control"),
    "controls_overdue_audit": ("Control audits overdue", "Implemented or operational controls past their next test date", "scalar", "Control"),
    "controls_by_status": ("Controls by status", "Control lifecycle distribution", "breakdown", "Control"),
    "incidents_open": ("Open incidents", "Incidents not yet resolved or closed", "scalar", "Incident"),
    "incidents_by_status": ("Incidents by status", "Incident status distribution", "breakdown", "Incident"),
    "compliance_total": ("Total requirements", "Count of compliance requirements", "scalar", "Compliance"),
    "compliance_compliant": ("Compliant requirements", "Requirements assessed as compliant", "scalar", "Compliance"),
    "compliance_by_status": ("Compliance by status", "Requirement compliance distribution", "breakdown", "Compliance"),
    "assets_by_criticality": ("Assets by criticality", "Asset criticality distribution", "breakdown", "Asset"),
    "vendors_total": ("Total vendors", "Count of third parties", "scalar", "Vendor"),
    "policies_published": ("Published policies", "Policies in published state", "scalar", "Governance"),
    "projects_by_status": ("Projects by status", "Project lifecycle distribution", "breakdown", "Governance"),
    "approvals_pending": ("Pending approvals", "Approval requests awaiting a decision", "scalar", "Workflow"),
}


def catalog() -> list[dict]:
    return [
        {"key": k, "label": v[0], "description": v[1], "kind": v[2], "category": v[3]}
        for k, v in CATALOG.items()
    ]


async def _count(db: AsyncSession, model, *conds) -> int:
    stmt = select(func.count()).select_from(model)
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    for c in conds:
        stmt = stmt.where(c)
    return await db.scalar(stmt) or 0


async def _breakdown(db: AsyncSession, col, model: type | None = None) -> list[dict]:
    """Counts of live rows per value of ``col`` — a column, or an expression over
    ``model``'s columns."""
    model = model or col.class_
    stmt = select(col, func.count()).select_from(model)
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    rows = (await db.execute(stmt.group_by(col))).all()
    out = []
    for label, count in rows:
        name = label.value if hasattr(label, "value") else (str(label) if label is not None else "—")
        out.append({"label": name.replace("_", " "), "value": count})
    out.sort(key=lambda r: r["value"], reverse=True)
    return out


async def compute(db: AsyncSession, key: str, tenant_id) -> dict:
    """Returns {kind, value, series} for a metric key."""
    today = date.today()

    if key == "risks_above_tolerance":
        settings: RiskSetting = await get_or_create_settings(db, tenant_id)
        # Each risk against its own category's tolerance (organisation default otherwise).
        book = await load_appetite_book(db, tenant_id, settings)
        # The dashboard's board register (F-21): validated risks only, so this widget and
        # the "Above tolerance" tile agree.
        from app.services.risk_query import board_register_clause

        risks = (await db.scalars(select(Risk).where(board_register_clause()))).all()
        n = sum(
            1
            for r in risks
            if (eff := effective_score(r.inherent_score, r.residual_score)) is not None
            and eff > book.tolerance_for(r.category_id)
        )
        return {"kind": "scalar", "value": n, "series": None}

    if key == "risks_by_severity":
        risks = (await db.scalars(select(Risk).where(Risk.deleted.is_(False)))).all()
        # The organisation's own banding (matrix size, thresholds, cell overrides) — the
        # same colours the heat map shows. Previously always the 5x5 default.
        scale = scale_for(await get_or_create_settings(db, tenant_id))
        buckets: dict[str, int] = {}
        from app.services.risk_scoring import current_severity

        for r in risks:
            # A draft nobody has scored is "unscored", not a low risk (F-23).
            sev = current_severity(r, scale)
            name = sev.value if sev else "unscored"
            buckets[name] = buckets.get(name, 0) + 1
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unscored": 4}
        series = sorted(
            [{"label": k, "value": v} for k, v in buckets.items()],
            key=lambda r: order.get(r["label"], 9),
        )
        return {"kind": "breakdown", "value": None, "series": series}

    scalars = {
        "risks_total": (Risk,),
        "risks_overdue_review": (Risk, Risk.next_review_date < today),
        "controls_total": (Control,),
        "controls_operational": (Control, Control.status == ControlStatus.operational),
        # Planned and retired controls carry no test clock, so are never overdue.
        "controls_overdue_audit": (
            Control, Control.next_audit_date < today, Control.status.notin_(UNTESTABLE_CONTROL_STATUSES)
        ),
        "incidents_open": (Incident, Incident.status.notin_([IncidentStatus.resolved, IncidentStatus.closed])),
        "compliance_total": (Requirement,),
        "compliance_compliant": (Requirement, Requirement.status == ComplianceStatus.compliant),
        "vendors_total": (Vendor,),
        "policies_published": (Policy, Policy.status == PolicyStatus.published),
        "approvals_pending": (ApprovalRequest, ApprovalRequest.status == ApprovalStatus.pending),
    }
    if key in scalars:
        model, *conds = scalars[key]
        return {"kind": "scalar", "value": await _count(db, model, *conds), "series": None}

    if key == "assets_by_criticality":
        # By the criticality the register shows (computed), not the stored input no form
        # sets — which put every real asset under "medium".
        from app.api.v1.assets import effective_criticality_expr

        return {"kind": "breakdown", "value": None,
                "series": await _breakdown(db, effective_criticality_expr(), model=Asset)}
    breakdowns = {
        "risks_by_status": Risk.status,
        "controls_by_status": Control.status,
        "incidents_by_status": Incident.status,
        "compliance_by_status": Requirement.status,
        "projects_by_status": Project.status,
    }
    if key in breakdowns:
        return {"kind": "breakdown", "value": None, "series": await _breakdown(db, breakdowns[key])}

    raise KeyError(key)
