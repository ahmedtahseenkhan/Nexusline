"""The risk register's filter, in one place.

Three callers need to agree on what "the risks I am looking at" means: the register's
list endpoint, the PDF export launched from it, and the report builder. Duplicating the
predicates is how a report quietly stops matching the screen it was launched from —
nothing errors, the numbers are just wrong — so they live here and everyone imports them.

Segment filters are ``EXISTS`` sub-queries rather than joins, because a risk in two
business units would otherwise come back twice and inflate every count on the page.

Phase 3 adds the hierarchy filters (``level``, ``max_level``, ``parent_id``,
``roots_only``) and the drill-through filters the dashboard links to, each defined
exactly as the dashboard counts it:

* ``review`` — ``overdue``: next review date before today; ``due_30d``: from today to
  30 days ahead (not yet overdue).
* ``appetite`` — ``within`` / ``elevated`` / ``breach``: the effective score (residual
  when assessed, else inherent) against the appetite and tolerance of the risk's own
  level-1 category, else the organisation's (``AppetiteBook``, as on the dashboard).
* ``has_controls`` — at least one live control linked (or none, when false).
* ``treatment_overdue`` — a risk that is not accepted or closed and has an open or
  in-progress treatment action past its due date, or — having no actions at all — a
  treatment deadline in the past (the dashboard's "treatment actions past due").
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import Select, and_, case, exists, func, not_, or_, select
from sqlalchemy.orm import aliased

from app.models.control import Control
from app.models.enums import RiskStatus
from app.models.risk import (
    Risk,
    RiskTreatmentAction,
    risk_assets,
    risk_business_units,
    risk_controls,
    risk_processes,
)
from app.services.risk_scoring import AppetiteBook

#: Accepted and closed risks have no treatment clock (the dashboard's "settled" set).
SETTLED_STATUSES: tuple[RiskStatus, ...] = (RiskStatus.accepted, RiskStatus.closed)
OPEN_ACTION_STATUSES: tuple[str, ...] = ("open", "in_progress")
REVIEW_FILTERS: tuple[str, ...] = ("overdue", "due_30d")
APPETITE_FILTERS: dict[str, str] = {
    "within": "within_appetite", "within_appetite": "within_appetite",
    "elevated": "elevated", "breach": "breach",
}
#: ``level=0`` asks for risks not yet placed in the hierarchy.
UNPLACED = 0


def effective_score_expr():
    """Residual when assessed, else inherent — ``risk_scoring.effective_score`` in SQL."""
    return func.coalesce(Risk.residual_score, Risk.inherent_score)


def appetite_thresholds(book: AppetiteBook):
    """``(appetite, tolerance)`` SQL expressions per risk: each category's level-1
    appetite where one is set, else the organisation's. Categories sharing thresholds
    share a CASE branch, so the expression stays small however long the list is."""
    groups: dict[tuple[int, int], list[uuid.UUID]] = {}
    for cid in {*book.parents, *book.by_category}:
        pair = book.thresholds(cid)
        if pair != (book.appetite, book.tolerance):
            groups.setdefault(pair, []).append(cid)
    if not groups:
        return book.appetite, book.tolerance
    ordered = sorted(groups.items(), key=lambda kv: kv[0])
    appetite = case(
        *((Risk.category_id.in_(sorted(ids, key=str)), a) for (a, _t), ids in ordered),
        else_=book.appetite,
    )
    tolerance = case(
        *((Risk.category_id.in_(sorted(ids, key=str)), t) for (_a, t), ids in ordered),
        else_=book.tolerance,
    )
    return appetite, tolerance


def appetite_clause(position: str, book: AppetiteBook):
    """The WHERE clause for one appetite position (``within``/``elevated``/``breach``)."""
    wanted = APPETITE_FILTERS.get(position)
    if wanted is None:
        raise ValueError(f"appetite must be one of {', '.join(sorted(set(APPETITE_FILTERS)))}")
    score = effective_score_expr()
    appetite, tolerance = appetite_thresholds(book)
    if wanted == "within_appetite":
        return score <= appetite
    if wanted == "elevated":
        return and_(score > appetite, score <= tolerance)
    return score > tolerance


def has_controls_clause():
    """At least one live (not archived) control is linked."""
    return exists(
        select(risk_controls.c.risk_id)
        .join(Control, Control.id == risk_controls.c.control_id)
        .where(risk_controls.c.risk_id == Risk.id, Control.deleted.is_(False))
    )


def treatment_overdue_clause(today: date):
    """Unsettled, with an open action past due — or no actions and a past deadline."""
    action_overdue = exists(
        select(RiskTreatmentAction.id).where(
            RiskTreatmentAction.risk_id == Risk.id,
            RiskTreatmentAction.status.in_(OPEN_ACTION_STATUSES),
            RiskTreatmentAction.due_date < today,
        )
    )
    has_actions = exists(select(RiskTreatmentAction.id).where(RiskTreatmentAction.risk_id == Risk.id))
    deadline_overdue = and_(not_(has_actions), Risk.treatment_deadline < today)
    return and_(Risk.status.not_in(SETTLED_STATUSES), or_(action_overdue, deadline_overdue))


def roots_clause():
    """No live parent: at the top of the tree, or under a parent that was archived."""
    parent = aliased(Risk)
    live_parent = exists(select(parent.id).where(parent.id == Risk.parent_id, parent.deleted.is_(False)))
    return or_(Risk.parent_id.is_(None), not_(live_parent))


def build_risk_query(
    *,
    status: RiskStatus | None = None,
    category: str | None = None,
    business_unit_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    search: str | None = None,
    owner_id: uuid.UUID | None = None,
    treatment_owner_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    level: int | None = None,
    max_level: int | None = None,
    parent_id: uuid.UUID | None = None,
    roots_only: bool | None = None,
    review: str | None = None,
    appetite: str | None = None,
    appetite_book: AppetiteBook | None = None,
    has_controls: bool | None = None,
    treatment_overdue: bool | None = None,
    today: date | None = None,
) -> Select:
    """Live risks matching the given filters. See the module docstring.

    ``category`` (legacy text, exact) and ``category_id`` (the picked risk category)
    may both be given; a risk must then match both. ``level`` is 1, 2 or 3, or
    ``UNPLACED`` (0) for risks with no level; ``max_level`` keeps placed risks at that
    level or above (the parent picker). ``appetite`` needs the tenant's
    ``appetite_book`` (``risk_settings.load_appetite_book``) — ValueError without it.
    """
    today = today or date.today()
    stmt: Select = select(Risk).where(Risk.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(Risk.status == status)
    if category:
        stmt = stmt.where(Risk.category == category)
    if category_id is not None:
        stmt = stmt.where(Risk.category_id == category_id)
    if owner_id is not None:
        stmt = stmt.where(Risk.owner_id == owner_id)
    if treatment_owner_id is not None:
        stmt = stmt.where(Risk.treatment_owner_id == treatment_owner_id)
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

    # --- phase 3: hierarchy
    if level is not None:
        stmt = stmt.where(Risk.level.is_(None) if level == UNPLACED else Risk.level == level)
    if max_level is not None:
        stmt = stmt.where(Risk.level.is_not(None), Risk.level <= max_level)
    if parent_id is not None:
        stmt = stmt.where(Risk.parent_id == parent_id)
    if roots_only:
        stmt = stmt.where(roots_clause())

    # --- phase 3: drill-through from the dashboard
    if review == "overdue":
        stmt = stmt.where(Risk.next_review_date < today)
    elif review == "due_30d":
        stmt = stmt.where(Risk.next_review_date >= today, Risk.next_review_date <= today + timedelta(days=30))
    elif review:
        raise ValueError(f"review must be one of {', '.join(REVIEW_FILTERS)}")
    if appetite:
        if appetite_book is None:
            raise ValueError("The appetite filter needs the organisation's appetite book")
        stmt = stmt.where(appetite_clause(appetite, appetite_book))
    if has_controls is not None:
        stmt = stmt.where(has_controls_clause() if has_controls else not_(has_controls_clause()))
    if treatment_overdue is not None:
        clause = treatment_overdue_clause(today)
        stmt = stmt.where(clause if treatment_overdue else not_(clause))
    return stmt


__all__ = [
    "APPETITE_FILTERS",
    "REVIEW_FILTERS",
    "UNPLACED",
    "appetite_clause",
    "appetite_thresholds",
    "build_risk_query",
    "effective_score_expr",
    "has_controls_clause",
    "roots_clause",
    "treatment_overdue_clause",
]
