"""Delegation-of-authority limits on the GRC decisions that carry an amount.

The authority matrix (``models/authority.py``) says which role may approve what, up to
which amount. :func:`dual_control.mandate_refusal` answers "may these roles approve this
amount under these lines?"; this module says *which* decisions are checked, against which
category and which amount, and enforces it where the decision is taken:

==========================  =================  =========================================
decision                    category           amount
==========================  =================  =========================================
approving a risk            risk_acceptance    the exposure being accepted, fixed on the
acceptance                                     request (:func:`acceptance_exposure`)
approving an exception      exception          the greater of the exposure recorded on
                                               the exception and the largest quantified
                                               exposure of the risks it covers
approving (signing off) a   operational_loss   its gross loss
loss event
approving an outsourcing    outsourcing        its total contract value
arrangement
==========================  =================  =========================================

The exposure of a risk (:func:`risk_exposure`) is its quantified annualised loss
exposure — the mean ALE of its latest simulated FAIR quantification, else the FAIR ALE
(frequency x single-loss expectancy) on the risk itself. That is the figure leading
GRC tools put against a risk-acceptance mandate (ServiceNow IRM and Archer both scope
acceptance authority by the monetary exposure accepted); a figure typed on the request
is used where the risk is not quantified, and never lowers a quantified one.

Rules, the same everywhere:

* **No lines, no restriction.** A category with no active matrix lines is not governed
  — the decision is taken exactly as before. A bank opts in by adding lines.
* **Governed, no amount: refused.** Once a category is under the matrix, a decision with
  no amount would escape it; the approver is told which figure to record first.
* **Currency.** The amount is converted into the currency the category's lines are
  written in (the reporting currency when any line uses it), through the exchange-rate
  table. With no rate for it the decision is refused until one is recorded — an amount
  that cannot be compared with the mandate is not within it.
* **Rejecting needs no mandate.** Only approval commits the bank; anyone who may decide
  may say no.

Enforced on the direct decision (``/risks/{id}/acceptances/{id}/decision``,
``/exceptions/{id}/decision``, a lifecycle Approve through
:func:`record_workflow.apply`) and on the approval that finishes an approval route or
request (:func:`record_workflow.write_back`) — the final approver needs the mandate,
earlier stages do not. ``GET /authority-matrix/mandate/{entity_type}/{id}`` gives the
decision forms the same answer before the approver clicks.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import dual_control

#: Record types whose approval is checked against the matrix, and their category.
CATEGORIES: dict[str, str] = {
    "risk_acceptance": "risk_acceptance",
    "exception": "exception",
    "loss_event": "operational_loss",
    "outsourcing_arrangement": "outsourcing",
}

#: What the refusal calls each decision.
ACTIVITIES: dict[str, str] = {
    "risk_acceptance": "accepting this risk",
    "exception": "approving this exception",
    "loss_event": "signing off this loss event",
    "outsourcing_arrangement": "approving this outsourcing arrangement",
}

#: The figure the approver is asked to record when a governed decision has none.
MISSING_AMOUNT: dict[str, str] = {
    "risk_acceptance": (
        "the exposure being accepted — quantify the risk, or request acceptance again "
        "with the exposure"
    ),
    "exception": "the exposure this exception leaves uncovered (Exposure on the exception)",
    "loss_event": "the gross loss",
    "outsourcing_arrangement": "the contract value",
}


@dataclass(frozen=True)
class Subject:
    """One decision as the matrix sees it."""

    entity_type: str
    category: str
    amount: float | None
    currency: str
    basis: str = ""

    @property
    def activity(self) -> str:
        return ACTIVITIES.get(self.entity_type, "this decision")


@dataclass
class Verdict:
    """The mandate check for one user and one decision (the endpoint's answer)."""

    subject: Subject
    governed: bool
    allowed: bool
    reason: str = ""
    compared_amount: float | None = None
    compared_currency: str = ""
    lines: list[dual_control.MandateLine] = field(default_factory=list)


def is_governed_type(entity_type: str) -> bool:
    return entity_type in CATEGORIES


# ------------------------------------------------------------------ amounts ---
def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def risk_exposure(db: AsyncSession, risk: Any) -> tuple[float | None, str, str]:
    """``(amount, currency, basis)``: a risk's quantified annualised loss exposure.

    The mean ALE of its latest simulated quantification, else the FAIR ALE on the risk
    (in the reporting currency), else ``(None, "", "")``."""
    from app.models.risk_quant import RiskQuantification
    from app.services import fx

    if risk is None:
        return None, "", ""
    quant = await db.scalar(
        select(RiskQuantification)
        .where(
            RiskQuantification.risk_id == risk.id,
            RiskQuantification.deleted.is_(False),
            RiskQuantification.last_simulated.is_not(None),
        )
        .order_by(RiskQuantification.last_simulated.desc(), RiskQuantification.updated_at.desc())
        .limit(1)
    )
    if quant is not None and _num(quant.last_mean_ale):
        return _num(quant.last_mean_ale), (quant.currency or "").upper(), (
            f"mean annual loss exposure of quantification {quant.reference or quant.title}"
        )
    ale = _num(getattr(risk, "annual_loss_expectancy", None))
    if ale:
        return ale, await fx.reporting_currency(db, getattr(risk, "tenant_id", None)), (
            "annual loss expectancy on the risk"
        )
    return None, "", ""


async def _in_reporting(db: AsyncSession, amount: float, currency: str) -> float | None:
    from app.services import fx

    conv = await fx.convert(db, amount, currency or None)
    return float(conv.amount) if conv.amount is not None else None


async def acceptance_exposure(
    db: AsyncSession, risk: Any, typed_amount: float | None, typed_currency: str = ""
) -> tuple[float | None, str, str]:
    """The exposure a new acceptance request fixes: the risk's quantified exposure, or
    the amount typed on the request where there is none — the greater of the two when
    both exist, so a request can never understate a quantified exposure."""
    from app.services import fx

    computed, cur, basis = await risk_exposure(db, risk)
    typed_cur = (typed_currency or "").upper() or await fx.reporting_currency(db, getattr(risk, "tenant_id", None))
    if typed_amount is None:
        return computed, cur, basis
    if computed is None:
        return float(typed_amount), typed_cur, "stated on the acceptance request"
    a = await _in_reporting(db, computed, cur)
    b = await _in_reporting(db, float(typed_amount), typed_cur)
    if a is not None and b is not None and b > a:
        return float(typed_amount), typed_cur, "stated on the acceptance request (above the quantified exposure)"
    return computed, cur, basis


async def _exception_subject(db: AsyncSession, record: Any) -> Subject:
    from app.services import fx

    reporting = await fx.reporting_currency(db, getattr(record, "tenant_id", None))
    stated = _num(record.exposure_amount)
    best: tuple[float | None, str, str] = (
        (stated, (record.exposure_currency or reporting).upper(), "stated on the exception")
        if stated is not None else (None, "", "")
    )
    best_rep = await _in_reporting(db, best[0], best[1]) if best[0] is not None else None
    for risk in getattr(record, "risks", None) or []:
        amount, cur, basis = await risk_exposure(db, risk)
        if amount is None:
            continue
        rep = await _in_reporting(db, amount, cur)
        if best[0] is None or (rep is not None and (best_rep is None or rep > best_rep)):
            best = (amount, cur, f"{basis} ({risk.reference or risk.title})")
            best_rep = rep
    return Subject("exception", CATEGORIES["exception"], best[0], best[1], best[2])


async def subject_for(db: AsyncSession, entity_type: str, record: Any) -> Subject | None:
    """The decision on ``record`` as the matrix sees it, or None when its type is not
    checked against the matrix."""
    from app.services import fx

    category = CATEGORIES.get(entity_type)
    if category is None or record is None:
        return None
    if entity_type == "risk_acceptance":
        amount = _num(record.exposure_amount)
        if amount is not None:
            return Subject(entity_type, category, amount, (record.exposure_currency or "").upper(),
                           record.exposure_basis or "")
        # Requested before the exposure was recorded: the risk's exposure today.
        from app.models.risk import Risk

        amount, cur, basis = await risk_exposure(db, await db.get(Risk, record.risk_id))
        return Subject(entity_type, category, amount, cur, basis)
    if entity_type == "exception":
        return await _exception_subject(db, record)
    reporting = await fx.reporting_currency(db, getattr(record, "tenant_id", None))
    if entity_type == "loss_event":
        return Subject(entity_type, category, _num(record.gross_loss),
                       (record.currency or reporting).upper(), "gross loss")
    if entity_type == "outsourcing_arrangement":
        return Subject(entity_type, category, _num(record.contract_value),
                       (record.contract_currency or reporting).upper(), "total contract value")
    return None


# ----------------------------------------------------------------- the check ---
async def _compare_in(db: AsyncSession, amount: float, currency: str, target: str) -> float | None:
    """``amount`` in ``currency`` expressed in ``target``, through the reporting currency."""
    from app.services import fx

    if not target or not currency or currency.upper() == target.upper():
        return amount
    book = await fx.load_rate_book(db)
    conv = book.convert(amount, currency)
    if conv.amount is None:
        return None
    if target.upper() == book.reporting_currency:
        return float(conv.amount)
    found = book.rate_for(target)
    if found is None:
        return None
    return float(conv.amount / found[0])


async def verdict(db: AsyncSession, subject: Subject, user: Any) -> Verdict:
    """May ``user`` approve ``subject`` under the matrix? Never raises."""
    from app.services import fx

    lines = await dual_control.authority_lines(db, subject.category)
    if not lines:
        return Verdict(subject, governed=False, allowed=True)
    if subject.amount is None:
        need = MISSING_AMOUNT.get(subject.entity_type, "the amount")
        return Verdict(subject, governed=True, allowed=False, lines=lines, reason=(
            f"Delegation of authority: {subject.activity} is under the {subject.category.replace('_', ' ')} "
            f"mandate, which needs an amount to check. Record {need} first."
        ))
    reporting = await fx.reporting_currency(db, getattr(user, "tenant_id", None))
    currencies = {(ln.currency or reporting).upper() for ln in lines}
    target = reporting if reporting in currencies else sorted(currencies)[0]
    compared = await _compare_in(db, subject.amount, subject.currency or reporting, target)
    if compared is None:
        return Verdict(subject, governed=True, allowed=False, lines=lines, reason=(
            f"Delegation of authority: the mandates for {subject.activity} are in {target}, and there "
            f"is no {subject.currency} exchange rate to compare {subject.currency} {subject.amount:,.0f} "
            "with them. Record the rate in Exchange Rates, then decide."
        ))
    in_target = [ln for ln in lines if (ln.currency or reporting).upper() == target]
    reason = dual_control.mandate_refusal(
        in_target, amount=compared, role_names=getattr(user, "role_names", None) or [],
        currency=target, activity=subject.activity,
    )
    return Verdict(subject, governed=True, allowed=reason is None, reason=reason or "",
                   compared_amount=compared, compared_currency=target, lines=in_target)


async def enforce(db: AsyncSession, entity_type: str, record: Any, user: Any) -> None:
    """403 when ``user`` may not approve ``record`` under the authority matrix. A no-op
    for a record type the matrix does not check, or a category with no lines."""
    if user is None or not is_governed_type(entity_type):
        return
    subject = await subject_for(db, entity_type, record)
    if subject is None:
        return
    result = await verdict(db, subject, user)
    if not result.allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.reason)


async def load_record(db: AsyncSession, entity_type: str, record_id: uuid.UUID) -> Any:
    """The record behind a governed decision, or None."""
    if entity_type == "risk_acceptance":
        from app.models.risk import RiskAcceptance

        return await db.get(RiskAcceptance, record_id)
    model = dual_control.model_for_entity_type(entity_type)
    if model is None:
        return None
    record = await db.get(model, record_id)
    return None if record is None or getattr(record, "deleted", False) else record


def as_decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(value, 2)))
