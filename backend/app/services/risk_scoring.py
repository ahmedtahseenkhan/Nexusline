"""Pure functions for risk scoring and review scheduling.

Kept dependency-free so they are trivial to unit-test and later reuse from an
AI-assisted scoring service.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models.enums import ReviewFrequency, Severity

_ONE_DAY = timedelta(days=1)

# 5x5 matrix → severity bands (score = likelihood x impact, 1..25)
_BANDS: list[tuple[int, int, Severity]] = [
    (1, 4, Severity.low),
    (5, 9, Severity.medium),
    (10, 14, Severity.high),
    (15, 25, Severity.critical),
]

_FREQUENCY_MONTHS: dict[ReviewFrequency, int] = {
    ReviewFrequency.monthly: 1,
    ReviewFrequency.quarterly: 3,
    ReviewFrequency.semiannual: 6,
    ReviewFrequency.annual: 12,
}


def score(likelihood: int, impact: int) -> int:
    return likelihood * impact


def severity_for_score(value: int | None) -> Severity | None:
    if value is None:
        return None
    for low, high, sev in _BANDS:
        if low <= value <= high:
            return sev
    return Severity.critical if value > 25 else Severity.low


def effective_score(inherent: int | None, residual: int | None) -> int | None:
    """The score that represents current exposure: residual if assessed, else inherent."""
    return residual if residual is not None else inherent


def appetite_status(score: int | None, appetite: int, tolerance: int) -> str | None:
    """Classify a risk against the org's appetite/tolerance thresholds.

    within_appetite: at/below appetite · elevated: above appetite, at/below tolerance ·
    breach: above tolerance (should trigger an alert).
    """
    if score is None:
        return None
    if score <= appetite:
        return "within_appetite"
    if score <= tolerance:
        return "elevated"
    return "breach"


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to the last valid day of the target month.
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = (next_month_first - _ONE_DAY).day
    return date(year, month, min(start.day, last_day))


def next_review_date(
    frequency: ReviewFrequency, anchor: date | None = None
) -> date | None:
    """Compute the next review date from a frequency and an anchor date."""
    if frequency == ReviewFrequency.none:
        return None
    months = _FREQUENCY_MONTHS.get(frequency)
    if months is None:
        return None
    return add_months(anchor or date.today(), months)
