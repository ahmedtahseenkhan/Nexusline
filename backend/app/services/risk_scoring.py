"""Pure functions for risk scoring and review scheduling.

Kept dependency-free so they are trivial to unit-test and later reuse from an
AI-assisted scoring service.

**Matrix size.** The likelihood x impact matrix is per-tenant configurable (3x3 to 6x6)
because banks baseline their register on different methodologies — ISO 27005 and ISO
31000 do not mandate a 5x5. Severity bands therefore cannot be fixed integers; they are
expressed as fractions of the maximum possible score and resolved against whatever
``max_score`` the tenant's matrix produces. At the default 5x5 (max 25) the fractions
reproduce the original hard-coded bands exactly — 1-4 low, 5-9 medium, 10-14 high,
15-25 critical — so an installation that never touches the setting sees no change.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models.enums import ReviewFrequency, Severity

_ONE_DAY = timedelta(days=1)

#: Matrix sizes a tenant may configure. Below 3 the bands collapse; above 6 the scale
#: stops being a usable qualitative judgement.
MIN_MATRIX_SIZE = 3
MAX_MATRIX_SIZE = 6
DEFAULT_MATRIX_SIZE = 5
DEFAULT_MAX_SCORE = DEFAULT_MATRIX_SIZE * DEFAULT_MATRIX_SIZE  # 25

# Upper bound of each band as a fraction of the maximum score. Derived from the original
# 5x5 bands (4/25, 9/25, 14/25) so the default matrix is bit-for-bit unchanged.
_BAND_FRACTIONS: tuple[float, float, float] = (0.16, 0.36, 0.56)

#: Cycles shorter than a month are scheduled in days: "add half a month" has no calendar
#: meaning, whereas a fortnight is exactly 14 days and lands on the same weekday, which
#: is what makes a fortnightly audit or control test schedulable by a team.
_FREQUENCY_DAYS: dict[ReviewFrequency, int] = {
    ReviewFrequency.fortnightly: 14,
}

_FREQUENCY_MONTHS: dict[ReviewFrequency, int] = {
    ReviewFrequency.monthly: 1,
    ReviewFrequency.quarterly: 3,
    ReviewFrequency.semiannual: 6,
    ReviewFrequency.annual: 12,
}


def score(likelihood: int, impact: int) -> int:
    return likelihood * impact


def max_score_for(matrix_size: int) -> int:
    return matrix_size * matrix_size


def band_ranges(max_score: int = DEFAULT_MAX_SCORE) -> list[tuple[int, int, Severity]]:
    """Inclusive ``(low, high, severity)`` bands covering 1..``max_score``.

    Each band's upper bound is its fraction of ``max_score``, floored, and then nudged
    up if rounding would leave the band empty — on a 3x3 matrix two fractions land on
    the same integer, and a band no score can fall into would silently disappear from
    the heat-map legend.
    """
    bounds: list[int] = []
    previous = 0
    for fraction in _BAND_FRACTIONS:
        upper = max(int(max_score * fraction), previous + 1)
        bounds.append(upper)
        previous = upper
    low_max, medium_max, high_max = bounds
    return [
        (1, low_max, Severity.low),
        (low_max + 1, medium_max, Severity.medium),
        (medium_max + 1, high_max, Severity.high),
        (high_max + 1, max(max_score, high_max + 1), Severity.critical),
    ]


def severity_for_score(
    value: int | None, max_score: int = DEFAULT_MAX_SCORE
) -> Severity | None:
    """Band a score. ``max_score`` defaults to the 5x5 matrix, so callers without a
    tenant context (and every pre-existing caller) behave exactly as before."""
    if value is None:
        return None
    for low, high, sev in band_ranges(max_score):
        if low <= value <= high:
            return sev
    return Severity.critical if value > max_score else Severity.low


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
    days = _FREQUENCY_DAYS.get(frequency)
    if days is not None:
        return (anchor or date.today()) + timedelta(days=days)
    months = _FREQUENCY_MONTHS.get(frequency)
    if months is None:
        return None
    return add_months(anchor or date.today(), months)
