"""The governance-health score, and why it is the number it is.

A single 0-100 figure on a dashboard is only worth showing if the reader can see what
moved it. This module makes the score a weighted mean of a few named components, each
a percentage the organisation can act on, and returns the components alongside the
score so the page can show "68 — because 42% of controls are assured" rather than a
gauge with no explanation.

The components follow what risk and compliance functions are actually judged on:

* **Within tolerance** — the share of risks whose effective score is at or under the
  organisation's tolerance. The board question: are we inside the boundary we set?
* **Control assurance** — the share of controls that are effective or partially
  effective. Mapped-but-untested does not count; a promise is not assurance.
* **Compliance assured** — the share of applicable clauses backed by a working
  control. Same rule as the gap analysis, so the two can never disagree.
* **Nothing overdue** — the share of tracked deadlines (reviews, tests, treatments,
  issues) that are not past due. A register that is never revisited decays.

Weights favour the first two because they describe exposure today; the last two
describe the discipline that keeps it that way. Everything here is pure: the endpoint
gathers the counts, this module turns them into a number and its reasons.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    #: 0-100
    value: float
    weight: float
    #: One line the page shows under the component — the raw counts behind the %.
    detail: str


def pct(numerator: int, denominator: int, *, empty: float = 100.0) -> float:
    """Percentage, treating an empty denominator as ``empty`` — no risks means nothing
    is out of tolerance, but no controls means nothing is assured."""
    if denominator <= 0:
        return empty
    return round(100.0 * numerator / denominator, 1)


def components(
    *,
    risks_total: int,
    risks_within_tolerance: int,
    controls_total: int,
    controls_assured: int,
    clauses_applicable: int,
    clauses_assured: int,
    deadlines_total: int,
    deadlines_overdue: int,
) -> list[Component]:
    return [
        Component(
            "tolerance", "Within tolerance",
            pct(risks_within_tolerance, risks_total),
            0.35, f"{risks_within_tolerance} of {risks_total} risks at or under tolerance",
        ),
        Component(
            "assurance", "Control assurance",
            pct(controls_assured, controls_total, empty=0.0),
            0.30, f"{controls_assured} of {controls_total} controls effective or partially effective",
        ),
        Component(
            "compliance", "Compliance assured",
            pct(clauses_assured, clauses_applicable, empty=0.0),
            0.20, f"{clauses_assured} of {clauses_applicable} applicable clauses backed by a working control",
        ),
        Component(
            "discipline", "Nothing overdue",
            pct(deadlines_total - deadlines_overdue, deadlines_total),
            0.15, f"{deadlines_overdue} of {deadlines_total} tracked deadlines past due",
        ),
    ]


def score(parts: list[Component]) -> int:
    total_weight = sum(c.weight for c in parts) or 1.0
    return int(round(sum(c.value * c.weight for c in parts) / total_weight))


def band(value: int) -> str:
    """Healthy / Elevated / Critical, on the same thresholds the gauge colours."""
    if value >= 80:
        return "healthy"
    if value >= 60:
        return "elevated"
    return "critical"


def kri_status(
    current: float | None, warning: float | None, limit: float | None, direction: str
) -> str:
    """RAG for a key risk indicator from its value and thresholds.

    ``direction`` is which way is bad: "above" (breaches when the value climbs past the
    threshold, e.g. failed logins) or "below" (breaches when it falls, e.g. liquidity
    cover). No value means no data, never green — silence is not comfort.
    """
    if current is None:
        return "no_data"
    worse = (lambda v, t: v >= t) if (direction or "above") != "below" else (lambda v, t: v <= t)
    if limit is not None and worse(current, limit):
        return "red"
    if warning is not None and worse(current, warning):
        return "amber"
    return "green"
