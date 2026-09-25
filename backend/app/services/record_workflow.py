"""One lifecycle per record: the only code allowed to move ``workflow_status``.

Every register carries the eramba approval lifecycle ``workflow_status``. Until now it
was an ordinary form field — anyone who could edit a record could mark it "approved",
and nothing tied it to the approvals inbox. This module makes it a governed state:

Transition table (:data:`TRANSITIONS`)::

    draft ──submit──▶ in_review ──approve──▶ approved ──retire──▶ retired
      ▲                   │                     │
      └──────reject───────┘                     │
      └───────────────revise────────────────────┘

* ``reject`` needs a reason, as the approvals inbox already demands.
* ``revise`` (approved → draft) is the standard way to change an approved record
  materially: it goes back to draft, is edited, and is re-submitted for review. It needs
  the module's write permission, like ``submit``.
* ``retired`` is terminal. A retired record that is needed again is a new record — a
  resurrected one would carry an approval nobody gave for its new purpose.

Permissions (:func:`required_permissions`): ``submit``, ``retire`` and ``revise`` need
the module's write permission; ``approve`` / ``reject`` need the module's read
permission plus ``<module>:approve`` when the catalog defines one (``exception:approve``),
otherwise the generic ``workflow:approve``.

Four eyes: approve and reject pass :func:`dual_control.enforce_record_maker_checker`
for ``(<entity_type>, approve)`` — the person who entered the record cannot decide it —
and the same rule is applied to whoever submitted it for review. Approving a record that
carries an amount (loss event, outsourcing arrangement, exception) also needs the
approver's delegation-of-authority mandate (``services.authority_limits``), here and on
the approval that finishes a route (:func:`write_back`).

Routing: when a :class:`~app.models.workflow.WorkflowDefinition` is enabled for the
record type, ``submit`` starts that route (whose first stage raises the
:class:`~app.models.approval.ApprovalRequest`) and the record waits in ``in_review``.
Approve / reject then come back through the approvals inbox and
:func:`write_back`; deciding directly on the record is refused while a route is live.

The guard (:func:`_before_flush`): an ORM ``before_flush`` hook refuses any UPDATE that
*changes* ``workflow_status`` outside :func:`apply`, :func:`write_back` or an explicit
:func:`system_write` block, with a 409 "Use Submit / Approve / Retire…". Chosen over
silently reverting because a reverted value would report success for a change that
did not happen. INSERTs are never restricted — seeding, CSV imports from legacy tools
and pack installs legitimately create records in any state — and echoing the current
value back (as a PATCH that returns the whole form does) is not a change, so it passes.
Sessions run with ``autoflush=False``: a handler that never flushes explicitly meets the
guard at commit, where the change is still refused (the transaction rolls back) but the
error may reach the client as a 500 rather than the 409.
"""
from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Iterable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import event, inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.permissions import PERMISSION_CATALOG
from app.services import record_registry

logger = logging.getLogger("nexusline.record_workflow")

__all__ = [
    "ACTIONS",
    "approval_complete",
    "attest_work_note",
    "LOCKED_DETAIL",
    "TRANSITIONS",
    "WorkflowStateLocked",
    "actions_for_user",
    "allowed_actions",
    "apply",
    "guard_violation",
    "history",
    "next_state",
    "required_permissions",
    "system_write",
    "write_back",
]

# --------------------------------------------------------------- the table ---
DRAFT, IN_REVIEW, APPROVED, RETIRED = "draft", "in_review", "approved", "retired"

#: state -> {action: next state}. The whole lifecycle; nothing else moves the state.
TRANSITIONS: dict[str, dict[str, str]] = {
    DRAFT: {"submit": IN_REVIEW},
    IN_REVIEW: {"approve": APPROVED, "reject": DRAFT},
    APPROVED: {"retire": RETIRED, "revise": DRAFT},
    RETIRED: {},
}

#: Every action, in the order buttons are shown.
ACTIONS: tuple[str, ...] = ("submit", "approve", "reject", "revise", "retire")

#: Actions that must carry a written reason.
REASON_REQUIRED: frozenset[str] = frozenset({"reject"})

#: Decisions — the four-eyes actions, and the ones a live route takes over.
DECISIONS: frozenset[str] = frozenset({"approve", "reject"})

#: Past tense for audit summaries and toasts.
PAST_TENSE: dict[str, str] = {
    "submit": "Submitted for review",
    "approve": "Approved",
    "reject": "Returned to draft",
    "revise": "Reopened for revision",
    "retire": "Retired",
    # Not a button: recorded when an approval route is cancelled mid-review.
    "withdraw": "Withdrawn from review",
}

LOCKED_DETAIL = "Use Submit / Approve / Retire to change the workflow state."

#: Audit ``action`` prefix for lifecycle entries; the history is read back by it.
AUDIT_PREFIX = "workflow_"


def state_value(state: Any) -> str:
    """``WorkflowState.draft`` / ``WorkflowStatus.draft`` / ``"draft"`` → ``"draft"``."""
    return str(getattr(state, "value", state) or DRAFT)


def approval_complete(state: Any) -> bool:
    """Decision 6: whether a record's approval is complete, so it may be attested. Pure.

    ``None`` means the record type has no approval lifecycle, which never blocks."""
    if state is None:
        return True
    return state_value(state) == APPROVED


def attest_work_note(state: Any) -> str | None:
    """What a review / attestation reminder says instead of "attest it" while the
    record's approval is incomplete (decision 6), or None when attesting is open. Pure.
    A retired record owes no attestation at all: callers skip it."""
    if approval_complete(state):
        return None
    value = state_value(state)
    if value == DRAFT:
        return "Submit it for approval: it can't be attested until approved"
    if value == IN_REVIEW:
        return "Awaiting approval: it can't be attested until approved"
    return None


def allowed_actions(state: Any) -> list[str]:
    """Actions the table allows from ``state``, in display order. Pure."""
    options = TRANSITIONS.get(state_value(state), {})
    return [a for a in ACTIONS if a in options]


def next_state(state: Any, action: str) -> str | None:
    """The state ``action`` leads to from ``state``, or None if it isn't allowed. Pure."""
    return TRANSITIONS.get(state_value(state), {}).get(action)


def _module_of(perm: str) -> str:
    return perm.split(":", 1)[0]


def required_permissions(
    entity_type: str, action: str, catalog: Iterable[str] | None = None
) -> tuple[str, ...]:
    """Permission codes the user must hold for ``action`` on this record type. Pure.

    ``catalog`` defaults to :data:`PERMISSION_CATALOG`; the module's own approve
    permission wins when it exists, else the generic ``workflow:approve``.
    """
    from app.services.entity_types import spec as entity_spec

    found = entity_spec(entity_type)
    known = set(catalog if catalog is not None else PERMISSION_CATALOG)
    if action in DECISIONS:
        module_approve = f"{_module_of(found.write_perm)}:approve"
        return (found.read_perm, module_approve if module_approve in known else "workflow:approve")
    if action in ("submit", "retire", "revise"):
        return (found.write_perm,)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unknown workflow action '{action}'. Use one of: {', '.join(ACTIONS)}.",
    )


def actions_for_user(
    state: Any, entity_type: str, permission_codes: Iterable[str], *, routing: bool = False
) -> list[str]:
    """The actions this user could take now — the table filtered by permission. Pure.

    While a route is live the decisions belong to the approvals inbox, so approve and
    reject are not offered on the record.
    """
    held = set(permission_codes)
    out = []
    for action in allowed_actions(state):
        if routing and action in DECISIONS:
            continue
        if set(required_permissions(entity_type, action)).issubset(held):
            out.append(action)
    return out


# ---------------------------------------------------------------- the guard ---
_WRITE_ALLOWED: ContextVar[bool] = ContextVar("record_workflow_write_allowed", default=False)


@contextlib.contextmanager
def system_write() -> Iterator[None]:
    """Allow ``workflow_status`` UPDATEs inside this block (flush inside it, too).

    For the platform's own transitions — :func:`apply`, :func:`write_back`, a CSV import
    that sets the imported state on a record it has just created — never for a form.
    """
    token = _WRITE_ALLOWED.set(True)
    try:
        yield
    finally:
        _WRITE_ALLOWED.reset(token)


class WorkflowStateLocked(HTTPException):
    """Raised from the flush when an edit tries to move ``workflow_status``.

    An ``HTTPException`` so FastAPI answers 409 with the message, wherever the flush
    happened, without a handler of its own."""

    def __init__(self, detail: str = LOCKED_DETAIL) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def guard_violation(old_values: Iterable[Any], new_values: Iterable[Any], allowed: bool) -> bool:
    """Whether an attribute history is a forbidden ``workflow_status`` change. Pure.

    ``old_values`` / ``new_values`` are the history's ``deleted`` / ``added`` lists. No
    old value means the row is new (or the value was never loaded): not a change we can
    or should refuse. The same value written back is not a change either.
    """
    if allowed:
        return False
    old = [state_value(v) for v in old_values if v is not None]
    new = [state_value(v) for v in new_values if v is not None]
    if not old or not new:
        return False
    return old[0] != new[-1]


def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    if _WRITE_ALLOWED.get():
        return
    for obj in list(session.dirty):
        try:
            state = sa_inspect(obj)
        except Exception:  # noqa: BLE001 - not a mapped instance
            continue
        if "workflow_status" not in state.mapper.column_attrs:
            continue
        hist = state.attrs.workflow_status.history
        if not hist.has_changes():
            continue
        if guard_violation(hist.deleted, hist.added, allowed=False):
            logger.warning(
                "Refused a workflow_status change on %s %s outside the lifecycle service",
                type(obj).__name__, getattr(obj, "id", "?"),
            )
            raise WorkflowStateLocked()


def install_guard() -> None:
    """Register the flush hook once (idempotent — safe on re-import)."""
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)


install_guard()


# ----------------------------------------------------------- state writes ---
def _coerce(record: Any, value: str) -> Any:
    """``value`` as the enum the record's column uses (assets use their own enum)."""
    column = type(record).__table__.c.workflow_status
    enum_class = getattr(column.type, "enum_class", None)
    return enum_class(value) if enum_class is not None else value


def synced_business_status(table: str, current: Any, workflow_state: str) -> str | None:
    """The business status a record should take when its lifecycle moves, or None. Pure.

    Two registers carry a business status that records the same decision as the
    lifecycle:

    * **Policies** (draft → under review → approved → published). A published policy
      stays published while a revision is drafted — the current version is still
      binding — until it is retired.
    * **Exceptions** (pending → approved). Approving an exception through its lifecycle
      (or its approval route) is the approval decision, so the exception is approved;
      reopening an approved one for revision puts it back to pending, since its new
      terms have not been approved. A rejected or closed exception is left alone.
    """
    if table not in ("exceptions", "policies"):
        # The specialist registers whose sign-off is this lifecycle (DPIAs, Shariah
        # rulings and products, the model inventory, FAIR quantifications).
        from app.services.lifecycle_gates import synced_status

        return synced_status(table, current, workflow_state)
    now = getattr(current, "value", current)
    if table == "exceptions":
        if workflow_state == "approved" and now == "pending":
            return "approved"
        if workflow_state == "draft" and now == "approved":
            return "pending"
        return None
    if table != "policies":
        return None
    if workflow_state == "retired":
        return "retired" if now != "retired" else None
    if now == "published":
        return None
    target = {"in_review": "under_review", "approved": "approved", "draft": "draft"}.get(workflow_state)
    return target if target and target != now else None


async def _set_state(db: AsyncSession, record: Any, value: str, *, decided_by: uuid.UUID | None = None) -> None:
    """Move the lifecycle state as the platform, with the business status that follows
    it (:func:`synced_business_status`). ``decided_by`` is the approver an exception's
    approval is recorded against."""
    with system_write():
        record.workflow_status = _coerce(record, value)
        business = synced_business_status(
            type(record).__tablename__, getattr(record, "status", None), value
        )
        if business is not None:
            column = type(record).__table__.c.status
            enum_class = getattr(column.type, "enum_class", None)
            record.status = enum_class(business) if enum_class is not None else business
            if type(record).__tablename__ == "exceptions":
                # The decision fields /exceptions/{id}/decision sets, kept in step.
                from datetime import date

                approved = business == "approved"
                record.approver_id = decided_by if approved else None
                record.decided_at = date.today() if approved else None
        await db.flush()


async def carry_state(db: AsyncSession, record: Any, value: str) -> None:
    """Set a state an import carried over from the source system onto a record it has
    just created — with the business status that follows it, as a decision here would
    (``services.import_registry``). Nobody here decided it, so no approver is named."""
    await _set_state(db, record, value)


async def last_submitter(db: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> uuid.UUID | None:
    """Who most recently submitted this record for review, from the audit trail."""
    from app.models.audit import AuditLog

    return await db.scalar(
        select(AuditLog.actor_id)
        .where(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
            AuditLog.action == f"{AUDIT_PREFIX}submit",
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )


async def _owner_email(db: AsyncSession, record: Any) -> str:
    owner_id = getattr(record, "workflow_owner_id", None)
    if owner_id is None:
        return ""
    from app.models.identity import User

    user = await db.get(User, owner_id)
    return user.email if user is not None else ""


def _summary(action: str, entity_type: str, record: Any, reason: str) -> str:
    label = record_registry.type_label(entity_type, type(record)).lower()
    text = f"{PAST_TENSE.get(action, action)}: {label} {record_registry.label_of(record)}"
    if reason:
        text += f" — {reason}"
    return text[:500]


@dataclass
class TransitionResult:
    state: str
    previous: str
    action: str
    routed: bool = False
    instance_id: uuid.UUID | None = None


async def apply(
    db: AsyncSession,
    user: Any,
    record: Any,
    entity_type: str,
    action: str,
    reason: str | None = None,
) -> TransitionResult:
    """Take ``action`` on ``record`` as ``user``: check, move, audit.

    Raises 422 for an unknown action or a missing reason, 409 when the action is not
    allowed from the current state (or a route owns the decision), 403 for a missing
    permission or a four-eyes refusal.
    """
    from app.services import audit, dual_control, workflow_engine

    reason = (reason or "").strip()
    needed = required_permissions(entity_type, action)  # 422 on an unknown action
    current = state_value(record.workflow_status)
    target = next_state(current, action)
    label = record_registry.type_label(entity_type, type(record))
    if target is None:
        options = allowed_actions(current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This {label.lower()} is {current.replace('_', ' ')}, so it can't be "
                f"{PAST_TENSE.get(action, action).lower()}. "
                + (f"Available: {', '.join(options)}." if options else "It is final.")
            ),
        )
    missing = [p for p in needed if p not in set(user.permission_codes)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires permission(s): {', '.join(missing)}",
        )
    if action in REASON_REQUIRED and not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A reason is required to send a record back to draft.",
        )
    if entity_type == "risk" and current == DRAFT:
        # F-21: a risk goes to its approvers — and so towards the board figures — only
        # with someone accountable for it and the business unit it sits in.
        from app.services.risk_integrity import draft_exit_refusal

        refusal = draft_exit_refusal(
            has_owner=getattr(record, "owner_id", None) is not None,
            has_business_unit=bool(getattr(record, "business_units", None)),
        )
        if refusal:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=refusal)

    if action in DECISIONS:
        instance = await workflow_engine.instance_for(db, entity_type, record.id)
        if instance is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This record is going through its approval route; each stage is "
                    "decided from the Approvals inbox."
                ),
            )
        subject = label.lower()
        await dual_control.enforce_record_maker_checker(
            db, module=entity_type, action="approve", entity_type=entity_type,
            entity_id=record.id, checker_id=user.id, subject=subject, record=record,
        )
        await dual_control.enforce_maker_checker(
            db, module=entity_type, action="approve",
            maker_id=await last_submitter(db, entity_type, record.id),
            checker_id=user.id, subject=subject,
        )
        if action == "approve":
            # What the record needs before its sign-off (a current simulation, a passed
            # validation…), then the delegation of authority, where the record carries an
            # amount (a loss event's gross loss, an outsourcing contract's value, an
            # exception's exposure).
            from app.services import authority_limits, lifecycle_gates

            lifecycle_gates.enforce_approval_precondition(entity_type, record)
            await authority_limits.enforce(db, entity_type, record, user)

    if action == "submit":
        from app.services import lifecycle_gates

        # Nothing goes to an approver that could not be approved as it stands.
        lifecycle_gates.enforce_approval_precondition(entity_type, record)
        # Submitting is the maker's step: a rule's maker role, where one is named.
        await dual_control.enforce_maker_role(db, module=entity_type, action="approve", maker_id=user.id)

    result = TransitionResult(state=target, previous=current, action=action)
    if action == "submit":
        instance = await workflow_engine.start(
            db,
            tenant_id=user.tenant_id,
            entity_type=entity_type,
            entity_id=record.id,
            entity_label=record_registry.label_of(record)[:255],
            link=record_registry.link_for(record),
            requested_by=user.id,
            requested_by_email=user.email,
            record_owner_email=await _owner_email(db, record),
        )
        if instance is not None:
            result.routed = True
            result.instance_id = instance.id

    await _set_state(db, record, target, decided_by=user.id if action == "approve" else None)
    changes: dict[str, Any] = {"from": current, "to": target}
    if reason:
        changes["reason"] = reason
    if result.instance_id is not None:
        changes["route"] = str(result.instance_id)
    await audit.record(
        db, actor=user, action=f"{AUDIT_PREFIX}{action}", entity_type=entity_type,
        entity_id=record.id, summary=_summary(action, entity_type, record, reason),
        changes=changes,
    )
    return result


def write_back_target(current: Any, approved: bool) -> str | None:
    """The state an approval decision moves a record to, or None to leave it. Pure.

    Approval promotes a draft or in-review record to approved; rejection returns an
    in-review record to draft. Anything else is left alone — rejecting an ad-hoc
    request raised against an already-approved record does not un-approve it, and a
    retired record is never revived.
    """
    value = state_value(current)
    if approved:
        return APPROVED if value in (DRAFT, IN_REVIEW) else None
    return DRAFT if value == IN_REVIEW else None


def _decide_audit_plan(plan: Any, approved: bool) -> tuple[str, str] | None:
    """Board / audit-committee sign-off of an annual audit plan, from the approvals inbox.

    The plan has no ``workflow_status``: its own ``status`` (draft → submitted →
    approved) *is* the sign-off lifecycle, so the decision lands there, and approval is
    dated because "approved by the audit committee on …" is what the plan must show.
    """
    from datetime import date

    from app.models.audit_plan import plan_decision_target

    current = plan.status
    target = plan_decision_target(current, approved)
    if target is None:
        return None
    plan.status = target
    plan.approved_on = date.today() if approved else None
    return current.value, target.value


#: Records whose sign-off moves a business ``status`` instead of ``workflow_status``,
#: by table: ``(record, approved) -> (from, to)``, or None when the decision moves nothing.
_STATUS_DECISIONS: dict[str, Any] = {
    "audit_plans": _decide_audit_plan,
}


async def write_back(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID | None,
    approved: bool,
    via: str,
    comment: str = "",
    actor: Any = None,
    tenant_id: uuid.UUID | None = None,
    action: str | None = None,
) -> str | None:
    """Apply an approvals-inbox decision to the record it was about.

    Called by ``approvals.decide_approval`` for a single-stage request and by
    ``workflow_engine.on_approval_decided`` when a route finishes. Returns the new state,
    or None when nothing changed (no record, no lifecycle, or not a state the decision
    moves). A record whose sign-off is its own business ``status`` rather than
    ``workflow_status`` (the annual audit plan) is moved by its :data:`_STATUS_DECISIONS`
    entry instead. Audited as the deciding user, or as the platform when there is none.
    ``action`` overrides the audit verb (``withdraw`` when a route is cancelled).
    """
    from app.services import audit

    if not entity_type or entity_id is None:
        return None
    model = record_registry.model_for(entity_type)
    if model is None:
        return None
    if not record_registry.has_workflow(model):
        decide = _STATUS_DECISIONS.get(getattr(model, "__tablename__", ""))
        if decide is None:
            return None
        record = await db.get(model, entity_id)
        if record is None or getattr(record, "deleted", False):
            return None
        moved = decide(record, approved)
        if moved is None:
            return None
        current, target = moved
        await db.flush()
    else:
        record = await db.get(model, entity_id)
        if record is None or getattr(record, "deleted", False):
            return None
        current = state_value(record.workflow_status)
        target = write_back_target(current, approved)
        if target is None:
            return None
        if target == APPROVED:
            from app.services import lifecycle_gates

            lifecycle_gates.enforce_approval_precondition(entity_type, record)
        if target == APPROVED and actor is not None:
            # The approval that finishes the route or request is the one the delegation
            # of authority governs: its decider needs the mandate (earlier stages don't).
            from app.services import authority_limits

            await authority_limits.enforce(db, entity_type, record, actor)
        await _set_state(db, record, target, decided_by=getattr(actor, "id", None) if approved else None)

    action = action or ("approve" if approved else "reject")
    reason = (comment or "").strip()
    summary = _summary(action, entity_type, record, reason)
    summary = f"{summary} (via {via})"[:500]
    changes: dict[str, Any] = {"from": current, "to": target, "via": via}
    if reason:
        changes["reason"] = reason
    if actor is not None:
        await audit.record(
            db, actor=actor, action=f"{AUDIT_PREFIX}{action}", entity_type=entity_type,
            entity_id=entity_id, summary=summary, changes=changes,
        )
    else:
        await audit.record_system(
            db, tenant_id=tenant_id or record.tenant_id, action=f"{AUDIT_PREFIX}{action}",
            entity_type=entity_type, entity_id=entity_id, summary=summary, changes=changes,
        )
    return target


async def set_owner(
    db: AsyncSession, user: Any, record: Any, entity_type: str, owner_id: uuid.UUID | None
) -> None:
    """Name (or clear) the record's approval owner — a user, validated and audited."""
    from app.services import audit, master_data

    await master_data.check_user(db, owner_id, field="workflow_owner_id")
    previous = getattr(record, "workflow_owner_id", None)
    if previous == owner_id:
        return
    record.workflow_owner_id = owner_id
    await db.flush()
    await audit.record(
        db, actor=user, action=f"{AUDIT_PREFIX}owner", entity_type=entity_type,
        entity_id=record.id,
        summary=(
            f"Changed the approval owner of {record_registry.label_of(record)}"[:500]
        ),
        changes={
            "owner_from": str(previous) if previous else None,
            "owner_to": str(owner_id) if owner_id else None,
        },
    )


async def history(db: AsyncSession, entity_type: str, entity_id: uuid.UUID, limit: int = 50) -> list[dict]:
    """Who moved the record, when, how and why — newest first, from the audit trail."""
    from app.models.audit import AuditLog

    rows = (
        await db.scalars(
            select(AuditLog)
            .where(
                AuditLog.entity_type == entity_type,
                AuditLog.entity_id == entity_id,
                AuditLog.action.like(f"{AUDIT_PREFIX}%"),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).all()
    out = []
    for row in rows:
        changes = row.changes or {}
        out.append(
            {
                "action": row.action[len(AUDIT_PREFIX):],
                "actor_id": row.actor_id,
                "actor_email": row.actor_email,
                "at": row.created_at,
                "from_state": changes.get("from"),
                "to_state": changes.get("to"),
                "reason": changes.get("reason") or "",
                "owner_to": changes.get("owner_to"),
                "via": changes.get("via") or "",
                "summary": row.summary,
            }
        )
    return out
