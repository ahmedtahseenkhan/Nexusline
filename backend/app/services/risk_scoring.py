"""Pure functions for risk scoring and review scheduling.

Kept dependency-free so they are trivial to unit-test and later reuse from an
AI-assisted scoring service.

**Matrix size.** The likelihood x impact matrix is per-tenant configurable (3x3 to
10x10) because banks baseline their register on different methodologies — ISO 27005 and
ISO 31000 do not mandate a 5x5, and a bank whose board-approved ERM matrix runs 1-10
must be able to say so rather than re-score its whole register to fit us. Severity bands
therefore cannot be fixed integers; they are expressed as fractions of the maximum
possible score and resolved against whatever ``max_score`` the tenant's matrix produces.
At the default 5x5 (max 25) the fractions reproduce the original hard-coded bands
exactly — 1-4 low, 5-9 medium, 10-14 high, 15-25 critical — so an installation that
never touches the setting sees no change.

**Configured bands and cells (phase 2).** A bank's methodology usually states its own
thresholds ("15 and above is critical"), and some matrices are not symmetric — a 2x5
(rare but catastrophic) may be rated high even though 10 falls in the medium band.
``RiskSetting.severity_bands`` (``{low_max, medium_max, high_max}``) replaces the
fractions when set, and ``RiskSetting.matrix_cells`` (``{"L,I": band}``) overrides the
band of individual cells. :class:`SeverityScale` carries all three (matrix maximum,
bands, cell overrides) so a caller bands a risk the way the heat map colours it.
Without configuration every function here behaves exactly as before.
"""
from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core.risk_scale import DEFAULT_MATRIX_SIZE, MAX_MATRIX_SIZE, MIN_MATRIX_SIZE
from app.models.enums import ReviewFrequency, Severity

__all__ = [
    "DEFAULT_MATRIX_SIZE", "DEFAULT_MAX_SCORE", "MAX_MATRIX_SIZE", "MIN_MATRIX_SIZE",
    "AppetiteBook", "IMPACT_MODES", "SEVERITY_VALUES", "SeverityScale",
    "add_months", "appetite_status", "band_ranges", "cell_key", "effective_score",
    "impact_from_dimensions", "max_score_for", "next_review_date", "parse_cell_key",
    "score", "severity_for_score", "validate_bands", "validate_cells",
]

_ONE_DAY = timedelta(days=1)

# The matrix bounds live in ``app.core.risk_scale`` and are re-exported here, because
# the ORM constraints and the DDL patches need them too and neither can import a service
# without closing an import cycle through the models package.
DEFAULT_MAX_SCORE = DEFAULT_MATRIX_SIZE * DEFAULT_MATRIX_SIZE  # 25

# Upper bound of each band as a fraction of the maximum score. Derived from the original
# 5x5 bands (4/25, 9/25, 14/25) so the default matrix is bit-for-bit unchanged.
_BAND_FRACTIONS: tuple[float, float, float] = (0.16, 0.36, 0.56)

#: Cycles shorter than a month are scheduled in days: "add half a month" has no calendar
#: meaning, whereas a fortnight is exactly 14 days and lands on the same weekday, which
#: is what makes a fortnightly audit or control test schedulable by a team.
_FREQUENCY_DAYS: dict[ReviewFrequency, int] = {
    ReviewFrequency.daily: 1,
    ReviewFrequency.weekly: 7,
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


#: The four bands, lowest first — also the order a matrix-editor cell cycles through.
SEVERITY_VALUES: tuple[str, ...] = tuple(s.value for s in Severity)

#: How per-dimension impact scores combine into the overall impact.
#: ``max`` — the worst dimension decides (the usual bank rule: a risk that is minor
#: financially but severe for the regulator is severe). ``average`` — the mean, rounded
#: up so a split never understates.
IMPACT_MODES: tuple[str, ...] = ("max", "average")


def validate_bands(bands: Mapping | None, max_score: int) -> tuple[int, int, int] | None:
    """Check configured band thresholds; return them as a tuple, or None when unset.

    ``bands`` is ``{"low_max", "medium_max", "high_max"}`` — the highest score in each of
    the first three bands; everything above ``high_max`` is critical. They must be
    strictly increasing, start at 1 or more, and leave room for a critical band
    (``high_max < max_score``), so all four bands exist on the matrix. Raises
    ``ValueError`` with a sentence a user can act on.
    """
    if not bands:
        return None
    try:
        low, medium, high = (int(bands[k]) for k in ("low_max", "medium_max", "high_max"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Give all three thresholds: low_max, medium_max and high_max") from exc
    if not 1 <= low < medium < high:
        raise ValueError(
            "Band thresholds must increase: low up to low_max, medium up to medium_max, "
            "high up to high_max"
        )
    if high >= max_score:
        raise ValueError(
            f"high_max must be below the matrix maximum of {max_score}, or no score would be critical"
        )
    return low, medium, high


def cell_key(likelihood: int, impact: int) -> str:
    """The key a matrix cell is stored under in ``RiskSetting.matrix_cells``."""
    return f"{int(likelihood)},{int(impact)}"


def parse_cell_key(key: str) -> tuple[int, int]:
    likelihood, impact = (int(x) for x in str(key).split(","))
    return likelihood, impact


def validate_cells(cells: Mapping | None, size: int) -> dict[str, str]:
    """Check per-cell band overrides against the matrix; return them normalised.

    Keys are ``"likelihood,impact"`` within 1..``size``; values one of the four bands.
    Raises ``ValueError`` naming the first bad entry.
    """
    out: dict[str, str] = {}
    for key, band in (cells or {}).items():
        try:
            likelihood, impact = parse_cell_key(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Cell '{key}' is not 'likelihood,impact'") from exc
        if not (1 <= likelihood <= size and 1 <= impact <= size):
            raise ValueError(f"Cell '{key}' is outside the {size}x{size} matrix")
        if band not in SEVERITY_VALUES:
            raise ValueError(f"Cell '{key}': band must be one of {', '.join(SEVERITY_VALUES)}")
        out[cell_key(likelihood, impact)] = band
    return out


def band_ranges(
    max_score: int = DEFAULT_MAX_SCORE, bands: tuple[int, int, int] | Mapping | None = None
) -> list[tuple[int, int, Severity]]:
    """Inclusive ``(low, high, severity)`` bands covering 1..``max_score``.

    ``bands`` are the tenant's configured thresholds (``RiskSetting.severity_bands``, as a
    mapping or a validated tuple). Configured thresholds that no longer fit the matrix
    (it was shrunk) are ignored rather than trusted, and the fractions apply.

    Without them each band's upper bound is its fraction of ``max_score``, floored, and
    then nudged up if rounding would leave the band empty — on a 3x3 matrix two fractions
    land on the same integer, and a band no score can fall into would silently disappear
    from the heat-map legend.
    """
    configured = None
    if bands:
        try:
            configured = validate_bands(bands if isinstance(bands, Mapping) else dict(
                zip(("low_max", "medium_max", "high_max"), bands)
            ), max_score)
        except ValueError:
            configured = None
    if configured is not None:
        low_max, medium_max, high_max = configured
        return [
            (1, low_max, Severity.low),
            (low_max + 1, medium_max, Severity.medium),
            (medium_max + 1, high_max, Severity.high),
            (high_max + 1, max_score, Severity.critical),
        ]
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
    value: int | None,
    max_score: int = DEFAULT_MAX_SCORE,
    bands: tuple[int, int, int] | Mapping | None = None,
) -> Severity | None:
    """Band a score. ``max_score`` defaults to the 5x5 matrix, so callers without a
    tenant context (and every pre-existing caller) behave exactly as before; ``bands``
    are the tenant's configured thresholds, when it has any."""
    if value is None:
        return None
    for low, high, sev in band_ranges(max_score, bands):
        if low <= value <= high:
            return sev
    return Severity.critical if value > max_score else Severity.low


@dataclass(frozen=True)
class SeverityScale:
    """Everything needed to band a risk the way the heat map colours it.

    ``bands`` — configured thresholds (validated tuple) or None for the fractions;
    ``cells`` — per-cell overrides ``{"L,I": band}``. Build one per request with
    ``risk_settings.get_severity_scale`` and pass it wherever a risk is banded.
    """

    max_score: int = DEFAULT_MAX_SCORE
    bands: tuple[int, int, int] | None = None
    cells: Mapping[str, str] = field(default_factory=dict)

    def ranges(self) -> list[tuple[int, int, Severity]]:
        return band_ranges(self.max_score, self.bands)

    def for_score(self, value: int | None) -> Severity | None:
        return severity_for_score(value, self.max_score, self.bands)

    def for_cell(self, likelihood: int | None, impact: int | None) -> Severity | None:
        """The cell's band: its override when one is set, else its score's band."""
        if not likelihood or not impact:
            return None
        override = self.cells.get(cell_key(likelihood, impact)) if self.cells else None
        if override in SEVERITY_VALUES:
            return Severity(override)
        return self.for_score(likelihood * impact)

    def for_risk(
        self,
        inherent_likelihood: int | None,
        inherent_impact: int | None,
        residual_likelihood: int | None,
        residual_impact: int | None,
    ) -> Severity | None:
        """Band of the effective cell: residual when assessed, else inherent."""
        if residual_likelihood and residual_impact:
            return self.for_cell(residual_likelihood, residual_impact)
        return self.for_cell(inherent_likelihood, inherent_impact)


def impact_from_dimensions(scores: Iterable[int], mode: str = "max") -> int | None:
    """Combine per-dimension impact scores into the overall impact.

    ``max`` takes the worst dimension; ``average`` the mean rounded up (3 and 4 make 4).
    None when no dimension is scored. An unknown mode is treated as ``max``, the
    conservative reading.
    """
    values = [int(v) for v in scores if v is not None]
    if not values:
        return None
    if mode == "average":
        return math.ceil(sum(values) / len(values))
    return max(values)


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


@dataclass
class AppetiteBook:
    """Appetite and tolerance per top-level risk category, with the tenant default.

    A risk takes its thresholds from the level-1 category above its own category
    (``parents`` walks ``Lookup.parent_id`` up), and from the organisation-wide
    ``RiskSetting`` values when that category has none — so a register with no
    per-category appetite behaves exactly as before. Pure; loaded by
    ``risk_settings.load_appetite_book``.
    """

    appetite: int = 6
    tolerance: int = 12
    #: level-1 category id -> (appetite, tolerance)
    by_category: dict[uuid.UUID, tuple[int, int]] = field(default_factory=dict)
    #: risk_category lookup id -> its parent id (None for a level-1 value)
    parents: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)

    def top_of(self, category_id: uuid.UUID | None) -> uuid.UUID | None:
        """The level-1 category above ``category_id`` (itself when it is level 1)."""
        seen: set[uuid.UUID] = set()
        current = category_id
        while current is not None and current not in seen:
            seen.add(current)
            parent = self.parents.get(current)
            if parent is None:
                return current
            current = parent
        return current

    def source_of(self, category_id: uuid.UUID | None) -> uuid.UUID | None:
        """The level-1 category whose appetite applies, or None for the default."""
        top = self.top_of(category_id)
        return top if top in self.by_category else None

    def thresholds(self, category_id: uuid.UUID | None) -> tuple[int, int]:
        top = self.source_of(category_id)
        return self.by_category[top] if top is not None else (self.appetite, self.tolerance)

    def tolerance_for(self, category_id: uuid.UUID | None) -> int:
        return self.thresholds(category_id)[1]

    def status(self, score: int | None, category_id: uuid.UUID | None) -> str | None:
        appetite, tolerance = self.thresholds(category_id)
        return appetite_status(score, appetite, tolerance)

    @property
    def min_tolerance(self) -> int:
        """The lowest tolerance anywhere — a safe SQL pre-filter for breach scans."""
        return min([self.tolerance, *(t for _a, t in self.by_category.values())])


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
