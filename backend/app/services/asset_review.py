"""An asset's review clock: what may move it, and keeping its schedule in step.

An asset carries its next review date, and its review history carries scheduled and
completed review records. Two ways the two drifted apart, both closed here:

* **A date edit is not a review.** Editing ``next_review_date`` — one asset or a bulk
  selection — turned an overdue review "current" without anyone reviewing anything, and
  the scheduled review record kept its old date. An overdue review can now only be
  cleared by completing it; a date inside the cycle can still be moved, and the pending
  review record moves with it.
* **Completing a review schedules the next one.** Completion stamped the dates on the
  asset but left no scheduled review for the next cycle, and the record named the
  planned reviewer, not the person who did it.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from app.models.enums import AssetReviewStatus, ReviewFrequency
from app.services.risk_scoring import next_review_date


def _freq(value: Any) -> ReviewFrequency | None:
    if value is None:
        return None
    return value if isinstance(value, ReviewFrequency) else ReviewFrequency(getattr(value, "value", value))


def date_change_problem(
    current: date | None, new: date | None, frequency: Any, today: date
) -> str | None:
    """Why ``next_review_date`` may not move from ``current`` to ``new``, or None. Pure.

    * An overdue review can't be pushed later (or cleared): complete it instead.
    * A date can't be set past one full cycle from today — a review that far out is a
      skipped cycle, which is a decision to change the frequency, not the date.
    Bringing a review earlier is always allowed."""
    if new == current:
        return None
    if current is not None and current < today and (new is None or new > current):
        return (
            f"its review has been overdue since {current.isoformat()} — complete the review "
            "to set the next date; changing the date doesn't count as a review"
        )
    if new is None:
        if _freq(frequency) not in (None, ReviewFrequency.none):
            return (
                "clearing it takes the asset off its review cycle without a decision — set "
                "the review frequency to 'none' instead"
            )
        return None
    if new is not None:
        latest = next_review_date(_freq(frequency) or ReviewFrequency.annual, today)
        if latest is not None and new > latest:
            label = (_freq(frequency) or ReviewFrequency.annual).value.replace("_", " ")
            return (
                f"{new.isoformat()} is more than one {label} cycle away; the latest is "
                f"{latest.isoformat()} — change the review frequency to review less often"
            )
    return None


async def pending_review(db, asset_id) -> Any:
    """The asset's earliest scheduled (not yet completed) review record, or None."""
    from app.models.asset import AssetReview

    return await db.scalar(
        select(AssetReview)
        .where(AssetReview.asset_id == asset_id, AssetReview.status == AssetReviewStatus.scheduled)
        .order_by(AssetReview.scheduled_date.asc())
        .limit(1)
    )


async def sync_schedule(db, asset: Any, *, reviewer: str = "") -> None:
    """Make the pending review record carry the asset's ``next_review_date``: move the
    earliest scheduled one, or schedule one when there is none."""
    from app.models.asset import AssetReview

    due = asset.next_review_date
    if due is None:
        return
    pending = await pending_review(db, asset.id)
    if pending is not None:
        pending.scheduled_date = due
        return
    db.add(AssetReview(
        tenant_id=asset.tenant_id, asset_id=asset.id, reviewer=reviewer,
        scheduled_date=due, status=AssetReviewStatus.scheduled,
    ))


def completer_name(user: Any) -> str:
    return (getattr(user, "full_name", "") or getattr(user, "email", "") or "")[:200]
