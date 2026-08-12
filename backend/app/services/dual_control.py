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

Canonical (module, action) keys enforced today — configure a matching DualControlRule to
tune threshold/roles, or to switch one off; otherwise the global switch governs:

===================  ==================  ==============================================
module               action              decision that is gated
===================  ==================  ==============================================
risk                 accept              accepting a risk
exception            approve             approving a risk exception
control              audit               recording a control-audit result
policy               publish             publishing (approving) a policy
aml                  file_sar            marking an STR/SAR as filed with the FMU
shariah              charity_approved    approving a purification disbursement
shariah              charity_disbursed   releasing a purification disbursement
authority            update              amending an authority-matrix line
===================  ==================  ==============================================

With the global switch on and no rule configured, each of these refuses when the maker
and the checker are the same person. Single-operator installs (demos, evaluations)
should either add a second user or set ``ENFORCE_SEGREGATION_OF_DUTIES=false``.
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


async def maker_of(db: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> uuid.UUID | None:
    """Who created this record — the "maker" for four-eyes purposes.

    The registers under dual control (SARs, charity disbursements, policies, control
    audits, authority-matrix rows) store an owner *name*, not a user id, so the trail is
    the authoritative record of who actually entered it: the earliest ``create`` audit
    entry for the record. Returns None when the record predates the audit trail or was
    seeded, in which case the caller's four-eyes check is a no-op rather than a false
    block.
    """
    from app.models.audit import AuditLog

    return await db.scalar(
        select(AuditLog.actor_id)
        .where(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
            AuditLog.action == "create",
        )
        .order_by(AuditLog.created_at.asc())
        .limit(1)
    )


async def enforce_record_maker_checker(
    db: AsyncSession,
    *,
    module: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    checker_id: uuid.UUID | None,
    amount: float | None = None,
    subject: str = "request",
) -> DualControlRule | None:
    """Four-eyes for a decision taken *on an existing record*.

    Resolves the maker from the record's creation entry in the audit trail, then applies
    the same rule as :func:`enforce_maker_checker`. Use this for sign-offs where the
    maker is "whoever entered the record" — filing a SAR, approving a policy, releasing
    a charity disbursement.
    """
    maker_id = await maker_of(db, entity_type, entity_id)
    return await enforce_maker_checker(
        db,
        module=module,
        action=action,
        maker_id=maker_id,
        checker_id=checker_id,
        amount=amount,
        subject=subject,
    )


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
