from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AwarenessStatus, ReviewFrequency, TrainingStatus


# ---------------------------------------------------------------- quiz builder
class OptionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=500)
    is_correct: bool = False
    order_index: int = 0


class OptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    is_correct: bool
    order_index: int


class QuestionCreate(BaseModel):
    text: str = Field(min_length=1)
    order_index: int = 0
    options: list[OptionCreate] = Field(default_factory=list)


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    order_index: int
    options: list[OptionRead] = []


# ------------------------------------------------------------------ participants
class ParticipantCreate(BaseModel):
    participant_name: str = Field(min_length=1, max_length=200)
    participant_email: str = ""


class QuizSubmit(BaseModel):
    answers: dict[uuid.UUID, uuid.UUID]  # question_id -> chosen option_id


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    program_id: uuid.UUID
    participant_name: str
    participant_email: str
    status: TrainingStatus
    score: int | None
    completed_at: date | None


# --------------------------------------------------------------------- programs
class ProgramBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    content: str = ""
    status: AwarenessStatus = AwarenessStatus.draft
    passing_score: int = Field(default=80, ge=0, le=100)
    frequency: ReviewFrequency = ReviewFrequency.annual
    due_date: date | None = None


class ProgramCreate(ProgramBase):
    questions: list[QuestionCreate] = Field(default_factory=list)


class ProgramUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    content: str | None = None
    status: AwarenessStatus | None = None
    passing_score: int | None = Field(default=None, ge=0, le=100)
    frequency: ReviewFrequency | None = None
    due_date: date | None = None


class ProgramSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    name: str
    status: AwarenessStatus
    passing_score: int
    next_due_date: date | None
    question_count: int
    participant_count: int
    completed_count: int
    compliant_count: int
    completion_pct: float
    compliance_pct: float


class ProgramRead(ProgramSummary):
    description: str
    content: str
    frequency: ReviewFrequency
    due_date: date | None
    questions: list[QuestionRead] = []
    participants: list[ParticipantRead] = []
    created_at: datetime
