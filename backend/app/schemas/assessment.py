from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FindingStatus, Severity, VendorAssessmentStatus


class VendorRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class QuestionnaireRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


# ------------------------------------------------------------ questionnaire builder
class OptionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    score: float = Field(default=0.0, ge=0)
    order_index: int = 0


class OptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    score: float
    order_index: int


class QuestionCreate(BaseModel):
    text: str = Field(min_length=1)
    guidance: str = ""
    order_index: int = 0
    options: list[OptionCreate] = Field(default_factory=list)


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    guidance: str
    order_index: int
    max_score: float
    options: list[OptionRead] = []


class QuestionnaireCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    questions: list[QuestionCreate] = Field(default_factory=list)


class QuestionnaireUpdate(BaseModel):
    """Partial update for a questionnaire template. When ``questions`` is provided
    the whole question/option tree is replaced (builder semantics)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    questions: list[QuestionCreate] | None = None


class QuestionnaireSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    question_count: int
    max_score: float


class QuestionnaireRead(QuestionnaireSummary):
    questions: list[QuestionRead] = []


# ------------------------------------------------------------------- assessments
class AssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    vendor_id: uuid.UUID | None = None
    questionnaire_id: uuid.UUID
    due_date: date | None = None
    status: VendorAssessmentStatus | None = None
    review_notes: str = ""


class AssessmentUpdate(BaseModel):
    """Partial update for the assessment header (only sent fields are applied)."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    vendor_id: uuid.UUID | None = None
    questionnaire_id: uuid.UUID | None = None
    due_date: date | None = None
    status: VendorAssessmentStatus | None = None
    review_notes: str | None = None


class AnswerSubmit(BaseModel):
    question_id: uuid.UUID
    option_id: uuid.UUID | None = None
    comment: str = ""


class SubmitAnswers(BaseModel):
    answers: list[AnswerSubmit]
    submit: bool = False  # mark the assessment as submitted


class AnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    question_id: uuid.UUID
    option_id: uuid.UUID | None
    comment: str


class FindingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    severity: Severity = Severity.medium
    status: FindingStatus = FindingStatus.open
    deadline: date | None = None


class FindingUpdate(BaseModel):
    """Partial update for a finding (edit any field, including reopen/close)."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    severity: Severity | None = None
    status: FindingStatus | None = None
    deadline: date | None = None


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str
    severity: Severity
    status: FindingStatus
    deadline: date | None
    created_at: datetime


class AssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    vendor_id: uuid.UUID | None
    vendor: VendorRef | None = None
    questionnaire_id: uuid.UUID
    questionnaire: QuestionnaireRead | None = None
    status: VendorAssessmentStatus
    access_hash: str
    due_date: date | None
    submitted_at: date | None
    review_notes: str
    question_count: int
    answered_count: int
    max_score: float
    total_score: float
    score_pct: float
    open_findings: int
    answers: list[AnswerRead] = []
    findings: list[FindingRead] = []
    created_at: datetime


class AssessmentSummary(BaseModel):
    """Lightweight row for the assessment list."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    vendor: VendorRef | None = None
    questionnaire: QuestionnaireRef | None = None
    questionnaire_id: uuid.UUID
    status: VendorAssessmentStatus
    due_date: date | None
    submitted_at: date | None = None
    question_count: int
    answered_count: int
    max_score: float = 0.0
    total_score: float = 0.0
    score_pct: float
    open_findings: int
    created_at: datetime
