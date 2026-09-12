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
risk                 bulk_archive        archiving risks with no live links (an
                                         immediate action: refused while dual control
                                         applies — configure a rule to allow it)
<entity type>        attest              attesting a record's review (the person who
                                         entered the record may not certify it)
risk, control,       delete              archiving a core record (the person who entered
policy, business_unit,                   it may not also delete it)
process, issue,
incident, vendor
<entity type>        approve             approving or rejecting a record submitted for
                                         review (services/record_workflow.py)
===================  ==================  ==============================================

With the global switch on and no rule configured, each of these refuses when the maker
and the checker are the same person. Single-operator installs (demos, evaluations)
should either add a second user or set ``ENFORCE_SEGREGATION_OF_DUTIES=false``.

Who the maker of an existing record is — :func:`maker_of`, first answer wins:

1. The actor of the record's earliest ``create`` entry in the audit trail.
2. A user reference on the record itself, checked in :data:`MAKER_ATTRIBUTES` order
   (``created_by_id``, ``created_by``, ``maker_id``, ``owner_id``) — only a UUID, and
   only when the column is not a foreign key to some other table (``Asset.owner_id``
   names a business unit, not a person). This is what keeps seeded and imported records,
   which have no ``create`` audit entry, from being exempt from four-eyes: a risk owner
   cannot accept their own risk just because the risk arrived by import.
3. Otherwise ``None`` — no maker is known, and the check cannot block anyone.
"""
from __future__ import annotations

import uuid
from typing import Any

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


#: Attributes on a record that may name the user who made it, in the order tried.
MAKER_ATTRIBUTES: tuple[str, ...] = ("created_by_id", "created_by", "maker_id", "owner_id")

#: entity_type strings whose table name is not simply the plural of the type.
_ENTITY_TABLES: dict[str, str] = {
    "sar": "suspicious_activity_reports",
    "authority_matrix": "authority_matrix",
}


def _points_at_users(record: Any, attr: str) -> bool:
    """False when ``attr`` is a mapped column with a foreign key to a table other than
    ``users``. Plain attributes and un-keyed UUID columns are taken at their word."""
    table = getattr(type(record), "__table__", None)
    columns = getattr(table, "c", None)
    if columns is None or attr not in columns:
        return True
    fks = columns[attr].foreign_keys
    return not fks or any(fk.target_fullname.split(".")[0] == "users" for fk in fks)


def maker_from_record(record: Any) -> uuid.UUID | None:
    """The first user id found on the record among :data:`MAKER_ATTRIBUTES`."""
    if record is None:
        return None
    for attr in MAKER_ATTRIBUTES:
        value = getattr(record, attr, None)
        if isinstance(value, uuid.UUID) and _points_at_users(record, attr):
            return value
    return None


def model_for_entity_type(entity_type: str):
    """The ORM class behind a polymorphic ``entity_type`` string, or None — the
    versioning registry first, then the table named after the type."""
    from app.models.base import Base
    from app.services.versioning import MODEL_MAP

    if entity_type in MODEL_MAP:
        return MODEL_MAP[entity_type]
    wanted = _ENTITY_TABLES.get(entity_type)
    candidates = (wanted,) if wanted else (
        f"{entity_type}s",
        f"{entity_type}es",
        f"{entity_type[:-1]}ies" if entity_type.endswith("y") else "",
        entity_type,
    )
    by_table = {
        getattr(m.class_, "__tablename__", None): m.class_ for m in Base.registry.mappers
    }
    for name in candidates:
        if name and name in by_table:
            return by_table[name]
    return None


async def maker_of(
    db: AsyncSession, entity_type: str, entity_id: uuid.UUID, record: Any = None
) -> uuid.UUID | None:
    """Who created this record — the "maker" for four-eyes purposes.

    The registers under dual control (SARs, charity disbursements, policies, control
    audits, authority-matrix rows) mostly store an owner *name*, not a user id, so the
    trail is the authoritative record of who actually entered it: the earliest ``create``
    audit entry for the record. Seeded and imported records have no such entry; for them
    the record's own user reference is used (see the module docstring for the order).
    Pass ``record`` when the caller already holds it to skip loading it again. Returns
    None only when neither source names anyone.
    """
    from app.models.audit import AuditLog

    maker = await db.scalar(
        select(AuditLog.actor_id)
        .where(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
            AuditLog.action == "create",
        )
        .order_by(AuditLog.created_at.asc())
        .limit(1)
    )
    if maker is not None:
        return maker

    if record is None:
        model = model_for_entity_type(entity_type)
        if model is None or not any(hasattr(model, a) for a in MAKER_ATTRIBUTES):
            return None
        record = await db.get(model, entity_id)
    return maker_from_record(record)


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
    record: Any = None,
) -> DualControlRule | None:
    """Four-eyes for a decision taken *on an existing record*.

    Resolves the maker with :func:`maker_of` (audit trail first, then the record's own
    user reference), then applies the same rule as :func:`enforce_maker_checker`. Use
    this for sign-offs where the maker is "whoever entered the record" — filing a SAR,
    approving a policy, releasing a charity disbursement.
    """
    maker_id = await maker_of(db, entity_type, entity_id, record=record)
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
