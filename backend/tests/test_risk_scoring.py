"""Pure unit tests for risk scoring and review scheduling (no DB required)."""
from datetime import date

import pytest

from app.models.enums import ReviewFrequency, Severity
from app.services.risk_scoring import (
    add_months,
    next_review_date,
    score,
    severity_for_score,
)


def test_score_is_product():
    assert score(4, 5) == 20
    assert score(1, 1) == 1


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (1, Severity.low),
        (4, Severity.low),
        (5, Severity.medium),
        (9, Severity.medium),
        (10, Severity.high),
        (14, Severity.high),
        (15, Severity.critical),
        (25, Severity.critical),
    ],
)
def test_severity_bands(value, expected):
    assert severity_for_score(value) == expected


def test_add_months_clamps_end_of_month():
    # Jan 31 + 1 month -> Feb 28 (2025 is not a leap year)
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    # Crosses year boundary
    assert add_months(date(2025, 11, 30), 3) == date(2026, 2, 28)


def test_next_review_date():
    anchor = date(2025, 1, 15)
    assert next_review_date(ReviewFrequency.quarterly, anchor) == date(2025, 4, 15)
    assert next_review_date(ReviewFrequency.annual, anchor) == date(2026, 1, 15)
    assert next_review_date(ReviewFrequency.none, anchor) is None
