"""Runtime maker-checker (four-eyes) enforcement.

The ``DualControlRule`` registry (``models/authority.py``) is where a bank *configures*
which module actions require dual control, above which monetary threshold, for which
roles. This service *enforces* that configuration at the moment a checker decides a
maker's request: the person who made a request can never be the one who approves it.

Resolution order for "does four-eyes apply to this action?":

1. If an explicit, enabled, active ``DualControlRule`` exists for the (module, action),
   it decides — honoring its ``requires_dual_control`` flag and ``threshold_amount``
   (below the threshold the control does not trigger).
2. With no rule configured, fall back to the global ``enforce_segregation_of_duties``
   switch. Banks keep it on, so sensitive decisions are **fail-closed** by default.

Canonical (module, action) keys used by callers today: ("risk", "accept") and
("exception", "approve"). Configure a matching DualControlRule to tune threshold/roles;
otherwise the global switch governs.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.authority import DualControlRule, DualControlStatus


async def find_rule(db: AsyncSession, module: str, action: str) -> DualControlRule | None:
    """The most recently configured, non-deleted dual-control rule for a module+action."""
    return await db.scalar(
        select(DualControlRule)
        .where(
            DualControlRule.module == module,
            DualControlRule.action == action,
            DualControlRule.deleted.is_(False),
        )
        .order_by(DualControlRule.created_at.desc())
    )


async def dual_control_required(
    db: AsyncSession, module: str, action: str, amount: float | None = None
) -> tuple[bool, DualControlRule | None]:
    """Return ``(required, rule)`` for (module, action[, amount]).

    Only an *active, enabled* rule governs an action explicitly: it can require dual
    control (optionally above a monetary threshold) or exempt the action outright
    (``requires_dual_control = False``). A disabled/inactive rule does NOT silently turn
    the control off — it falls through to the global ``enforce_segregation_of_duties``
    switch, which is fail-closed for banks."""
    rule = await find_rule(db, module, action)
    active = rule is not None and rule.enabled and rule.status == DualControlStatus.active
    if active:
        if not rule.requires_dual_control:
            return False, rule  # explicit opt-out
        if rule.threshold_amount is not None and amount is not None:
            return float(amount) >= float(rule.threshold_amount), rule
        return True, rule
    # No active rule governs this action → global fail-closed switch decides.
    return settings.enforce_segregation_of_duties, None


async def enforce_maker_checker(
    db: AsyncSession,
    *,
    module: str,
    action: str,
    maker_id: uuid.UUID | None,
    checker_id: uuid.UUID | None,
    amount: float | None = None,
    subject: str = "request",
) -> DualControlRule | None:
    """Raise 403 when four-eyes applies and the maker is trying to be their own checker.

    Returns the matched rule (or ``None``) so callers may log/inspect it. Safe to call on
    every decision path: when the control does not apply it is a no-op."""
    required, rule = await dual_control_required(db, module, action, amount)
    if not required:
        return rule
    if maker_id is not None and checker_id is not None and maker_id == checker_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Segregation of duties: the maker of this {subject} cannot approve it — "
                "an independent checker must decide."
            ),
        )
    return rule
