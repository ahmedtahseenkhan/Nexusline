"""Risk acceptance of a vulnerability finding — who may ask, who may decide.

Accepting a vulnerability's risk instead of fixing it is a risk acceptance. Qualys,
Tenable and ServiceNow Vulnerability Response all treat it as one: somebody asks, with a
justification and an end date, and somebody else approves it; at the end date the
finding is fixed or accepted again. SBP's Enterprise Technology Governance & Risk
Management Framework expects exceptions to security requirements to be approved and
time-bound in the same way. Here:

* **Request** (``POST /vuln-findings/{id}/risk-acceptance``, ``vuln:write``): an open
  finding, a reason, an end date within :data:`MAX_ACCEPTANCE_DAYS`. A rule's maker role
  for ``vuln_finding / accept_risk`` applies (``dual_control.enforce_maker_role``).
* **Decision** (``.../risk-acceptance/decision``): ``vuln:read`` and ``workflow:approve``
  — the finding's lifecycle approve permissions — and, while four-eyes applies, not the
  person who asked, and a holder of the rule's checker role where one is named
  (:func:`decision_refusal`). Approving moves the finding to ``risk_accepted``; nothing
  else does (``lifecycle_gates.VULN_STATUS``). Rejecting needs a reason.

:func:`decision_refusal` is the one answer the decide endpoint, the finding's page and
My Work share, so the request is offered to exactly the people who can decide it.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

#: The dual-control key of the decision.
MODULE, ACTION = "vuln_finding", "accept_risk"
#: What deciding needs (the finding's lifecycle approve permissions).
DECIDE_PERMISSIONS: tuple[str, ...] = ("vuln:read", "workflow:approve")
#: Longest a vulnerability's risk may be accepted for before it is decided again.
MAX_ACCEPTANCE_DAYS = 365

REQUESTED, ACCEPTED, REJECTED = "requested", "accepted", "rejected"
OPEN_STATES: frozenset[str] = frozenset({"open", "in_progress"})


def _value(raw: Any) -> str:
    return str(getattr(raw, "value", raw) or "")


def request_refusal(finding: Any, until: date, today: date) -> str | None:
    """Why this finding's risk can't be put up for acceptance now, or None. Pure."""
    if _value(finding.status) not in OPEN_STATES:
        return (
            f"This finding is {_value(finding.status).replace('_', ' ')}; only an open finding's "
            "risk can be accepted."
        )
    if finding.acceptance_status == REQUESTED:
        return "An acceptance request on this finding is already waiting for a decision."
    if until <= today:
        return "The acceptance must end in the future: give the date by which it is fixed or decided again."
    if until > today + timedelta(days=MAX_ACCEPTANCE_DAYS):
        return (
            f"An acceptance can run for at most {MAX_ACCEPTANCE_DAYS} days; decide it again "
            "when it ends."
        )
    return None


async def decision_refusal(
    db: AsyncSession, finding: Any, *, user_id: Any, permissions: Any, approve: bool = True,
    directory: Any = None,
) -> str | None:
    """Why this user may not decide the pending acceptance on ``finding``, or None.

    Checked in the decide endpoint's order: a request is pending; the user holds
    :data:`DECIDE_PERMISSIONS`; while four-eyes applies to ``vuln_finding /
    accept_risk``, they did not ask for it and — where the rule names a checker role
    someone else holds — they hold it. Approving also needs the finding still open.
    ``directory`` reuses an already-loaded ``notifications.Directory``."""
    from app.services import dual_control

    if finding.acceptance_status != REQUESTED:
        return "No acceptance request is waiting for a decision on this finding."
    missing = [p for p in DECIDE_PERMISSIONS if p not in set(permissions or ())]
    if missing:
        return f"Deciding a risk acceptance needs the {', '.join(missing)} permission."
    required, rule = await dual_control.dual_control_required(db, MODULE, ACTION)
    if required:
        maker = finding.acceptance_requested_by_id
        if maker is not None and maker == user_id:
            return dual_control.maker_checker_message("risk-acceptance request")
        refusal = await dual_control.checker_role_refusal(
            db, rule, module=MODULE, action=ACTION, checker_id=user_id, maker_id=maker,
            directory=directory,
        )
        if refusal:
            return refusal
    if approve and _value(finding.status) not in OPEN_STATES:
        return (
            f"This finding is now {_value(finding.status).replace('_', ' ')}, so there is no open "
            "risk to accept. Reject the request."
        )
    return None
