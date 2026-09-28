"""Status values only a workflow action reaches — one rule set for create, edit and import.

A register's status is partly bookkeeping (a risk is *identified*, *assessed*, *treated*)
and partly the record of a decision somebody took (a risk was *accepted* by a holder of
``risk:accept``; a policy was *approved* and *published* by someone other than its
author; an access review was *completed* once every account was decided). The decision
states are reached only through the action that takes the decision — with its checks,
its four-eyes rule and its dates — never by writing the status field:

* **Create** (form or API): a record asking to start in a decision state is refused
  (422). There is no decision yet to record.
* **Edit** (PATCH): moving *into* a decision state is refused (422); echoing the stored
  value back (a form that saves every field) and moving out of one are not.
* **Import**: a row asking for a decision state is brought in at the rule's ``initial``
  state with a row warning, unless the importer could have taken the decision alone in
  the app (``services.import_registry.ImportGate``) — how a single-operator installation
  migrates its approved records. The engine resolves the gate per row, then calls the
  module's own create function inside :func:`import_decided`, which is what lets that
  create accept the carried state.

The rules are declared once here (:data:`RULES`, by entity type) and read by the create
and update endpoints and by the import registry, so the three paths cannot drift apart.
Issues keep their own closure rules in ``services.issue_closure`` (validate, then close);
the import reads their :class:`StateRule` from here as well.

Two companions, for registers whose sign-off is their approval lifecycle (FAIR
quantifications, Shariah rulings and products, the model inventory, DPIAs):

* :data:`SYNCED_STATUS` — the business status that follows the lifecycle decision
  (approving a DPIA makes it approved), applied by ``record_workflow``;
* :func:`approval_precondition` — what the record needs before it can be submitted or
  approved (a current simulation, a completed assessment, an approved ruling, a passed
  validation), and :func:`approve_refusal`, which adds the delegation-of-authority
  mandate: the one answer the approve paths, the Approvals inbox and My Work share.

:data:`APPROVED_FIRST` holds operational states that need the approval to exist first
(an Islamic product going live, a model in production, an outsourced service starting).
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import HTTPException


@dataclass(frozen=True)
class StateRule:
    """A status value the product reaches only through a workflow action.

    Creating a record through the UI starts it in its initial state; approving,
    publishing, closing or accepting it is a separate decision, taken — where maker-
    checker applies — by someone other than the person who entered it. An import is a
    create, so a row asking for one of ``later`` is brought in at ``initial`` with a row
    warning, unless the importer could have taken the decision alone in the app: they
    hold ``permissions`` (default: the record type's approve permissions), no four-eyes
    rule governs any of ``four_eyes`` for the record type, and — for ``routed`` rules —
    no approval route is configured for it. Values in ``always`` are never carried (an
    ``in_review`` row cannot join an approval route by import). ``clears`` are fields
    dropped with the downgrade (a closed issue's ``closed_date``).

    ``noun`` names the record in refusals; ``steps`` names, per value, the action that
    reaches it ("Publish"), falling back to ``how``.

    Downgrading rather than failing the row keeps the export of a register importable
    (approved records re-import as drafts, to be approved again here) and loses none of
    the row's data; preview shows the same warning before anything is written.
    """

    field: str
    later: frozenset[str]
    initial: str
    how: str
    permissions: tuple[str, ...] = ()
    four_eyes: tuple[str, ...] = ("approve",)
    module: str = ""  # dual-control / permission module; default the record's entity type
    routed: bool = False
    always: frozenset[str] = frozenset()
    clears: tuple[str, ...] = ()
    noun: str = "record"
    steps: tuple[tuple[str, str], ...] = ()

    def step_for(self, value: str) -> str:
        return dict(self.steps).get(value, "")


def _value(raw: Any) -> str:
    return str(getattr(raw, "value", raw) or "")


def _label(value: str) -> str:
    return value.replace("_", " ")


def _a(noun: str) -> str:
    return f"{'an' if noun[:1].lower() in 'aeiou' else 'a'} {noun}"


# ------------------------------------------------------------------- the rules ---
POLICY_STATUS = StateRule(
    field="status", later=frozenset({"under_review", "approved", "published"}),
    initial="draft", four_eyes=("approve", "publish"), routed=True, noun="policy",
    steps=(
        ("under_review", "Submit for review"),
        ("approved", "Submit for review and Approve"),
        ("published", "Publish"),
    ),
    how="A policy is approved through Submit for review and Approve, then published "
    "with Publish.",
)

RISK_STATUS = StateRule(
    field="status", later=frozenset({"accepted"}), initial="assessed",
    permissions=("risk:read", "risk:accept"), four_eyes=("accept",), noun="risk",
    steps=(("accepted", "Request acceptance, decided by a holder of risk:accept"),),
    how="Request acceptance from the risk; a holder of risk:accept decides it.",
)

ISSUE_STATUS = StateRule(
    field="status", later=frozenset({"remediated", "closed", "risk_accepted"}),
    initial="open", four_eyes=("validate", "close"), clears=("closed_date",), noun="issue",
    how="Close it from the issue: its remediation is validated and the issue closed "
    "by someone other than whoever raised it.",
)

#: Completing an access review is the sign-off on a decision for every account in it.
#: An import brings no accounts or decisions, so it never carries the completion.
ACCESS_REVIEW_STATUS = StateRule(
    field="status", later=frozenset({"completed"}), initial="draft",
    permissions=("review:write",), four_eyes=(), always=frozenset({"completed"}),
    noun="access review",
    steps=(("completed", "Complete review, once every account has been decided"),),
    how="Add the accounts under review, decide each one, then use Complete review.",
)

#: An exception's business status records the approval decision. It is not a create
#: field (a new exception is a pending request) and not importable; the approval an
#: import carries arrives as ``workflow_status`` and brings this status with it
#: (``record_workflow.synced_business_status``). ``expired`` is never stored.
EXCEPTION_STATUS = StateRule(
    field="status", later=frozenset({"approved", "rejected", "expired"}), initial="pending",
    permissions=("exception:read", "exception:approve"), noun="exception",
    steps=(
        ("approved", "Approve — the decision on the exception, or its approval workflow"),
        ("rejected", "Reject — the decision on the exception"),
        ("expired", "its expiry date passing (expiry is worked out, never set)"),
    ),
    how="Approve or reject it with the decision action.",
)

# --- Specialist registers (2026-09-25) --------------------------------------------
# Each of these had a status that recorded a sign-off anyone with write permission could
# type in. The sign-off is now the record's approval lifecycle (``record_workflow``):
# Submit for review, then Approve — by someone other than whoever entered or submitted
# the record while four-eyes applies (``(<type>, approve)``), by a holder of the rule's
# checker role, through the approval route where one is configured — and the business
# status follows the decision (:data:`SYNCED_STATUS`). What each register needs before it
# can be approved is :func:`approval_precondition`.

#: A FAIR quantification is approved as the figure the bank stands behind (it feeds the
#: delegation-of-authority exposure of the risk and the board's loss-exposure view), so
#: its sign-off is independent of whoever ran it — Archer / RiskLens analyses are
#: reviewed and approved before they are reported.
QUANT_STATUS = StateRule(
    field="status", later=frozenset({"approved"}), initial="draft",
    noun="risk quantification",
    steps=(("approved", "Submit for review and Approve, once the simulation has run on its current inputs"),),
    how="Run the simulation, then Submit for review; an approver other than the analyst "
    "approves it.",
)

#: SBP Shariah Governance Framework (2018): rulings are the Shariah Board's decisions.
#: The Shariah Compliance Department enters the resolution; its approval is recorded by
#: someone else (the Board secretary / RSBM), through the approval lifecycle.
SHARIAH_RULING_STATUS = StateRule(
    field="status", later=frozenset({"under_review", "approved"}), initial="draft",
    routed=True, noun="Shariah ruling",
    steps=(
        ("under_review", "Submit for review"),
        ("approved", "Submit for review and Approve (the Shariah Board's decision)"),
    ),
    how="Submit the ruling for review; its approval records the Shariah Board's decision.",
)

#: SGF 2018: no Islamic product is offered without the Shariah Board's approval, given
#: as a ruling. The product is approved through its lifecycle once the ruling approving
#: it is itself approved, and only an approved product can go live (:data:`APPROVED_FIRST`).
ISLAMIC_PRODUCT_STATUS = StateRule(
    field="status", later=frozenset({"approved"}), initial="in_development",
    noun="Islamic product",
    steps=(("approved", "Submit for review and Approve, once its approving Shariah ruling is approved"),),
    how="Link the approved Shariah ruling that approves it, then Submit for review.",
)

#: SR 11-7 / SBP model-risk expectations: a model is approved for use after an
#: independent validation, by someone other than its developer. "Validated" is that
#: sign-off, given through the lifecycle once a completed validation passed the model;
#: production use needs it (:data:`APPROVED_FIRST`).
MODEL_STATUS = StateRule(
    field="status", later=frozenset({"validated"}), initial="development",
    noun="model",
    steps=(("validated", "Submit for review and Approve, once a completed validation passed it"),),
    how="Record the completed validation, then Submit the model for review.",
)

#: Accepting a vulnerability's risk instead of fixing it is a risk acceptance (Qualys,
#: Tenable and ServiceNow VR all route it for approval, with a reason and an end date):
#: requested by one person, decided by another (dual control ``vuln_finding /
#: accept_risk``) — ``api/v1/vulnerability.py``.
VULN_STATUS = StateRule(
    field="status", later=frozenset({"risk_accepted"}), initial="open",
    permissions=("vuln:read", "workflow:approve"), four_eyes=("accept_risk",), noun="vulnerability",
    steps=(("risk_accepted", "Request risk acceptance, decided by someone other than whoever asked"),),
    how="Request risk acceptance with a reason and an end date; someone else who can "
    "approve decides it.",
)

#: A DPIA is signed off by the DPO once it is completed (PDPA readiness, GDPR art. 35(2)
#: "seek the advice of the DPO"): the assessor completes it, someone else approves it.
DPIA_STATUS = StateRule(
    field="status", later=frozenset({"approved"}), initial="required",
    noun="DPIA",
    steps=(("approved", "Submit for review and the DPO's Approve, once the assessment is completed"),),
    how="Complete the assessment, then Submit it for review; the DPO approves it.",
)

#: Entity type -> the rules its create, edit and import apply.
RULES: dict[str, tuple[StateRule, ...]] = {
    "policy": (POLICY_STATUS,),
    "risk": (RISK_STATUS,),
    "issue": (ISSUE_STATUS,),
    "access_review": (ACCESS_REVIEW_STATUS,),
    "exception": (EXCEPTION_STATUS,),
    "risk_quantification": (QUANT_STATUS,),
    "shariah_ruling": (SHARIAH_RULING_STATUS,),
    "islamic_product": (ISLAMIC_PRODUCT_STATUS,),
    "model_inventory": (MODEL_STATUS,),
    "vuln_finding": (VULN_STATUS,),
    "dpia": (DPIA_STATUS,),
}


# ------------------------------------------------------ live only once approved ---
@dataclass(frozen=True)
class ApprovedFirst:
    """Status values a record may take only once its approval lifecycle is approved.

    Not a decision in itself — launching a product, putting a model into production,
    starting an outsourced service are operational facts — but each needs the approval
    to exist first. Create refuses them (a new record is a draft); an edit may move into
    one only while ``workflow_status`` is approved. Echoing the stored value, and moving
    out, always pass, so a record that went live before this rule keeps working."""

    field: str
    values: frozenset[str]
    noun: str
    approval: str  # what the approval is, for the refusal ("the Shariah Board's approval")


APPROVED_FIRST: dict[str, tuple[ApprovedFirst, ...]] = {
    "islamic_product": (ApprovedFirst(
        "status", frozenset({"active"}), "Islamic product", "its Shariah approval",
    ),),
    "model_inventory": (ApprovedFirst(
        "status", frozenset({"in_production"}), "model", "its validation sign-off",
    ),),
    # SBP Framework for Risk Management in Outsourcing Arrangements: a material
    # arrangement is approved (board / senior management, within the delegation of
    # authority) before the service starts.
    "outsourcing_arrangement": (ApprovedFirst(
        "status", frozenset({"active", "under_review"}), "outsourcing arrangement",
        "its approval (within the delegation of authority)",
    ),),
}


def _approved_first_refusal(rule: ApprovedFirst, value: str) -> str:
    return (
        f"{_a(rule.noun).capitalize()} can't be {_label(value)} before {rule.approval}. "
        "Submit it for review and have it approved first."
    )


def allowed_values(entity_type: str, field: str, stored: str | None, workflow_state: str | None) -> set[str]:
    """Values of ``field`` a form may offer to save, given the stored value (None on
    create) and the record's lifecycle state — every value except those only a decision
    reaches and, before approval, those that need it. Pure; the forms mirror it."""
    blocked: set[str] = set()
    for rule in RULES.get(entity_type, ()):
        if rule.field == field:
            blocked |= set(rule.later)
    if workflow_state != "approved":
        for rule in APPROVED_FIRST.get(entity_type, ()):
            if rule.field == field:
                blocked |= set(rule.values)
    if stored:
        blocked.discard(stored)
    return blocked


# --------------------------------------------- the decision's business status ---
#: When a record's lifecycle moves, the business status that records the same decision
#: follows: table -> lifecycle state -> (statuses it moves from, status it moves to).
#: ``draft`` covers both a rejection (from in review) and Revise (from approved), and
#: ``retired`` retires the record's status too. Read by
#: ``record_workflow.synced_business_status``.
SYNCED_STATUS: dict[str, dict[str, tuple[frozenset[str], str]]] = {
    "risk_quantifications": {
        "approved": (frozenset({"simulated"}), "approved"),
        # Reopened: the simulation still describes the inputs until they change.
        "draft": (frozenset({"approved"}), "simulated"),
    },
    "shariah_rulings": {
        "in_review": (frozenset({"draft"}), "under_review"),
        "approved": (frozenset({"draft", "under_review"}), "approved"),
        "draft": (frozenset({"under_review", "approved"}), "draft"),
        "retired": (frozenset({"draft", "under_review", "approved"}), "superseded"),
    },
    "islamic_products": {
        "approved": (frozenset({"in_development"}), "approved"),
        # A live product stays live while its approval is revised, as a published policy
        # stays binding; suspending it is a separate business decision.
        "draft": (frozenset({"approved"}), "in_development"),
        "retired": (frozenset({"in_development", "approved", "active", "suspended"}), "withdrawn"),
    },
    "model_inventory": {
        "approved": (frozenset({"development", "under_review"}), "validated"),
        "draft": (frozenset({"validated"}), "development"),
        "retired": (frozenset({"development", "validated", "in_production", "under_review"}), "retired"),
    },
    "dpias": {
        "approved": (frozenset({"completed"}), "approved"),
        "draft": (frozenset({"approved"}), "completed"),
    },
}


def synced_status(table: str, current: Any, workflow_state: str) -> str | None:
    """The business status a record of ``table`` takes when its lifecycle moves to
    ``workflow_state``, or None to leave it (:data:`SYNCED_STATUS`). Pure."""
    step = SYNCED_STATUS.get(table, {}).get(workflow_state)
    if step is None:
        return None
    sources, target = step
    now = _value(current)
    return target if now in sources and now != target else None


# ------------------------------------------------- what an approval needs first ---
_PASSING_VALIDATIONS = frozenset({"pass", "pass_with_findings"})


def approval_precondition(entity_type: str, record: Any) -> str | None:
    """Why ``record`` can't be submitted for review or approved yet, or None. Pure —
    reads the record and its loaded relationships only.

    * a risk quantification needs a simulation of its current inputs;
    * a DPIA needs its assessment completed (or a "not required" screening);
    * an Islamic product needs its approving Shariah ruling, itself approved;
    * a model needs its latest completed validation to have passed it.
    """
    if record is None:
        return None
    status = _value(getattr(record, "status", None))
    if entity_type == "risk_quantification":
        if getattr(record, "last_simulated", None) is None or status not in ("simulated", "approved"):
            return "Run the simulation on the current inputs before this quantification is approved."
    elif entity_type == "dpia":
        if status not in ("completed", "not_required", "approved"):
            return (
                f"This DPIA is {_label(status)}. Complete the assessment (status Completed) "
                "before it goes to the DPO for approval."
            )
    elif entity_type == "islamic_product":
        ruling = getattr(record, "approving_ruling", None)
        if ruling is None or getattr(ruling, "deleted", False):
            return (
                "Link the Shariah ruling that approves this product (Approving ruling) before "
                "it is approved: the product rests on the Shariah Board's decision."
            )
        if _value(getattr(ruling, "status", None)) != "approved":
            ref = getattr(ruling, "reference", "") or getattr(ruling, "title", "")
            return f"The approving ruling {ref} is not approved yet; approve the ruling first."
    elif entity_type == "model_inventory":
        done = [
            v for v in (getattr(record, "validations", None) or [])
            if _value(getattr(v, "status", None)) == "completed"
        ]
        if not done:
            return "Record a completed independent validation of this model before it is approved."
        latest = max(done, key=lambda v: (v.validation_date or date.min, v.created_at.timestamp() if v.created_at else 0.0))
        if _value(latest.outcome) not in _PASSING_VALIDATIONS:
            return (
                f"The latest validation ({latest.reference or 'completed'}) did not pass the model "
                f"({_label(_value(latest.outcome))}). Remediate and revalidate before approving it."
            )
    return None


def enforce_approval_precondition(entity_type: str, record: Any) -> None:
    """422 when :func:`approval_precondition` refuses."""
    refusal = approval_precondition(entity_type, record)
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)


#: Record types :func:`approval_precondition` checks.
PRECONDITION_TYPES: frozenset[str] = frozenset({"risk_quantification", "dpia", "islamic_product", "model_inventory"})


def approval_is_checked(entity_type: str | None) -> bool:
    """Whether approving this record type can be refused beyond who may decide (a
    precondition, or the delegation-of-authority matrix)."""
    from app.services import authority_limits

    return bool(entity_type) and (
        entity_type in PRECONDITION_TYPES or authority_limits.is_governed_type(entity_type)
    )


async def approve_refusal(db: Any, entity_type: str, record: Any, user: Any) -> str | None:
    """Why ``user`` may not give the approval that finishes ``record``'s review, beyond
    who may decide at all: the record is not ready (:func:`approval_precondition`) or
    the amount is above their delegation-of-authority mandate
    (``authority_limits.verdict``). The exact texts the approve paths raise; rejecting
    needs neither. Never raises."""
    from app.services import authority_limits

    refusal = approval_precondition(entity_type, record)
    if refusal:
        return refusal
    if user is None or not authority_limits.is_governed_type(entity_type):
        return None
    subject = await authority_limits.subject_for(db, entity_type, record)
    if subject is None:
        return None
    verdict = await authority_limits.verdict(db, subject, user)
    return None if verdict.allowed else verdict.reason


# ------------------------------------------------------- the import's carve-out ---
_IMPORT_DECIDED: ContextVar[bool] = ContextVar("lifecycle_import_decided", default=False)


@contextlib.contextmanager
def import_decided() -> Iterator[None]:
    """Mark the create calls inside as an import row the import gate has already
    decided (``ImportGate.apply``): a decision state still in the payload passed it."""
    token = _IMPORT_DECIDED.set(True)
    try:
        yield
    finally:
        _IMPORT_DECIDED.reset(token)


def in_import() -> bool:
    return _IMPORT_DECIDED.get()


# ------------------------------------------------------------------ refusals ---
def create_refusal(entity_type: str, data: Mapping[str, Any]) -> str | None:
    """Why a new record may not start with these values, or None. Pure.

    Inside :func:`import_decided` the import gate has already decided, so nothing is
    refused here."""
    if in_import():
        return None
    for rule in RULES.get(entity_type, ()):
        value = _value(data.get(rule.field))
        if value in rule.later:
            step = rule.step_for(value)
            reach = f"it becomes {_label(value)} through {step}" if step else rule.how.rstrip(".")
            return (
                f"A new {rule.noun} starts as {_label(rule.initial)}; {reach}, not when it "
                "is created."
            )
    for first in APPROVED_FIRST.get(entity_type, ()):
        value = _value(data.get(first.field))
        if value in first.values:
            return _approved_first_refusal(first, value)
    return None


def edit_refusal(entity_type: str, current: Any, data: Mapping[str, Any]) -> str | None:
    """Why an edit may not write these values onto a record whose stored values are
    ``current`` (the record, or a mapping of its fields), or None. Pure.

    Only a move *into* a decision state is refused: resending the stored value, and
    leaving a decision state (reopening), pass."""
    for rule in RULES.get(entity_type, ()):
        if rule.field not in data:
            continue
        value = _value(data.get(rule.field))
        stored = current.get(rule.field) if isinstance(current, Mapping) else getattr(current, rule.field, None)
        if value not in rule.later or value == _value(stored):
            continue
        step = rule.step_for(value)
        if step:
            return f"{_a(rule.noun).capitalize()} becomes {_label(value)} through {step}, not by editing its status."
        return f"{_a(rule.noun).capitalize()} can't be set to {_label(value)} by editing it. {rule.how}"

    def stored_of(name: str) -> str:
        return _value(current.get(name) if isinstance(current, Mapping) else getattr(current, name, None))

    for first in APPROVED_FIRST.get(entity_type, ()):
        if first.field not in data:
            continue
        value = _value(data.get(first.field))
        if value not in first.values or value == stored_of(first.field):
            continue
        if stored_of("workflow_status") != "approved":
            return _approved_first_refusal(first, value)
    return None


def enforce_create(entity_type: str, data: Mapping[str, Any]) -> None:
    """422 when :func:`create_refusal` refuses."""
    refusal = create_refusal(entity_type, data)
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)


def enforce_edit(entity_type: str, current: Any, data: Mapping[str, Any]) -> None:
    """422 when :func:`edit_refusal` refuses."""
    refusal = edit_refusal(entity_type, current, data)
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)


async def write_back_refusal(db: Any, entity_type: str | None, entity_id: Any, user: Any) -> str | None:
    """:func:`approve_refusal` for the approval an Approvals-inbox decision would write
    back onto its record (``record_workflow.write_back``) — None when the request is
    about no record, a record type that is not checked, or a record the approval would
    not move to approved. Loads the record. Never raises."""
    from app.services import record_registry, record_workflow

    if entity_id is None or not approval_is_checked(entity_type):
        return None
    model = record_registry.model_for(entity_type)
    if model is None or not record_registry.has_workflow(model):
        return None
    record = await db.get(model, entity_id)
    if record is None or getattr(record, "deleted", False):
        return None
    if record_workflow.write_back_target(record.workflow_status, True) != record_workflow.APPROVED:
        return None
    return await approve_refusal(db, entity_type, record, user)
