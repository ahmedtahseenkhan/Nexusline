"""The assessment workflow around the questionnaire engine (product review phase 4E).

Lifecycle: ``draft`` → **send** (a portal link for the contact, e-mailed) → ``sent`` →
first save → ``in_progress`` → **submit** (every visible mandatory question answered;
score and band snapshotted; flagged answers raise findings) → ``submitted`` → the
reviewer accepts or returns each answer; **return** sends returned answers back to the
respondent (``in_progress``, only those answers editable) → resubmit → **final review**
(nothing returned; the reviewer is not the sender — ``services/dual_control``, module
``assessment``, action ``review``) → ``reviewed``: score and band snapshotted again and
the results drive records:

* ``vendor_tiering`` — the vendor's inherent tier (``services/vendor_tiering``; also on
  submit, as before phase 4E);
* ``vendor_due_diligence`` — the band's rating becomes the vendor's ``risk_rating`` unless a
  reasoned override is on record (:func:`apply_rating`); the vendor's last due-diligence
  date is the review date and the next one is due after the recurrence (12 months when
  none is set);
* ``rcsa_control_self_assessment`` run for an RCSA — each line's design / operation answers
  set its self-ratings and its control effectiveness (the worse of the two) (:func:`apply_rcsa`).

Scheduler (:func:`run_due`, once per sweep per organisation): reminders to the contact
7 days before the due date and again every 3 days until due, one overdue alert (event
notification to the sender and the reviewer, e-mail to the contact) and weekly overdue
reminders; reminder e-mails carry a fresh link. Recurrence: a reviewed assessment with
``recurrence_months`` is re-issued as a draft on its ``next_issue_on`` date, against the
questionnaire's current published version, and the sender is told to send it.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.models.assessment import (
    REVIEW_ACCEPTED,
    REVIEW_PENDING,
    REVIEW_RETURNED,
    Assessment,
    AssessmentAnswer,
    AssessmentFinding,
)
from app.models.enums import FindingStatus, Severity, VendorAssessmentStatus
from app.services import questionnaire_logic as ql

logger = logging.getLogger("nexusline.questionnaires")

REMINDER_LEAD_DAYS = 7
REMINDER_EVERY_DAYS = 3
OVERDUE_REMINDER_EVERY_DAYS = 7
DEFAULT_DUE_DILIGENCE_MONTHS = 12
REISSUE_DUE_DAYS = 30
RATING_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
RCSA_RANK = {"ineffective": 0, "partially_effective": 1, "effective": 2}


class WorkflowError(ValueError):
    def __init__(self, message: str, *, status: int = 422, problems: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.problems = problems or []


def _status(value: Any) -> str:
    return getattr(value, "value", value) or ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ================================================================== answers ===
def question_index(version: Any) -> dict[uuid.UUID, Any]:
    return {q.id: q for q in (getattr(version, "questions", None) or [])}


def _changed(row: Any, fields: Mapping[str, Any]) -> bool:
    return any(getattr(row, k, None) != v for k, v in fields.items())


def answer_fields(question: Any, sent: Any) -> dict[str, Any]:
    """The stored fields for one sent answer, validated against the question's type.
    Raises :class:`WorkflowError`. Pure."""
    qtype = getattr(question, "qtype", None) or "single_choice"
    options = {o.id: o for o in question.options or []}
    fields: dict[str, Any] = {
        "option_id": None, "option_ids": [], "value_text": "", "value_number": None,
        "value_date": None, "not_applicable": False,
    }
    label = f"'{(question.text or '')[:60]}'"
    if qtype in ql.CHOICE_TYPES:
        chosen: list[uuid.UUID] = []
        if getattr(sent, "option_id", None) is not None:
            chosen.append(sent.option_id)
        chosen += [i for i in (getattr(sent, "option_ids", None) or []) if i not in chosen]
        if getattr(sent, "not_applicable", None):
            na = [o.id for o in question.options if getattr(o, "is_na", False)]
            if not na:
                raise WorkflowError(f"Question {label} has no 'not applicable' answer.")
            chosen = [na[0]]
        for i in chosen:
            if i not in options:
                raise WorkflowError(f"Option does not belong to question {question.id}")
        if qtype != "multiple_choice" and len(chosen) > 1:
            raise WorkflowError(f"Question {label} takes one answer.")
        if chosen and all(getattr(options[i], "is_na", False) for i in chosen):
            fields["not_applicable"] = True
            chosen = chosen[:1]
        if qtype == "multiple_choice":
            fields["option_ids"] = [str(i) for i in chosen]
            fields["option_id"] = None
        else:
            fields["option_id"] = chosen[0] if chosen else None
    elif qtype in ("text", "long_text"):
        text = getattr(sent, "value_text", None) or ""
        if qtype == "text" and len(text) > 1000:
            raise WorkflowError(f"Question {label}: keep a short answer under 1,000 characters.")
        fields["value_text"] = text
    elif qtype == "number":
        fields["value_number"] = getattr(sent, "value_number", None)
    elif qtype == "date":
        fields["value_date"] = getattr(sent, "value_date", None)
    # file_upload: files are attached separately; only the comment is stored here.
    return fields


def upsert_answers(
    assessment: Assessment, sent: Sequence[Any], *, tenant_id: uuid.UUID, answered_by: str,
    only_questions: set[uuid.UUID] | None = None,
) -> tuple[list[AssessmentAnswer], int]:
    """Apply sent answers to the assessment. Returns ``(new rows to add, rows changed)``.
    ``only_questions`` limits which questions may change (returned answers). Pure apart
    from mutating the loaded rows."""
    questions = question_index(assessment.questionnaire)
    existing = {a.question_id: a for a in assessment.answers}
    new_rows: list[AssessmentAnswer] = []
    changed = 0
    now = _now()
    for item in sent:
        question = questions.get(item.question_id)
        if question is None:
            raise WorkflowError(f"Unknown question {item.question_id}", status=400)
        fields = answer_fields(question, item)
        fields["comment"] = getattr(item, "comment", "") or ""
        row = existing.get(item.question_id)
        if row is not None and not _changed(row, fields):
            continue
        if only_questions is not None and item.question_id not in only_questions:
            raise WorkflowError(
                "Only the answers the reviewer returned can be changed now.", status=409,
            )
        if row is None:
            row = AssessmentAnswer(
                tenant_id=tenant_id, assessment_id=assessment.id, question_id=item.question_id,
                review_state=REVIEW_PENDING, **fields,
            )
            row.answered_by, row.answered_at = answered_by[:255], now
            new_rows.append(row)
            existing[item.question_id] = row
        else:
            for k, v in fields.items():
                setattr(row, k, v)
            row.answered_by, row.answered_at = answered_by[:255], now
            if row.review_state in (REVIEW_RETURNED, REVIEW_ACCEPTED):
                row.review_state = REVIEW_PENDING
        changed += 1
    return new_rows, changed


def evaluate(assessment: Assessment, file_counts: Mapping[Any, int] | None = None):
    """``(spec, answer values, score result)`` for an assessment. Pure."""
    spec = ql.spec_from_version(assessment.questionnaire)
    values = ql.answer_values(spec, assessment.answers, file_counts or {})
    return spec, values, ql.score(spec, values)


def question_labels(spec: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {str(q["key"]): str(q.get("text") or "") for s in spec for q in s.get("questions") or []}


def snapshot(assessment: Assessment, result: Any) -> None:
    """Store the score and band on the assessment (on submit and on review)."""
    band = ql.band_for(assessment.questionnaire.bands if assessment.questionnaire else None, result.pct)
    assessment.result_score = result.earned
    assessment.result_max = result.maximum
    assessment.result_pct = result.pct
    assessment.result_band = str(band.get("label")) if band else ""
    assessment.result_rating = band.get("rating") if band else None
    assessment.scored_at = _now()


def submit_refusal(result: Any, spec: Sequence[Mapping[str, Any]]) -> WorkflowError | None:
    if not result.missing_mandatory:
        return None
    labels = question_labels(spec)
    names = [labels.get(k, k)[:90] for k in result.missing_mandatory]
    n = len(names)
    return WorkflowError(
        f"{n} required question{'s are' if n != 1 else ' is'} unanswered.",
        problems=[f"Unanswered: {name}" for name in names],
    )


# ================================================================= findings ===
def sync_flag_findings(assessment: Assessment, spec, values, *, tenant_id: uuid.UUID) -> tuple[list[AssessmentFinding], int]:
    """Findings for flagged answers: one per (question, option) not already raised; an
    automatic finding whose answer no longer flags (and that was not raised to an issue)
    is closed. Returns ``(new findings to add, findings closed)``."""
    flags = ql.risk_flags(spec, values)
    wanted = {(f.question_key, f.option_value): f for f in flags}
    have = {(f.question_key, f.option_value): f for f in assessment.findings if f.auto_raised}
    answers_by_key: dict[str, Any] = {}
    ids = {q.get("id"): str(q["key"]) for s in spec for q in s.get("questions") or []}
    for a in assessment.answers:
        if a.question_id in ids:
            answers_by_key[ids[a.question_id]] = a
    labels = question_labels(spec)
    created: list[AssessmentFinding] = []
    for key, flag in wanted.items():
        existing = have.get(key)
        if existing is not None:
            if _status(existing.status) == FindingStatus.closed.value and existing.issue_id is None:
                existing.status = FindingStatus.open
            continue
        answer = answers_by_key.get(flag.question_key)
        comment = (getattr(answer, "comment", "") or "").strip()
        description = f"Raised by the answer to: {labels.get(flag.question_key, flag.question_key)}"
        if comment:
            description += f"\nRespondent's comment: {comment}"
        created.append(AssessmentFinding(
            tenant_id=tenant_id, assessment_id=assessment.id, title=flag.title,
            description=description, severity=Severity(flag.severity), status=FindingStatus.open,
            answer_id=getattr(answer, "id", None), question_key=flag.question_key,
            option_value=flag.option_value, auto_raised=True,
        ))
    closed = 0
    for key, finding in have.items():
        if key not in wanted and _status(finding.status) == FindingStatus.open.value and finding.issue_id is None:
            finding.status = FindingStatus.closed
            closed += 1
    return created, closed


# ============================================================== review rules ===
def review_answer(answer: AssessmentAnswer, decision: str, comment: str, reviewer_id: uuid.UUID | None) -> None:
    if decision == "return" and not (comment or "").strip():
        raise WorkflowError("Say what the respondent needs to change: returning an answer needs a comment.")
    answer.review_state = REVIEW_ACCEPTED if decision == "accept" else REVIEW_RETURNED
    answer.review_comment = (comment or "").strip()
    answer.reviewed_by_id = reviewer_id
    answer.reviewed_at = _now()


def review_refusal(assessment: Assessment) -> str | None:
    """Why the final review can't be given yet (apart from segregation of duties). Pure."""
    status = _status(assessment.status)
    if status == VendorAssessmentStatus.reviewed.value:
        return "This assessment has already been reviewed."
    if status != VendorAssessmentStatus.submitted.value:
        return "Only a submitted assessment can be reviewed."
    returned = sum(1 for a in assessment.answers if a.review_state == REVIEW_RETURNED)
    if returned:
        return (f"{returned} answer{'s are' if returned != 1 else ' is'} returned to the respondent; "
                "send them back and wait for the resubmission, or accept them.")
    return None


def next_due(on: date, months: int | None) -> date:
    from app.services.risk_scoring import add_months

    return add_months(on, int(months or DEFAULT_DUE_DILIGENCE_MONTHS))


# ======================================================= vendor risk rating ===
RATING_OVERRIDE_NEEDED = (
    "risk_rating_override_reason: the risk rating differs from the {proposed} proposed by the latest "
    "reviewed due-diligence assessment ({band}); give a reason for the override or pick {proposed}."
)


def apply_rating(vendor: Any, rating: str, severity_type: Any = None) -> dict[str, dict[str, Any]]:
    """Write a due-diligence rating onto a vendor, like ``vendor_tiering.apply_tier``:
    the rating follows the band unless a reasoned override is on record; a stale reason
    is cleared when the stored rating already equals the proposal. Returns the changes."""
    changes: dict[str, dict[str, Any]] = {}
    current = _status(getattr(vendor, "risk_rating", None)) or None
    reason = (getattr(vendor, "risk_rating_override_reason", "") or "").strip()
    if current == rating:
        if reason:
            changes["risk_rating_override_reason"] = {"from": reason, "to": ""}
            vendor.risk_rating_override_reason = ""
    elif not reason:
        changes["risk_rating"] = {"from": current, "to": rating}
        vendor.risk_rating = severity_type(rating) if severity_type else rating
    return changes


def resolve_rating(*, proposed: str | None, band: str, stored_rating: Any, stored_reason: str, sent: Mapping[str, Any]) -> str | None:
    """The override reason a vendor edit leaves (``None`` = leave as is). Pure. Raises
    :class:`WorkflowError` when the resulting rating differs from the due-diligence
    proposal without a reason on record."""
    new_reason = sent.get("risk_rating_override_reason")
    if not proposed:
        return new_reason
    target = _status(sent["risk_rating"]) if "risk_rating" in sent else _status(stored_rating)
    reason = (new_reason if new_reason is not None else stored_reason) or ""
    if (target or None) == proposed:
        return "" if (stored_reason or new_reason) else None
    if not reason.strip():
        raise WorkflowError(RATING_OVERRIDE_NEEDED.format(proposed=proposed, band=band or "no band"))
    return reason.strip() if new_reason is not None else None


def latest_due_diligence(assessments: Iterable[Any]) -> Any | None:
    done = [
        a for a in assessments
        if _status(getattr(a, "status", None)) == VendorAssessmentStatus.reviewed.value
        and getattr(getattr(a, "questionnaire", None), "purpose", "") == "vendor_due_diligence"
    ]
    if not done:
        return None
    return max(done, key=lambda a: (getattr(a, "reviewed_at", None) or datetime.min.replace(tzinfo=timezone.utc),
                                    getattr(a, "created_at", None) or datetime.min.replace(tzinfo=timezone.utc)))


def due_diligence_view(vendor: Any, today: date | None = None) -> dict[str, Any] | None:
    """What the vendor record shows about due diligence. Pure."""
    assessments = list(getattr(vendor, "assessments", None) or [])
    latest = latest_due_diligence(assessments)
    open_findings = sum(
        a.open_findings for a in assessments
        if getattr(getattr(a, "questionnaire", None), "purpose", "") == "vendor_due_diligence"
    )
    in_flight = [a for a in assessments
                 if getattr(getattr(a, "questionnaire", None), "purpose", "") == "vendor_due_diligence"
                 and _status(a.status) in ("draft", "sent", "in_progress", "submitted")]
    if latest is None and not in_flight and not open_findings:
        return None
    today = today or date.today()
    nxt = getattr(vendor, "next_due_diligence_on", None)
    rating = _status(getattr(vendor, "risk_rating", None)) or None
    proposed = getattr(latest, "result_rating", None) if latest else None
    return {
        "assessment_id": getattr(latest, "id", None),
        "title": getattr(latest, "title", "") if latest else "",
        "questionnaire": getattr(latest.questionnaire, "name", "") if latest else "",
        "reviewed_at": getattr(latest, "reviewed_at", None) if latest else None,
        "score_pct": getattr(latest, "result_pct", None) if latest else None,
        "band": getattr(latest, "result_band", "") if latest else "",
        "proposed_rating": proposed,
        "overridden": bool(proposed and rating and rating != proposed),
        "override_reason": getattr(vendor, "risk_rating_override_reason", "") or "",
        "last_on": getattr(vendor, "last_due_diligence_on", None),
        "next_on": nxt,
        "overdue": bool(nxt and nxt < today and _status(getattr(vendor, "status", "")) != "offboarded"),
        "open_findings": open_findings,
        "in_progress": len(in_flight),
    }


async def apply_due_diligence(db, vendor: Any, assessment: Assessment, actor: Any, *, today: date | None = None) -> dict:
    from app.models.enums import AssessmentStatus
    from app.services import audit

    today = today or date.today()
    changes: dict[str, Any] = {}
    rating = assessment.result_rating
    if rating:
        changes.update(apply_rating(vendor, rating, Severity))
    nxt = next_due(today, assessment.recurrence_months)
    for field, value in (("last_due_diligence_on", today), ("next_due_diligence_on", nxt), ("last_assessed_at", today)):
        if getattr(vendor, field, None) != value:
            changes[field] = {"from": str(getattr(vendor, field, None) or ""), "to": value.isoformat()}
            setattr(vendor, field, value)
    if _status(getattr(vendor, "assessment_status", None)) != AssessmentStatus.completed.value:
        vendor.assessment_status = AssessmentStatus.completed
    await db.flush()
    kept = bool(rating and _status(vendor.risk_rating) != rating)
    summary = (
        f"Due diligence of {vendor.name}: {assessment.result_pct if assessment.result_pct is not None else '–'}% "
        f"({assessment.result_band or 'no band'})"
    )
    if "risk_rating" in changes:
        summary += f"; risk rating set to {rating}"
    elif kept:
        summary += f"; manual risk rating kept over the proposed {rating} (override reason on record)"
    summary += f"; next due {nxt.isoformat()}"
    await audit.record(
        db, actor=actor, action="due_diligence", entity_type="vendor", entity_id=vendor.id, summary=summary,
        changes={**changes, "assessment_id": str(assessment.id), "score_pct": assessment.result_pct,
                 "band": assessment.result_band},
    )
    return changes


# ===================================================================== RCSA ===
def worse_rating(*ratings: str | None) -> str | None:
    rated = [r for r in ratings if r in RCSA_RANK]
    return min(rated, key=lambda r: RCSA_RANK[r]) if rated else None


def rcsa_ratings(spec: Sequence[Mapping[str, Any]], values: Mapping[str, ql.AnswerValue]) -> dict[str, dict[str, str | None]]:
    """``{rcsa_risk_id: {"design": value, "operation": value}}`` from the visible answers
    of questions marked with ``config.rcsa_risk_id`` and ``config.rcsa_role``. Pure."""
    vis = ql.visibility(spec, values)
    out: dict[str, dict[str, str | None]] = {}
    for s in spec:
        for q in s.get("questions") or []:
            cfg = q.get("config") or {}
            role, line = cfg.get("rcsa_role"), cfg.get("rcsa_risk_id")
            if role not in ("design", "operation") or not line:
                continue
            entry = out.setdefault(str(line), {"design": None, "operation": None})
            answer = values.get(str(q["key"]))
            if str(q["key"]) not in vis.questions or answer is None:
                continue
            chosen = [v for v in answer.option_values]
            entry[role] = chosen[0] if chosen else None
    return out


def build_rcsa_tree(blueprint: Sequence[Mapping[str, Any]], lines: Sequence[Any]) -> list[dict[str, Any]]:
    """Repeat the blueprint's sections once per RCSA line: keys get a ``_<n>`` suffix,
    conditions are rewritten to the suffixed keys, and rating questions are tied to the
    line (``config.rcsa_risk_id``). Pure."""
    import copy

    tree: list[dict[str, Any]] = []
    blueprint_keys = {str(q["key"]) for s in blueprint for q in s.get("questions") or []}

    def rekey(condition: Mapping[str, Any] | None, n: int) -> dict[str, Any]:
        if not condition:
            return {}
        c = copy.deepcopy(dict(condition))
        for rule in c.get("rules") or []:
            if str(rule.get("question")) in blueprint_keys:
                rule["question"] = f"{rule['question']}_{n}"
        return c

    for n, line in enumerate(lines, start=1):
        control = getattr(getattr(line, "control", None), "name", None) or getattr(line, "control_description", "") or ""
        for s in blueprint:
            questions = []
            for q in s.get("questions") or []:
                qc = copy.deepcopy(dict(q))
                qc["key"] = f"{q['key']}_{n}"
                qc["conditions"] = rekey(q.get("conditions"), n)
                cfg = dict(qc.get("config") or {})
                if cfg.get("rcsa_role"):
                    cfg["rcsa_risk_id"] = str(line.id)
                qc["config"] = cfg
                qc.pop("id", None)
                for o in qc.get("options") or []:
                    o.pop("id", None)
                questions.append(qc)
            title = f"{n}. {getattr(line, 'title', '') or 'Risk'}"
            desc = f"Control: {control}" if control else (s.get("description") or "")
            tree.append({"key": f"{s['key']}_{n}", "title": title[:255], "description": desc,
                         "conditions": rekey(s.get("conditions"), n), "questions": questions})
    return tree


async def apply_rcsa(db, assessment: Assessment, actor: Any) -> int:
    """Write each linked RCSA line's self-ratings and control effectiveness."""
    from app.models.enums import ControlEffectiveness
    from app.models.operational_risk import RcsaRisk
    from app.services import audit

    if assessment.rcsa_assessment_id is None:
        return 0
    spec, values, _ = evaluate(assessment)
    ratings = rcsa_ratings(spec, values)
    if not ratings:
        return 0
    rows = (await db.scalars(select(RcsaRisk).where(RcsaRisk.assessment_id == assessment.rcsa_assessment_id))).all()
    updated = 0
    for row in rows:
        r = ratings.get(str(row.id))
        if r is None:
            continue
        row.self_design_rating = r["design"]
        row.self_operation_rating = r["operation"]
        row.self_assessment_id = assessment.id
        worst = worse_rating(r["design"], r["operation"])
        row.control_effectiveness = ControlEffectiveness(worst) if worst else ControlEffectiveness.not_assessed
        updated += 1
    await db.flush()
    await audit.record(
        db, actor=actor, action="self_assess", entity_type="rcsa_assessment", entity_id=assessment.rcsa_assessment_id,
        summary=f"Control self-ratings from '{assessment.title}' written to {updated} RCSA line{'s' if updated != 1 else ''}",
        changes={"assessment_id": str(assessment.id), "lines": updated},
    )
    return updated


# ================================================================== e-mail ===
def _esc(value: Any) -> str:
    import html

    return html.escape(str(value if value is not None else ""), quote=True)


def render_request(
    kind: str, *, organisation: str, assessment: Any, url: str, expires_at: datetime | None,
    contact_name: str = "", message: str = "", returned: int = 0,
) -> tuple[str, str, str]:
    """``(subject, html, text)`` for invite | reminder | overdue | returned."""
    title = getattr(assessment, "title", "") or "questionnaire"
    due = getattr(assessment, "due_date", None)
    due_text = due.strftime("%d %b %Y") if due else ""
    heads = {
        "invite": (f"{organisation}: please complete '{title}'",
                   f"{organisation} asks you to complete the questionnaire below."),
        "reminder": (f"Reminder from {organisation}: '{title}' is due {due_text}".strip(),
                     f"This is a reminder that the questionnaire below is due{(' on ' + due_text) if due_text else ''}."),
        "overdue": (f"Overdue: '{title}' for {organisation}",
                    f"The questionnaire below was due on {due_text} and has not been submitted."),
        "returned": (f"{organisation} has questions about your answers to '{title}'",
                     f"The reviewer has returned {returned} answer{'s' if returned != 1 else ''} with comments. "
                     "Please update them and submit again."),
    }
    subject, lead = heads.get(kind, heads["invite"])
    greeting = f"Dear {contact_name}," if contact_name else "Hello,"
    expiry = expires_at.strftime("%d %b %Y") if expires_at else ""
    html = (
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:620px;margin:0 auto;font-size:14px;color:#222">'
        f"<p>{_esc(greeting)}</p><p>{_esc(lead)}</p>"
        f'<p style="margin:14px 0"><strong>{_esc(title)}</strong>'
        + (f"<br><span style=\"color:#555\">Due {_esc(due_text)}</span>" if due_text else "") + "</p>"
        + (f'<p style="white-space:pre-wrap;border-left:3px solid #ccc;padding-left:10px">{_esc(message)}</p>' if message else "")
        + f'<p><a href="{_esc(url)}" style="display:inline-block;background:#1d4fd7;color:#fff;padding:8px 14px;'
        'border-radius:6px;text-decoration:none">Open the questionnaire</a></p>'
        '<p style="color:#666;font-size:12px">You can save your answers and come back later. The link is personal to you'
        + (f" and works until {_esc(expiry)}" if expiry else "")
        + ". Do not forward it. If you did not expect this e-mail, contact "
        + _esc(organisation) + ".</p></div>"
    )
    text = (
        f"{greeting}\n\n{lead}\n\n{title}\n" + (f"Due {due_text}\n" if due_text else "")
        + (f"\n{message}\n" if message else "")
        + f"\nOpen the questionnaire: {url}\n\nYou can save your answers and come back later. The link is personal to you"
        + (f" and works until {expiry}" if expiry else "") + ". Do not forward it.\n"
    )
    return subject, html, text


async def email_link(kind: str, *, organisation: str, assessment: Any, link: Any, token: str, message: str = "",
                     returned: int = 0) -> bool:
    """E-mail a link to its contact. True when actually sent."""
    from app.services import email, questionnaire_portal

    if not getattr(link, "contact_email", ""):
        return False
    subject, html, text = render_request(
        kind, organisation=organisation, assessment=assessment, url=questionnaire_portal.respond_url(token),
        expires_at=link.expires_at, contact_name=link.contact_name, message=message, returned=returned,
    )
    sent = await email.send_email(link.contact_email, subject, html, text)
    if sent:
        link.emailed_at = _now()
    return sent


def event_notification(tenant_id: uuid.UUID, assessment: Any, *, user_id: uuid.UUID | None, key: str, title: str,
                       body: str, category: Any = None) -> Any:
    from app.models.enums import NotificationCategory
    from app.models.notification import EVENT_PREFIX, Notification

    return Notification(
        tenant_id=tenant_id, user_id=user_id, role_name="", title=title[:255], body=body,
        category=category or NotificationCategory.warning, entity_type="assessment", entity_id=assessment.id,
        link=f"/assessments?id={assessment.id}", dedup_key=f"{EVENT_PREFIX}{key}"[:255],
    )


# =============================================================== scheduler ===
@dataclass(frozen=True)
class DueAction:
    kind: str  # reminder | overdue_first | overdue_reminder


def due_action(assessment: Any, today: date) -> DueAction | None:
    """What the scheduler owes an assessment today, if anything. Pure."""
    if _status(assessment.status) not in ("sent", "in_progress") or assessment.due_date is None:
        return None
    days_left = (assessment.due_date - today).days
    last = assessment.last_reminder_on
    if days_left < 0:
        if assessment.overdue_alerted_on is None:
            return DueAction("overdue_first")
        if last is None or (today - last).days >= OVERDUE_REMINDER_EVERY_DAYS:
            return DueAction("overdue_reminder")
        return None
    if days_left <= REMINDER_LEAD_DAYS and (last is None or (today - last).days >= REMINDER_EVERY_DAYS):
        return DueAction("reminder")
    return None


def reissue_due(assessment: Any, today: date) -> bool:
    return (
        _status(assessment.status) == VendorAssessmentStatus.reviewed.value
        and bool(assessment.recurrence_months) and assessment.next_issue_on is not None
        and assessment.next_issue_on <= today
    )


async def run_due(db, tenant_id: uuid.UUID, tenant_name: str, today: date | None = None) -> dict[str, int]:
    """Reminders, overdue alerts and recurrence for one organisation (scheduler step)."""
    from app.models.enums import NotificationCategory
    from app.services import audit, email, questionnaire_portal, questionnaire_versions

    today = today or date.today()
    summary = {"reminders": 0, "overdue": 0, "reissued": 0}
    open_rows = (await db.scalars(
        select(Assessment).where(Assessment.status.in_([VendorAssessmentStatus.sent, VendorAssessmentStatus.in_progress]),
                                 Assessment.due_date.is_not(None))
    )).all()
    for a in open_rows:
        action = due_action(a, today)
        if action is None:
            continue
        if action.kind == "overdue_first":
            a.overdue_alerted_on = today
            for uid in {a.sent_by_id, a.reviewer_id} - {None}:
                db.add(event_notification(
                    tenant_id, a, user_id=uid, key=f"assessment-overdue:{a.id}:{uid}",
                    title=f"Assessment overdue: {a.title}",
                    body=f"'{a.title}' was due on {a.due_date.isoformat()} and has not been submitted"
                         + (f" by {a.contact_email}" if a.contact_email else "") + ".",
                    category=NotificationCategory.warning,
                ))
            summary["overdue"] += 1
        a.last_reminder_on = today
        if a.contact_email and email.is_configured():
            link, token = questionnaire_portal.issue_link(
                tenant_id=tenant_id, assessment_id=a.id, contact_name=a.contact_name, contact_email=a.contact_email,
                reason="reminder",
            )
            db.add(link)
            kind = "reminder" if action.kind == "reminder" else "overdue"
            if await email_link(kind, organisation=tenant_name, assessment=a, link=link, token=token):
                summary["reminders"] += 1
        await audit.record_system(
            db, tenant_id=tenant_id, action="remind", entity_type="assessment", entity_id=a.id,
            summary=f"{'Reminder' if action.kind == 'reminder' else 'Overdue notice'} for '{a.title}'"
                    + (f" to {a.contact_email}" if a.contact_email else ""),
        )
    await db.flush()

    reviewed = (await db.scalars(
        select(Assessment).where(Assessment.status == VendorAssessmentStatus.reviewed,
                                 Assessment.next_issue_on.is_not(None), Assessment.next_issue_on <= today)
    )).all()
    for parent in reviewed:
        if not reissue_due(parent, today):
            continue
        version = await questionnaire_versions.published_version(db, parent.questionnaire.family_id or parent.questionnaire_id)
        child = Assessment(
            tenant_id=tenant_id, title=f"{_base_title(parent.title)} ({today.strftime('%b %Y')})"[:255],
            vendor_id=parent.vendor_id, questionnaire_id=(version.id if version else parent.questionnaire_id),
            status=VendorAssessmentStatus.draft, due_date=today + timedelta(days=REISSUE_DUE_DAYS),
            contact_name=parent.contact_name, contact_email=parent.contact_email, reviewer_id=parent.reviewer_id,
            recurrence_months=parent.recurrence_months, parent_assessment_id=parent.id,
            rcsa_assessment_id=parent.rcsa_assessment_id, sent_by_id=parent.sent_by_id, review_notes="",
        )
        db.add(child)
        parent.next_issue_on = None
        await db.flush()
        if parent.sent_by_id:
            db.add(event_notification(
                tenant_id, child, user_id=parent.sent_by_id, key=f"assessment-reissued:{child.id}",
                title=f"Assessment re-issued: {child.title}",
                body=f"'{parent.title}' recurs every {parent.recurrence_months} months. The new assessment is a draft: "
                     "check the contact and due date, then send it.",
                category=NotificationCategory.info,
            ))
        await audit.record_system(
            db, tenant_id=tenant_id, action="create", entity_type="assessment", entity_id=child.id,
            summary=f"Re-issued '{parent.title}' as '{child.title}' (every {parent.recurrence_months} months)",
            changes={"parent_assessment_id": str(parent.id)},
        )
        summary["reissued"] += 1
    await db.flush()
    return summary


def _base_title(title: str) -> str:
    import re

    return re.sub(r"\s*\([A-Z][a-z]{2} \d{4}\)$", "", title or "").strip() or "Assessment"
