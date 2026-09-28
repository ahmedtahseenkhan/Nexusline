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
control              review_test         approving or returning a control test (the
                                         tester, and whoever recorded or edited the
                                         test, may not review it)
policy               publish             publishing (approving) a policy
aml                  file_sar            marking an STR/SAR as filed with the FMU
shariah              charity_approved    approving a purification disbursement
shariah              charity_disbursed   releasing a purification disbursement
authority            update              amending an authority-matrix line
issue                validate            validating an issue's remediation (not its
                                         owner, not whoever raised it)
issue                close               closing an issue (not whoever raised it)
issue                extend_due_date     approving a later due date on a regulator-
                                         related / high / critical issue (not whoever
                                         asked for it)
assessment           review              completing the review of a questionnaire
                                         assessment (not whoever sent it)
board_pack           release             reviewing and releasing a board pack (none of
                                         its preparers)
capital_calculation  reopen              reopening a final regulatory capital figure
                                         (not whoever marked it final)
vuln_finding         accept_risk         accepting a vulnerability's risk instead of
                                         fixing it (not whoever asked for it)
risk                 bulk_archive        archiving risks with no live links (an
                                         immediate action: refused while dual control
                                         applies — configure a rule to allow it)
<entity type>        attest              attesting a record's review. Decision 9: this key
                                         is honoured only where an organisation has
                                         configured a rule for it — the attest call does
                                         not fall back to the global switch, because the
                                         attestation is the record owner's own
                                         certification (``api/v1/attestations.py``)
risk, control,       delete              archiving a core record (the person who entered
policy, business_unit,                   it may not also delete it)
process, legal, issue,
incident, vendor
<entity type>        approve             approving or rejecting a record submitted for
                                         review (services/record_workflow.py)
===================  ==================  ==============================================

The same list is :func:`enforced_keys`: the Delegation of Authority page offers only
these keys, and ``POST/PATCH /dual-control-rules`` refuses any other (a rule for a key no
code checks — "payments / disburse" — looked like a control and enforced nothing).

Relaxing a rule is itself controlled (:func:`relaxations`): switching a rule off,
exempting an action, raising or adding a threshold, moving a rule to another key or
deleting one needs an administrator (``settings:manage``), not just ``authority:write`` —
otherwise the maker a rule binds could switch it off for their own decision. Every rule
change is on the activity trail with its before and after values.

With the global switch on and no rule configured, each of these refuses when the maker
and the checker are the same person. Single-operator installs (demos, evaluations)
should either add a second user or set ``ENFORCE_SEGREGATION_OF_DUTIES=false``.

Every organisation now starts with a rule for each of these keys **except** ``attest``
(``services/default_governance.py``: on provisioning, at the end of onboarding, and once
for older organisations at start-up). They are created enabled when the global switch is
on — which refuses exactly what the switch alone refused — and disabled when it is off,
so the switch keeps deciding until an administrator turns an individual rule on. A key
whose rule is deleted falls back to the switch again; the defaults never re-create it.

A rule's ``checker_role`` and ``maker_role`` narrow who may check and who may ask
(see "maker and checker roles" below); each binds only while another active user holds
the role, so a vacated role never locks a decision out. Decisions that carry an amount
are also held to the delegation-of-authority matrix (``services/authority_limits.py``).

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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
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
    message: str | None = None,
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
        message=message,
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
    message: str | None = None,
) -> DualControlRule | None:
    """Raise 403 when four-eyes applies and the maker is trying to be their own checker.

    Returns the matched rule (or ``None``) so callers may log/inspect it. Safe to call on
    every decision path: when the control does not apply it is a no-op. ``message``
    replaces the generic wording where "approve" is the wrong verb (recording a test of
    a control you entered, say)."""
    required, rule = await dual_control_required(db, module, action, amount)
    if not required:
        return rule
    if maker_id is not None and checker_id is not None and maker_id == checker_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=maker_checker_message(subject, message),
        )
    await enforce_checker_role(db, rule, module=module, action=action,
                               checker_id=checker_id, maker_id=maker_id)
    return rule


def maker_checker_message(subject: str = "request", message: str | None = None) -> str:
    """The refusal a maker hears when they try to be their own checker."""
    return message or (
        f"Segregation of duties: the maker of this {subject} cannot approve it — "
        "an independent checker must decide."
    )


async def record_maker_checker_refusal(
    db: AsyncSession,
    *,
    module: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    checker_id: uuid.UUID | None,
    amount: float | None = None,
    subject: str = "request",
    message: str | None = None,
    record: Any = None,
) -> str | None:
    """:func:`enforce_record_maker_checker` as a question instead of a gate.

    Returns the exact text the enforcing call would raise as its 403 detail, or ``None``
    when this checker may decide. Never raises (beyond a database error), so a read
    endpoint can tell the user *before* they try — the attestation panel's ``can_attest``
    / ``blocked_reason`` — while the write path keeps enforcing with the raising call.
    Same resolution as the gate: the rule from :func:`dual_control_required`, the maker
    from :func:`maker_of` (only looked up when the rule applies).
    """
    required, rule = await dual_control_required(db, module, action, amount)
    if not required or checker_id is None:
        return None
    maker_id = await maker_of(db, entity_type, entity_id, record=record)
    if maker_id is not None and maker_id == checker_id:
        return maker_checker_message(subject, message)
    return await checker_role_refusal(db, rule, module=module, action=action,
                                      checker_id=checker_id, maker_id=maker_id)


# ------------------------------------------------- maker and checker roles ---
# A rule's ``maker_role`` / ``checker_role`` say who may make and who may check. They
# narrow four-eyes, never replace it: the checker is still never the maker.
#
# * ``checker_role`` is enforced wherever the rule's decision is checked (every
#   caller of :func:`enforce_maker_checker`, :func:`record_maker_checker_refusal` and
#   the sites that call :func:`checker_role_refusal` themselves).
# * ``maker_role`` is enforced where a maker *asks* for the decision — requesting a risk
#   acceptance, raising an exception, asking for a later issue due date, submitting a
#   record for review (:func:`enforce_maker_role`). Decisions whose maker is simply
#   "whoever entered the record" have no request step; there the rule's checker role
#   and the four-eyes check apply, and the maker role is not checked after the fact
#   (a record entered before the rule existed would otherwise become undecidable).
#
# Fallback, as approval routes do for a stage role nobody can decide
# (``default_governance.stage_decision_refusal``): the role binds only while some
# *other* active user holds it — and, for the checker, also holds the permission the
# decision needs. With nobody there, anyone who may take the step may take it, so a
# mis-configured or vacated role never locks an organisation out of a decision; the
# refusal text, the Delegation of Authority page and the activity trail make the gap
# visible instead.

#: The permission a checker of each fixed decision needs (holders without it could not
#: decide, so they do not count as available checkers). ``<type>/approve`` keys use the
#: record lifecycle's approve permission; keys not listed count role holders only.
CHECKER_PERMISSIONS: dict[tuple[str, str], str] = {
    ("risk", "accept"): "risk:accept",
    ("risk", "bulk_archive"): "risk:write",
    ("exception", "approve"): "exception:approve",
    ("control", "audit"): "control:test",
    ("control", "review_test"): "control:test",
    ("policy", "publish"): "policy:write",
    ("issue", "validate"): "issue:write",
    ("issue", "close"): "issue:write",
    ("authority", "update"): "authority:write",
    ("assessment", "review"): "assessment:write",
    ("board_pack", "release"): "boardpack:release",
    ("capital_calculation", "reopen"): "scenario:write",
    ("aml", "file_sar"): "aml:write",
    ("shariah", "charity_approved"): "shariah:write",
    ("shariah", "charity_disbursed"): "shariah:write",
    ("vuln_finding", "accept_risk"): "workflow:approve",
}


def checker_permission(module: str, action: str) -> str | None:
    """The permission an available checker of (module, action) must hold, or None."""
    if (module, action) in CHECKER_PERMISSIONS:
        return CHECKER_PERMISSIONS[(module, action)]
    if action == "approve":
        from app.services import record_workflow

        try:
            return record_workflow.required_permissions(module, "approve")[-1]
        except Exception:  # noqa: BLE001 - not a record type with a lifecycle
            return None
    return None


def role_gate_refusal(
    role: str | None, held_roles: Iterable[str], available: int, *, step: str, reference: str = "",
) -> str | None:
    """Why someone holding ``held_roles`` may not take ``step`` under a rule that
    reserves it for ``role``, or None. Pure.

    ``available`` counts the *other* active users who hold the role (and can take the
    step); with none the role does not bind (the fallback above)."""
    wanted = _norm(role)
    if not wanted or available <= 0:
        return None
    if wanted in {_norm(r) for r in held_roles if r}:
        return None
    rule = f" ({reference})" if reference else ""
    return (
        f"Maker-checker rule{rule}: {step} is reserved for the {' '.join((role or '').split())} role. "
        "Ask someone who holds it."
    )


async def _role_facts(
    db: AsyncSession, role: str, user_id: Any, exclude: set, permission: str | None, directory: Any = None,
) -> tuple[tuple[str, ...], int]:
    """``(roles user_id holds, other active holders of role able to act)``. Pass the
    ``notifications.Directory`` already loaded to skip loading it again (My Work checks
    many items against one directory)."""
    from app.services.notifications import load_directory

    if directory is None:
        directory = await load_directory(db)
    canonical = directory.role(role)
    held = directory.roles_of(user_id) if user_id is not None else ()
    if canonical is None:
        return held, 0
    available = sum(
        1 for uid in directory.members(canonical)
        if uid not in exclude and uid != user_id
        and (permission is None or permission in directory.permissions_of(uid))
    )
    return held, available


async def checker_role_refusal(
    db: AsyncSession, rule: DualControlRule | None, *, module: str, action: str,
    checker_id: uuid.UUID | None, maker_id: uuid.UUID | None, directory: Any = None,
) -> str | None:
    """Why ``checker_id`` may not check under ``rule``'s checker role, or None.
    ``directory``: an already-loaded ``notifications.Directory``, to reuse."""
    role = (getattr(rule, "checker_role", "") or "").strip() if rule is not None else ""
    if not role or checker_id is None:
        return None
    exclude = {maker_id} if maker_id is not None else set()
    held, available = await _role_facts(db, role, checker_id, exclude, checker_permission(module, action),
                                        directory)
    return role_gate_refusal(role, held, available, step="checking this decision",
                             reference=getattr(rule, "reference", "") or "")


async def enforce_checker_role(
    db: AsyncSession, rule: DualControlRule | None, *, module: str, action: str,
    checker_id: uuid.UUID | None, maker_id: uuid.UUID | None,
) -> None:
    refusal = await checker_role_refusal(db, rule, module=module, action=action,
                                         checker_id=checker_id, maker_id=maker_id)
    if refusal:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)


async def enforce_maker_role(
    db: AsyncSession, *, module: str, action: str, maker_id: uuid.UUID | None,
    amount: float | None = None,
) -> None:
    """403 when an active rule for (module, action) names a maker role the requester
    does not hold, while someone else does (the fallback above). Called where the maker
    asks for the decision; a no-op when four-eyes does not apply."""
    required, rule = await dual_control_required(db, module, action, amount)
    role = (getattr(rule, "maker_role", "") or "").strip() if rule is not None else ""
    if not required or not role or maker_id is None:
        return
    held, available = await _role_facts(db, role, maker_id, set(), None)
    refusal = role_gate_refusal(role, held, available, step="asking for this decision",
                                reference=getattr(rule, "reference", "") or "")
    if refusal:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)


# ------------------------------------------------------------- enforced keys ---
@dataclass(frozen=True)
class EnforcedKey:
    """A (module, action) the code actually checks, with what it gates."""

    module: str
    action: str
    label: str
    group: str


#: Decisions checked at one call site each (the table in the module docstring).
FIXED_KEYS: tuple[EnforcedKey, ...] = (
    EnforcedKey("risk", "accept", "Accepting a risk", "Decisions"),
    EnforcedKey("risk", "bulk_archive", "Archiving risks in bulk", "Decisions"),
    EnforcedKey("exception", "approve", "Approving a risk exception", "Decisions"),
    EnforcedKey("control", "audit", "Recording a control test", "Decisions"),
    EnforcedKey("control", "review_test", "Reviewing a control test", "Decisions"),
    EnforcedKey("policy", "publish", "Publishing a policy", "Decisions"),
    EnforcedKey("issue", "validate", "Validating an issue's remediation", "Decisions"),
    EnforcedKey("issue", "close", "Closing an issue", "Decisions"),
    EnforcedKey("issue", "extend_due_date", "Approving a later issue due date", "Decisions"),
    EnforcedKey("authority", "update", "Amending a delegation-of-authority line", "Decisions"),
    EnforcedKey("assessment", "review", "Completing a questionnaire assessment review", "Decisions"),
    EnforcedKey("board_pack", "release", "Reviewing and releasing a board pack", "Decisions"),
    EnforcedKey("capital_calculation", "reopen", "Reopening a final capital calculation", "Decisions"),
    EnforcedKey("aml", "file_sar", "Marking an STR / SAR as filed with the FMU", "Decisions"),
    EnforcedKey("shariah", "charity_approved", "Approving a purification disbursement", "Decisions"),
    EnforcedKey("shariah", "charity_disbursed", "Releasing a purification disbursement", "Decisions"),
    EnforcedKey("vuln_finding", "accept_risk", "Accepting a vulnerability's risk", "Decisions"),
)

#: Registers whose archive goes through ``services/delete_guard.py``.
DELETE_GUARDED_TYPES: tuple[str, ...] = (
    "risk", "control", "policy", "business_unit", "process", "legal", "issue", "incident", "vendor",
)


@lru_cache(maxsize=1)
def enforced_keys() -> tuple[EnforcedKey, ...]:
    """Every (module, action) a dual-control rule can govern: the fixed decisions, the
    guarded deletes, approval of each record type with a review lifecycle, and
    attestation of each registered record type. Computed from the registries, so a new
    record type with a lifecycle appears without editing this list."""
    from app.services import record_registry
    from app.services.entity_types import ENTITY_TYPES

    out = list(FIXED_KEYS)
    for et in DELETE_GUARDED_TYPES:
        out.append(EnforcedKey(et, "delete", f"Archiving a {ENTITY_TYPES[et].label.lower()}", "Deleting records"))
    for et, spec in sorted(ENTITY_TYPES.items(), key=lambda kv: kv[1].label):
        if record_registry.has_workflow(record_registry.model_for(et)):
            out.append(EnforcedKey(et, "approve", f"Approving a {spec.label.lower()} submitted for review",
                                   "Approving submitted records"))
    for et, spec in sorted(ENTITY_TYPES.items(), key=lambda kv: kv[1].label):
        out.append(EnforcedKey(et, "attest", f"Attesting a {spec.label.lower()}'s review", "Attestations"))
    return out


def is_enforced_key(module: str, action: str) -> bool:
    return any(k.module == module and k.action == action for k in enforced_keys())


def unknown_key_message(module: str, action: str) -> str:
    return (
        f"No part of the system checks a maker-checker rule for {module} / {action}, so the "
        "rule would enforce nothing. Pick one of the listed decisions (GET "
        "/dual-control-rules/keys)."
    )


# ------------------------------------------------------- relaxing a rule ---
@dataclass(frozen=True)
class Effect:
    """What four-eyes does for one key: whether it applies, and from which amount."""

    required: bool
    threshold: float | None = None


def _field(rule: Any, name: str) -> Any:
    return rule.get(name) if isinstance(rule, Mapping) else getattr(rule, name, None)


def _role(rule: Any, name: str) -> str:
    """A rule's maker / checker role, normalised for comparison ("" when none)."""
    return " ".join(str(_field(rule, name) or "").lower().split())


def rule_effect(rule: Any, *, action: str, global_switch: bool) -> Effect:
    """The effect of ``rule`` (an ORM row, a dict of its fields, or None for "no rule")
    — the same resolution as :func:`dual_control_required`. Attestation keys do not
    fall back to the global switch (``api/v1/attestations.py``)."""
    status_value = _field(rule, "status") if rule is not None else None
    status_value = getattr(status_value, "value", status_value)
    active = (
        rule is not None and bool(_field(rule, "enabled"))
        and status_value == DualControlStatus.active.value
    )
    if not active:
        return Effect(required=False if action == "attest" else bool(global_switch))
    if not _field(rule, "requires_dual_control"):
        return Effect(required=False)
    threshold = _field(rule, "threshold_amount")
    return Effect(required=True, threshold=float(threshold) if threshold is not None else None)


def loosens(before: Effect, after: Effect) -> bool:
    """True when some decision four-eyes caught under ``before`` escapes it under
    ``after``: switched off, or a threshold added or raised."""
    if not before.required:
        return False
    if not after.required:
        return True
    if after.threshold is None:
        return False
    return before.threshold is None or after.threshold > before.threshold


def relaxations(
    *, before: Any, after: Any, global_switch: bool,
    superseded: Any = None, new_key_current: Any = None,
) -> list[str]:
    """Why a rule change weakens four-eyes, as plain phrases (empty when it does not).

    ``before`` is the rule as it was (None when it is being created), ``after`` as it
    will be (None when it is being deleted). ``superseded`` is the rule that governs the
    key today when a new rule is created (the newest rule wins); ``new_key_current`` is
    the rule already governing the key a rule is being moved to."""
    out: list[str] = []
    if before is None:  # create
        key_action = _field(after, "action")
        if loosens(rule_effect(superseded, action=key_action, global_switch=global_switch),
                   rule_effect(after, action=key_action, global_switch=global_switch)):
            out.append(f"it relaxes four-eyes on {_field(after, 'module')} / {key_action}")
        return out
    old_key = (_field(before, "module"), _field(before, "action"))
    old_effect = rule_effect(before, action=old_key[1], global_switch=global_switch)
    if after is None:  # delete
        if loosens(old_effect, rule_effect(None, action=old_key[1], global_switch=global_switch)):
            out.append(f"deleting it hands {old_key[0]} / {old_key[1]} to a weaker default")
        elif old_effect.required and any(_role(before, r) for r in ("maker_role", "checker_role")):
            out.append("deleting it drops the maker / checker roles it names")
        return out
    new_key = (_field(after, "module"), _field(after, "action"))
    if new_key != old_key:
        if loosens(old_effect, rule_effect(None, action=old_key[1], global_switch=global_switch)):
            out.append(f"moving it leaves {old_key[0]} / {old_key[1]} to a weaker default")
        if loosens(rule_effect(new_key_current, action=new_key[1], global_switch=global_switch),
                   rule_effect(after, action=new_key[1], global_switch=global_switch)):
            out.append(f"it relaxes four-eyes on {new_key[0]} / {new_key[1]}")
        return out
    new_effect = rule_effect(after, action=old_key[1], global_switch=global_switch)
    if loosens(old_effect, new_effect):
        if old_effect.required and not new_effect.required:
            out.append("it switches four-eyes off for this action")
        else:
            out.append("it lets more decisions through without a second person (threshold)")
    # The roles are enforced (maker_role / checker_role): removing or replacing one widens
    # who may ask or decide; naming one where there was none only narrows it.
    for name, what in (("maker_role", "maker"), ("checker_role", "checker")):
        was = _role(before, name)
        if was and _role(after, name) != was:
            out.append(f"it changes the {what} role from {_field(before, name).strip()}")
    return out


#: Who may relax a rule. Maker-checker configuration is itself under dual control in
#: core-banking systems (Temenos, Finacle authorise parameter changes); here the
#: equivalent is that only an administrator — never an ordinary ``authority:write``
#: holder, who may be the very maker the rule binds — can weaken one.
RELAX_PERMISSION = "settings:manage"


def relax_refusal(reasons: Iterable[str], permission_codes: Iterable[str]) -> str | None:
    """The 403 text when a rule change weakens four-eyes and the user may not do that."""
    reasons = list(reasons)
    if not reasons or RELAX_PERMISSION in set(permission_codes or ()):
        return None
    return (
        "Only an administrator can relax a maker-checker rule — "
        + "; ".join(reasons)
        + ". Four-eyes cannot be switched off by the people it binds. Ask an administrator "
        "(settings:manage) to make this change; it is recorded in the activity trail."
    )


# ------------------------------------------------ delegation-of-authority limits ---
@dataclass(frozen=True)
class MandateLine:
    """The parts of an authority-matrix line a limit check reads."""

    reference: str
    role_title: str
    approval_level: int
    amount_from: float
    amount_to: float | None
    currency: str


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def mandate_refusal(
    lines: Iterable[MandateLine], *, amount: float | None, role_names: Iterable[str],
    currency: str = "", activity: str = "this decision",
) -> str | None:
    """Why someone holding ``role_names`` may not approve ``amount`` under the matrix
    ``lines`` (the active lines of one category), or None when they may.

    * No lines, or no amount: the matrix does not govern this decision — None. A bank
      that has not put a category in its matrix is not locked out of it.
    * A line applies to a role when its ``role_title`` names one of the user's roles
      (case- and spacing-insensitive) and the amount is inside its band.
    * Lines in another currency are ignored when ``currency`` is given.
    """
    lines = [
        ln for ln in lines
        if not currency or not ln.currency or ln.currency.upper() == currency.upper()
    ]
    if not lines or amount is None:
        return None
    amount = float(amount)
    held = {_norm(r) for r in role_names if r}

    def covers(ln: MandateLine) -> bool:
        return float(ln.amount_from or 0) <= amount and (ln.amount_to is None or amount <= float(ln.amount_to))

    if any(_norm(ln.role_title) in held and covers(ln) for ln in lines):
        return None
    able = sorted({ln.role_title for ln in lines if covers(ln) and ln.role_title},
                  key=lambda t: min(ln.approval_level for ln in lines if ln.role_title == t))
    shown = f"{currency + ' ' if currency else ''}{amount:,.0f}"
    needs = (
        f"It needs {', '.join(able)}." if able else
        "No line in the delegation-of-authority matrix covers that amount, so it needs a "
        "line added (or an existing band raised) before anyone can approve it."
    )
    return f"Delegation of authority: {activity} for {shown} is above your mandate. {needs}"


async def authority_lines(db: AsyncSession, category: str) -> list[MandateLine]:
    """The active, current authority-matrix lines of one category."""
    from datetime import date

    from app.models.authority import AuthorityMatrix, AuthorityStatus

    rows = (await db.scalars(
        select(AuthorityMatrix).where(
            AuthorityMatrix.deleted.is_(False),
            AuthorityMatrix.category == category,
            AuthorityMatrix.status == AuthorityStatus.active,
        )
    )).all()
    today = date.today()
    return [
        MandateLine(
            reference=r.reference or "", role_title=r.role_title or "",
            approval_level=int(r.approval_level or 1),
            amount_from=float(r.amount_from or 0),
            amount_to=float(r.amount_to) if r.amount_to is not None else None,
            currency=r.currency or "",
        )
        for r in rows
        if r.effective_date is None or r.effective_date <= today
    ]


async def enforce_authority_limit(
    db: AsyncSession, *, category: str, amount: float | Decimal | None, user: Any,
    currency: str = "", activity: str = "this decision",
) -> None:
    """Raise 403 when the matrix has lines for ``category`` and none of the user's roles
    holds a mandate covering ``amount``. A no-op when the category is not in the matrix
    or there is no amount — see :func:`mandate_refusal`."""
    if amount is None:
        return
    refusal = mandate_refusal(
        await authority_lines(db, category), amount=float(amount),
        role_names=getattr(user, "role_names", None) or [], currency=currency, activity=activity,
    )
    if refusal:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)
