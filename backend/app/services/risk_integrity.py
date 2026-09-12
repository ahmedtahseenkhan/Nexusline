"""Integrity rules for the risk register (product review, phase 0).

Two rules live here so the API layer and the tests read the same code:

* **Residual never above inherent (D-01).** Controls can only reduce a risk, so a
  residual score above the inherent score is a data error unless someone who may accept
  risk has written down why. The rule depends on the stored row (a PATCH carries only
  what changed) and on the caller's permissions, so it is checked in the API rather than
  in a Pydantic validator; :func:`residual_rule_violation` is the pure core.
* **Orphaned means no live link of any kind (F-02).** A risk whose assets were all
  deleted can still be mitigated by controls, owned by a business unit, raised as an
  issue or cited by a KRI. Only a risk that reaches *nothing* live any more is offered
  for archiving. :data:`LINK_KINDS` lists every edge counted; :func:`is_orphaned` is the
  pure predicate.

Needs-review reasons are stored one per line in ``Risk.review_reason`` so several can
stand at once (an asset removed *and* a residual to correct) and each can be cleared on
its own when the thing it describes is fixed.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, func, literal_column, select, union_all

# ----------------------------------------------------------------- residual rule
RESIDUAL_ABOVE_INHERENT_DETAIL = (
    "Residual risk cannot be higher than inherent risk. "
    "Lower the residual, or record an override reason."
)
RESIDUAL_OVERRIDE_NEEDS_ACCEPT_DETAIL = (
    "Only a user who can accept risk may record a residual above inherent."
)
#: The permission that lets a user record a residual above inherent.
ACCEPT_PERMISSION = "risk:accept"

#: Fields whose change re-opens the residual question.
SCORING_FIELDS = frozenset({
    "inherent_likelihood", "inherent_impact",
    "residual_likelihood", "residual_impact",
    "residual_override_reason",
})


def residual_exceeds_inherent(
    inherent_likelihood: int | None,
    inherent_impact: int | None,
    residual_likelihood: int | None,
    residual_impact: int | None,
) -> bool:
    """True when both scores are complete and residual is the larger product."""
    if None in (inherent_likelihood, inherent_impact, residual_likelihood, residual_impact):
        return False
    return residual_likelihood * residual_impact > inherent_likelihood * inherent_impact


def residual_rule_violation(
    *,
    inherent_likelihood: int | None,
    inherent_impact: int | None,
    residual_likelihood: int | None,
    residual_impact: int | None,
    override_reason: str | None,
    can_accept: bool,
    changes_scoring: bool = True,
) -> tuple[int, str] | None:
    """Return ``(status_code, detail)`` when the state breaks the rule, else ``None``.

    Pass the *resulting* state — incoming fields laid over the stored row. A residual
    above inherent needs a written reason (422 without one). Recording or changing it
    also needs ``risk:accept`` (403 without it). ``changes_scoring=False`` means the
    request left every scoring field alone: an override a permitted user recorded
    earlier then stands, so a colleague can still fix a typo in the title.
    """
    if not residual_exceeds_inherent(
        inherent_likelihood, inherent_impact, residual_likelihood, residual_impact
    ):
        return None
    if not (override_reason or "").strip():
        return 422, RESIDUAL_ABOVE_INHERENT_DETAIL
    if changes_scoring and not can_accept:
        return status.HTTP_403_FORBIDDEN, RESIDUAL_OVERRIDE_NEEDS_ACCEPT_DETAIL
    return None


def enforce_residual_rule(**kwargs) -> None:
    """:func:`residual_rule_violation`, raised as an ``HTTPException``."""
    violation = residual_rule_violation(**kwargs)
    if violation is not None:
        code, detail = violation
        raise HTTPException(status_code=code, detail=detail)


def can_accept_risk(user) -> bool:
    return ACCEPT_PERMISSION in set(getattr(user, "permission_codes", ()) or ())


# ------------------------------------------------------------- review reasons
ASSET_REMOVED_REASON = "Asset removed – review: {name}"


def review_reasons(text: str | None) -> list[str]:
    return [line for line in (text or "").splitlines() if line.strip()]


def add_review_reason(existing: str | None, reason: str) -> str:
    """Append ``reason`` on its own line, once."""
    lines = review_reasons(existing)
    if reason not in lines:
        lines.append(reason)
    return "\n".join(lines)


def remove_review_reason(existing: str | None, reason: str) -> str:
    return "\n".join(line for line in review_reasons(existing) if line != reason)


async def clear_asset_removed(db, asset) -> int:
    """An archived asset came back: drop its "Asset removed" line from the risks still
    linked to it. ``needs_review`` goes off only when no other reason remains. Returns
    the risks changed."""
    from sqlalchemy import select

    from app.models.risk import Risk, risk_assets

    reason = ASSET_REMOVED_REASON.format(name=asset.name)
    risks = (
        await db.scalars(
            select(Risk).join(risk_assets, risk_assets.c.risk_id == Risk.id).where(
                risk_assets.c.asset_id == asset.id, Risk.deleted.is_(False)
            )
        )
    ).all()
    changed = 0
    for risk in risks:
        if reason not in review_reasons(risk.review_reason):
            continue
        risk.review_reason = remove_review_reason(risk.review_reason, reason)
        if not risk.review_reason:
            risk.needs_review = False
        changed += 1
    return changed


def clear_residual_flag(risk, residual_reason: str) -> bool:
    """Drop the residual-above-inherent reason once the risk no longer breaks the rule.

    Returns True when something changed. Other reasons (an asset removed) stay, and
    ``needs_review`` stays on while any reason remains.
    """
    if residual_reason not in review_reasons(risk.review_reason):
        return False
    still_broken = residual_exceeds_inherent(
        risk.inherent_likelihood, risk.inherent_impact,
        risk.residual_likelihood, risk.residual_impact,
    ) and not (risk.residual_override_reason or "").strip()
    if still_broken:
        return False
    risk.review_reason = remove_review_reason(risk.review_reason, residual_reason)
    if not risk.review_reason:
        risk.needs_review = False
    return True


# ------------------------------------------------------------- orphan predicate
#: Every edge that keeps a risk in use, in the order the review dialog lists them.
#: ``assets`` counts live assets only; a deleted asset is what makes a candidate.
LINK_KINDS: tuple[tuple[str, str], ...] = (
    ("assets", "Assets"),
    ("controls", "Controls"),
    ("business_units", "Business units"),
    ("processes", "Processes"),
    ("policies", "Policies"),
    ("incidents", "Incidents"),
    ("threats", "Threats"),
    ("vulnerabilities", "Vulnerabilities"),
    ("requirements", "Requirements"),
    ("exceptions", "Exceptions"),
    ("vendors", "Third parties"),
    ("projects", "Projects"),
    ("goals", "Goals"),
    ("processing_activities", "Processing activities"),
    ("audit_findings", "Audit findings"),
    ("kris", "KRIs"),
    ("loss_events", "Loss events"),
    ("continuity_plans", "Continuity plans"),
    ("rcsa_lines", "RCSA lines"),
    ("quantifications", "Quantifications"),
    ("issues", "Issues"),
)
LINK_KEYS: tuple[str, ...] = tuple(k for k, _ in LINK_KINDS)


def empty_link_counts() -> dict[str, int]:
    return {k: 0 for k in LINK_KEYS}


def is_orphaned(*, deleted_asset_links: int, live_links: Mapping[str, int]) -> bool:
    """A risk is orphaned only if it was written against assets that are all gone and
    nothing else live points at it or from it.

    A risk that never had an asset is a hand-made register entry and is never orphaned.
    """
    if deleted_asset_links <= 0:
        return False
    return not any(n > 0 for n in live_links.values())


def _kind(key: str):
    # A constant from LINK_KEYS, rendered inline: a bound parameter in a UNION's select
    # list has no type Postgres can infer.
    assert key in LINK_KEYS, key
    return literal_column(f"'{key}'").label("kind")


def _live(stmt: Select, model) -> Select:
    return stmt.where(model.deleted.is_(False)) if hasattr(model, "deleted") else stmt


def link_count_query(risk_ids: Sequence[uuid.UUID]):
    """One UNION ALL over every link kind: rows of ``(kind, risk_id, n)`` counting live
    targets only. Kinds with no rows for a risk are simply absent."""
    from app.models.base import Base
    from app.models.asset import Asset
    from app.models.compliance import Requirement
    from app.models.continuity import ContinuityPlan
    from app.models.control import Control
    from app.models.exception import ExceptionRecord
    from app.models.goal import Goal
    from app.models.incident import Incident
    from app.models.internal_audit import AuditFinding
    from app.models.issue import Issue
    from app.models.operational_risk import (
        KeyRiskIndicator,
        LossEvent,
        RcsaAssessment,
        RcsaRisk,
    )
    from app.models.organization import BusinessUnit, Process
    from app.models.policy import Policy
    from app.models.privacy import ProcessingActivity
    from app.models.project import Project
    from app.models.risk_quant import RiskQuantification
    from app.models.threat import Threat, Vulnerability
    from app.models.vendor import Vendor

    ids = list(risk_ids)
    tables = Base.metadata.tables
    # (kind, join table, column pointing at the target, target model)
    m2m = (
        ("assets", "risk_assets", "asset_id", Asset),
        ("controls", "risk_controls", "control_id", Control),
        ("business_units", "risk_business_units", "business_unit_id", BusinessUnit),
        ("processes", "risk_processes", "process_id", Process),
        ("policies", "risk_policies", "policy_id", Policy),
        ("incidents", "risk_incidents", "incident_id", Incident),
        ("threats", "risk_threats", "threat_id", Threat),
        ("vulnerabilities", "risk_vulnerabilities", "vulnerability_id", Vulnerability),
        ("requirements", "requirement_risks", "requirement_id", Requirement),
        ("exceptions", "exception_risks", "exception_id", ExceptionRecord),
        ("vendors", "vendor_risks", "vendor_id", Vendor),
        ("projects", "project_risks", "project_id", Project),
        ("goals", "goal_risks", "goal_id", Goal),
        ("processing_activities", "ropa_risks", "ropa_id", ProcessingActivity),
        ("audit_findings", "audit_finding_risks", "audit_finding_id", AuditFinding),
        ("kris", "kri_risks", "kri_id", KeyRiskIndicator),
        ("loss_events", "loss_event_risks", "loss_event_id", LossEvent),
        ("continuity_plans", "continuity_plan_risks", "continuity_plan_id", ContinuityPlan),
    )
    parts: list[Select] = []
    for kind, table_name, target_col, model in m2m:
        t = tables[table_name]
        parts.append(
            _live(
                select(_kind(kind), t.c.risk_id.label("risk_id"),
                       func.count().label("n"))
                .select_from(t.join(model, model.id == t.c[target_col]))
                .where(t.c.risk_id.in_(ids)),
                model,
            ).group_by(t.c.risk_id)
        )
    # Direct foreign keys pointing at the risk.
    parts.append(
        select(_kind("rcsa_lines"), RcsaRisk.risk_id.label("risk_id"),
               func.count().label("n"))
        .select_from(RcsaRisk)
        .join(RcsaAssessment, and_(RcsaAssessment.id == RcsaRisk.assessment_id,
                                   RcsaAssessment.deleted.is_(False)))
        .where(RcsaRisk.risk_id.in_(ids))
        .group_by(RcsaRisk.risk_id)
    )
    parts.append(
        select(_kind("quantifications"),
               RiskQuantification.risk_id.label("risk_id"), func.count().label("n"))
        .where(RiskQuantification.risk_id.in_(ids), RiskQuantification.deleted.is_(False))
        .group_by(RiskQuantification.risk_id)
    )
    parts.append(
        select(_kind("issues"), Issue.source_id.label("risk_id"),
               func.count().label("n"))
        .where(Issue.source_id.in_(ids), Issue.deleted.is_(False))
        .group_by(Issue.source_id)
    )
    return union_all(*parts)


async def live_link_counts(
    db, risk_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    """Per risk, how many live records of each kind it still links to."""
    ids = list(risk_ids)
    out = {rid: empty_link_counts() for rid in ids}
    if not ids:
        return out
    for kind, rid, n in (await db.execute(link_count_query(ids))).all():
        if rid in out:
            out[rid][kind] = int(n)
    return out


async def asset_orphan_candidates(db) -> list[uuid.UUID]:
    """Live risks with at least one link to a deleted asset and none to a live one."""
    from app.models.asset import Asset
    from app.models.risk import Risk, risk_assets

    to_deleted = (
        select(risk_assets.c.risk_id)
        .join(Asset, Asset.id == risk_assets.c.asset_id)
        .where(Asset.deleted.is_(True))
    )
    to_live = (
        select(risk_assets.c.risk_id)
        .join(Asset, Asset.id == risk_assets.c.asset_id)
        .where(Asset.deleted.is_(False))
    )
    return list(
        (
            await db.scalars(
                select(Risk.id).where(
                    Risk.deleted.is_(False),
                    Risk.id.in_(to_deleted),
                    Risk.id.notin_(to_live),
                )
            )
        ).all()
    )


@dataclass
class OrphanScan:
    #: Risks that reach nothing live — the only ones that may be archived.
    orphaned: list[uuid.UUID] = field(default_factory=list)
    #: Live-link counts for every candidate (all zero for the orphaned ones).
    counts: dict[uuid.UUID, dict[str, int]] = field(default_factory=dict)
    #: Candidates kept because something else live still links to them.
    kept: list[uuid.UUID] = field(default_factory=list)


async def scan_orphans(db) -> OrphanScan:
    candidates = await asset_orphan_candidates(db)
    counts = await live_link_counts(db, candidates)
    scan = OrphanScan(counts=counts)
    for rid in candidates:
        # Every candidate has at least one deleted-asset link by construction.
        if is_orphaned(deleted_asset_links=1, live_links=counts[rid]):
            scan.orphaned.append(rid)
        else:
            scan.kept.append(rid)
    return scan


# ------------------------------------------------------------- asset removal
async def live_risks_for_assets(db, asset_ids: Sequence[uuid.UUID]) -> list:
    from app.models.risk import Risk, risk_assets

    if not asset_ids:
        return []
    return list(
        (
            await db.scalars(
                select(Risk)
                .join(risk_assets, risk_assets.c.risk_id == Risk.id)
                .where(risk_assets.c.asset_id.in_(list(asset_ids)), Risk.deleted.is_(False))
                .distinct()
            )
        ).all()
    )


def flag_for_asset_removal(risks: Iterable, asset_name: str) -> int:
    """Mark each risk as needing review because ``asset_name`` was removed."""
    reason = ASSET_REMOVED_REASON.format(name=asset_name)
    n = 0
    for risk in risks:
        risk.needs_review = True
        risk.review_reason = add_review_reason(risk.review_reason, reason)
        n += 1
    return n


async def asset_impact(db, asset_id: uuid.UUID) -> dict[str, int]:
    """Live records that link to one asset: what its deletion would touch."""
    from app.models.control import Control, control_assets
    from app.models.risk import Risk, risk_assets

    risks = await db.scalar(
        select(func.count(func.distinct(Risk.id)))
        .select_from(risk_assets)
        .join(Risk, Risk.id == risk_assets.c.risk_id)
        .where(risk_assets.c.asset_id == asset_id, Risk.deleted.is_(False))
    ) or 0
    controls = await db.scalar(
        select(func.count(func.distinct(Control.id)))
        .select_from(control_assets)
        .join(Control, Control.id == control_assets.c.control_id)
        .where(control_assets.c.asset_id == asset_id, Control.deleted.is_(False))
    ) or 0
    return {"risks": int(risks), "controls": int(controls)}


__all__ = [
    "ACCEPT_PERMISSION",
    "ASSET_REMOVED_REASON",
    "LINK_KINDS",
    "LINK_KEYS",
    "OrphanScan",
    "RESIDUAL_ABOVE_INHERENT_DETAIL",
    "RESIDUAL_OVERRIDE_NEEDS_ACCEPT_DETAIL",
    "SCORING_FIELDS",
    "add_review_reason",
    "asset_impact",
    "can_accept_risk",
    "clear_residual_flag",
    "enforce_residual_rule",
    "flag_for_asset_removal",
    "is_orphaned",
    "link_count_query",
    "live_link_counts",
    "live_risks_for_assets",
    "remove_review_reason",
    "residual_exceeds_inherent",
    "residual_rule_violation",
    "review_reasons",
    "scan_orphans",
]
