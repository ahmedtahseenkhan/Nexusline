"""Attestation API — periodic review sign-off on any record (polymorphic).

An attestation is a four-eyes act on a record, not a checkbox:

* The record must exist, be live, and be out of draft. A draft is still being written;
  certifying it certifies nothing.
* The attester must be independent of it: not its owner, and — where dual control
  applies to ``(<entity_type>, attest)`` — not the person who entered it (resolved from
  the audit trail by :mod:`app.services.dual_control`).
* The signer certifies a stated sentence ("I confirm this risk assessment is current and
  complete") over an optional scope, and a second person may confirm it.

Records that carry their own review cycle (risk, policy, vendor, asset —
:data:`REVIEW_CLOCK_ENTITY_TYPES`) keep exactly one clock: the attestation takes its
cadence from the record's ``review_frequency`` and writes the record's
``last_review_date`` / ``next_review_date``, and the alert scanner and My Work watch that
date instead of raising a separate attestation reminder.

Every response also says whether the *current user* may attest the record now
(``can_attest``) and, when not, why (``blocked_reason``) — decided here, in the same
order and with the same rules the attest call enforces, so the panel never guesses.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.attestation import Attestation
from app.models.identity import User
from app.schemas.attestation import AttestationCreate, AttestationRead, AttestationStatus
from app.services import audit, dual_control, entity_types
from app.services.notifications import NATIVE_REVIEW_ENTITY_TYPES
# Resolving a type to its class is shared with archive/restore, impact and the record
# lifecycle, so it lives in one service (re-exported here for existing callers).
from app.services.record_registry import model_for  # noqa: F401
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/attestations", tags=["attestations"])

#: Entity types whose attestation *is* the record's review: it takes the record's
#: ``review_frequency`` and moves its ``last_review_date`` / ``next_review_date``
#: (``native_review`` in the response). Exactly the types with their own overdue-review
#: sweep (``notifications.NATIVE_REVIEW_ENTITY_TYPES``; the asset joined in record-page
#: spec B4), so the panel, the alert and My Work all read the same date.
REVIEW_CLOCK_ENTITY_TYPES: frozenset[str] = NATIVE_REVIEW_ENTITY_TYPES


# ------------------------------------------------------------ statements ---
#: What an attester certifies, per entity type. The panel pre-fills it; the signer may
#: reword it, and whatever they submit is stored verbatim on the attestation.
DEFAULT_STATEMENTS: dict[str, str] = {
    "risk": "I confirm this risk assessment is current and complete.",
    "control": "I confirm this control is designed and operating as described.",
    "policy": "I confirm this policy is current and has been reviewed.",
    "vendor": "I confirm this third party's profile, risk rating and contracts are current.",
    "asset": "I confirm this asset's details, owner and classification are current.",
    "framework": "I confirm this framework's applicability and status are current.",
    "requirement": "I confirm this requirement's status and supporting controls are current.",
    "continuity_plan": "I confirm this continuity plan is current and has been reviewed.",
    "key_risk_indicator": "I confirm this indicator's definition, thresholds and latest value are current.",
    "outsourcing_arrangement": "I confirm this outsourcing arrangement is current and has been reviewed.",
}


def default_statement(entity_type: str) -> str:
    if entity_type in DEFAULT_STATEMENTS:
        return DEFAULT_STATEMENTS[entity_type]
    found = entity_types.ENTITY_TYPES.get(entity_type)
    label = found.label.lower() if found else "record"
    return f"I confirm this {label} is current and complete."


def owner_user_id(record: Any) -> uuid.UUID | None:
    """The record's owning *user*, when it has one as a foreign key.

    Only a column that names an owner and points at ``users`` counts: ``Asset.owner_id``
    is a business unit, and most registers still hold the owner as free text (F-08),
    which can't be compared safely.
    """
    from sqlalchemy import inspect as sa_inspect

    try:
        mapper = sa_inspect(type(record))
    except Exception:  # noqa: BLE001 - not a mapped object
        return None
    for col in mapper.columns:
        if "owner" not in col.key:
            continue
        if any(fk.column.table.name == "users" for fk in col.foreign_keys):
            value = getattr(record, col.key, None)
            if value is not None:
                return value
    return None


# ------------------------------------------------------ the decision rule ---
OWNER_REFUSAL = "You own this record, so someone independent must attest it."
DRAFT_REFUSAL = "A draft record can't be attested. Submit it for review first."
SELF_CONFIRM_REFUSAL = "You signed this attestation, so someone else must confirm it."
#: ``blocked_reason`` when the user lacks the module's write permission (the attest call
#: itself answers with the bare permission code).
PERMISSION_REFUSAL = "You don't have permission to attest {label} records."


def lifecycle_state(record: Any) -> Any:
    """The state that says whether a record is still a draft.

    A record's own business ``status`` (a risk's Draft → Assessed …, a policy's Draft →
    Published) when it has one; the generic ``workflow_status`` only for records without
    one. Since phase 1 ``workflow_status`` does advance (Submit / Approve through
    ``services/record_workflow.py``), but records created before that were never
    submitted, so the business status stays the primary signal; the reviewer's case, a
    risk still in Draft, is caught by it.
    """
    business = getattr(record, "status", None)
    if business is not None:
        return business
    return getattr(record, "workflow_status", None)


def attest_refusal(
    *, attester_id: uuid.UUID | None, owner_id: uuid.UUID | None, workflow_status: Any
) -> tuple[int, str] | None:
    """Why this person may not attest this record, as ``(status code, message)``.

    Pure: the record's owner and workflow state are passed in. Maker-checker (the
    person who entered the record) needs the audit trail and is applied separately by
    ``dual_control.enforce_record_maker_checker``.
    """
    if owner_id is not None and attester_id is not None and owner_id == attester_id:
        return status.HTTP_403_FORBIDDEN, OWNER_REFUSAL
    if getattr(workflow_status, "value", workflow_status) == "draft":
        return status.HTTP_409_CONFLICT, DRAFT_REFUSAL
    return None


def confirm_refusal(
    *, confirmer_id: uuid.UUID, attester_id: uuid.UUID | None, already_confirmed: bool
) -> tuple[int, str] | None:
    """Why this person may not add the second signature."""
    if attester_id is not None and confirmer_id == attester_id:
        return status.HTTP_403_FORBIDDEN, SELF_CONFIRM_REFUSAL
    if already_confirmed:
        return status.HTTP_409_CONFLICT, "This attestation has already been confirmed."
    return None


def _raise(refusal: tuple[int, str] | None) -> None:
    if refusal is not None:
        raise HTTPException(status_code=refusal[0], detail=refusal[1])


def label_in_text(label: str) -> str:
    """A type label inside a sentence: "Risk" → "risk", "Third party" → "third party";
    a label that starts with an acronym keeps it ("DPIA", "SAR / STR", "RCSA assessment")."""
    first = label.split(" ", 1)[0]
    if len(first) > 1 and first.isupper():
        return label
    return label[:1].lower() + label[1:]


async def attest_eligibility(
    db, user: User, entity_type: str, entity_id: uuid.UUID, record: Any
) -> tuple[bool, str | None]:
    """``(can_attest, blocked_reason)`` for this user and record, without raising.

    The attest call's own gates, in its order: the module's write permission
    (``entity_types.require_write``), the record still existing, the owner and draft rule
    (:func:`attest_refusal` over :func:`lifecycle_state` — the business status first,
    exactly as ``attest()`` judges it), then four-eyes against whoever entered the record
    (``dual_control.record_maker_checker_refusal``). The first refusal wins and its text
    is the one the attest call would answer with, so the panel can print it beside a
    disabled button.
    """
    try:
        found = entity_types.require_write(user, entity_type)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise
        label = entity_types.spec(entity_type).label
        return False, PERMISSION_REFUSAL.format(label=label_in_text(label))
    if record is None:
        return False, f"{found.label} not found"
    refusal = attest_refusal(
        attester_id=user.id,
        owner_id=owner_user_id(record),
        workflow_status=lifecycle_state(record),
    )
    if refusal is not None:
        return False, refusal[1]
    text = await dual_control.record_maker_checker_refusal(
        db, module=entity_type, action="attest", entity_type=entity_type, entity_id=entity_id,
        checker_id=user.id, subject=found.label.lower(), record=record,
    )
    if text:
        return False, text
    return True, None


async def _load_record(db, user: User, entity_type: str, entity_id: uuid.UUID, *, required: bool):
    model = model_for(entity_type)
    record = await db.get(model, entity_id) if model is not None else None
    if record is not None and (
        getattr(record, "deleted", False)
        or getattr(record, "tenant_id", user.tenant_id) != user.tenant_id
    ):
        record = None
    if record is None and required:
        label = entity_types.spec(entity_type).label
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
    return record


# ---------------------------------------------------------------- reads ---
async def _history(db, entity_type: str, entity_id: uuid.UUID) -> list[Attestation]:
    return list(
        (
            await db.scalars(
                select(Attestation)
                .where(Attestation.entity_type == entity_type, Attestation.entity_id == entity_id)
                .order_by(Attestation.attested_at.desc(), Attestation.created_at.desc())
            )
        ).all()
    )


def _native(entity_type: str, record: Any) -> bool:
    return (
        entity_type in REVIEW_CLOCK_ENTITY_TYPES
        and record is not None
        and hasattr(record, "review_frequency")
        and hasattr(record, "next_review_date")
    )


async def _bundle(
    db, entity_type: str, entity_id: uuid.UUID, record: Any, user: User
) -> AttestationStatus:
    rows = await _history(db, entity_type, entity_id)
    native = _native(entity_type, record)

    confirmer_ids = {r.confirmed_by_id for r in rows if r.confirmed_by_id}
    emails: dict[uuid.UUID, str] = {}
    if confirmer_ids:
        for u in (await db.scalars(select(User).where(User.id.in_(confirmer_ids)))).all():
            emails[u.id] = u.email
    history = []
    for r in rows:
        item = AttestationRead.model_validate(r)
        item.confirmed_by_email = emails.get(r.confirmed_by_id) if r.confirmed_by_id else None
        history.append(item)

    # One clock: for a record with its own review cycle, the record's dates are the truth
    # (a review recorded on the record itself moves them too).
    next_due = record.next_review_date if native else (rows[0].next_due if rows else None)
    frequency = record.review_frequency if native else (rows[0].frequency if rows else None)
    if not rows:
        state = "never"
    elif next_due is not None and next_due < date.today():
        state = "overdue"
    else:
        state = "current"
    can_attest, blocked_reason = await attest_eligibility(db, user, entity_type, entity_id, record)
    return AttestationStatus(
        status=state,
        last_attested_at=rows[0].attested_at if rows else None,
        last_by=rows[0].attested_by_email if rows else None,
        next_due=next_due,
        frequency=frequency,
        history=history,
        native_review=native,
        default_statement=default_statement(entity_type),
        can_attest=can_attest,
        blocked_reason=blocked_reason,
    )


@router.get("/{entity_type}/{entity_id}", response_model=AttestationStatus)
async def get_status(
    entity_type: str, entity_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> AttestationStatus:
    entity_types.require_read(user, entity_type)
    # Reads never fail on a missing record: legacy history stays visible.
    record = await _load_record(db, user, entity_type, entity_id, required=False)
    return await _bundle(db, entity_type, entity_id, record, user)


# --------------------------------------------------------------- writes ---
# Declared before the generic ``POST /{entity_type}/{entity_id}`` so "/<id>/confirm" is
# not swallowed by it (Starlette matches routes in order, before validation).
@router.post("/{attestation_id}/confirm", response_model=AttestationStatus)
async def confirm(attestation_id: uuid.UUID, db: DbSession, user: CurrentUser) -> AttestationStatus:
    """Second signature: an independent person confirms an existing attestation."""
    row = await db.get(Attestation, attestation_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attestation not found")
    entity_types.require_write(user, row.entity_type)
    _raise(confirm_refusal(
        confirmer_id=user.id, attester_id=row.attested_by_id, already_confirmed=row.confirmed_by_id is not None,
    ))
    record = await _load_record(db, user, row.entity_type, row.entity_id, required=True)
    row.confirmed_by_id = user.id
    row.confirmed_at = date.today()
    await db.flush()
    await audit.record(
        db, actor=user, action="attest_confirm", entity_type=row.entity_type, entity_id=row.entity_id,
        summary=f"Confirmed the {row.attested_at} attestation by {row.attested_by_email or 'n/a'}",
        changes={"attestation_id": str(row.id)},
    )
    return await _bundle(db, row.entity_type, row.entity_id, record, user)


@router.post("/{entity_type}/{entity_id}", response_model=AttestationStatus, status_code=201)
async def attest(
    entity_type: str, entity_id: uuid.UUID, body: AttestationCreate, db: DbSession, user: CurrentUser
) -> AttestationStatus:
    # Signing off a record's review cycle is a governance act on that record: it needs
    # the owning module's write permission, not merely a session.
    found = entity_types.require_write(user, entity_type)
    record = await _load_record(db, user, entity_type, entity_id, required=True)
    _raise(attest_refusal(
        attester_id=user.id,
        owner_id=owner_user_id(record),
        workflow_status=lifecycle_state(record),
    ))
    # Four-eyes: whoever entered the record may not certify it (when dual control applies
    # to "<entity_type>/attest", which by default it does — fail-closed).
    await dual_control.enforce_record_maker_checker(
        db, module=entity_type, action="attest", entity_type=entity_type, entity_id=entity_id,
        checker_id=user.id, subject=found.label.lower(), record=record,
    )

    today = date.today()
    native = _native(entity_type, record)
    frequency = record.review_frequency if native else body.frequency
    next_due = next_review_date(frequency, today)
    statement = body.statement.strip() or default_statement(entity_type)
    row = Attestation(
        tenant_id=user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        attested_by_id=user.id,
        attested_by_email=user.email,
        attested_at=today,
        comment=body.comment,
        frequency=frequency,
        next_due=next_due,
        statement=statement,
        scope=body.scope.strip(),
    )
    db.add(row)
    changes: dict[str, Any] = {"statement": statement}
    if native:
        # One review clock: the attestation *is* the record's review.
        if hasattr(record, "last_review_date"):
            record.last_review_date = today
        record.next_review_date = next_due
        changes.update(last_review_date=str(today), next_review_date=str(next_due) if next_due else None)
    await db.flush()
    await audit.record(
        db, actor=user, action="attest", entity_type=entity_type, entity_id=entity_id,
        summary=f"Attested {entity_type} (next due {row.next_due})",
        changes=changes,
    )
    return await _bundle(db, entity_type, entity_id, record, user)
