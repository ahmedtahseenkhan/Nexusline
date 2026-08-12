"""Suggest a residual risk score from the effectiveness of the linked controls.

**The system suggests; the risk owner decides.** ISO 27005 and ISO 31000 both treat
residual risk as an assessed judgement made *after* considering control effectiveness —
not as an arithmetic output. A number a tool produced on its own, with no owner
acceptance and no reasoning on the record, is a finding waiting to happen when a
regulator asks "why is this residual 6?". So this module never writes a residual: it
returns a proposal plus a line-by-line rationale, which the API offers for explicit
acceptance or override-with-reason.

What the suggestion is worth is entirely down to the tenant's policy: how much credit a
control earns per effectiveness rating, whether that credit reduces likelihood, impact
or both, and the maximum credit any one risk may accumulate. The defaults below are
deliberately conservative and reduce **likelihood only** — controls generally change how
often something happens, not how badly it hurts when it does. A bank whose methodology
says otherwise changes the policy, not the code.

Controls that are *not currently working* earn nothing. A failed audit, an open audit
finding or an overdue test means the control cannot be relied on today, so it drops out
of the calculation and says so in the rationale — which is what makes the suggestion
move back up on its own when assurance lapses.

Pure and dependency-free (like ``risk_scoring``) so the arithmetic is unit-testable
without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import ControlEffectiveness

__all__ = [
    "ControlInput",
    "ResidualPolicySpec",
    "ResidualSuggestion",
    "DEFAULT_POLICY",
    "suggest_residual",
]

#: Where a control's credit is applied.
APPLIES_LIKELIHOOD = "likelihood"
APPLIES_IMPACT = "impact"
APPLIES_BOTH = "both"
APPLIES_TO_CHOICES = (APPLIES_LIKELIHOOD, APPLIES_IMPACT, APPLIES_BOTH)


@dataclass(frozen=True)
class ResidualPolicySpec:
    """A tenant's reduction rules. Mirrors the ``ResidualPolicy`` row."""

    weight_effective: int = 2
    weight_partially_effective: int = 1
    weight_ineffective: int = 0
    weight_not_assessed: int = 0
    applies_to: str = APPLIES_LIKELIHOOD
    max_reduction: int = 3
    enabled: bool = True

    def weight_for(self, effectiveness: ControlEffectiveness | None) -> int:
        return {
            ControlEffectiveness.effective: self.weight_effective,
            ControlEffectiveness.partially_effective: self.weight_partially_effective,
            ControlEffectiveness.ineffective: self.weight_ineffective,
            ControlEffectiveness.not_assessed: self.weight_not_assessed,
        }.get(effectiveness, 0)  # type: ignore[arg-type]


DEFAULT_POLICY = ResidualPolicySpec()


@dataclass(frozen=True)
class ControlInput:
    """One mitigating control as the engine sees it.

    ``healthy`` is False when the control cannot be relied on right now — a failed
    audit, an overdue test, or an open finding against it. ``health_note`` explains
    which, so the rationale can say *why* a control earned nothing.
    """

    label: str
    effectiveness: ControlEffectiveness | None
    healthy: bool = True
    health_note: str = ""


@dataclass(frozen=True)
class ResidualSuggestion:
    likelihood: int
    impact: int
    score: int
    reduction: int
    rationale: list[str] = field(default_factory=list)

    @property
    def differs_from(self) -> bool:  # pragma: no cover - convenience for callers
        return True


def suggest_residual(
    inherent_likelihood: int,
    inherent_impact: int,
    controls: list[ControlInput],
    policy: ResidualPolicySpec = DEFAULT_POLICY,
) -> ResidualSuggestion:
    """Propose residual likelihood/impact, with a line of reasoning per control.

    With no controls, no policy or a disabled policy, the suggestion *is* the inherent
    score — an unmitigated risk has no residual reduction to claim, and saying so
    explicitly is more useful than returning nothing.
    """
    rationale: list[str] = []

    if not policy.enabled:
        rationale.append("Automatic residual suggestion is switched off for this organisation.")
        return _build(inherent_likelihood, inherent_impact, inherent_likelihood, inherent_impact, 0, rationale)

    if not controls:
        rationale.append("No controls are linked to this risk, so residual equals inherent.")
        return _build(inherent_likelihood, inherent_impact, inherent_likelihood, inherent_impact, 0, rationale)

    earned = 0
    for control in controls:
        weight = policy.weight_for(control.effectiveness)
        rating = control.effectiveness.value.replace("_", " ") if control.effectiveness else "not assessed"
        if not control.healthy:
            note = control.health_note or "not currently reliable"
            rationale.append(f"{control.label}: no credit — {note}.")
            continue
        if weight <= 0:
            rationale.append(f"{control.label}: no credit — rated {rating}.")
            continue
        earned += weight
        rationale.append(f"{control.label}: −{weight} ({rating}).")

    reduction = min(earned, policy.max_reduction)
    if earned > policy.max_reduction:
        rationale.append(
            f"Total credit {earned} capped at the policy maximum of {policy.max_reduction}."
        )

    likelihood, impact = _apply(inherent_likelihood, inherent_impact, reduction, policy.applies_to)
    if reduction == 0:
        rationale.append("No effective, currently reliable controls — residual equals inherent.")
    else:
        rationale.append(
            f"Applied −{reduction} to {policy.applies_to}: "
            f"{inherent_likelihood}x{inherent_impact} → {likelihood}x{impact}."
        )
    return _build(inherent_likelihood, inherent_impact, likelihood, impact, reduction, rationale)


def _apply(likelihood: int, impact: int, reduction: int, applies_to: str) -> tuple[int, int]:
    """Spend the reduction on the configured axis, never dropping below 1.

    On ``both`` the odd point goes to likelihood: controls act on frequency first, so
    that is the more defensible place for an uneven split.
    """
    if reduction <= 0:
        return likelihood, impact
    if applies_to == APPLIES_IMPACT:
        return likelihood, max(1, impact - reduction)
    if applies_to == APPLIES_BOTH:
        to_likelihood = (reduction + 1) // 2
        to_impact = reduction // 2
        return max(1, likelihood - to_likelihood), max(1, impact - to_impact)
    return max(1, likelihood - reduction), impact


def _build(
    inherent_likelihood: int,
    inherent_impact: int,
    likelihood: int,
    impact: int,
    reduction: int,
    rationale: list[str],
) -> ResidualSuggestion:
    inherent = inherent_likelihood * inherent_impact
    suggested = likelihood * impact
    if suggested < inherent:
        rationale.append(f"Suggested residual score {suggested} (inherent {inherent}).")
    return ResidualSuggestion(
        likelihood=likelihood, impact=impact, score=suggested, reduction=reduction, rationale=rationale
    )
