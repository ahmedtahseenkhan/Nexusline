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

Phase 2 (risk v2, F-09) adds the record-depth rules, pure so they are unit-testable:

* **The risk statement composes the title** when none is given
  (:func:`compose_title`).
* **Every score change carries a reason and a stamp** (:func:`assessment_decision`).
  Changing an inherent or residual score needs a new ``assessment_rationale``; each
  change stamps ``last_assessed_at``/``last_assessed_by_id``. A draft may carry
  provisional scores without one. Leaving draft needs chosen inherent scores and a
  rationale — the server side of "the form no longer pre-fills 3x3".
* **Target never above residual, residual never above inherent**
  (:func:`target_rule_violation`).
* **Impact by dimension** decides the overall impact for its basis
  (:func:`derive_dimension_impacts`).

Needs-review reasons are stored one per line in ``Risk.review_reason`` so several can
stand at once (an asset removed *and* a residual to correct) and each can be cleared on
its own when the thing it describes is fixed.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, func, literal_column, select, union, union_all

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


# ------------------------------------------------------------ risk statement
TITLE_NEEDS_STATEMENT_DETAIL = (
    "Give the risk a title, or describe the event — the title is then composed as "
    "'<event>, caused by <cause>, resulting in <consequence>'."
)
_TITLE_LIMIT = 255


def _clause(text: str | None) -> str:
    return " ".join((text or "").split()).rstrip(" .;,")


def _lower_first(text: str) -> str:
    """'Phishing emails' -> 'phishing emails', but 'SWIFT outage' stays as typed."""
    first = text.split(" ", 1)[0]
    if len(first) > 1 and first[:2].isupper():
        return text
    return text[:1].lower() + text[1:]


def compose_title(cause: str | None, event: str | None, consequence: str | None) -> str:
    """"<Event>, caused by <cause>, resulting in <consequence>", trimmed to fit.

    The event is the risk; without one there is nothing to name, so the result is ""
    and the caller asks for a title. Cause and consequence are added when given.
    """
    event_text = _clause(event)
    if not event_text:
        return ""
    parts = [event_text[:1].upper() + event_text[1:]]
    if _clause(cause):
        parts.append(f"caused by {_lower_first(_clause(cause))}")
    if _clause(consequence):
        parts.append(f"resulting in {_lower_first(_clause(consequence))}")
    title = ", ".join(parts)
    if len(title) > _TITLE_LIMIT:
        title = title[: _TITLE_LIMIT - 1].rstrip(" ,") + "…"
    return title


# ------------------------------------------------------------ assessment trail
#: The four scores whose change is an assessment.
SCORE_FIELDS: tuple[str, ...] = (
    "inherent_likelihood", "inherent_impact", "residual_likelihood", "residual_impact",
)
RATIONALE_REQUIRED_DETAIL = (
    "The scores changed: write down why in the assessment rationale. Only a draft may "
    "carry provisional scores without one."
)
LEAVE_DRAFT_DETAIL = (
    "Before this risk leaves draft, choose its inherent likelihood and impact and write "
    "the assessment rationale."
)


ACCEPT_UNASSESSED_DETAIL = (
    "This risk hasn't been assessed yet. Score it and write the assessment rationale "
    "before asking for — or granting — its acceptance."
)


def acceptance_refusal(status, last_assessed_at, rationale: str | None) -> str | None:
    """Why a risk can't be accepted yet, or None. Pure.

    Accepting a risk is a decision about an assessed exposure; a draft nobody has scored
    has nothing to accept. The same gate as leaving draft: scores chosen and a rationale.
    """
    value = getattr(status, "value", status)
    if value != "draft":
        return None
    if last_assessed_at is None or not (rationale or "").strip():
        return ACCEPT_UNASSESSED_DETAIL
    return None


#: F-21: an unowned, untagged risk is not a board number. Leaving Draft — by a status
#: change or by submitting it for approval — needs someone accountable and the part of
#: the bank it sits in.
LEAVE_DRAFT_NEEDS_OWNER_AND_UNIT = (
    "Before this risk leaves Draft, give it a risk owner and at least one business unit."
)
LEAVE_DRAFT_NEEDS_OWNER = "Before this risk leaves Draft, give it a risk owner."
LEAVE_DRAFT_NEEDS_UNIT = "Before this risk leaves Draft, tag at least one business unit."


def draft_exit_refusal(*, has_owner: bool, has_business_unit: bool) -> str | None:
    """Why a risk may not leave Draft for want of an owner or a business unit, or None."""
    if not has_owner and not has_business_unit:
        return LEAVE_DRAFT_NEEDS_OWNER_AND_UNIT
    if not has_owner:
        return LEAVE_DRAFT_NEEDS_OWNER
    if not has_business_unit:
        return LEAVE_DRAFT_NEEDS_UNIT
    return None


@dataclass(frozen=True)
class Assessment:
    """What a write does to the assessment trail."""

    #: Stamp ``last_assessed_at`` / ``last_assessed_by_id``.
    stamp: bool
    #: The rationale to store; None leaves the stored one alone.
    rationale: str | None


def changed_scores(stored: Mapping | None, incoming: Mapping) -> list[str]:
    """Score fields the request sets to a different value (all given ones on create).

    The register form sends every field on each save, so presence is not a change.
    """
    out: list[str] = []
    for name in SCORE_FIELDS:
        if name not in incoming:
            continue
        new = incoming[name]
        if stored is None:
            if new is not None:
                out.append(name)
        elif new != stored.get(name):
            out.append(name)
    return out


def assessment_decision(
    *,
    creating: bool,
    changed: bool,
    sends_inherent: bool,
    rationale: str | None,
    stored_rationale: str | None,
    status_before: str | None,
    status_after: str | None,
    previously_assessed: bool,
    has_owner: bool | None = None,
    has_business_unit: bool | None = None,
) -> Assessment:
    """Apply the assessment-trail rule; raise 422 when the write breaks it.

    ``has_owner`` / ``has_business_unit`` describe the risk *after* the write; given, a
    risk leaving Draft without either is refused (422 :func:`draft_exit_refusal`), after
    the scores-and-rationale rule. None skips the check (callers that don't know).

    * ``changed`` — an inherent or residual score moves. Unless the risk is a draft
      after the write, that needs a *new* rationale (the old one described the old
      scores): 422 :data:`RATIONALE_REQUIRED_DETAIL`.
    * Leaving draft (creating in, or moving to, any other status) needs the inherent
      scores chosen — sent with this request, or recorded by an earlier assessment
      (``previously_assessed``) — and a rationale: 422 :data:`LEAVE_DRAFT_DETAIL`.
    * Every score change is stamped. So is sending the inherent scores with a new
      rationale (re-affirming the assessment, or confirming it on leaving draft).
    * A draft's provisional score change without a rationale clears the stored one:
      it described scores that no longer stand.
    """
    text = (rationale or "").strip()
    stored = (stored_rationale or "").strip()
    fresh = bool(text) and text != stored
    draft_after = status_after == "draft"
    leaving = not draft_after and (creating or status_before == "draft")

    if leaving:
        chosen = sends_inherent or previously_assessed
        has_reason = bool(text) or (bool(stored) and not changed)
        if not (chosen and has_reason):
            raise HTTPException(status_code=422, detail=LEAVE_DRAFT_DETAIL)
        if has_owner is not None or has_business_unit is not None:
            refusal = draft_exit_refusal(
                has_owner=has_owner is not False, has_business_unit=has_business_unit is not False
            )
            if refusal:
                raise HTTPException(status_code=422, detail=refusal)
    if changed and not draft_after and not fresh:
        raise HTTPException(status_code=422, detail=RATIONALE_REQUIRED_DETAIL)

    confirmed = sends_inherent and bool(text) and (fresh or leaving)
    if text and (fresh or creating):
        new_rationale: str | None = text
    elif changed and not text:
        new_rationale = ""
    else:
        new_rationale = None
    return Assessment(stamp=changed or confirmed, rationale=new_rationale)


# ------------------------------------------------------------------ target rule
TARGET_INCOMPLETE_DETAIL = "Give both the target likelihood and the target impact, or neither."
TARGET_ABOVE_DETAIL = (
    "Target risk {target} cannot be higher than {basis} risk {score}: treatment only "
    "lowers a risk (target <= residual <= inherent)."
)


def target_rule_violation(
    *,
    inherent: tuple[int | None, int | None],
    residual: tuple[int | None, int | None],
    target: tuple[int | None, int | None],
) -> str | None:
    """The detail of a 422 when the target is incomplete or above residual/inherent."""
    tl, ti = target
    if tl is None and ti is None:
        return None
    if tl is None or ti is None:
        return TARGET_INCOMPLETE_DETAIL
    value = tl * ti
    for basis, (lk, im) in (("residual", residual), ("inherent", inherent)):
        if lk is not None and im is not None and value > lk * im:
            return TARGET_ABOVE_DETAIL.format(target=value, basis=basis, score=lk * im)
    return None


# ------------------------------------------------------------- impact dimensions
DIMENSION_DUPLICATE_DETAIL = "impact_dimensions: {dimension} is scored twice for the {basis} basis."
DIMENSION_DISAGREES_DETAIL = (
    "{basis_title} impact {explicit} disagrees with its dimension scores: the {mode} of "
    "{scores} is {derived}. Send the derived impact, or leave it out."
)


def derive_dimension_impacts(
    rows: Sequence[Mapping], incoming: Mapping, mode: str
) -> dict[str, int]:
    """The overall impact per basis the dimension rows decide.

    ``rows`` are ``{dimension_id, basis, score}``. Returns ``{"inherent_impact": 4, …}``
    for each basis that has rows. Raises 422 when a dimension repeats within a basis,
    or when the request also sends that basis' impact and it disagrees.
    """
    from app.services.risk_scoring import impact_from_dimensions

    by_basis: dict[str, list[int]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["dimension_id"]), row["basis"])
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=DIMENSION_DUPLICATE_DETAIL.format(dimension=row["dimension_id"], basis=row["basis"]),
            )
        seen.add(key)
        by_basis.setdefault(row["basis"], []).append(int(row["score"]))
    out: dict[str, int] = {}
    for basis, scores in by_basis.items():
        derived = impact_from_dimensions(scores, mode)
        field_name = f"{basis}_impact"
        explicit = incoming.get(field_name)
        if explicit is not None and explicit != derived:
            raise HTTPException(
                status_code=422,
                detail=DIMENSION_DISAGREES_DETAIL.format(
                    basis_title=basis.title(), explicit=explicit, mode=mode if mode == "average" else "highest",
                    scores=", ".join(map(str, sorted(scores, reverse=True))), derived=derived,
                ),
            )
        out[field_name] = derived  # type: ignore[assignment]
    return out


# ------------------------------------------------------------- treatment actions
#: Action statuses that still need work.
OPEN_ACTION_STATUSES: frozenset[str] = frozenset({"open", "in_progress"})


def action_is_overdue(action, today) -> bool:
    return (
        getattr(action, "status", None) in OPEN_ACTION_STATUSES
        and action.due_date is not None
        and action.due_date < today
    )


def derive_treatment_deadline(actions: Sequence) -> "date | None":
    """The risk's treatment deadline when it has actions: the latest due date among the
    open actions — when the plan should be finished. Once every action is closed, the
    latest due date of any action (when it was planned to finish). None when no action
    has a date; the caller leaves a risk without actions alone."""
    open_dates = [a.due_date for a in actions if a.status in OPEN_ACTION_STATUSES and a.due_date]
    if open_dates:
        return max(open_dates)
    live = [a.due_date for a in actions if a.status != "cancelled" and a.due_date]
    return max(live) if live else None


def treatment_progress(actions: Sequence, today) -> dict[str, int]:
    """``done`` of ``total`` (cancelled actions are not part of the plan), open and
    overdue counts, and the percentage done."""
    plan = [a for a in actions if a.status != "cancelled"]
    done = sum(1 for a in plan if a.status == "done")
    return {
        "done": done,
        "total": len(plan),
        "open": sum(1 for a in plan if a.status in OPEN_ACTION_STATUSES),
        "overdue": sum(1 for a in plan if action_is_overdue(a, today)),
        "percent": round(100 * done / len(plan)) if plan else 0,
    }


def apply_action_status(action, *, status: str | None, percent: int | None, now) -> None:
    """Move an action's status and percentage together.

    ``done`` stamps ``completed_at`` (once) and makes it 100 %; leaving ``done`` clears
    the stamp. A percentage sent alongside wins over the implied one, except that a done
    action is always 100 %.
    """
    if status is not None:
        action.status = status
    if percent is not None:
        action.percent_complete = percent
    if action.status == "done":
        action.percent_complete = 100
        if action.completed_at is None:
            action.completed_at = now
    else:
        action.completed_at = None


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

    from app.core.schema_loading import options_for

    reason = ASSET_REMOVED_REASON.format(name=asset.name)
    # Only the review columns change: load none of the risks' links (each risk's linked
    # assets, with theirs, made restoring one asset take tens of seconds).
    risks = (
        await db.scalars(
            select(Risk).join(risk_assets, risk_assets.c.risk_id == Risk.id).where(
                risk_assets.c.asset_id == asset.id, Risk.deleted.is_(False)
            ).options(*options_for(Risk, None))
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
    # Phase 3 hierarchy: a risk that rolls others up, or sits under one, is in use.
    ("child_risks", "Child risks"),
    ("parent_risk", "Parent risk"),
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
    # Issues point at a risk two ways: the legacy ``source_id`` and (phase 2) the typed
    # ``issue_risks`` link. One row per risk, each issue counted once.
    issue_risks = tables["issue_risks"]
    by_issue = union(
        select(Issue.id.label("issue_id"), Issue.source_id.label("risk_id"))
        .where(Issue.source_id.in_(ids), Issue.deleted.is_(False)),
        select(issue_risks.c.issue_id.label("issue_id"), issue_risks.c.risk_id.label("risk_id"))
        .select_from(issue_risks.join(Issue, Issue.id == issue_risks.c.issue_id))
        .where(issue_risks.c.risk_id.in_(ids), Issue.deleted.is_(False)),
    ).subquery("issue_links")
    parts.append(
        select(_kind("issues"), by_issue.c.risk_id.label("risk_id"),
               func.count(func.distinct(by_issue.c.issue_id)).label("n"))
        .group_by(by_issue.c.risk_id)
    )
    # Phase 3 hierarchy, both directions: live children under the risk, and a live parent.
    from sqlalchemy.orm import aliased

    from app.models.risk import Risk

    child = aliased(Risk)
    parts.append(
        select(_kind("child_risks"), child.parent_id.label("risk_id"), func.count().label("n"))
        .where(child.parent_id.in_(ids), child.deleted.is_(False))
        .group_by(child.parent_id)
    )
    parent = aliased(Risk)
    parts.append(
        select(_kind("parent_risk"), Risk.id.label("risk_id"), func.count().label("n"))
        .select_from(Risk)
        .join(parent, and_(parent.id == Risk.parent_id, parent.deleted.is_(False)))
        .where(Risk.id.in_(ids))
        .group_by(Risk.id)
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
    """Live risks written against any of ``asset_ids``, without their links — callers
    flag them (columns) and name them. Loading each risk's linked assets, and theirs,
    made archiving one asset take minutes when a risk sat on the whole estate."""
    from app.core.schema_loading import options_for
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
                .options(*options_for(Risk, None))
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
    "Assessment",
    "LEAVE_DRAFT_DETAIL",
    "RATIONALE_REQUIRED_DETAIL",
    "SCORE_FIELDS",
    "TARGET_ABOVE_DETAIL",
    "TARGET_INCOMPLETE_DETAIL",
    "TITLE_NEEDS_STATEMENT_DETAIL",
    "OPEN_ACTION_STATUSES",
    "action_is_overdue",
    "apply_action_status",
    "assessment_decision",
    "changed_scores",
    "derive_treatment_deadline",
    "treatment_progress",
    "compose_title",
    "derive_dimension_impacts",
    "target_rule_violation",
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


# ------------------------------------------ generated title names an unlinked asset
# Re-check of 17 Sep 2026 (F-04): R-116 "Ransomware encrypts Firewall" was linked to Core
# Banking Server. A title written from a scenario template names its asset; when that
# asset exists in the register but is not among the risk's linked assets, the title or
# the link is wrong, and the risk is flagged for review until one of them is fixed.
TITLE_ASSET_REASON = (
    "The title names the asset “{name}”, which is not linked to this risk. "
    "Link that asset, or correct the title."
)
_TITLE_ASSET_PREFIX = TITLE_ASSET_REASON.split("{name}", 1)[0]


def is_title_asset_reason(line: str) -> bool:
    return line.startswith(_TITLE_ASSET_PREFIX)


def generated_title_mismatch(
    title: str | None,
    patterns: Sequence,
    linked_names: Iterable[str],
    register_names: Mapping[str, str],
) -> str | None:
    """The asset a generated-style title names but the risk does not link, or None. Pure.

    ``patterns`` come from ``risk_scenarios.title_patterns``; ``linked_names`` are the
    names of every asset the risk links (archived ones too — an archived asset has its
    own review reason); ``register_names`` maps lower-cased names of every asset in the
    register to their spelling. A risk is flagged only when it links at least one
    asset, no reading of its title names a linked asset, and some reading names an
    asset that exists — so a hand-written "Unauthorised access to SWIFT" with no asset
    called SWIFT is not an error. The longest existing name wins.
    """
    from app.services.risk_scenarios import match_generated_title

    linked = {(n or "").strip().lower() for n in linked_names if (n or "").strip()}
    if not linked:
        return None
    hits = match_generated_title(title or "", patterns)
    if not hits:
        return None
    readings = [name.strip() for _ref, names in hits for name in names if name.strip()]
    if any(name.lower() in linked for name in readings):
        return None
    existing = [register_names[name.lower()] for name in readings if name.lower() in register_names]
    return max(existing, key=len) if existing else None


def apply_title_asset_reason(risk, named: str | None) -> tuple[bool, bool]:
    """Set the risk's title-vs-asset review line to match ``named`` (None clears it).
    Other reasons are untouched; ``needs_review`` goes off only when none remain.
    Returns ``(flagged, cleared)``."""
    wanted = TITLE_ASSET_REASON.format(name=named) if named else None
    lines = review_reasons(risk.review_reason)
    stale = [line for line in lines if is_title_asset_reason(line) and line != wanted]
    flagged = wanted is not None and wanted not in lines
    if not stale and not flagged:
        return False, False
    lines = [line for line in lines if line not in stale]
    if flagged:
        lines.append(wanted)
    risk.review_reason = "\n".join(lines)
    if flagged:
        risk.needs_review = True
    elif not lines:
        risk.needs_review = False
    return flagged, bool(stale) and not flagged


async def reconcile_generated_title_flags(db, risk_ids: Iterable[uuid.UUID] | None = None) -> tuple[int, int]:
    """Flag live risks whose generated-style title names an asset they do not link, and
    clear the flag from those fixed since (:func:`generated_title_mismatch`). All risks,
    or only ``risk_ids`` — call it after a risk's asset links or title change. Returns
    ``(flagged, cleared)``. A handful of queries whatever the register's size."""
    from app.models.asset import Asset
    from app.models.risk import Risk, risk_assets
    from app.models.risk_scenario import RiskScenarioTemplate
    from app.services.risk_scenarios import match_generated_title, title_patterns

    wanted = None if risk_ids is None else list(dict.fromkeys(risk_ids))
    if wanted == []:
        return 0, 0
    patterns = title_patterns(
        (ref, title) for ref, title in (
            await db.execute(select(RiskScenarioTemplate.reference, RiskScenarioTemplate.title))
        ).all()
    )
    stmt = select(Risk.id, Risk.title, Risk.review_reason).where(Risk.deleted.is_(False))
    if wanted is not None:
        stmt = stmt.where(Risk.id.in_(wanted))
    matched: dict[uuid.UUID, str] = {}
    reasons: dict[uuid.UUID, str] = {}
    readings: set[str] = set()
    for rid, title, reason in (await db.execute(stmt)).all():
        reasons[rid] = reason or ""
        hits = match_generated_title(title or "", patterns) if patterns else []
        if hits:
            matched[rid] = title or ""
            readings |= {n.strip().lower() for _ref, names in hits for n in names if n.strip()}
    decisions: dict[uuid.UUID, str | None] = {
        rid: None for rid, reason in reasons.items()
        if rid not in matched and any(is_title_asset_reason(line) for line in review_reasons(reason))
    }
    if matched:
        linked: dict[uuid.UUID, list[str]] = {}
        for rid, name in (
            await db.execute(
                select(risk_assets.c.risk_id, Asset.name)
                .join(Asset, Asset.id == risk_assets.c.asset_id)
                .where(risk_assets.c.risk_id.in_(list(matched)))
            )
        ).all():
            linked.setdefault(rid, []).append(name or "")
        register: dict[str, str] = {}
        if readings:
            for (name,) in (
                await db.execute(select(Asset.name).where(func.lower(func.trim(Asset.name)).in_(sorted(readings))))
            ).all():
                register.setdefault((name or "").strip().lower(), (name or "").strip())
        for rid, title in matched.items():
            decisions[rid] = generated_title_mismatch(title, patterns, linked.get(rid, []), register)
    # Load only the risks whose review lines actually change.
    changing = [
        rid for rid, named in decisions.items()
        if [line for line in review_reasons(reasons.get(rid)) if is_title_asset_reason(line)]
        != ([TITLE_ASSET_REASON.format(name=named)] if named else [])
    ]
    if not changing:
        return 0, 0
    flagged = cleared = 0
    for risk in (await db.scalars(select(Risk).where(Risk.id.in_(changing)))).all():
        did_flag, did_clear = apply_title_asset_reason(risk, decisions.get(risk.id))
        flagged += int(did_flag)
        cleared += int(did_clear)
    return flagged, cleared
