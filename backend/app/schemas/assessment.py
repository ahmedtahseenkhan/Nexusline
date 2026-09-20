from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import FindingStatus, Severity, VendorAssessmentStatus

QuestionType = Literal[
    "single_choice", "multiple_choice", "yes_no_na", "text", "long_text", "number", "date", "file_upload"
]
Purpose = Literal["general", "vendor_tiering", "vendor_due_diligence", "rcsa_control_self_assessment"]
Rating = Literal["low", "medium", "high", "critical"]


class VendorRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class QuestionnaireRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    version: int = 1
    status: str = "published"
    purpose: str = "general"


# ------------------------------------------------------------ questionnaire builder
_CONDITIONS = (
    'Display condition: {"match": "all" | "any", "rules": [{"question": "<earlier question key>", '
    '"op": "in" | "not_in" | "answered" | "not_answered" | "eq" | "neq" | "gt" | "gte" | "lt" | "lte", '
    '"values": ["<option value>"], "value": 3}]}. Empty shows always.'
)


class BandIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    min_pct: float = Field(ge=0, le=100)
    rating: Rating


class OptionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    score: float = Field(default=0.0, ge=0)
    order_index: int = 0
    value: str = Field(default="", max_length=64, description="Stable key conditions refer to; generated from the label when blank.")
    is_na: bool = Field(default=False, description="Not applicable: the question drops out of scoring.")
    risk_flag: bool = Field(default=False, description="Choosing this answer raises a finding on submit.")
    finding_title: str = Field(default="", max_length=255)
    finding_severity: Rating = "medium"


class OptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    score: float
    order_index: int
    value: str = ""
    is_na: bool = False
    risk_flag: bool = False
    finding_title: str = ""
    finding_severity: str = "medium"


class QuestionCreate(BaseModel):
    text: str = Field(min_length=1)
    guidance: str = ""
    order_index: int = 0
    key: str = Field(default="", max_length=64, description="Stable key; generated when blank.")
    type: QuestionType = "single_choice"
    mandatory: bool = False
    weight: float = Field(default=1.0, ge=0, le=100)
    conditions: dict[str, Any] = Field(default_factory=dict, description=_CONDITIONS)
    config: dict[str, Any] = Field(default_factory=dict)
    options: list[OptionCreate] = Field(default_factory=list)


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    guidance: str
    order_index: int
    max_score: float
    key: str = ""
    type: str = "single_choice"
    mandatory: bool = False
    weight: float = 1.0
    conditions: dict[str, Any] = {}
    config: dict[str, Any] = {}
    section_id: uuid.UUID | None = None
    options: list[OptionRead] = []


class SectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    key: str = Field(default="", max_length=64)
    conditions: dict[str, Any] = Field(default_factory=dict, description=_CONDITIONS)
    questions: list[QuestionCreate] = Field(default_factory=list)


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    key: str
    title: str
    description: str
    order_index: int
    conditions: dict[str, Any] = {}


class QuestionnaireCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    purpose: Purpose = "general"
    bands: list[BandIn] = Field(default_factory=list)
    change_note: str = ""
    sections: list[SectionCreate] | None = None
    #: Older clients: a flat question list, placed in one "Questions" section.
    questions: list[QuestionCreate] = Field(default_factory=list)


class QuestionnaireUpdate(BaseModel):
    """Save a *draft* version. Sending ``sections`` (or the legacy flat ``questions``)
    replaces the draft's whole section / question tree. A published version can't be
    edited: create a new version first (``POST /questionnaires/{id}/new-version``)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    purpose: Purpose | None = None
    bands: list[BandIn] | None = None
    change_note: str | None = None
    sections: list[SectionCreate] | None = None
    questions: list[QuestionCreate] | None = None


class QuestionnaireSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    question_count: int
    max_score: float
    family_id: uuid.UUID | None = None
    version: int = 1
    status: str = "published"
    purpose: str = "general"
    section_count: int = 0
    origin: str = "tenant"
    library_key: str = ""
    library_version: int | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    #: Set on list rows: the family's published version id (new assessments use it) and
    #: whether a draft is open.
    published_version_id: uuid.UUID | None = None
    published_version: int | None = None
    draft_version_id: uuid.UUID | None = None


class QuestionnaireRead(QuestionnaireSummary):
    bands: list[dict[str, Any]] = []
    change_note: str = ""
    published_by_id: uuid.UUID | None = None
    sections: list[SectionRead] = []
    questions: list[QuestionRead] = []
    in_use: int = 0


class VersionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    status: str
    name: str
    change_note: str = ""
    published_at: datetime | None = None
    published_by_id: uuid.UUID | None = None
    created_at: datetime
    question_count: int
    in_use: int = 0


class PublishRequest(BaseModel):
    change_note: str = Field(default="", max_length=2000)


class StructureProblems(BaseModel):
    problems: list[str]


class LibraryTemplate(BaseModel):
    key: str
    version: int
    name: str
    purpose: str
    description: str
    section_count: int
    question_count: int
    scored_question_count: int
    risk_flag_count: int
    installed_versions: list[int] = []


class LibraryInstall(BaseModel):
    name: str | None = Field(default=None, max_length=255)


class PreviewScoreRequest(BaseModel):
    """Answers by question key: ``{"q1": {"option_values": ["yes"], "number": 3, "na": false}}``."""

    answers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PreviewScoreResult(BaseModel):
    visible_sections: list[str]
    visible_questions: list[str]
    earned: float
    maximum: float
    pct: float | None
    band: str
    rating: str | None
    missing_mandatory: list[str]
    risk_flags: list[dict[str, Any]]


# ------------------------------------------------------------------- assessments
class AssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    vendor_id: uuid.UUID | None = None
    questionnaire_id: uuid.UUID = Field(description="Any version of the questionnaire; the assessment pins its published version.")
    due_date: date | None = None
    status: VendorAssessmentStatus | None = Field(default=None, description="Ignored: a new assessment starts as a draft.")
    review_notes: str = ""
    contact_name: str = Field(default="", max_length=200)
    contact_email: str = Field(default="", max_length=255)
    reviewer_id: uuid.UUID | None = None
    recurrence_months: int | None = Field(default=None, ge=1, le=60)
    rcsa_assessment_id: uuid.UUID | None = None


class AssessmentUpdate(BaseModel):
    """Partial update for the assessment header (only sent fields are applied). The
    questionnaire can change only while nothing has been answered; status moves through
    send / submit / review, not here (a legacy status edit up to ``submitted`` is kept)."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    vendor_id: uuid.UUID | None = None
    questionnaire_id: uuid.UUID | None = None
    due_date: date | None = None
    status: VendorAssessmentStatus | None = None
    review_notes: str | None = None
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=255)
    reviewer_id: uuid.UUID | None = None
    recurrence_months: int | None = Field(default=None, ge=1, le=60)


class AnswerSubmit(BaseModel):
    question_id: uuid.UUID
    option_id: uuid.UUID | None = None
    option_ids: list[uuid.UUID] | None = None
    value_text: str | None = Field(default=None, max_length=20000)
    value_number: float | None = None
    value_date: date | None = None
    not_applicable: bool | None = None
    comment: str = Field(default="", max_length=5000)


class SubmitAnswers(BaseModel):
    answers: list[AnswerSubmit]
    submit: bool = False  # mark the assessment as submitted


class FileRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    filename: str
    content_type: str = ""
    size_bytes: int = 0
    uploaded_by_email: str = ""
    created_at: datetime | None = None


class AnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    question_id: uuid.UUID
    option_id: uuid.UUID | None
    comment: str
    option_ids: list[uuid.UUID] = []
    value_text: str = ""
    value_number: float | None = None
    value_date: date | None = None
    not_applicable: bool = False
    review_state: str = "pending"
    review_comment: str = ""
    reviewed_at: datetime | None = None
    reviewed_by_id: uuid.UUID | None = None
    answered_by: str = ""
    answered_at: datetime | None = None
    files: list[FileRef] = []


class AnswerReview(BaseModel):
    decision: Literal["accept", "return"]
    comment: str = Field(default="", max_length=5000)


class AssessmentReviewRequest(BaseModel):
    notes: str = Field(default="", max_length=10000)


class ReturnRequest(BaseModel):
    message: str = Field(default="", max_length=5000)


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


class IssueRefLite(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    status: str


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str
    severity: Severity
    status: FindingStatus
    deadline: date | None
    created_at: datetime
    answer_id: uuid.UUID | None = None
    question_key: str = ""
    option_value: str = ""
    auto_raised: bool = False
    issue_id: uuid.UUID | None = None
    issue_ref: IssueRefLite | None = None
    effective_status: str = "open"


class RaiseIssueRequest(BaseModel):
    owner_id: uuid.UUID | None = None
    due_date: date | None = None
    severity: Severity | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class AssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    vendor_id: uuid.UUID | None
    vendor: VendorRef | None = None
    questionnaire_id: uuid.UUID
    questionnaire: QuestionnaireRead | None = None
    status: VendorAssessmentStatus
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
    # Phase 4E
    purpose: str = "general"
    progress_pct: int = 0
    missing_mandatory: int = 0
    band: str = ""
    band_rating: str | None = None
    returned_count: int = 0
    is_overdue: bool = False
    contact_name: str = ""
    contact_email: str = ""
    sent_at: datetime | None = None
    sent_by_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    reviewed_by_id: uuid.UUID | None = None
    submitted_by: str = ""
    result_score: float | None = None
    result_max: float | None = None
    result_pct: float | None = None
    result_band: str = ""
    result_rating: str | None = None
    scored_at: datetime | None = None
    recurrence_months: int | None = None
    next_issue_on: date | None = None
    parent_assessment_id: uuid.UUID | None = None
    rcsa_assessment_id: uuid.UUID | None = None
    active_links: int = 0
    #: Why the signed-in user can't give the final review (segregation of duties), if so.
    review_blocked_reason: str | None = None


class AssessmentSummary(BaseModel):
    """Lightweight row for the assessment list."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    vendor: VendorRef | None = None
    vendor_id: uuid.UUID | None = None
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
    purpose: str = "general"
    progress_pct: int = 0
    band: str = ""
    result_band: str = ""
    result_rating: str | None = None
    returned_count: int = 0
    is_overdue: bool = False
    contact_email: str = ""


# ------------------------------------------------------------ respondent links
class LinkCreate(BaseModel):
    contact_name: str = Field(default="", max_length=200)
    contact_email: str = Field(default="", max_length=255)
    expires_in_days: int = Field(default=30, ge=1, le=90)
    send_email: bool = True
    message: str = Field(default="", max_length=2000)

    @field_validator("contact_email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = (v or "").strip()
        if v and ("@" not in v or " " in v or len(v.split("@")[-1]) < 3):
            raise ValueError("Enter a valid e-mail address.")
        return v


class SendRequest(LinkCreate):
    """Send the assessment: a portal link for the contact, e-mailed when mail is set up."""


class LinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    contact_name: str
    contact_email: str
    reason: str
    expires_at: datetime
    revoked_at: datetime | None = None
    emailed_at: datetime | None = None
    last_used_at: datetime | None = None
    use_count: int = 0
    created_at: datetime
    state: str = "active"


class LinkIssued(BaseModel):
    link: LinkRead
    #: The token and URL exist only in this response (and the e-mail): only a hash is kept.
    token: str
    url: str
    emailed: bool
    assessment: AssessmentRead | None = None


class AccessLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    link_id: uuid.UUID | None
    action: str
    outcome: str
    detail: str
    ip_address: str
    user_agent: str
    created_at: datetime


class RcsaRunRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    reviewer_id: uuid.UUID | None = None


# -------------------------------------------------------------- respondent portal
class PortalOption(BaseModel):
    id: uuid.UUID
    value: str
    label: str
    is_na: bool = False


class PortalQuestion(BaseModel):
    id: uuid.UUID
    key: str
    text: str
    guidance: str
    type: str
    mandatory: bool
    conditions: dict[str, Any] = {}
    options: list[PortalOption] = []


class PortalSection(BaseModel):
    id: uuid.UUID | None
    key: str
    title: str
    description: str
    conditions: dict[str, Any] = {}
    questions: list[PortalQuestion] = []


class PortalAnswer(BaseModel):
    question_id: uuid.UUID
    option_ids: list[uuid.UUID] = []
    value_text: str = ""
    value_number: float | None = None
    value_date: date | None = None
    not_applicable: bool = False
    comment: str = ""
    review_state: str = "pending"
    review_comment: str = ""
    files: list[FileRef] = []


class PortalView(BaseModel):
    organisation: str
    assessment_title: str
    vendor_name: str = ""
    questionnaire_name: str
    questionnaire_version: int
    contact_name: str = ""
    due_date: date | None = None
    status: str
    editable: bool
    #: When the reviewer returned answers: only these question ids can change.
    reopened_question_ids: list[uuid.UUID] | None = None
    submitted_at: date | None = None
    expires_at: datetime
    sections: list[PortalSection]
    answers: list[PortalAnswer]
    max_upload_mb: int
    allowed_file_types: list[str]
    message: str = ""


class PortalSave(BaseModel):
    answers: list[AnswerSubmit] = Field(default_factory=list, max_length=1000)
