"""Vendor Assessments API — questionnaire builder + assessment answering/scoring/findings."""
from __future__ import annotations

import secrets
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.assessment import (
    Assessment,
    AssessmentAnswer,
    AssessmentFinding,
    Question,
    QuestionOption,
    Questionnaire,
)
from app.models.enums import FindingStatus, VendorAssessmentStatus
from app.models.vendor import Vendor
from app.schemas.assessment import (
    AssessmentCreate,
    AssessmentRead,
    AssessmentSummary,
    AssessmentUpdate,
    FindingCreate,
    FindingUpdate,
    QuestionnaireCreate,
    QuestionnaireRead,
    QuestionnaireSummary,
    QuestionnaireUpdate,
    SubmitAnswers,
)
from app.services import audit

router = APIRouter(tags=["assessments"])


# ============================================================ questionnaire builder
@router.get(
    "/questionnaires",
    response_model=list[QuestionnaireSummary],
    dependencies=[Depends(require("assessment:read"))],
)
async def list_questionnaires(db: DbSession) -> list[QuestionnaireSummary]:
    rows = (await db.scalars(select(Questionnaire).order_by(Questionnaire.name))).all()
    return [QuestionnaireSummary.model_validate(r) for r in rows]


async def _load_questionnaire(db, qid: uuid.UUID) -> Questionnaire:
    obj = await db.scalar(select(Questionnaire).where(Questionnaire.id == qid))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionnaire not found")
    return obj


async def _fresh_questionnaire(db, qid: uuid.UUID) -> Questionnaire:
    """Re-read after a mutation, refreshing the identity-mapped instance + children."""
    return await db.scalar(
        select(Questionnaire).where(Questionnaire.id == qid).execution_options(populate_existing=True)
    )


def _build_questions(tenant_id, questions) -> list[Question]:
    """Materialise the question/option tree from the builder payload."""
    built: list[Question] = []
    for i, qc in enumerate(questions):
        question = Question(
            tenant_id=tenant_id,
            text=qc.text,
            guidance=qc.guidance,
            order_index=qc.order_index or i,
        )
        question.options = [
            QuestionOption(
                tenant_id=tenant_id, label=o.label, score=o.score, order_index=o.order_index or j
            )
            for j, o in enumerate(qc.options)
        ]
        built.append(question)
    return built


@router.post(
    "/questionnaires",
    response_model=QuestionnaireRead,
    status_code=201,
    dependencies=[Depends(require("assessment:write"))],
)
async def create_questionnaire(
    body: QuestionnaireCreate, db: DbSession, user: CurrentUser
) -> QuestionnaireRead:
    q = Questionnaire(tenant_id=user.tenant_id, name=body.name, description=body.description)
    q.questions = _build_questions(user.tenant_id, body.questions)
    db.add(q)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="questionnaire", entity_id=q.id,
        summary=f"Created questionnaire '{q.name}'",
    )
    return QuestionnaireRead.model_validate(await _load_questionnaire(db, q.id))


@router.patch(
    "/questionnaires/{qid}",
    response_model=QuestionnaireRead,
    dependencies=[Depends(require("assessment:write"))],
    summary="Update a questionnaire; sending `questions` replaces the whole question tree",
)
async def update_questionnaire(
    qid: uuid.UUID, body: QuestionnaireUpdate, db: DbSession, user: CurrentUser
) -> QuestionnaireRead:
    obj = await _load_questionnaire(db, qid)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        obj.name = data["name"]
    if "description" in data:
        obj.description = data["description"]
    if body.questions is not None:
        # cascade="all, delete-orphan" removes the old questions/options on reassign
        obj.questions = _build_questions(user.tenant_id, body.questions)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="questionnaire", entity_id=obj.id,
        summary=f"Updated questionnaire '{obj.name}'",
    )
    return QuestionnaireRead.model_validate(await _fresh_questionnaire(db, obj.id))


@router.get(
    "/questionnaires/{qid}",
    response_model=QuestionnaireRead,
    dependencies=[Depends(require("assessment:read"))],
)
async def get_questionnaire(qid: uuid.UUID, db: DbSession) -> QuestionnaireRead:
    return QuestionnaireRead.model_validate(await _load_questionnaire(db, qid))


@router.delete(
    "/questionnaires/{qid}", status_code=204, dependencies=[Depends(require("assessment:write"))]
)
async def delete_questionnaire(qid: uuid.UUID, db: DbSession) -> None:
    obj = await _load_questionnaire(db, qid)
    # The assessments.questionnaire_id FK is RESTRICT. Without this check the DELETE
    # only fails at commit — which happens after the response is sent — so the client
    # would get a false 204 while the row survives. Reject up front instead.
    in_use = await db.scalar(
        select(func.count()).select_from(Assessment).where(Assessment.questionnaire_id == qid)
    )
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Questionnaire is used by {in_use} assessment(s); delete or repoint them first.",
        )
    await db.delete(obj)


# ===================================================================== assessments
async def _load(db, aid: uuid.UUID) -> Assessment:
    obj = await db.scalar(select(Assessment).where(Assessment.id == aid))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return obj


async def _fresh(db, aid: uuid.UUID) -> Assessment:
    return await db.scalar(
        select(Assessment).where(Assessment.id == aid).execution_options(populate_existing=True)
    )


@router.get(
    "/assessments",
    response_model=list[AssessmentSummary],
    dependencies=[Depends(require("assessment:read"))],
)
async def list_assessments(db: DbSession) -> list[AssessmentSummary]:
    rows = (await db.scalars(select(Assessment).order_by(Assessment.created_at.desc()))).all()
    return [AssessmentSummary.model_validate(r) for r in rows]


@router.post(
    "/assessments",
    response_model=AssessmentRead,
    status_code=201,
    dependencies=[Depends(require("assessment:write"))],
)
async def create_assessment(body: AssessmentCreate, db: DbSession, user: CurrentUser) -> AssessmentRead:
    # validate questionnaire exists in this tenant
    await _load_questionnaire(db, body.questionnaire_id)
    if body.vendor_id is not None:
        v = await db.scalar(
            select(Vendor.id).where(Vendor.id == body.vendor_id, Vendor.deleted.is_(False))
        )
        if v is None:
            raise HTTPException(status_code=400, detail=f"Unknown or archived vendor id: {body.vendor_id}")
    obj = Assessment(
        tenant_id=user.tenant_id,
        title=body.title,
        vendor_id=body.vendor_id,
        questionnaire_id=body.questionnaire_id,
        due_date=body.due_date,
        review_notes=body.review_notes,
        access_hash=secrets.token_urlsafe(24),
        status=body.status or VendorAssessmentStatus.draft,
    )
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="assessment", entity_id=obj.id,
        summary=f"Created vendor assessment '{obj.title}'",
    )
    return AssessmentRead.model_validate(await _fresh(db, obj.id))


@router.get(
    "/assessments/{aid}",
    response_model=AssessmentRead,
    dependencies=[Depends(require("assessment:read"))],
)
async def get_assessment(aid: uuid.UUID, db: DbSession) -> AssessmentRead:
    return AssessmentRead.model_validate(await _load(db, aid))


@router.patch(
    "/assessments/{aid}",
    response_model=AssessmentRead,
    dependencies=[Depends(require("assessment:write"))],
    summary="Update the assessment header (title, vendor, questionnaire, due date, status, notes)",
)
async def update_assessment(
    aid: uuid.UUID, body: AssessmentUpdate, db: DbSession, user: CurrentUser
) -> AssessmentRead:
    obj = await _load(db, aid)
    data = body.model_dump(exclude_unset=True)
    # validate a re-pointed questionnaire belongs to this tenant
    if data.get("questionnaire_id") is not None:
        await _load_questionnaire(db, data["questionnaire_id"])
    for field, value in data.items():
        setattr(obj, field, value)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="assessment", entity_id=obj.id,
        summary=f"Updated vendor assessment '{obj.title}'",
    )
    return AssessmentRead.model_validate(await _fresh(db, aid))


@router.post(
    "/assessments/{aid}/answers",
    response_model=AssessmentRead,
    dependencies=[Depends(require("assessment:write"))],
    summary="Submit/update answers (weighted-scored); optionally mark submitted",
)
async def submit_answers(
    aid: uuid.UUID, body: SubmitAnswers, db: DbSession, user: CurrentUser
) -> AssessmentRead:
    assessment = await _load(db, aid)

    # valid question ids for this assessment's questionnaire, and each question's option ids
    questions = {q.id: q for q in assessment.questionnaire.questions}
    valid_options = {q.id: {o.id for o in q.options} for q in assessment.questionnaire.questions}

    existing = {a.question_id: a for a in assessment.answers}
    for ans in body.answers:
        if ans.question_id not in questions:
            raise HTTPException(status_code=400, detail=f"Unknown question {ans.question_id}")
        if ans.option_id is not None and ans.option_id not in valid_options[ans.question_id]:
            raise HTTPException(
                status_code=400, detail=f"Option does not belong to question {ans.question_id}"
            )
        row = existing.get(ans.question_id)
        if row is None:
            db.add(
                AssessmentAnswer(
                    tenant_id=user.tenant_id,
                    assessment_id=aid,
                    question_id=ans.question_id,
                    option_id=ans.option_id,
                    comment=ans.comment,
                )
            )
        else:
            row.option_id = ans.option_id
            row.comment = ans.comment

    if body.submit:
        assessment.status = VendorAssessmentStatus.submitted
        assessment.submitted_at = date.today()
    elif assessment.status == VendorAssessmentStatus.draft:
        assessment.status = VendorAssessmentStatus.in_progress

    await db.flush()
    return AssessmentRead.model_validate(await _fresh(db, aid))


@router.post(
    "/assessments/{aid}/findings",
    response_model=AssessmentRead,
    status_code=201,
    dependencies=[Depends(require("assessment:write"))],
)
async def add_finding(
    aid: uuid.UUID, body: FindingCreate, db: DbSession, user: CurrentUser
) -> AssessmentRead:
    await _load(db, aid)
    db.add(AssessmentFinding(tenant_id=user.tenant_id, assessment_id=aid, **body.model_dump()))
    await db.flush()
    return AssessmentRead.model_validate(await _fresh(db, aid))


async def _load_finding(db, aid: uuid.UUID, fid: uuid.UUID) -> AssessmentFinding:
    finding = await db.scalar(
        select(AssessmentFinding).where(
            AssessmentFinding.id == fid, AssessmentFinding.assessment_id == aid
        )
    )
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    return finding


@router.patch(
    "/assessments/{aid}/findings/{fid}",
    response_model=AssessmentRead,
    dependencies=[Depends(require("assessment:write"))],
    summary="Edit a finding (title, description, severity, status, deadline)",
)
async def update_finding(
    aid: uuid.UUID, fid: uuid.UUID, body: FindingUpdate, db: DbSession
) -> AssessmentRead:
    finding = await _load_finding(db, aid, fid)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(finding, field, value)
    await db.flush()
    return AssessmentRead.model_validate(await _fresh(db, aid))


@router.post(
    "/assessments/{aid}/findings/{fid}/close",
    response_model=AssessmentRead,
    dependencies=[Depends(require("assessment:write"))],
)
async def close_finding(aid: uuid.UUID, fid: uuid.UUID, db: DbSession) -> AssessmentRead:
    finding = await _load_finding(db, aid, fid)
    finding.status = FindingStatus.closed
    await db.flush()
    return AssessmentRead.model_validate(await _fresh(db, aid))


@router.delete(
    "/assessments/{aid}", status_code=204, dependencies=[Depends(require("assessment:write"))]
)
async def delete_assessment(aid: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _load(db, aid))
