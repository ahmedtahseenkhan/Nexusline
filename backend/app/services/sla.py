"""The turnaround-time clock: what is due when, what is late, and who hears about it.

A remediation standard that only exists in a policy document is discovered to have been
missed when someone counts, months later. This module measures it continuously:

* :func:`reconcile` recomputes every open record's ``tat_due_date`` from the tenant's
  policy and stamps ``tat_breached_at`` the first time a window lapses. It is idempotent
  and cheap, so it runs both on the background sweep and whenever the dashboard asks —
  which means a policy change takes effect immediately rather than at the next sweep.
* :func:`state_of` classifies one record as on-track, at-risk or breached.
* :func:`summary` rolls the whole tenant up for the dashboard widget and the sign-in
  reminder.

**Which clock this is.** ``tat_due_date`` is what the *policy* allows, derived from the
record's severity. A record's own ``due_date`` is what was *agreed* with the action
owner. Banks track both, and the gap between them is itself worth seeing, so neither
overwrites the other.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    AuditFindingStatus,
    IncidentStatus,
    Severity,
)
from app.models.incident import Incident
from app.models.internal_audit import AuditFinding
from app.models.issue import Issue, IssueStatus2
from app.models.risk import Risk
from app.models.sla import SlaPolicy

__all__ = [
    "ENTITIES",
    "DEFAULT_TARGETS",
    "EntitySla",
    "SlaState",
    "TatRecord",
    "reconcile",
    "state_of",
    "summary",
]

ON_TRACK = "on_track"
AT_RISK = "at_risk"
BREACHED = "breached"

_SEVERITIES = (Severity.critical, Severity.high, Severity.medium, Severity.low)


@dataclass(frozen=True)
class EntitySla:
    """How one record type participates in the TAT clock."""

    key: str
    label: str
    model: type
    link: str  # frontend path for the notification/widget deep-link
    #: Severity of a row. Risks have no severity column — theirs comes from the score.
    severity_of: object
    #: True while the record is still someone's problem.
    is_open: object
    #: Human label for an alert body.
    label_of: object


def _risk_severity(risk: Risk, bands) -> Severity:
    from app.services.risk_scoring import effective_score, severity_for_score

    score = effective_score(risk.inherent_score, risk.residual_score)
    return severity_for_score(score, bands) or Severity.low


ENTITIES: dict[str, EntitySla] = {
    "risk": EntitySla(
        key="risk", label="Risk", model=Risk, link="/risks",
        severity_of=_risk_severity,
        is_open=lambda r: r.status.value not in ("closed", "accepted"),
        label_of=lambda r: f"{r.reference}: {r.title}",
    ),
    "issue": EntitySla(
        key="issue", label="Issue", model=Issue, link="/issues",
        severity_of=lambda i, _bands: i.severity,
        is_open=lambda i: i.status not in (
            IssueStatus2.closed, IssueStatus2.remediated, IssueStatus2.risk_accepted
        ),
        label_of=lambda i: f"{i.reference}: {i.title}",
    ),
    "audit_finding": EntitySla(
        key="audit_finding", label="Audit finding", model=AuditFinding, link="/internal-audit",
        severity_of=lambda f, _bands: f.rating,
        is_open=lambda f: f.status not in (
            AuditFindingStatus.closed, AuditFindingStatus.risk_accepted
        ),
        label_of=lambda f: f"{f.reference}: {f.title}",
    ),
    "incident": EntitySla(
        key="incident", label="Incident", model=Incident, link="/incidents",
        severity_of=lambda i, _bands: i.severity,
        is_open=lambda i: i.status not in (IncidentStatus.closed, IncidentStatus.resolved),
        label_of=lambda i: f"{i.reference}: {i.title}",
    ),
}

# Calendar days, by record type and severity, applied until a bank sets its own. Risk
# and issue remediation follows a typical 15/30/60/90 standard; audit findings get
# longer because they usually need a project; incidents are far shorter because the
# clock there is response, not remediation.
DEFAULT_TARGETS: dict[str, dict[Severity, int]] = {
    "risk": {Severity.critical: 15, Severity.high: 30, Severity.medium: 60, Severity.low: 90},
    "issue": {Severity.critical: 15, Severity.high: 30, Severity.medium: 60, Severity.low: 90},
    "audit_finding": {
        Severity.critical: 30, Severity.high: 60, Severity.medium: 90, Severity.low: 120
    },
    "incident": {Severity.critical: 1, Severity.high: 3, Severity.medium: 7, Severity.low: 14},
}

DEFAULT_WARN_PERCENT = 80


@dataclass(frozen=True)
class SlaState:
    state: str  # on_track | at_risk | breached
    due: date | None
    days_remaining: int | None  # negative once overdue


@dataclass(frozen=True)
class TatRecord:
    """One record's TAT position, for the dashboard widget and the sign-in reminder."""

    entity_type: str
    entity_label: str
    entity_id: object
    label: str
    severity: str
    due: date | None
    days_overdue: int
    link: str


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def due_from(started: date, target_days: int) -> date:
    return started + timedelta(days=target_days)


def state_of(
    started: date | None,
    due: date | None,
    *,
    today: date | None = None,
    warn_at_percent: int = DEFAULT_WARN_PERCENT,
) -> SlaState:
    """Classify a record against its window.

    ``at_risk`` fires once ``warn_at_percent`` of the window has elapsed, so the owner
    hears about it while there is still time to act — an alert that only arrives on the
    day of breach is a report, not a control.
    """
    if due is None:
        return SlaState(ON_TRACK, None, None)
    today = today or date.today()
    remaining = (due - today).days
    if remaining < 0:
        return SlaState(BREACHED, due, remaining)
    if started is not None:
        window = (due - started).days
        if window > 0:
            elapsed_pct = ((today - started).days / window) * 100
            if elapsed_pct >= warn_at_percent:
                return SlaState(AT_RISK, due, remaining)
        elif remaining == 0:
            # A same-day window (1-day incident TAT) is at risk on the day itself.
            return SlaState(AT_RISK, due, remaining)
    return SlaState(ON_TRACK, due, remaining)


# ---------------------------------------------------------------------------
# Policy lookup
# ---------------------------------------------------------------------------
async def policy_map(db: AsyncSession) -> dict[tuple[str, Severity], SlaPolicy]:
    rows = (await db.scalars(select(SlaPolicy))).all()
    return {(r.entity_type, r.severity): r for r in rows}


def target_for(
    policies: dict[tuple[str, Severity], SlaPolicy], entity_type: str, severity: Severity
) -> tuple[int | None, int, str]:
    """``(target_days, warn_at_percent, escalate_to_role)`` for one scope.

    A configured-but-disabled policy switches the clock **off** for that scope and
    returns no target; an absent policy falls back to the shipped default, so a fresh
    installation measures something sensible from day one.
    """
    policy = policies.get((entity_type, severity))
    if policy is not None:
        if not policy.enabled:
            return None, policy.warn_at_percent, policy.escalate_to_role
        return policy.target_days, policy.warn_at_percent, policy.escalate_to_role
    default = DEFAULT_TARGETS.get(entity_type, {}).get(severity)
    return default, DEFAULT_WARN_PERCENT, ""


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------
async def reconcile(db: AsyncSession, tenant_id) -> list[TatRecord]:
    """Recompute every open record's TAT window; return those now at risk or breached.

    Idempotent. ``tat_breached_at`` is stamped only the first time a window lapses, so
    it records *when* the breach happened even if the policy is later relaxed; it is
    cleared if the record's due date moves back into the future (a severity downgrade,
    or a longer policy), because a record that is no longer late should not keep
    reporting as historically late.
    """
    from app.services.risk_scoring import max_score_for
    from app.services.risk_settings import get_matrix_size

    policies = await policy_map(db)
    bands = max_score_for(await get_matrix_size(db, tenant_id))
    today = date.today()
    flagged: list[TatRecord] = []

    for spec in ENTITIES.values():
        stmt = select(spec.model)
        if hasattr(spec.model, "deleted"):
            stmt = stmt.where(spec.model.deleted.is_(False))
        for row in (await db.scalars(stmt)).all():
            open_now = spec.is_open(row)
            if not open_now:
                # A closed record keeps whatever breach history it earned, but stops
                # carrying a live due date that would re-alert forever.
                row.tat_due_date = None
                continue

            severity = spec.severity_of(row, bands)
            target, warn_pct, _role = target_for(policies, spec.key, severity)
            started = _started_on(row)
            if target is None or started is None:
                row.tat_due_date = None
                continue

            due = due_from(started, target)
            row.tat_due_date = due
            state = state_of(started, due, today=today, warn_at_percent=warn_pct)

            if state.state == BREACHED:
                if row.tat_breached_at is None:
                    row.tat_breached_at = today
            elif row.tat_breached_at is not None:
                row.tat_breached_at = None

            if state.state in (AT_RISK, BREACHED):
                flagged.append(
                    TatRecord(
                        entity_type=spec.key,
                        entity_label=spec.label,
                        entity_id=row.id,
                        label=spec.label_of(row),
                        severity=severity.value,
                        due=due,
                        days_overdue=max(0, -(state.days_remaining or 0)),
                        link=spec.link,
                    )
                )

    await db.flush()
    flagged.sort(key=lambda r: (-r.days_overdue, r.due or today))
    return flagged


def _started_on(row) -> date | None:
    """When the clock started — the record's creation date."""
    created = getattr(row, "created_at", None)
    if created is None:
        return None
    return created.date() if hasattr(created, "date") else created


async def summary(db: AsyncSession, tenant_id) -> dict:
    """Reconcile, then roll up for the dashboard widget and the sign-in reminder."""
    flagged = await reconcile(db, tenant_id)
    breached = [r for r in flagged if r.days_overdue > 0]
    at_risk = [r for r in flagged if r.days_overdue == 0]

    by_type: dict[str, dict[str, int]] = {}
    for record in flagged:
        bucket = by_type.setdefault(
            record.entity_type, {"label": ENTITIES[record.entity_type].label, "breached": 0, "at_risk": 0}
        )
        bucket["breached" if record.days_overdue > 0 else "at_risk"] += 1

    return {
        "breached": len(breached),
        "at_risk": len(at_risk),
        "by_type": [
            {"entity_type": key, **counts} for key, counts in sorted(by_type.items())
        ],
        "records": flagged,
    }


async def escalation_recipients(db: AsyncSession, entity_type: str, severity: Severity) -> list[str]:
    """Email addresses of the role a breach on this scope escalates to.

    Notifications are tenant-wide rather than addressed to individuals, so escalation is
    delivered by email to the members of the configured role — which is also what a bank
    means by escalation: the line above the owner is told, in writing.
    """
    from app.models.identity import Role, User

    policies = await policy_map(db)
    _target, _warn, role_name = target_for(policies, entity_type, severity)
    if not role_name:
        return []
    role = await db.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        return []
    users = (await db.scalars(select(User).where(User.is_active.is_(True)))).all()
    return sorted({u.email for u in users for r in u.roles if r.id == role.id and u.email})
