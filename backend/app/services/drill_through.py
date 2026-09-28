"""Drill-through: the list behind every dashboard number, and the one query both use.

Every number on the dashboard links to the list that produced it — "98 controls never
tested" opens ``/controls?assurance=not_assessed``. That promise holds only if the count
and the list are the same predicate, so the predicates live here and both sides import
them: :func:`app.api.v1.dashboard.get_overview` counts with them and the list endpoints
filter with them. Change a rule here and the number and its list move together.

The vocabulary a link may carry (query parameters on the list endpoints):

``GET /controls``
    ``assurance`` — ``assured`` (effective or partially effective), ``effective``,
    ``partially_effective``, ``failing`` (ineffective), ``not_assessed`` (never tested),
    ``not_operating`` (planned or retired), ``unmapped`` (implements no live clause).
    Every rating value counts operating controls only, as the dashboard does: a planned
    or retired control has nothing to test.
    ``test`` — ``overdue``, ``due_30d``, ``failed`` (the latest test that counts — reviewed,
    or recorded before reviews existed — failed). ``key`` — key controls only (or not).
``GET /issues``      ``overdue=true`` — open (not closed, remediated or risk accepted) and past due.
``GET /incidents``   ``open=true`` — not resolved or closed (``status=open`` is the literal status).
``GET /policies``    ``review=overdue`` — approved or published, next review in the past.
``GET /vendors``     ``review=overdue`` — next review in the past; ``criticality``.
``GET /risks``       ``appetite=breach``, ``review=overdue``, ``treatment_overdue=true``,
                     ``pending_validation=true``, ``business_unit_id`` — the risk
                     register's own filters (``services.risk_query``); the dashboard
                     counts treatment with the register's predicate
                     (:func:`risk_treatment_overdue` delegates), and every appetite
                     figure over the board register (:func:`risk_board_register`).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, get_args
from urllib.parse import urlencode

from sqlalchemy import and_, exists, select

from app.models.compliance import Framework, Requirement, requirement_controls
from app.models.control import UNTESTABLE_CONTROL_STATUSES, Control, ControlAudit
from app.models.enums import ControlEffectiveness, IncidentStatus, PolicyStatus, TestResult
from app.models.incident import Incident
from app.models.issue import Issue
from app.models.policy import Policy
from app.models.risk import Risk
from app.models.vendor import Vendor
from app.services import control_assurance
from app.services.issue_closure import CLOSED_STATES as _ISSUE_CLOSED

# ------------------------------------------------------------------ vocabulary ---
#: ``GET /controls?assurance=`` values (the query parameter's type).
AssuranceFilter = Literal[
    "assured", "effective", "partially_effective", "failing", "not_assessed", "not_operating", "unmapped",
]
#: ``GET /controls?test=`` values.
TestFilter = Literal["overdue", "due_30d", "failed"]
#: ``?review=`` values on policies and third parties.
ReviewFilter = Literal["overdue"]
CONTROL_ASSURANCE: tuple[str, ...] = get_args(AssuranceFilter)
CONTROL_TEST: tuple[str, ...] = get_args(TestFilter)
REVIEW: tuple[str, ...] = get_args(ReviewFilter)
#: The "due soon" window the dashboard reports, in days.
DUE_SOON_DAYS = 30

#: Issue statuses that are done (one definition: ``services.issue_closure``).
ISSUE_CLOSED_STATES = tuple(sorted(_ISSUE_CLOSED, key=lambda s: s.value))
#: Incident statuses that are no longer open.
INCIDENT_CLOSED_STATES: tuple[IncidentStatus, ...] = (IncidentStatus.resolved, IncidentStatus.closed)
#: Policy statuses in force — the only ones whose review can be overdue.
POLICY_IN_FORCE: tuple[PolicyStatus, ...] = (PolicyStatus.approved, PolicyStatus.published)



# -------------------------------------------------------------------- controls ---
def operating_control():
    """Implemented or operational: a control with a test clock. Planned and retired
    controls have nothing to test, so they are never overdue, due, failing or untested."""
    return Control.status.not_in(UNTESTABLE_CONTROL_STATUSES)


def latest_counted_tests():
    """Each control's latest test that counts towards its rating — reviewed, or recorded
    before reviews existed — as ``(control_id, result)`` (PostgreSQL ``DISTINCT ON``)."""
    return (
        select(ControlAudit.control_id, ControlAudit.result)
        .where(ControlAudit.review_status.in_(control_assurance.COUNTING_REVIEW_STATES))
        .distinct(ControlAudit.control_id)
        .order_by(
            ControlAudit.control_id,
            ControlAudit.conducted_date.desc().nulls_last(),
            ControlAudit.created_at.desc(),
        )
        .subquery()
    )


def mapped_to_live_clause():
    """The control implements at least one live requirement of a live framework."""
    return exists(
        select(requirement_controls.c.control_id)
        .join(Requirement, Requirement.id == requirement_controls.c.requirement_id)
        .join(Framework, Framework.id == Requirement.framework_id)
        .where(
            requirement_controls.c.control_id == Control.id,
            Requirement.deleted.is_(False),
            Framework.deleted.is_(False),
        )
    )


def control_assurance_clause(value: str):
    """``GET /controls?assurance=<value>``. Raises ``ValueError`` for an unknown value."""
    if value == "not_operating":
        return Control.status.in_(UNTESTABLE_CONTROL_STATUSES)
    if value == "unmapped":
        return ~mapped_to_live_clause()
    rating = {
        "assured": Control.effectiveness.in_(control_assurance.ASSURED_EFFECTIVENESS),
        "effective": Control.effectiveness == ControlEffectiveness.effective,
        "partially_effective": Control.effectiveness == ControlEffectiveness.partially_effective,
        "failing": Control.effectiveness == ControlEffectiveness.ineffective,
        "not_assessed": Control.effectiveness == ControlEffectiveness.not_assessed,
    }.get(value)
    if rating is None:
        raise ValueError(f"Unknown assurance filter '{value}'")
    return and_(operating_control(), rating)


def control_test_clause(value: str, today: date):
    """``GET /controls?test=<value>``. Raises ``ValueError`` for an unknown value."""
    if value == "overdue":
        return and_(operating_control(), Control.next_audit_date < today)
    if value == "due_30d":
        return and_(
            operating_control(),
            Control.next_audit_date >= today,
            Control.next_audit_date <= today + timedelta(days=DUE_SOON_DAYS),
        )
    if value == "failed":
        latest = latest_counted_tests()
        return and_(
            operating_control(),
            Control.id.in_(select(latest.c.control_id).where(latest.c.result == TestResult.failed)),
        )
    raise ValueError(f"Unknown test filter '{value}'")


# ------------------------------------------------------------- other registers ---
def issue_open():
    """Not closed, remediated or risk accepted."""
    return Issue.status.not_in(ISSUE_CLOSED_STATES)


def issue_overdue(today: date):
    """``GET /issues?overdue=true``: open and past its due date."""
    return and_(issue_open(), Issue.due_date.is_not(None), Issue.due_date < today)


def incident_open():
    """``GET /incidents?open=true``: not resolved or closed (triage, investigating and
    contained incidents are open too)."""
    return Incident.status.not_in(INCIDENT_CLOSED_STATES)


def policy_review_overdue(today: date):
    """``GET /policies?review=overdue``: a policy in force whose next review has passed."""
    return and_(Policy.status.in_(POLICY_IN_FORCE), Policy.next_review_date < today)


def vendor_review_overdue(today: date):
    """``GET /vendors?review=overdue``: a third party still in use whose next review has
    passed. An offboarded supplier has nothing left to review."""
    from app.models.enums import VendorStatus

    return and_(Vendor.status != VendorStatus.offboarded, Vendor.next_review_date < today)


def risk_review_overdue(today: date):
    """``GET /risks?review=overdue``: the next review date has passed."""
    return Risk.next_review_date < today


def risk_board_register():
    """The risks board figures are taken over — scored, out of Draft, not accepted or
    closed (``risk_query.board_register_clause``). ``GET /risks?appetite=`` filters to
    the same set, so "3 above tolerance" opens three risks."""
    from app.services.risk_query import board_register_clause

    return board_register_clause()


def risk_pending_validation():
    """``GET /risks?pending_validation=true``: live drafts, left out of board figures."""
    from app.services.risk_query import pending_validation_clause

    return pending_validation_clause()


def risk_treatment_overdue(today: date):
    """``GET /risks?treatment_overdue=true``: an unsettled risk with an open treatment
    action past due, or — with no actions yet — a treatment deadline in the past. The
    risk register owns the rule (``risk_query.treatment_overdue_clause``); the dashboard
    counts with it through here."""
    from app.services.risk_query import treatment_overdue_clause

    return treatment_overdue_clause(today)


# ----------------------------------------------------------------------- links ---
def href(path: str, **params: object) -> str:
    """``href("/controls", test="overdue")`` → ``/controls?test=overdue``. ``None`` values
    are dropped; booleans are written ``true`` / ``false``."""
    query = {
        k: ("true" if v is True else "false" if v is False else str(v))
        for k, v in params.items()
        if v is not None
    }
    return f"{path}?{urlencode(query)}" if query else path


#: Where each line of the dashboard's "Needs a decision or is overdue" queue opens.
#: Tested against the list endpoints' parameters (tests/test_drill_through.py).
ACTION_LINKS: dict[str, str] = {
    "breach": href("/risks", appetite="breach"),
    "tat": "/sla-policies",
    "tests_failed": href("/controls", test="failed"),
    "findings_overdue": "/internal-audit",
    "issues_overdue": href("/issues", overdue=True),
    "treatments_overdue": href("/risks", treatment_overdue=True),
    "tests_overdue": href("/controls", test="overdue"),
    "acceptances_expiring": "/risks",
    "reviews_overdue": href("/risks", review="overdue"),
    "policies_overdue": href("/policies", review="overdue"),
    # The asset registers read the same filters from the link as from their toolbars.
    "it_asset_reviews_overdue": href("/it-assets", review_overdue=True),
    "info_asset_reviews_overdue": href("/information-assets", review_overdue=True),
    "it_assets_in_review": href("/it-assets", workflow_status="in_review"),
    "info_assets_in_review": href("/information-assets", workflow_status="in_review"),
    "acceptances_pending": "/approvals",
    "not_assessed": href("/controls", assurance="not_assessed"),
}

#: Where the dashboard's "N risks pending validation" banner opens: the drafts its
#: figures leave out (not a queue line — nothing is overdue, the data is incomplete).
PENDING_VALIDATION_LINK: str = href("/risks", pending_validation=True)
