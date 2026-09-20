"""The governance-health score, and why it is the number it is.

A single 0-100 figure on a dashboard is only worth showing if the reader can see what
moved it. This module makes the score a weighted mean of a few named components, each
a percentage the organisation can act on, and returns the components alongside the
score so the page can show "68 — because 42% of controls are assured" rather than a
gauge with no explanation.

The components follow what risk and compliance functions are actually judged on:

* **Within tolerance** — the share of risks whose effective score is at or under the
  tolerance that applies to them: their top-level category's where one is set, else the
  organisation's. The board question: are we inside the boundary we set? Taken over the
  *board register* (``risk_query.board_register_clause``): scored, out of Draft, not
  accepted or closed. An unowned draft nobody validated is not a board number (F-21);
  the dashboard reports those as "pending validation" beside the score instead.
* **Control assurance** — the share of controls that are effective or partially
  effective. Mapped-but-untested does not count; a promise is not assurance.
* **Compliance assured** — the share of applicable clauses backed by a working
  control. Same rule as the gap analysis, so the two can never disagree.
* **Nothing overdue** — the share of tracked deadlines (reviews, tests, treatments,
  issues) that are not past due. A register that is never revisited decays.

Weights favour the first two because they describe exposure today; the last two
describe the discipline that keeps it that way. Everything here is pure: the endpoint
gathers the counts, this module turns them into a number and its reasons.

**An empty measure is not a green one.** A component with nothing behind it (no risks,
no controls, no applicable clauses, no tracked deadlines) has no value at all: it is left
out of the score and the remaining weights are re-normalised, and the page says what the
score was actually computed on ("scored on 2 of 4 measures, 55 % of weight"). Treating
"no risks" as "100 % within tolerance" is how a controls-only tenant used to collect two
free full-marks components.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    #: 0-100, or None when there is nothing to measure (``population == 0``).
    value: float | None
    weight: float
    #: One line the page shows under the component — the raw counts behind the %.
    detail: str
    #: How many records the percentage is taken over. Zero means "no data": the
    #: component is excluded from the score rather than counted as 0 % or 100 %.
    population: int = 0
    #: The rule behind the number, in plain words, for the "how is this calculated" note.
    formula: str = ""

    @property
    def scored(self) -> bool:
        return self.population > 0


def pct(numerator: int, denominator: int) -> float | None:
    """Percentage of ``denominator``; None when there is nothing to take a share of.

    There is deliberately no "empty" default: an empty population is neither 0 % nor
    100 %, it is unknown, and the caller decides what unknown means (here: excluded).
    """
    if denominator <= 0:
        return None
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
            0.35, f"{risks_within_tolerance} of {risks_total} validated risks at or under tolerance",
            population=max(risks_total, 0),
            formula="Risks whose current score (residual if assessed, otherwise inherent) is at "
                    "or under their tolerance — the top-level risk category's where one is set, "
                    "otherwise the organisation's — as a share of validated risks: scored, out "
                    "of Draft, and not accepted or closed. Drafts are left out until validated.",
        ),
        Component(
            "assurance", "Control assurance",
            pct(controls_assured, controls_total),
            0.30, f"{controls_assured} of {controls_total} operating controls effective or partially effective",
            population=max(controls_total, 0),
            formula="Controls rated effective or partially effective by their last test, as a "
                    "share of controls that are implemented or operational. Mapped but untested "
                    "counts as not assured; planned and retired controls are left out.",
        ),
        Component(
            "compliance", "Compliance assured",
            pct(clauses_assured, clauses_applicable),
            0.20, f"{clauses_assured} of {clauses_applicable} applicable clauses backed by a working control",
            population=max(clauses_applicable, 0),
            formula="Applicable clauses of compliance frameworks backed by at least one working "
                    "control, as a share of all applicable clauses. Maturity and guidance "
                    "frameworks are not counted.",
        ),
        Component(
            "discipline", "Nothing overdue",
            pct(deadlines_total - deadlines_overdue, deadlines_total),
            0.15, f"{deadlines_overdue} of {deadlines_total} tracked deadlines past due",
            population=max(deadlines_total, 0),
            formula="Tracked deadlines (risk reviews, open risk-treatment actions — or the "
                    "treatment deadline of a risk with no actions — tests of operating "
                    "controls, policy reviews, issue and audit-finding due dates) that are not "
                    "yet past due, as a share of all of them.",
        ),
    ]


def scored_parts(parts: list[Component]) -> list[Component]:
    """The components that have a population behind them."""
    return [c for c in parts if c.scored and c.value is not None]


def score(parts: list[Component]) -> int:
    """Weighted mean of the scored components, weights re-normalised over them.

    Returns 0 when nothing is scored; callers pair it with :func:`has_data` so that
    case is shown as "no data", never as a critical 0.
    """
    live = scored_parts(parts)
    total_weight = sum(c.weight for c in live)
    if total_weight <= 0:
        return 0
    return int(round(sum(c.value * c.weight for c in live) / total_weight))  # type: ignore[operator]


@dataclass(frozen=True)
class Coverage:
    """What the score was actually computed on."""

    #: Components with data behind them.
    scored: int
    #: Components the score is defined over.
    total: int
    #: Share of the full weight those scored components carry, 0-100.
    weight_pct: float


def coverage(parts: list[Component]) -> Coverage:
    total_weight = sum(c.weight for c in parts) or 1.0
    live = scored_parts(parts)
    return Coverage(
        scored=len(live),
        total=len(parts),
        weight_pct=round(100.0 * sum(c.weight for c in live) / total_weight, 1),
    )


#: Band for an organisation with nothing to score yet — no risks, no controls, no
#: clauses, no deadlines. A number here would be arithmetic on an empty set.
NO_DATA = "no_data"


def has_data(parts: list[Component]) -> bool:
    """Whether any component has a population behind it.

    An empty tenant is not healthy and it is not critical — there is nothing to
    judge. Scoring one anyway is how a freshly wiped system reported 70/100.
    """
    return any(c.population > 0 for c in parts)


def band(value: int, *, data: bool = True) -> str:
    """Healthy / Elevated / Critical, on the same thresholds the gauge colours."""
    if not data:
        return NO_DATA
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
