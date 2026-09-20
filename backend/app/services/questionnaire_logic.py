"""The questionnaire engine's rules: conditional display, scoring, bands and structure
checks (product review phase 4E). Pure — no database, no ORM — so the same rules run
on the server, in tests, and (mirrored line for line in ``frontend/lib/questionnaireLogic.ts``)
in the builder preview and the respondent portal.

**Shape.** A questionnaire version is a list of *sections*, each with *questions*. Both
are plain mappings (see :func:`spec_from_version` for the ORM adapter)::

    section  = {"key": str, "conditions": Condition, "questions": [question, ...]}
    question = {"key": str, "type": str, "mandatory": bool, "weight": float,
                "conditions": Condition, "options": [option, ...]}
    option   = {"value": str, "score": float, "is_na": bool, "risk_flag": bool}

Answers are keyed by question key (:class:`AnswerValue`).

**Conditions.** ``{"match": "all" | "any", "rules": [rule, ...]}``; an empty or missing
condition always shows. A rule names an *earlier* question by key and an operator:

==============  ====================================================================
``in``          one of the selected options' values is in ``values``
``not_in``      none of the selected options' values is in ``values`` (also true when
                the question is unanswered)
``answered``    the question has any answer (N/A counts)
``not_answered`` it has none
``eq`` ``neq``  the number answer equals / differs from ``value``
``gt`` ``gte``  greater than / at least ``value``
``lt`` ``lte``  less than / at most ``value``
==============  ====================================================================

A number comparison is false when there is no number (``neq`` included). A question that
is hidden — by its own condition or its section's — counts as unanswered for every rule
that refers to it, so hiding cascades. Rules may only refer to questions that come
earlier in the questionnaire (checked on save and publish).

**Scoring.** Only choice questions score. A question's maximum is its best non-N/A option
(single choice, yes/no/N-A) or the sum of its positive non-N/A options (multiple choice),
times its weight. Hidden questions and questions answered N/A drop out of both the score
and the maximum; a visible scored question left blank earns 0 but keeps its maximum.
``pct = 100 × earned / maximum`` rounded to one decimal, or ``None`` when nothing is
scorable.

**Bands.** ``[{"label", "min_pct", "rating"}]``: the band with the highest ``min_pct`` not
above the score applies. A band set must include a 0 % band so every score lands
somewhere; ``rating`` is low / medium / high / critical (a vendor risk rating).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

QUESTION_TYPES: tuple[str, ...] = (
    "single_choice", "multiple_choice", "yes_no_na", "text", "long_text", "number", "date", "file_upload",
)
CHOICE_TYPES: frozenset[str] = frozenset({"single_choice", "multiple_choice", "yes_no_na"})
TYPE_LABELS: dict[str, str] = {
    "single_choice": "Single choice",
    "multiple_choice": "Multiple choice",
    "yes_no_na": "Yes / No / Not applicable",
    "text": "Short text",
    "long_text": "Long text",
    "number": "Number",
    "date": "Date",
    "file_upload": "File upload (evidence)",
}
OPERATORS: tuple[str, ...] = ("in", "not_in", "answered", "not_answered", "eq", "neq", "gt", "gte", "lt", "lte")
OPTION_OPERATORS: frozenset[str] = frozenset({"in", "not_in"})
NUMBER_OPERATORS: frozenset[str] = frozenset({"eq", "neq", "gt", "gte", "lt", "lte"})
MATCHES: tuple[str, ...] = ("all", "any")
RATINGS: tuple[str, ...] = ("low", "medium", "high", "critical")
PURPOSES: tuple[str, ...] = ("general", "vendor_tiering", "vendor_due_diligence", "rcsa_control_self_assessment")
PURPOSE_LABELS: dict[str, str] = {
    "general": "General",
    "vendor_tiering": "Vendor tiering",
    "vendor_due_diligence": "Vendor due diligence",
    "rcsa_control_self_assessment": "Control self-assessment (RCSA)",
}
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


# ================================================================== answers ===
@dataclass(frozen=True)
class AnswerValue:
    """One question's answer, in the form the rules read."""

    option_values: tuple[str, ...] = ()
    number: float | None = None
    text: str = ""
    date: str | None = None
    na: bool = False
    files: int = 0

    def is_answered(self) -> bool:
        return bool(
            self.na or self.option_values or self.number is not None or (self.text or "").strip()
            or self.date or self.files > 0
        )


def _answered(answer: AnswerValue | None) -> bool:
    return answer is not None and answer.is_answered()


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# =============================================================== conditions ===
def rule_holds(rule: Mapping[str, Any], answer: AnswerValue | None) -> bool:
    """Whether one rule holds for the referred question's (visible) answer. Pure."""
    op = rule.get("op")
    if op == "answered":
        return _answered(answer)
    if op == "not_answered":
        return not _answered(answer)
    if op in OPTION_OPERATORS:
        wanted = {str(v) for v in (rule.get("values") or [])}
        chosen = set(answer.option_values) if answer is not None else set()
        hit = bool(chosen & wanted)
        return hit if op == "in" else not hit
    if op in NUMBER_OPERATORS:
        target = _num(rule.get("value"))
        have = answer.number if answer is not None else None
        if target is None or have is None:
            return False
        return {
            "eq": have == target, "neq": have != target, "gt": have > target,
            "gte": have >= target, "lt": have < target, "lte": have <= target,
        }[op]
    return False  # an unknown operator never shows anything


def _rules(condition: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not condition:
        return []
    return [r for r in (condition.get("rules") or []) if isinstance(r, Mapping)]


def condition_holds(condition: Mapping[str, Any] | None, answers: Mapping[str, AnswerValue]) -> bool:
    """Whether a section or question with this condition shows. Pure. ``answers`` holds
    only *visible* answers (a hidden question's answer must already be left out)."""
    rules = _rules(condition)
    if not rules:
        return True
    results = (rule_holds(r, answers.get(str(r.get("question")))) for r in rules)
    return any(results) if (condition or {}).get("match") == "any" else all(results)


@dataclass
class Visibility:
    sections: set[str] = field(default_factory=set)
    questions: set[str] = field(default_factory=set)


def visibility(sections: Sequence[Mapping[str, Any]], answers: Mapping[str, AnswerValue]) -> Visibility:
    """Which sections and questions show for these answers, in document order. Pure."""
    seen: dict[str, AnswerValue] = {}
    out = Visibility()
    for section in sections:
        section_shows = condition_holds(section.get("conditions"), seen)
        if section_shows:
            out.sections.add(str(section.get("key")))
        for q in section.get("questions") or []:
            key = str(q.get("key"))
            if section_shows and condition_holds(q.get("conditions"), seen):
                out.questions.add(key)
                if key in answers:
                    seen[key] = answers[key]
    return out


# ================================================================== scoring ===
def _options(q: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(q.get("options") or [])


def question_max(q: Mapping[str, Any]) -> float:
    """The unweighted best score of a question (0 for unscored types). Pure."""
    qtype = q.get("type") or "single_choice"
    if qtype not in CHOICE_TYPES:
        return 0.0
    scores = [float(o.get("score") or 0) for o in _options(q) if not o.get("is_na")]
    if not scores:
        return 0.0
    if qtype == "multiple_choice":
        return float(sum(s for s in scores if s > 0))
    return float(max(max(scores), 0.0))


def _weight(q: Mapping[str, Any]) -> float:
    w = _num(q.get("weight"))
    return 1.0 if w is None else max(w, 0.0)


def question_earned(q: Mapping[str, Any], answer: AnswerValue | None) -> float | None:
    """The unweighted score an answer earns; ``None`` when it drops out (N/A). Pure."""
    qtype = q.get("type") or "single_choice"
    if qtype not in CHOICE_TYPES:
        return 0.0
    if answer is None:
        return 0.0
    by_value = {str(o.get("value")): o for o in _options(q)}
    chosen = [by_value[v] for v in answer.option_values if v in by_value]
    if answer.na or (chosen and all(o.get("is_na") for o in chosen)):
        return None
    chosen = [o for o in chosen if not o.get("is_na")]
    if not chosen:
        return 0.0
    if qtype == "multiple_choice":
        return float(min(sum(float(o.get("score") or 0) for o in chosen), question_max(q)))
    return float(chosen[0].get("score") or 0)


@dataclass(frozen=True)
class ScoreResult:
    earned: float
    maximum: float
    pct: float | None
    visible_questions: int
    answered_questions: int
    not_applicable: int
    missing_mandatory: tuple[str, ...]

    @property
    def progress_pct(self) -> int:
        if not self.visible_questions:
            return 0
        return round(100 * self.answered_questions / self.visible_questions)


def score(sections: Sequence[Mapping[str, Any]], answers: Mapping[str, AnswerValue]) -> ScoreResult:
    """Score a set of answers against a questionnaire (see the module notes). Pure."""
    vis = visibility(sections, answers)
    earned = maximum = 0.0
    visible = answered = na = 0
    missing: list[str] = []
    for section in sections:
        for q in section.get("questions") or []:
            key = str(q.get("key"))
            if key not in vis.questions:
                continue
            visible += 1
            answer = answers.get(key)
            if _answered(answer):
                answered += 1
            elif q.get("mandatory"):
                missing.append(key)
            got = question_earned(q, answer)
            if got is None:
                na += 1
                continue
            w = _weight(q)
            earned += w * got
            maximum += w * question_max(q)
    earned, maximum = round(earned, 2), round(maximum, 2)
    pct = round(100 * earned / maximum, 1) if maximum > 0 else None
    return ScoreResult(earned, maximum, pct, visible, answered, na, tuple(missing))


def static_max(sections: Sequence[Mapping[str, Any]]) -> float:
    """The maximum with every question shown and nothing N/A (the builder's headline)."""
    return round(sum(_weight(q) * question_max(q) for s in sections for q in s.get("questions") or []), 2)


# ==================================================================== bands ===
def sorted_bands(bands: Iterable[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    return sorted((b for b in (bands or []) if isinstance(b, Mapping)),
                  key=lambda b: _num(b.get("min_pct")) or 0.0, reverse=True)


def band_for(bands: Iterable[Mapping[str, Any]] | None, pct: float | None) -> Mapping[str, Any] | None:
    """The band a score falls in, or None (no bands, or nothing scorable). Pure."""
    if pct is None:
        return None
    for band in sorted_bands(bands):
        if pct >= (_num(band.get("min_pct")) or 0.0):
            return band
    return None


def band_problems(bands: Sequence[Mapping[str, Any]] | None) -> list[str]:
    """What is wrong with a band set (empty is allowed: the questionnaire just has no
    bands). Pure."""
    problems: list[str] = []
    rows = list(bands or [])
    if not rows:
        return problems
    mins: list[float] = []
    for i, band in enumerate(rows, start=1):
        label = str(band.get("label") or "").strip()
        minimum = _num(band.get("min_pct"))
        if not label:
            problems.append(f"Band {i} needs a label.")
        if minimum is None or not 0 <= minimum <= 100:
            problems.append(f"Band {i} ({label or 'unnamed'}): the minimum score must be between 0 and 100%.")
        else:
            mins.append(minimum)
        if band.get("rating") not in RATINGS:
            problems.append(f"Band {i} ({label or 'unnamed'}): the rating must be low, medium, high or critical.")
    if len(set(mins)) != len(mins):
        problems.append("Two bands start at the same score; each band needs its own minimum.")
    if mins and 0 not in mins:
        problems.append("Add a band that starts at 0% so every score falls in a band.")
    return problems


# ================================================================ structure ===
def structure_problems(sections: Sequence[Mapping[str, Any]], *, for_publish: bool = False) -> list[str]:
    """What stops this questionnaire being saved (or, with ``for_publish``, published).
    Pure. Messages name the section and question by position so the builder can show them."""
    problems: list[str] = []
    earlier: dict[str, Mapping[str, Any]] = {}
    keys_seen: set[str] = set()
    section_keys: set[str] = set()
    total = 0

    def check_condition(where: str, condition: Mapping[str, Any] | None) -> None:
        if not condition:
            return
        if condition.get("match", "all") not in MATCHES:
            problems.append(f"{where}: a condition must match all or any of its rules.")
        for j, rule in enumerate(_rules(condition), start=1):
            ref = str(rule.get("question") or "")
            op = rule.get("op")
            label = f"{where}, rule {j}"
            if op not in OPERATORS:
                problems.append(f"{label}: unknown comparison '{op}'.")
                continue
            target = earlier.get(ref)
            if target is None:
                problems.append(f"{label}: it must refer to a question that comes earlier.")
                continue
            ttype = target.get("type") or "single_choice"
            if op in OPTION_OPERATORS:
                if ttype not in CHOICE_TYPES:
                    problems.append(f"{label}: 'is one of' needs a choice question.")
                    continue
                values = [str(v) for v in (rule.get("values") or [])]
                known = {str(o.get("value")) for o in _options(target)}
                if not values:
                    problems.append(f"{label}: pick at least one answer.")
                elif any(v not in known for v in values):
                    problems.append(f"{label}: it names an answer the earlier question does not offer.")
            elif op in NUMBER_OPERATORS:
                if ttype != "number":
                    problems.append(f"{label}: number comparisons need a number question.")
                elif _num(rule.get("value")) is None:
                    problems.append(f"{label}: give the number to compare with.")

    for si, section in enumerate(sections, start=1):
        s_where = f"Section {si}"
        skey = str(section.get("key") or "")
        if not str(section.get("title") or "").strip():
            problems.append(f"{s_where} needs a title.")
        if skey in section_keys:
            problems.append(f"{s_where}: its key '{skey}' is used twice.")
        section_keys.add(skey)
        check_condition(s_where, section.get("conditions"))
        for qi, q in enumerate(section.get("questions") or [], start=1):
            total += 1
            where = f"Section {si}, question {qi}"
            key = str(q.get("key") or "")
            qtype = q.get("type") or "single_choice"
            if not KEY_PATTERN.match(key):
                problems.append(f"{where}: the key must be lower-case letters, digits, '_', '-' or '.'.")
            elif key in keys_seen:
                problems.append(f"{where}: the key '{key}' is used by another question.")
            keys_seen.add(key)
            if not str(q.get("text") or "").strip():
                problems.append(f"{where} needs its question text.")
            if qtype not in QUESTION_TYPES:
                problems.append(f"{where}: unknown question type '{qtype}'.")
            w = _num(q.get("weight"))
            if q.get("weight") is not None and (w is None or w < 0):
                problems.append(f"{where}: the weight must be zero or more.")
            check_condition(where, q.get("conditions"))
            options = _options(q)
            if qtype in CHOICE_TYPES:
                need = 2 if qtype == "yes_no_na" else 1
                if len(options) < need:
                    problems.append(f"{where}: add at least {need} answer option{'s' if need > 1 else ''}.")
                values = [str(o.get("value") or "") for o in options]
                if any(not v for v in values):
                    problems.append(f"{where}: every answer option needs a value key.")
                if len(set(values)) != len(values):
                    problems.append(f"{where}: two answer options share a value key.")
                if any(not str(o.get("label") or "").strip() for o in options):
                    problems.append(f"{where}: every answer option needs a label.")
                for o in options:
                    s = _num(o.get("score"))
                    if s is None or s < 0:
                        problems.append(f"{where}: option '{o.get('label')}' needs a score of zero or more.")
                    if o.get("risk_flag") and o.get("finding_severity", "medium") not in RATINGS:
                        problems.append(f"{where}: option '{o.get('label')}' raises a finding with an unknown severity.")
            elif options:
                problems.append(f"{where}: a {TYPE_LABELS.get(qtype, qtype).lower()} question has no answer options.")
            earlier[key] = q
    if for_publish and total == 0:
        problems.append("Add at least one question before publishing.")
    return problems


# ================================================================= findings ===
@dataclass(frozen=True)
class RiskFlag:
    question_key: str
    option_value: str
    title: str
    severity: str


def risk_flags(sections: Sequence[Mapping[str, Any]], answers: Mapping[str, AnswerValue]) -> list[RiskFlag]:
    """The flagged answers among the visible ones, in document order. Pure."""
    vis = visibility(sections, answers)
    flags: list[RiskFlag] = []
    for section in sections:
        for q in section.get("questions") or []:
            key = str(q.get("key"))
            answer = answers.get(key)
            if key not in vis.questions or answer is None:
                continue
            by_value = {str(o.get("value")): o for o in _options(q)}
            for value in answer.option_values:
                o = by_value.get(value)
                if o is None or not o.get("risk_flag"):
                    continue
                title = str(o.get("finding_title") or "").strip() or (
                    f"{_short(str(q.get('text') or ''))}: {o.get('label')}"
                )
                severity = o.get("finding_severity") if o.get("finding_severity") in RATINGS else "medium"
                flags.append(RiskFlag(key, value, title[:255], severity))
    return flags


def _short(text: str, limit: int = 180) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ============================================================ ORM adapters ===
def slug(text: str, fallback: str = "q") -> str:
    """A key from free text: lower-case, digits and underscores. Pure."""
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:48]
    return s or fallback


def spec_from_version(version: Any) -> list[dict[str, Any]]:
    """The section/question/option mappings of a questionnaire version row. Questions
    without a section (never after migration) are gathered into one trailing section."""
    def q_spec(q: Any) -> dict[str, Any]:
        return {
            "id": getattr(q, "id", None), "key": q.key or f"q{str(q.id).replace('-', '')[:10]}",
            "text": q.text, "type": getattr(q, "qtype", None) or "single_choice",
            "mandatory": bool(getattr(q, "mandatory", False)),
            "weight": 1.0 if getattr(q, "weight", None) is None else float(q.weight),
            "conditions": getattr(q, "conditions", None) or {},
            "config": getattr(q, "config", None) or {},
            "options": [
                {
                    "id": getattr(o, "id", None), "value": o.value or f"o{str(o.id).replace('-', '')[:10]}",
                    "label": o.label, "score": float(o.score or 0), "is_na": bool(getattr(o, "is_na", False)),
                    "risk_flag": bool(getattr(o, "risk_flag", False)),
                    "finding_title": getattr(o, "finding_title", "") or "",
                    "finding_severity": getattr(o, "finding_severity", "") or "medium",
                }
                for o in sorted(q.options or [], key=lambda o: o.order_index or 0)
            ],
        }

    sections = sorted(getattr(version, "sections", None) or [], key=lambda s: s.order_index or 0)
    questions = sorted(getattr(version, "questions", None) or [], key=lambda q: q.order_index or 0)
    out: list[dict[str, Any]] = []
    placed: set[Any] = set()
    for s in sections:
        qs = [q for q in questions if getattr(q, "section_id", None) == s.id]
        placed.update(q.id for q in qs)
        out.append({
            "id": s.id, "key": s.key or f"s{str(s.id).replace('-', '')[:10]}", "title": s.title,
            "description": s.description or "", "conditions": s.conditions or {},
            "questions": [q_spec(q) for q in qs],
        })
    loose = [q for q in questions if q.id not in placed]
    if loose:
        out.append({"id": None, "key": "_unsectioned", "title": "Questions", "description": "",
                    "conditions": {}, "questions": [q_spec(q) for q in loose]})
    return out


def answer_values(spec: Sequence[Mapping[str, Any]], answers: Iterable[Any], file_counts: Mapping[Any, int] | None = None) -> dict[str, AnswerValue]:
    """Answer rows (``AssessmentAnswer``-like) as :class:`AnswerValue` by question key."""
    by_id: dict[Any, Mapping[str, Any]] = {}
    for s in spec:
        for q in s.get("questions") or []:
            by_id[q.get("id")] = q
    out: dict[str, AnswerValue] = {}
    for a in answers:
        q = by_id.get(getattr(a, "question_id", None))
        if q is None:
            continue
        option_ids = [getattr(a, "option_id", None)] + list(getattr(a, "option_ids", None) or [])
        option_value = {str(o.get("id")): str(o.get("value")) for o in q.get("options") or []}
        values = tuple(dict.fromkeys(option_value[str(i)] for i in option_ids if i is not None and str(i) in option_value))
        raw_date = getattr(a, "value_date", None)
        out[str(q["key"])] = AnswerValue(
            option_values=values,
            number=_num(getattr(a, "value_number", None)),
            text=getattr(a, "value_text", "") or "",
            date=raw_date.isoformat() if hasattr(raw_date, "isoformat") else raw_date,
            na=bool(getattr(a, "not_applicable", False)),
            files=int((file_counts or {}).get(getattr(a, "id", None), 0)),
        )
    return out
