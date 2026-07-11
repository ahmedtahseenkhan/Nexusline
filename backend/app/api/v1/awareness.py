"""Awareness Training API — program/quiz builder, participant assignment, quiz scoring."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.awareness import (
    AwarenessOption,
    AwarenessProgram,
    AwarenessQuestion,
    TrainingRecord,
)
from app.models.enums import TrainingStatus
from app.schemas.awareness import (
    ParticipantCreate,
    ParticipantUpdate,
    ProgramCreate,
    ProgramRead,
    ProgramSummary,
    ProgramUpdate,
    QuizSubmit,
)
from app.schemas.common import Page
from app.services.refs import next_reference
from app.services import audit
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/awareness-programs", tags=["awareness"])


async def _load(db, program_id: uuid.UUID) -> AwarenessProgram:
    obj = await db.scalar(
        select(AwarenessProgram).where(
            AwarenessProgram.id == program_id, AwarenessProgram.deleted.is_(False)
        )
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")
    return obj


async def _fresh(db, program_id: uuid.UUID) -> AwarenessProgram:
    return await db.scalar(
        select(AwarenessProgram).where(AwarenessProgram.id == program_id).execution_options(populate_existing=True)
    )


async def _next_ref(db) -> str:
    return await next_reference(db, AwarenessProgram, "AW")


_PROGRAM_SORTABLE = {
    "reference": AwarenessProgram.reference,
    "name": AwarenessProgram.name,
    "status": AwarenessProgram.status,
    "frequency": AwarenessProgram.frequency,
    "passing_score": AwarenessProgram.passing_score,
    "next_due_date": AwarenessProgram.next_due_date,
    "due_date": AwarenessProgram.due_date,
    "created_at": AwarenessProgram.created_at,
}


@router.get("", response_model=Page[ProgramSummary], dependencies=[Depends(require("awareness:read"))])
async def list_programs(
    db: DbSession,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProgramSummary]:
    stmt = select(AwarenessProgram).where(AwarenessProgram.deleted.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            AwarenessProgram.name.ilike(like) | AwarenessProgram.reference.ilike(like)
        )
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _PROGRAM_SORTABLE, default=AwarenessProgram.name)
    else:
        stmt = stmt.order_by(AwarenessProgram.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(
        items=[ProgramSummary.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


def _build_questions(tenant_id, question_specs) -> list[AwarenessQuestion]:
    """Materialize quiz question/option ORM objects from create-shaped specs."""
    out: list[AwarenessQuestion] = []
    for i, qc in enumerate(question_specs):
        q = AwarenessQuestion(tenant_id=tenant_id, text=qc.text, order_index=qc.order_index or i)
        q.options = [
            AwarenessOption(
                tenant_id=tenant_id, label=o.label, is_correct=o.is_correct, order_index=o.order_index or j
            )
            for j, o in enumerate(qc.options)
        ]
        out.append(q)
    return out


@router.post("", response_model=ProgramRead, status_code=201, dependencies=[Depends(require("awareness:write"))])
async def create_program(body: ProgramCreate, db: DbSession, user: CurrentUser) -> ProgramRead:
    data = body.model_dump(exclude={"questions"})
    program = AwarenessProgram(tenant_id=user.tenant_id, **data)
    program.reference = await _next_ref(db)
    program.next_due_date = next_review_date(program.frequency)
    program.questions = _build_questions(user.tenant_id, body.questions)
    db.add(program)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="awareness_program", entity_id=program.id,
        summary=f"Created awareness program {program.reference}: {program.name}",
    )
    return ProgramRead.model_validate(await _load(db, program.id))


@router.get("/{program_id}", response_model=ProgramRead, dependencies=[Depends(require("awareness:read"))])
async def get_program(program_id: uuid.UUID, db: DbSession) -> ProgramRead:
    return ProgramRead.model_validate(await _load(db, program_id))


@router.patch("/{program_id}", response_model=ProgramRead, dependencies=[Depends(require("awareness:write"))])
async def update_program(
    program_id: uuid.UUID, body: ProgramUpdate, db: DbSession, user: CurrentUser
) -> ProgramRead:
    program = await _load(db, program_id)
    data = body.model_dump(exclude_unset=True)
    # When `questions` is supplied, fully replace the quiz (delete-orphan cascade handles removals).
    if "questions" in data:
        data.pop("questions")
        if body.questions is not None:
            program.questions = _build_questions(program.tenant_id, body.questions)
    for f, v in data.items():
        setattr(program, f, v)
    if "frequency" in data:
        program.next_due_date = next_review_date(program.frequency)
    await db.flush()
    return ProgramRead.model_validate(await _fresh(db, program.id))


@router.delete("/{program_id}", status_code=204, dependencies=[Depends(require("awareness:write"))])
async def delete_program(program_id: uuid.UUID, db: DbSession) -> None:
    from datetime import datetime, timezone

    obj = await _load(db, program_id)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)


# ---------------------------------------------------------------- participants
@router.post(
    "/{program_id}/participants",
    response_model=ProgramRead,
    status_code=201,
    dependencies=[Depends(require("awareness:write"))],
)
async def add_participant(program_id: uuid.UUID, body: ParticipantCreate, db: DbSession, user: CurrentUser) -> ProgramRead:
    await _load(db, program_id)
    db.add(TrainingRecord(tenant_id=user.tenant_id, program_id=program_id, **body.model_dump()))
    await db.flush()
    return ProgramRead.model_validate(await _fresh(db, program_id))


@router.patch(
    "/{program_id}/participants/{participant_id}",
    response_model=ProgramRead,
    dependencies=[Depends(require("awareness:write"))],
    summary="Edit a training record (status / score / completion date)",
)
async def update_participant(
    program_id: uuid.UUID, participant_id: uuid.UUID, body: ParticipantUpdate, db: DbSession
) -> ProgramRead:
    record = await db.scalar(
        select(TrainingRecord).where(
            TrainingRecord.id == participant_id, TrainingRecord.program_id == program_id
        )
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(record, f, v)
    await db.flush()
    return ProgramRead.model_validate(await _fresh(db, program_id))


@router.post(
    "/{program_id}/participants/{participant_id}/quiz",
    response_model=ProgramRead,
    dependencies=[Depends(require("awareness:write"))],
    summary="Submit a participant's quiz answers; auto-scores and marks completed",
)
async def submit_quiz(
    program_id: uuid.UUID, participant_id: uuid.UUID, body: QuizSubmit, db: DbSession
) -> ProgramRead:
    program = await _load(db, program_id)
    record = await db.scalar(
        select(TrainingRecord).where(
            TrainingRecord.id == participant_id, TrainingRecord.program_id == program_id
        )
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")

    questions = program.questions
    if not questions:
        raise HTTPException(status_code=400, detail="Program has no questions")
    correct_option = {q.id: next((o.id for o in q.options if o.is_correct), None) for q in questions}

    correct = 0
    for q in questions:
        chosen = body.answers.get(q.id)
        if chosen is not None and chosen == correct_option[q.id]:
            correct += 1
    record.score = round(100 * correct / len(questions))
    record.status = TrainingStatus.completed
    record.completed_at = date.today()
    await db.flush()
    return ProgramRead.model_validate(await _fresh(db, program_id))


@router.delete(
    "/{program_id}/participants/{participant_id}",
    status_code=204,
    dependencies=[Depends(require("awareness:write"))],
)
async def delete_participant(program_id: uuid.UUID, participant_id: uuid.UUID, db: DbSession) -> None:
    record = await db.scalar(
        select(TrainingRecord).where(
            TrainingRecord.id == participant_id, TrainingRecord.program_id == program_id
        )
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    await db.delete(record)
