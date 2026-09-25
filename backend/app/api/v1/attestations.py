"""Attestation API — periodic review sign-off on any record (polymorphic).

An attestation is the record **owner's own certification** (decision 9, 2026-09-20), the
way a control owner certifies design and operation under SOX 302/404, ISO 27001 A.5.36
and a ServiceNow/Archer attestation campaign. It is not a checkbox:

* The record must exist and be live.
* Its approval must be complete (decision 6, 2026-09-17): for a type registered for
  approval (it carries ``workflow_status``), only an ``approved`` record may be attested
  — draft and in review are refused with "Approve this <type> before attesting it", and
  retired is final. **The approval state is the gate** for these types (fixed
  2026-09-25): a risk's business status stays "Draft" until it is assessed, which is not
  an approval stage, so reading it as one refused approved risks with "Submit it for
  review first" — an instruction the user had already carried out.
* Types without an approval workflow must be out of their own draft status: a draft is
  still being written, and certifying it certifies nothing.
* A risk must carry a real assessment (:func:`risk_scoring.is_scored`): the statement
  certifies "this risk assessment is current and complete", which a risk still on the
  1×1 placeholder score can't be, whoever approved it.
* The signer needs the owning module's **write permission** (``entity_types.require_write``).
  The owner is the expected signer; anyone else with that permission may sign, and the
  attestation then records whose certification it stands in for ("attested by X on
  behalf of Y" — :func:`on_behalf_of`).
* The signer certifies a stated sentence ("I confirm this risk assessment is current and
  complete") over an optional scope.
* Independence comes from the approval above and from the **second signature**
  (:func:`confirm`), which the person who signed can never give. On a high-stakes record
  — a key control, a critical or high residual risk, a material outsourcing arrangement
  or third party, any policy (:func:`second_signature_required`) — it is required: until
  it is given the attestation is signed but **not complete**, and the review clock has
  not reset.
* Maker-checker on ``(<entity_type>, attest)`` is no longer fail-closed on the global
  segregation-of-duties switch, because in a bank the first-line owner usually also
  entered the record and decision 6 already stops a self-written record being certified
  unapproved. It applies only where an administrator explicitly configured a rule
  (:func:`attest_dual_control_rule`), which then still refuses whoever entered the record.

Records that carry their own review cycle (risk, policy, vendor, asset —
:data:`REVIEW_CLOCK_ENTITY_TYPES`) keep exactly one clock: the attestation takes its
cadence from the record's ``review_frequency`` and writes the record's
``last_review_date`` / ``next_review_date``, and the alert scanner and My Work watch that
date instead of raising a separate attestation reminder. The clock moves when the
attestation becomes **complete** — on signing when no second signature is needed, on the
confirmation when one is — and it is anchored to the date it was signed, not the date it
was confirmed: the certification speaks as of the day the owner made it.

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
from app.services import modules as module_service
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
#: For types without an approval workflow, judged on their own business status.
DRAFT_REFUSAL = "A draft record can't be attested. Complete it and move it out of Draft first."
UNSCORED_REFUSAL = (
    "This risk hasn't been scored yet, so there is no assessment to certify. "
    "Score its likelihood and impact first."
)
#: Decision 6 (2026-09-17): a record whose approval is not complete can't be attested.
APPROVAL_REFUSAL = "Approve this {label} before attesting it — its approval is {state}."
RETIRED_REFUSAL = "This {label} is retired, so it can't be attested."
SELF_CONFIRM_REFUSAL = "You signed this attestation, so someone else must confirm it."
#: ``blocked_reason`` when the user lacks the module's write permission (the attest call
#: itself answers with the bare permission code).
PERMISSION_REFUSAL = "You don't have permission to attest {label} records."


def lifecycle_state(record: Any) -> Any:
    """The state that says whether a record is still a draft.

    A record's own business ``status`` (a policy's Draft → Published …) when it has one;
    the generic ``workflow_status`` only for records without one. :func:`attest_refusal`
    reads it only for types without an approval workflow — for the others the approval
    state (:func:`approval_state`) is the gate.
    """
    business = getattr(record, "status", None)
    if business is not None:
        return business
    return getattr(record, "workflow_status", None)


def approval_state(record: Any) -> str | None:
    """The record's approval state (``workflow_status``) when its type is registered for
    approval, else None.

    "Registered for approval" is the record lifecycle's own test
    (:func:`record_registry.has_workflow` — the table carries ``workflow_status``), so the
    attestation gate and Submit / Approve agree on which records have an approval to
    complete. Unmapped stand-ins (tests, plain objects) have none.
    """
    from app.services.record_registry import has_workflow

    if record is None or not has_workflow(type(record)):
        return None
    value = getattr(record, "workflow_status", None)
    if value is None:
        return None
    return str(getattr(value, "value", value))


def approval_refusal(state: str | None, label: str = "record") -> tuple[int, str] | None:
    """Decision 6: only a record whose approval is complete may be attested. Pure.

    ``state`` is :func:`approval_state` (None = the type has no approval workflow, which
    keeps the pre-decision behaviour). ``approved`` passes; ``retired`` is final and
    refused on its own words; draft and in review (the only other states the lifecycle
    has — a rejection returns the record to draft) are asked to be approved first.
    """
    if state is None or state == "approved":
        return None
    if state == "retired":
        return status.HTTP_409_CONFLICT, RETIRED_REFUSAL.format(label=label)
    return status.HTTP_409_CONFLICT, APPROVAL_REFUSAL.format(label=label, state=state.replace("_", " "))


def attest_refusal(
    *,
    attester_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    workflow_status: Any,
    approval: str | None = None,
    label: str = "record",
    unscored: bool = False,
) -> tuple[int, str] | None:
    """Why this person may not attest this record, as ``(status code, message)``.

    Pure: the record's lifecycle state (:func:`lifecycle_state`), approval state
    (:func:`approval_state`) and, for a risk, whether it is still unscored are passed in.

    A type with an approval workflow (``approval`` is not None) is judged on its approval
    alone — decision 6: approved passes, anything else is told what approval is missing.
    A type without one is judged on its own draft status. Then a risk must be scored.

    Decision 9: owning the record is no longer a refusal — the owner *is* the expected
    signer, and independence comes from the approval and the second signature.
    ``attester_id`` / ``owner_id`` stay in the signature because callers pass them and
    because who signs decides whose certification it is (:func:`on_behalf_of`).
    Maker-checker, where an administrator configured it, needs the audit trail and is
    applied separately (:func:`attest_maker_checker_refusal`).
    """
    if approval is not None:
        refusal = approval_refusal(approval, label)
        if refusal is not None:
            return refusal
    elif getattr(workflow_status, "value", workflow_status) == "draft":
        return status.HTTP_409_CONFLICT, DRAFT_REFUSAL
    if unscored:
        return status.HTTP_409_CONFLICT, UNSCORED_REFUSAL
    return None


def risk_unscored(entity_type: str, record: Any) -> bool:
    """Whether this is a risk still on the placeholder score (never assessed). Pure."""
    if entity_type != "risk" or record is None:
        return False
    from app.services.risk_scoring import is_scored

    return not is_scored(getattr(record, "status", None), getattr(record, "last_assessed_at", None))


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


# ------------------------------------------------ decision 9: on behalf of ---
def on_behalf_of(attester_id: uuid.UUID | None, owner_id: uuid.UUID | None) -> uuid.UUID | None:
    """The owner an attestation stands in for, or None when the signer is the owner (or
    the record names none). Pure."""
    if owner_id is None or attester_id is None or owner_id == attester_id:
        return None
    return owner_id


async def owner_name(db, owner_id: uuid.UUID | None) -> str:
    """The owner's name for the attestation row, so the trail reads "on behalf of Ayesha
    Siddiqui" without a join. Falls back to their e-mail, then to nothing."""
    if owner_id is None:
        return ""
    person = await db.get(User, owner_id)
    if person is None:
        return ""
    return (getattr(person, "full_name", "") or "").strip() or (getattr(person, "email", "") or "")


def on_behalf_of_text(row: Any) -> str | None:
    """"attested by ayesha@bank.pk on behalf of Bilal Khan", or None when the signer was
    the owner. The one sentence the record page, the trail and exports all use. Pure."""
    owner = (getattr(row, "on_behalf_of_name", "") or "").strip()
    if not owner and getattr(row, "on_behalf_of_id", None) is None:
        return None
    signer = (getattr(row, "attested_by_email", "") or "").strip() or "another user"
    return f"attested by {signer} on behalf of {owner or 'the owner'}"


# -------------------------------- decision 9: the required second signature ---
#: Why a record's attestation needs an independent second signature, by entity type.
#: These are the records a bank examiner reads first, so one person's word is not enough:
#: SOX 404 key controls, the risks above appetite, SBP material outsourcing, and policy.
KEY_CONTROL_REASON = "Key control"
HIGH_RISK_REASON = "Critical or high residual risk"
MATERIAL_OUTSOURCING_REASON = "Material outsourcing"
POLICY_REASON = "Policy"
#: Residual ratings that need the second signature.
HIGH_STAKES_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})


def material_outsourcing(record: Any) -> bool:
    """Whether this record is (or carries) a live *material* outsourcing arrangement —
    an arrangement itself, or a third party with one. Pure: ``Vendor`` loads its
    arrangements eagerly, so this never issues a query."""
    from app.models.outsourcing import LIVE_STATUSES, OutsourcingMateriality

    def is_material(arrangement: Any) -> bool:
        materiality = getattr(arrangement, "materiality", None)
        if str(getattr(materiality, "value", materiality)) != OutsourcingMateriality.material.value:
            return False
        if getattr(arrangement, "deleted", False):
            return False
        state = getattr(arrangement, "status", None)
        return any(str(getattr(state, "value", state)) == s.value for s in LIVE_STATUSES)

    if hasattr(record, "materiality"):
        return is_material(record)
    try:
        arrangements = list(getattr(record, "outsourcing_arrangements", None) or [])
    except Exception:  # noqa: BLE001 - an unloaded relationship on a detached record
        return False
    return any(is_material(a) for a in arrangements)


def high_stakes_reason(entity_type: str, record: Any, severity: Any = None) -> str | None:
    """Why this record's attestation needs a second signature, or None. Pure.

    ``severity`` is the risk's current residual band (:func:`risk_severity`); it is only
    read for a risk.
    """
    if record is None:
        return None
    if entity_type == "policy":
        return POLICY_REASON
    if entity_type == "control":
        return KEY_CONTROL_REASON if getattr(record, "is_key", False) else None
    if entity_type == "risk":
        band = str(getattr(severity, "value", severity) or "")
        return HIGH_RISK_REASON if band in HIGH_STAKES_SEVERITIES else None
    if entity_type in {"vendor", "outsourcing_arrangement"}:
        return MATERIAL_OUTSOURCING_REASON if material_outsourcing(record) else None
    return None


async def risk_severity(db, user: User, record: Any):
    """A risk's current band on the tenant's scale — residual when assessed, else
    inherent, and None for a risk nobody has scored."""
    from app.services.risk_scoring import current_severity
    from app.services.risk_settings import get_or_create_settings, scale_for

    settings = await get_or_create_settings(db, user.tenant_id)
    return current_severity(record, scale_for(settings))


async def second_signature_required(db, user: User, entity_type: str, record: Any) -> str | None:
    """Why an attestation of this record needs an independent second signature to count,
    or None when the signature is optional (as it is for every other record).

    One module-level helper so the read, the write and the tests all ask the same
    question; only a risk costs a query (its band comes from the tenant's scale).
    """
    if entity_type == "risk":
        return high_stakes_reason(entity_type, record, await risk_severity(db, user, record))
    return high_stakes_reason(entity_type, record)


# ------------------------------------- decision 9: maker-checker, if configured ---
async def attest_dual_control_rule(db, entity_type: str):
    """The maker-checker rule an administrator configured for attesting this record type,
    or None.

    Decision 9: attesting is the owner's own certification, so it is **not** fail-closed
    on the global segregation-of-duties switch the way a four-eyes *decision* is — in a
    bank the first-line owner usually also entered the record, and refusing them would
    leave nobody able to certify it. An organisation that explicitly configured
    ``(<type>, attest)`` dual control keeps it, and it still refuses whoever entered the
    record; a rule that is disabled, inactive or an explicit exemption does not apply.
    """
    from app.models.authority import DualControlStatus

    rule = await dual_control.find_rule(db, entity_type, "attest")
    if rule is None or not rule.enabled or rule.status != DualControlStatus.active:
        return None
    return rule if rule.requires_dual_control else None


async def attest_maker_checker_refusal(
    db, *, entity_type: str, entity_id: uuid.UUID, checker_id: uuid.UUID | None,
    subject: str, record: Any,
) -> str | None:
    """The four-eyes refusal for this attestation, or None — only where a rule is
    configured (:func:`attest_dual_control_rule`). Never raises."""
    if await attest_dual_control_rule(db, entity_type) is None:
        return None
    return await dual_control.record_maker_checker_refusal(
        db, module=entity_type, action="attest", entity_type=entity_type, entity_id=entity_id,
        checker_id=checker_id, subject=subject, record=record,
    )


async def attest_eligibility(
    db, user: User, entity_type: str, entity_id: uuid.UUID, record: Any
) -> tuple[bool, str | None]:
    """``(can_attest, blocked_reason)`` for this user and record, without raising.

    The attest call's own gates, in its order: the module's write permission
    (``entity_types.require_write``), the record still existing, :func:`attest_refusal`
    (the approval gate of decision 6 for types with an approval workflow, the draft rule
    for the others, then an unscored risk), then four-eyes against whoever
    entered the record where an administrator configured it
    (:func:`attest_maker_checker_refusal`). The first refusal wins and its text is the one
    the attest call would answer with, so the panel can print it beside a disabled button.
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
        approval=approval_state(record),
        label=label_in_text(found.label),
        unscored=risk_unscored(entity_type, record),
    )
    if refusal is not None:
        return False, refusal[1]
    text = await attest_maker_checker_refusal(
        db, entity_type=entity_type, entity_id=entity_id, checker_id=user.id,
        subject=found.label.lower(), record=record,
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


async def _native_frequency(db, user: User, entity_type: str, record: Any):
    """The cycle a record's own review clock runs on. A risk's is its *effective* cycle:
    the stricter of the frequency set and the longest its rating allows
    (``RiskSetting.review_cadence``, F-22) — the same one ``POST /risks/{id}/review`` uses."""
    if entity_type != "risk":
        return record.review_frequency
    from app.services.risk_scoring import effective_review_frequency
    from app.services.risk_settings import get_or_create_settings

    settings = await get_or_create_settings(db, user.tenant_id)
    severity = await risk_severity(db, user, record)
    return effective_review_frequency(record.review_frequency, severity, settings.review_cadence or {})[0]


def _native(entity_type: str, record: Any) -> bool:
    return (
        entity_type in REVIEW_CLOCK_ENTITY_TYPES
        and record is not None
        and hasattr(record, "review_frequency")
        and hasattr(record, "next_review_date")
    )


def is_complete(row: Any) -> bool:
    """Whether one attestation counts as a completed certification: signed, and confirmed
    where confirmation is required (decision 9). Pure — the same rule the model spells."""
    if not getattr(row, "confirmation_required", False):
        return True
    return getattr(row, "confirmed_by_id", None) is not None


def awaiting_second_signature(rows: list[Any]) -> Any | None:
    """The newest attestation that is signed but still owes its required second
    signature, or None. Pure; ``rows`` are newest first."""
    for row in rows:
        if getattr(row, "confirmation_required", False) and getattr(row, "confirmed_by_id", None) is None:
            return row
        if is_complete(row):
            return None  # a later, complete attestation has already superseded it
    return None


async def _bundle(
    db, entity_type: str, entity_id: uuid.UUID, record: Any, user: User
) -> AttestationStatus:
    rows = await _history(db, entity_type, entity_id)
    native = _native(entity_type, record)
    # Only a complete attestation counts: one still waiting for its second signature has
    # certified nothing yet, so it neither sets "last attested" nor moves the clock.
    done = [r for r in rows if is_complete(r)]
    pending = awaiting_second_signature(rows)

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
    # (a review recorded on the record itself moves them too), and they only move when
    # the attestation is complete.
    next_due = record.next_review_date if native else (done[0].next_due if done else None)
    frequency = await _native_frequency(db, user, entity_type, record) if native else (
        rows[0].frequency if rows else None
    )
    if not done:
        state = "never"
    elif next_due is not None and next_due < date.today():
        state = "overdue"
    else:
        state = "current"
    can_attest, blocked_reason = await attest_eligibility(db, user, entity_type, entity_id, record)
    reason = await second_signature_required(db, user, entity_type, record) if record is not None else None
    return AttestationStatus(
        status=state,
        last_attested_at=done[0].attested_at if done else None,
        last_by=done[0].attested_by_email if done else None,
        next_due=next_due,
        frequency=frequency,
        history=history,
        native_review=native,
        default_statement=default_statement(entity_type),
        can_attest=can_attest,
        blocked_reason=blocked_reason,
        confirmation_required=reason is not None,
        confirmation_reason=reason,
        awaiting_confirmation=pending is not None,
        awaiting_by=pending.attested_by_email if pending is not None else None,
        awaiting_at=pending.attested_at if pending is not None else None,
        last_on_behalf_of=(done[0].on_behalf_of_name or None) if done else None,
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
def move_review_clock(entity_type: str, record: Any, attested_at: date, next_due: date | None) -> dict:
    """Move a record's own review dates to a completed attestation, and say what changed.

    Only forwards: a confirmation arriving after a later attestation already moved the
    clock does not pull it back. ``{}`` when the record keeps no review cycle of its own.
    """
    if not _native(entity_type, record):
        return {}
    current = getattr(record, "next_review_date", None)
    if next_due is not None and current is not None and next_due < current:
        return {}
    if hasattr(record, "last_review_date"):
        record.last_review_date = attested_at
    record.next_review_date = next_due
    return {"last_review_date": str(attested_at), "next_review_date": str(next_due) if next_due else None}


@router.post("/{attestation_id}/confirm", response_model=AttestationStatus)
async def confirm(attestation_id: uuid.UUID, db: DbSession, user: CurrentUser) -> AttestationStatus:
    """Second signature: an independent person confirms an existing attestation.

    Where the signature was required (decision 9) this is the moment the attestation
    becomes complete, so it is also the moment the record's review clock moves — to the
    date the attestation was *signed*, not today: the certification speaks as of the day
    the owner made it, and the confirmation only attests that it holds.
    """
    row = await db.get(Attestation, attestation_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attestation not found")
    entity_types.require_write(user, row.entity_type)
    await module_service.require_entity_module(row.entity_type, user.tenant_id)
    _raise(confirm_refusal(
        confirmer_id=user.id, attester_id=row.attested_by_id, already_confirmed=row.confirmed_by_id is not None,
    ))
    record = await _load_record(db, user, row.entity_type, row.entity_id, required=True)
    completes = bool(row.confirmation_required)
    row.confirmed_by_id = user.id
    row.confirmed_at = date.today()
    changes: dict[str, Any] = {"attestation_id": str(row.id)}
    if completes:
        changes.update(move_review_clock(row.entity_type, record, row.attested_at, row.next_due))
    await db.flush()
    await audit.record(
        db, actor=user, action="attest_confirm", entity_type=row.entity_type, entity_id=row.entity_id,
        summary=f"Confirmed the {row.attested_at} attestation by {row.attested_by_email or 'n/a'}",
        changes=changes,
    )
    return await _bundle(db, row.entity_type, row.entity_id, record, user)


async def enforce_attestable(
    db, user: User, entity_type: str, entity_id: uuid.UUID, record: Any, found: Any
) -> None:
    """Raise the attest call's refusals, in :func:`attest_eligibility`'s order (after the
    permission check the caller has already made): approval (decision 6) or, for a type
    without one, draft; an unscored risk; then four-eyes against whoever entered the
    record where a rule is configured."""
    _raise(attest_refusal(
        attester_id=user.id,
        owner_id=owner_user_id(record),
        workflow_status=lifecycle_state(record),
        approval=approval_state(record),
        label=label_in_text(found.label),
        unscored=risk_unscored(entity_type, record),
    ))
    # Four-eyes: whoever entered the record may not certify it — only where an
    # administrator configured "<entity_type>/attest" dual control (decision 9).
    text = await attest_maker_checker_refusal(
        db, entity_type=entity_type, entity_id=entity_id, checker_id=user.id,
        subject=found.label.lower(), record=record,
    )
    if text:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=text)


async def record_attestation(
    db,
    user: User,
    entity_type: str,
    entity_id: uuid.UUID,
    record: Any,
    *,
    statement: str = "",
    comment: str = "",
    scope: str = "",
    frequency: Any = None,
    audit_action: str = "attest",
    audit_summary: str | None = None,
) -> Attestation:
    """Write one attestation and, when it is already complete, move the record's own
    review dates — the single place both happen (D-05b, one clock).

    The caller has already run :func:`enforce_attestable`. Used by ``POST
    /attestations/{type}/{id}`` and by ``POST /risks/{id}/review``, so a review recorded
    on the risk is an attestation, and neither writes the dates a second time. One audit
    row: ``audit_action`` (``attest``, or ``review`` from the risk) with the dates and
    the attestation id.

    Decision 9: the row records whose certification it is (the owner, when somebody else
    signed) and whether a second signature is required. A required signature leaves the
    attestation incomplete, so the clock stays where it is until :func:`confirm` — and
    the audit summary says so rather than promising a next due date that has not moved.
    """
    today = date.today()
    native = _native(entity_type, record)
    if native:
        frequency = await _native_frequency(db, user, entity_type, record)
    next_due = next_review_date(frequency, today)
    text = (statement or "").strip() or default_statement(entity_type)
    owner_id = on_behalf_of(user.id, owner_user_id(record))
    needs_second = await second_signature_required(db, user, entity_type, record)
    row = Attestation(
        tenant_id=user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        attested_by_id=user.id,
        attested_by_email=user.email,
        attested_at=today,
        comment=comment or "",
        frequency=frequency,
        next_due=next_due,
        statement=text,
        scope=(scope or "").strip(),
        confirmation_required=needs_second is not None,
        on_behalf_of_id=owner_id,
        on_behalf_of_name=await owner_name(db, owner_id),
    )
    db.add(row)
    changes: dict[str, Any] = {"statement": text}
    if needs_second:
        changes["confirmation_required"] = needs_second
    else:
        # One review clock: a complete attestation *is* the record's review.
        changes.update(move_review_clock(entity_type, record, today, next_due))
    if row.on_behalf_of_id is not None:
        changes["on_behalf_of"] = row.on_behalf_of_name or str(row.on_behalf_of_id)
    await db.flush()
    if getattr(row, "id", None) is not None:
        changes["attestation_id"] = str(row.id)
    tail = (
        f"awaiting independent confirmation ({needs_second.lower()})"
        if needs_second else f"next due {row.next_due}"
    )
    behalf = on_behalf_of_text(row)
    summary = audit_summary or f"Attested {entity_type} ({tail})"
    if behalf:
        summary = f"{summary} — {behalf}"
    await audit.record(
        db, actor=user, action=audit_action, entity_type=entity_type, entity_id=entity_id,
        summary=summary, changes=changes,
    )
    return row


@router.post("/{entity_type}/{entity_id}", response_model=AttestationStatus, status_code=201)
async def attest(
    entity_type: str, entity_id: uuid.UUID, body: AttestationCreate, db: DbSession, user: CurrentUser
) -> AttestationStatus:
    # Signing off a record's review cycle is a governance act on that record: it needs
    # the owning module's write permission, not merely a session.
    found = entity_types.require_write(user, entity_type)
    record = await _load_record(db, user, entity_type, entity_id, required=True)
    await enforce_attestable(db, user, entity_type, entity_id, record, found)
    await record_attestation(
        db, user, entity_type, entity_id, record,
        statement=body.statement, comment=body.comment, scope=body.scope, frequency=body.frequency,
    )
    return await _bundle(db, entity_type, entity_id, record, user)
