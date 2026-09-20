"""Inherent-risk tiering for third parties (product review F-11, plan §2.8).

A third party's *inherent* tier is how risky the relationship is before any of the
vendor's own controls are considered: what data it touches, what happens to customers
if it fails, whether it is a material outsourcing under the SBP framework, how easy it
is to replace, and so on. It is derived from one seeded questionnaire,
**"Inherent risk tiering"** (:data:`TIERING_QUESTIONNAIRE_NAME`, eight scored questions,
:data:`TIERING_QUESTIONS`), answered through the ordinary Assessments module.

How the tier is derived (:func:`derive_tier`, pure):

1. Every question must be answered. Each answer scores 0 (least risk) to its question's
   maximum (3 in the seeded set). The total is taken as a percentage of the maximum, so
   a tenant that re-weights the options keeps the same bands.
2. The percentage picks a band (:data:`TIER_BANDS`):

   ====================  ==========
   Score (% of maximum)  Tier
   ====================  ==========
   70 % and above        critical
   45 % to under 70 %    high
   20 % to under 45 %    medium
   under 20 %            low
   ====================  ==========

3. Worst-case answers set a floor, so a handful of severe answers can't be averaged
   away by benign ones: **one** answer at its question's maximum makes the tier at
   least *medium*; **three or more** make it at least *high*
   (:data:`WORST_CASE_FLOORS`).

The tier *proposes* a criticality (:data:`TIER_TO_CRITICALITY`, one-for-one). When a
tiering assessment of a vendor is completed (submitted or reviewed) the tier is written
to ``vendors.inherent_tier`` and the vendor's criticality follows the proposal — unless
someone has recorded a ``tier_override_reason``, in which case the manual criticality is
kept (:func:`apply_tier`). On an edit, choosing a criticality that differs from the
proposal needs that reason (:func:`resolve_criticality`, a 422 otherwise); choosing the
proposal clears it. Every write-back is audited.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

#: Name of the seeded questionnaire. Since phase 4E the questionnaire is recognised by
#: ``purpose = vendor_tiering`` (:data:`TIERING_PURPOSE`), not by this name; the seed is
#: still insert-only (skipped when a tiering questionnaire or this name exists).
TIERING_QUESTIONNAIRE_NAME = "Inherent risk tiering"
TIERING_QUESTIONNAIRE_DESCRIPTION = (
    "Eight scored questions that set a third party's inherent risk tier (low, medium, "
    "high, critical) before its own controls are considered. Completing an assessment of "
    "this questionnaire for a vendor writes the tier to the vendor and proposes its "
    "criticality. Score bands: 70% and above critical, 45% high, 20% medium, below that "
    "low; one worst-case answer makes it at least medium, three at least high."
)

TIERS: tuple[str, ...] = ("low", "medium", "high", "critical")
_RANK = {t: i for i, t in enumerate(TIERS)}

#: (minimum score %, tier), highest first.
TIER_BANDS: tuple[tuple[float, str], ...] = ((70.0, "critical"), (45.0, "high"), (20.0, "medium"), (0.0, "low"))
#: (worst-case answers at least, tier floor), strongest first.
WORST_CASE_FLOORS: tuple[tuple[int, str], ...] = ((3, "high"), (1, "medium"))
#: The criticality each tier proposes.
TIER_TO_CRITICALITY: dict[str, str] = {"low": "low", "medium": "medium", "high": "high", "critical": "critical"}

#: Assessment statuses that count as a completed tiering.
COMPLETED_STATUSES: frozenset[str] = frozenset({"submitted", "reviewed"})

OVERRIDE_REASON_NEEDED = (
    "tier_override_reason: the criticality differs from the one proposed by the inherent "
    "risk tier ({tier} proposes {proposed}); give a reason for the override or pick {proposed}."
)

#: The seeded questions: (text, guidance, ((option label, score), …)). Scores run from
#: 0 (least inherent risk) to 3 (worst case).
TIERING_QUESTIONS: tuple[tuple[str, str, tuple[tuple[str, float], ...]], ...] = (
    (
        "What is the most sensitive data the third party stores, processes or can see?",
        "Take the highest classification of any bank data it handles, including backups and logs.",
        (
            ("None of our data", 0.0),
            ("Internal, non-sensitive business data", 1.0),
            ("Confidential data (e.g. staff records, aggregated customer data)", 2.0),
            ("Restricted data: customer PII, account, card or payment data", 3.0),
        ),
    ),
    (
        "If the service failed for a full business day, what would customers experience?",
        "Consider branches, ATMs, the mobile app, internet banking, RAAST and card payments.",
        (
            ("Nothing: back-office service only", 0.0),
            ("Minor inconvenience; a workaround exists", 1.0),
            ("Visible disruption to a customer channel", 2.0),
            ("Customers unable to transact or reach their funds", 3.0),
        ),
    ),
    (
        "Is this an outsourcing arrangement under the SBP Framework for Risk Management in Outsourcing Arrangements?",
        "Material outsourcing is what the SBP framework calls material; record the arrangement under Outsourcing too.",
        (
            ("Not outsourcing (goods or a one-off service)", 0.0),
            ("Non-material outsourcing", 1.0),
            ("Material outsourcing", 2.0),
            ("Material outsourcing of a core banking or cloud service needing SBP approval", 3.0),
        ),
    ),
    (
        "How quickly could the service move to another provider or be brought in-house?",
        "Include data migration, contract notice periods and re-testing.",
        (
            ("Within a month; many alternatives", 0.0),
            ("Within three months", 1.0),
            ("Three to twelve months; few alternatives", 2.0),
            ("More than a year, or no practical alternative", 3.0),
        ),
    ),
    (
        "How concentrated is the bank's reliance on this provider?",
        "Concentration counts across services, and across the sector when most Pakistani banks use the same provider.",
        (
            ("Low: a small share of one minor service", 0.0),
            ("Sole provider of one non-critical service", 1.0),
            ("Sole provider of a critical service", 2.0),
            ("Provides several critical services, or is used by most of the sector", 3.0),
        ),
    ),
    (
        "What access does the third party have to our systems, network or premises?",
        "Count access by its staff and by anything it installs (agents, VPN links, APIs).",
        (
            ("None", 0.0),
            ("Premises only, or read-only access to non-production systems", 1.0),
            ("User-level access to production systems", 2.0),
            ("Privileged or remote access to production, or it hosts our systems", 3.0),
        ),
    ),
    (
        "Does the third party rely on sub-contractors (fourth parties) to deliver the service?",
        "List known sub-contractors on the vendor's due-diligence section.",
        (
            ("No", 0.0),
            ("Yes, for non-critical parts of the service", 1.0),
            ("Yes, for critical parts; sub-contractors known and approved", 2.0),
            ("Yes, for critical parts; sub-contractors unknown or not approved", 3.0),
        ),
    ),
    (
        "Where is our data stored or processed?",
        "Include disaster-recovery sites and support access from abroad.",
        (
            ("No data held", 0.0),
            ("In Pakistan only", 1.0),
            ("Outside Pakistan, with SBP approval where required", 2.0),
            ("Outside Pakistan without approval, or in an unassessed jurisdiction", 3.0),
        ),
    ),
)


class TieringError(ValueError):
    """The assessment can't yield a tier (not a tiering assessment, not completed,
    unanswered questions)."""


@dataclass(frozen=True)
class TierResult:
    tier: str
    total_score: float
    max_score: float
    score_pct: float
    band_tier: str  # the tier the percentage alone gives
    worst_case_answers: int
    floor_applied: bool

    @property
    def proposed_criticality(self) -> str:
        return TIER_TO_CRITICALITY[self.tier]

    def explanation(self) -> str:
        how = f"{self.total_score:g} of {self.max_score:g} ({self.score_pct:g}%) is {self.band_tier}"
        if self.floor_applied:
            how += (
                f"; raised to {self.tier} by {self.worst_case_answers} worst-case "
                f"answer{'s' if self.worst_case_answers != 1 else ''}"
            )
        return how


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


#: The questionnaire purpose that drives tiering (phase 4E). A questionnaire is recognised
#: by its purpose, so renaming it (or installing a second tiering questionnaire) keeps the
#: write-back working. An object with no ``purpose`` at all (a pre-4E caller) falls back
#: to the name.
TIERING_PURPOSE = "vendor_tiering"


def is_tiering_questionnaire(questionnaire: Any) -> bool:
    if questionnaire is None:
        return False
    purpose = getattr(questionnaire, "purpose", None)
    if purpose is not None:
        return purpose == TIERING_PURPOSE
    return _norm(getattr(questionnaire, "name", "")) == _norm(TIERING_QUESTIONNAIRE_NAME)


def _status(value: Any) -> str:
    return getattr(value, "value", value) or ""


def is_completed(assessment: Any) -> bool:
    return _status(getattr(assessment, "status", None)) in COMPLETED_STATUSES


def band_for(pct: float) -> str:
    for minimum, tier in TIER_BANDS:
        if pct >= minimum:
            return tier
    return "low"


def floor_for(worst_case_answers: int) -> str:
    for at_least, tier in WORST_CASE_FLOORS:
        if worst_case_answers >= at_least:
            return tier
    return "low"


def derive_tier(answers: Sequence[tuple[float, float]]) -> TierResult:
    """Tier from ``(score, question maximum)`` pairs, one per question. Pure.

    A question whose maximum is 0 carries no weight and can't be a worst case.
    """
    if not answers:
        raise TieringError("The tiering questionnaire has no questions.")
    total = round(sum(s for s, _ in answers), 2)
    maximum = round(sum(m for _, m in answers), 2)
    pct = round(100 * total / maximum, 1) if maximum else 0.0
    worst = sum(1 for s, m in answers if m > 0 and s >= m)
    band = band_for(pct)
    floor = floor_for(worst)
    tier = floor if _RANK[floor] > _RANK[band] else band
    return TierResult(
        tier=tier, total_score=total, max_score=maximum, score_pct=pct,
        band_tier=band, worst_case_answers=worst, floor_applied=tier != band,
    )


def answers_of(assessment: Any) -> list[tuple[float, float]]:
    """``(score, maximum)`` per question of the assessment's questionnaire; raises when
    any question is unanswered (a blank would otherwise count as the safest answer)."""
    questionnaire = assessment.questionnaire
    chosen = {a.question_id: a.option for a in assessment.answers if getattr(a, "option", None) is not None}
    pairs: list[tuple[float, float]] = []
    missing = 0
    for q in questionnaire.questions:
        maximum = max((o.score for o in q.options), default=0.0)
        option = chosen.get(q.id)
        if option is None:
            missing += 1
            continue
        pairs.append((float(option.score), float(maximum)))
    if missing:
        raise TieringError(
            f"{missing} of {len(questionnaire.questions)} tiering question"
            f"{'s are' if missing != 1 else ' is'} unanswered; answer every question to set a tier."
        )
    return pairs


def tier_assessment(assessment: Any) -> TierResult:
    if not is_tiering_questionnaire(getattr(assessment, "questionnaire", None)):
        raise TieringError(f"This assessment does not use the '{TIERING_QUESTIONNAIRE_NAME}' questionnaire.")
    if not is_completed(assessment):
        raise TieringError("The tiering assessment is not completed yet (submit it first).")
    return derive_tier(answers_of(assessment))


def _completed_at(assessment: Any) -> tuple:
    submitted = getattr(assessment, "submitted_at", None) or date.min
    created = getattr(assessment, "created_at", None) or datetime.min
    if isinstance(created, datetime) and created.tzinfo is not None:
        created = created.replace(tzinfo=None)
    return (submitted, created)


def latest_completed(assessments: Iterable[Any]) -> Any | None:
    """The most recently completed tiering assessment, or None."""
    done = [a for a in assessments if is_tiering_questionnaire(getattr(a, "questionnaire", None)) and is_completed(a)]
    return max(done, key=_completed_at) if done else None


# ============================================================ criticality rule ===
def _crit(value: Any) -> str:
    return getattr(value, "value", value) or ""


def resolve_criticality(
    *,
    tier: str | None,
    stored_criticality: Any,
    stored_reason: str,
    sent: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Decide the criticality / override reason an edit leaves on the vendor. Pure.

    ``sent`` is the update's set fields. Returns ``(criticality, reason)`` to write,
    ``None`` meaning "leave as is". Raises :class:`TieringError` (a 422) when the
    resulting criticality differs from the tier's proposal and no reason is on record.

    * No tier yet: criticality is entirely manual; the reason is stored as sent.
    * The resulting criticality equals the proposal: the override reason is cleared.
    * It differs: a non-blank reason must be in the request or already stored.
    """
    new_crit = _crit(sent["criticality"]) if sent.get("criticality") is not None else None
    new_reason = sent.get("tier_override_reason")
    if not tier:
        return new_crit, (new_reason if new_reason is not None else None)
    proposed = TIER_TO_CRITICALITY.get(tier)
    target = new_crit or _crit(stored_criticality)
    reason = (new_reason if new_reason is not None else stored_reason) or ""
    if target == proposed:
        return new_crit, ("" if (stored_reason or new_reason) else None)
    if not reason.strip():
        raise TieringError(OVERRIDE_REASON_NEEDED.format(tier=tier, proposed=proposed))
    return new_crit, (reason.strip() if new_reason is not None else None)


def apply_tier(vendor: Any, result: TierResult, criticality_type: Any = None) -> dict[str, dict[str, Any]]:
    """Write a tier onto a vendor. Returns the ``{field: {from, to}}`` changes.

    The criticality follows the proposal unless an override reason is recorded, in which
    case the manual criticality stands (and the reason keeps explaining it). When the
    manual criticality already equals the proposal, a stale reason is cleared.
    ``criticality_type`` converts the proposal back to the model's enum.
    """
    changes: dict[str, dict[str, Any]] = {}
    if vendor.inherent_tier != result.tier:
        changes["inherent_tier"] = {"from": vendor.inherent_tier, "to": result.tier}
        vendor.inherent_tier = result.tier
    proposed = result.proposed_criticality
    current = _crit(vendor.criticality)
    reason = (getattr(vendor, "tier_override_reason", "") or "").strip()
    if current == proposed:
        if reason:
            changes["tier_override_reason"] = {"from": reason, "to": ""}
            vendor.tier_override_reason = ""
    elif not reason:
        changes["criticality"] = {"from": current, "to": proposed}
        vendor.criticality = criticality_type(proposed) if criticality_type else proposed
    return changes


def summary_for(name: str, result: TierResult, changes: dict[str, dict[str, Any]], kept: bool) -> str:
    text = f"Inherent risk tier of {name}: {result.tier} ({result.explanation()})"
    if "criticality" in changes:
        text += f"; criticality set to the proposed {result.proposed_criticality}"
    elif kept:
        text += f"; manual criticality kept over the proposed {result.proposed_criticality} (override reason on record)"
    return text


async def write_back(db, vendor: Any, assessment: Any, actor: Any) -> TierResult:
    """Tier ``vendor`` from a completed tiering ``assessment``, and audit it."""
    from app.models.enums import Criticality
    from app.services import audit

    result = tier_assessment(assessment)
    changes = apply_tier(vendor, result, Criticality)
    kept = _crit(vendor.criticality) != result.proposed_criticality
    await db.flush()
    await audit.record(
        db, actor=actor, action="tier", entity_type="vendor", entity_id=vendor.id,
        summary=summary_for(vendor.name, result, changes, kept),
        changes={
            **changes,
            "assessment_id": str(getattr(assessment, "id", "")),
            "score_pct": result.score_pct,
            "worst_case_answers": result.worst_case_answers,
        },
    )
    return result
