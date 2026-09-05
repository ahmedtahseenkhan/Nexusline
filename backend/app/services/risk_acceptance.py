"""Lapsing risk acceptances when their approval runs out.

An accepted risk is the one place in the register where "do nothing" is a *decision*
rather than an omission, and the whole reason a bank tolerates it is that the decision
has an expiry date on it. Storing that date and never acting on it is worse than not
having it: the register keeps reporting the risk as accepted long after the approval
lapsed, and the board pack says the exposure is governed when nobody has looked at it
for two years.

This module closes that loop. Once an approved acceptance passes its expiry the record
is marked ``expired``, and the risk is put back exactly where approving it took it from
— ``accepted`` / treatment ``accept`` reverts to ``assessed`` with no strategy, so it
re-enters the register as a risk awaiting a decision. Nothing is deleted: the
``RiskAcceptance`` row stays as the evidence that it *was* accepted, until when, and by
whom, and a system audit entry records the lapse.

Called from the scheduled sweep, so it needs no user; the trail attributes it to the
platform rather than implying somebody clicked something.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AcceptanceStatus, NotificationCategory, RiskStatus, TreatmentStrategy
from app.models.notification import EVENT_PREFIX, Notification
from app.models.risk import Risk, RiskAcceptance
from app.services import audit

#: How long before expiry the register starts chasing. A month is the shortest notice on
#: which a bank can realistically re-paper an acceptance: the owner has to restate the
#: rationale and a second person has to approve it.
EXPIRY_WARNING_DAYS = 30


@dataclass
class ExpiryResult:
    """What one tenant's sweep changed. Empty is the normal case."""

    expired: int = 0
    reopened: int = 0
    references: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # pragma: no cover - convenience for callers
        return bool(self.expired)


def is_lapsed(acceptance: RiskAcceptance, today: date) -> bool:
    """An approved acceptance whose expiry date has passed.

    Expiry is exclusive of the day itself: an acceptance valid "until 31 December" is
    still in force on the 31st and lapses on 1 January. An acceptance with no expiry
    date never lapses — an open-ended acceptance is a policy choice, not an oversight
    this job should second-guess.
    """
    return (
        acceptance.status == AcceptanceStatus.approved
        and acceptance.expires_at is not None
        and acceptance.expires_at < today
    )


def expires_within(acceptance: RiskAcceptance, today: date, days: int) -> bool:
    """In force now, but due to lapse inside the warning window."""
    if acceptance.status != AcceptanceStatus.approved or acceptance.expires_at is None:
        return False
    return today <= acceptance.expires_at <= today + timedelta(days=days)


async def expire_lapsed(db: AsyncSession, tenant_id: uuid.UUID, today: date | None = None) -> ExpiryResult:
    """Lapse every approved acceptance past its expiry, and re-open its risk.

    Runs inside the caller's RLS-scoped transaction; the caller commits. ``today`` is
    injectable so the behaviour is testable without freezing the clock.
    """
    today = today or date.today()
    result = ExpiryResult()

    lapsed = (
        await db.scalars(
            select(RiskAcceptance).where(
                RiskAcceptance.status == AcceptanceStatus.approved,
                RiskAcceptance.expires_at.is_not(None),
                RiskAcceptance.expires_at < today,
            )
        )
    ).all()
    if not lapsed:
        return result

    for acceptance in lapsed:
        acceptance.status = AcceptanceStatus.expired
        result.expired += 1

        risk = await db.get(Risk, acceptance.risk_id)
        if risk is None or risk.deleted:
            continue

        # Only reverse what approving actually set. A risk somebody has since moved on
        # to treatment, or closed, is left alone — the acceptance lapsing is not a
        # reason to drag a closed risk back open.
        reopened = False
        if risk.status == RiskStatus.accepted:
            risk.status = RiskStatus.assessed
            reopened = True
        if risk.treatment_strategy == TreatmentStrategy.accept:
            # Leaving "accept" in place would have the register report a strategy the
            # bank no longer has approval for, which is the misstatement this job exists
            # to prevent. The decision itself survives on the RiskAcceptance row.
            risk.treatment_strategy = None
            reopened = True

        if reopened:
            result.reopened += 1
            result.references.append(risk.reference or risk.title)

        # An `event:` notification rather than a scanned alert: the lapse is something
        # that *happened* on a date, not a condition that can later become false, so it
        # must survive the reconciler that clears resolved alerts on every read.
        db.add(
            Notification(
                tenant_id=tenant_id,
                title=f"Risk acceptance expired: {risk.reference or risk.title}",
                body=(
                    f"The approved acceptance lapsed on {acceptance.expires_at}. "
                    + (
                        "The risk is back in the register awaiting a fresh decision."
                        if reopened
                        else "The risk had already moved on, so its status is unchanged."
                    )
                ),
                category=NotificationCategory.critical if reopened else NotificationCategory.warning,
                entity_type="risk",
                entity_id=risk.id,
                link="/risks",
                dedup_key=f"{EVENT_PREFIX}acceptance-expired:{acceptance.id}",
            )
        )

        await audit.record_system(
            db,
            tenant_id=tenant_id,
            action="expire_acceptance",
            entity_type="risk_acceptance",
            entity_id=acceptance.id,
            summary=(
                f"Acceptance for risk {risk.reference or risk.title} lapsed on "
                f"{acceptance.expires_at}"
                + (" — risk returned to the register" if reopened else "")
            ),
            changes={
                "expires_at": str(acceptance.expires_at),
                "risk_id": str(risk.id),
                "reopened": reopened,
            },
        )

    await db.flush()
    return result
