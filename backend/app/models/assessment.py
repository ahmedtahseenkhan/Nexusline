"""Questionnaires and assessments (vendor tiering, due diligence, RCSA, general).

Phase 4E turned the flat "questions with scored options" into a questionnaire engine:

* **Questionnaire** — one *version* of a questionnaire. Versions of the same
  questionnaire share ``family_id`` and are numbered (``version``). A version is
  ``draft`` (editable), ``published`` (immutable; the one new assessments use) or
  ``superseded`` (an older published version, still pinned by its assessments).
  ``purpose`` says what the results drive (vendor tiering, due diligence, RCSA, general),
  ``bands`` turn a score into a band and rating.
* **QuestionnaireSection** — ordered sections with a description and a display condition.
* **Question** — typed (choice, yes/no/N-A, text, number, date, file upload), mandatory,
  weighted, with a display condition and a stable ``key`` that conditions refer to.
* **QuestionOption** — a scored answer; may be N/A (drops out of scoring) or a *risk flag*
  that raises a finding with a suggested title and severity.
* **Assessment** — one run of a pinned version, for a vendor (or an RCSA, or neither),
  with the respondent contact, the send / review trail, the scored result and recurrence.
* **AssessmentAnswer** — the answer (option(s), text, number, date, N/A, comment) with the
  reviewer's per-answer decision.
* **AssessmentFinding** — a gap, raised by hand or by a flagged answer; may be raised to
  an Issue.
* **AssessmentLink** / **AssessmentAccessLog** — the respondent portal's token links
  (only a hash is stored) and every access through them.

The rules themselves live in ``services/questionnaire_logic.py`` (pure).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FindingStatus, Severity, VendorAssessmentStatus

#: Questionnaire version states.
VERSION_DRAFT, VERSION_PUBLISHED, VERSION_SUPERSEDED = "draft", "published", "superseded"
#: Per-answer review states.
REVIEW_PENDING, REVIEW_ACCEPTED, REVIEW_RETURNED = "pending", "accepted", "returned"


# ----------------------------------------------------------- questionnaire template
class Questionnaire(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One version of a questionnaire (see the module notes)."""

    __tablename__ = "questionnaires"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # Phase 4E: versioning, purpose and scoring bands.
    family_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=VERSION_DRAFT, nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(40), default="general", nullable=False, index=True)
    bands: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    change_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: tenant (built here) | library (installed from a shipped template) | rcsa_run
    #: (generated for one RCSA; hidden from the questionnaire list).
    origin: Mapped[str] = mapped_column(String(24), default="tenant", nullable=False)
    library_key: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    library_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sections: Mapped[list["QuestionnaireSection"]] = relationship(
        back_populates="questionnaire",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="QuestionnaireSection.order_index",
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="questionnaire",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Question.order_index",
    )

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def max_score(self) -> float:
        from app.services import questionnaire_logic as ql

        return ql.static_max(ql.spec_from_version(self))

    @property
    def is_editable(self) -> bool:
        return (self.status or VERSION_DRAFT) == VERSION_DRAFT


class QuestionnaireSection(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "questionnaire_sections"

    questionnaire_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    questionnaire: Mapped[Questionnaire] = relationship(back_populates="sections")


class Question(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "questions"

    questionnaire_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    guidance: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Phase 4E
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("questionnaire_sections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    qtype: Mapped[str] = mapped_column(String(24), default="single_choice", nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    questionnaire: Mapped[Questionnaire] = relationship(back_populates="questions")
    #: Never read (lazy="noload"): declared so a flush inserts sections before their
    #: questions and deletes questions before their sections.
    section: Mapped["QuestionnaireSection | None"] = relationship(lazy="noload")
    options: Mapped[list["QuestionOption"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="QuestionOption.order_index",
    )

    @property
    def type(self) -> str:
        return self.qtype or "single_choice"

    @property
    def max_score(self) -> float:
        from app.services import questionnaire_logic as ql

        spec = {"type": self.qtype or "single_choice", "options": [
            {"score": o.score, "is_na": bool(getattr(o, "is_na", False))} for o in self.options
        ]}
        return ql.question_max(spec)


class QuestionOption(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "question_options"

    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Phase 4E
    value: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    is_na: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    finding_title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    finding_severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)

    question: Mapped[Question] = relationship(back_populates="options")


# -------------------------------------------------------------- assessment campaign
class Assessment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "assessments"

    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: The pinned questionnaire *version*.
    questionnaire_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questionnaires.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[VendorAssessmentStatus] = mapped_column(
        SAEnum(VendorAssessmentStatus, name="vendor_assessment_status"),
        default=VendorAssessmentStatus.draft,
        nullable=False,
    )
    #: Unused since phase 4E (portal links live in ``assessment_links``); kept, blanked.
    access_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    submitted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_notes: Mapped[str] = mapped_column(Text, default="")

    # Phase 4E: respondent, workflow, result, recurrence, RCSA link.
    contact_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    result_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_band: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    result_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recurrence_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_issue_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    parent_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assessments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_reminder_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    overdue_alerted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    rcsa_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("rcsa_assessments.id", ondelete="SET NULL"), nullable=True, index=True
    )

    questionnaire: Mapped[Questionnaire] = relationship(lazy="selectin")
    vendor: Mapped["Vendor | None"] = relationship(lazy="selectin")  # noqa: F821
    answers: Mapped[list["AssessmentAnswer"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", lazy="selectin"
    )
    findings: Mapped[list["AssessmentFinding"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AssessmentFinding.created_at.desc()",
    )

    # ---- derived (services/questionnaire_logic.py) --------------------------------
    def _scored(self) -> Any:
        from app.services import questionnaire_logic as ql

        if self.questionnaire is None:
            return None
        spec = ql.spec_from_version(self.questionnaire)
        files = getattr(self, "_file_counts", None) or {}
        return ql.score(spec, ql.answer_values(spec, self.answers, files))

    @property
    def purpose(self) -> str:
        return (self.questionnaire.purpose if self.questionnaire is not None else "") or "general"

    @property
    def question_count(self) -> int:
        result = self._scored()
        return result.visible_questions if result else 0

    @property
    def answered_count(self) -> int:
        result = self._scored()
        return result.answered_questions if result else 0

    @property
    def progress_pct(self) -> int:
        result = self._scored()
        return result.progress_pct if result else 0

    @property
    def missing_mandatory(self) -> int:
        result = self._scored()
        return len(result.missing_mandatory) if result else 0

    @property
    def max_score(self) -> float:
        result = self._scored()
        return result.maximum if result else 0.0

    @property
    def total_score(self) -> float:
        result = self._scored()
        return result.earned if result else 0.0

    @property
    def score_pct(self) -> float:
        result = self._scored()
        return (result.pct or 0.0) if result else 0.0

    @property
    def band(self) -> str:
        from app.services import questionnaire_logic as ql

        result = self._scored()
        found = ql.band_for(self.questionnaire.bands if self.questionnaire else None, result.pct if result else None)
        return str(found.get("label")) if found else ""

    @property
    def band_rating(self) -> str | None:
        from app.services import questionnaire_logic as ql

        result = self._scored()
        found = ql.band_for(self.questionnaire.bands if self.questionnaire else None, result.pct if result else None)
        return found.get("rating") if found else None

    @property
    def returned_count(self) -> int:
        return sum(1 for a in self.answers if (a.review_state or "") == REVIEW_RETURNED)

    @property
    def open_findings(self) -> int:
        return sum(1 for f in self.findings if f.effective_status == FindingStatus.open.value)

    @property
    def is_overdue(self) -> bool:
        return (
            self.due_date is not None and self.due_date < date.today()
            and getattr(self.status, "value", self.status) in ("draft", "sent", "in_progress")
        )


class AssessmentAnswer(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "assessment_answers"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    option_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("question_options.id", ondelete="SET NULL"), nullable=True
    )
    comment: Mapped[str] = mapped_column(Text, default="")
    # Phase 4E: typed values, N/A and the reviewer's decision.
    option_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    value_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    value_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    not_applicable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_state: Mapped[str] = mapped_column(String(16), default=REVIEW_PENDING, nullable=False)
    review_comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="answers")
    option: Mapped["QuestionOption | None"] = relationship(lazy="selectin")


class AssessmentFinding(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "assessment_findings"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity"), default=Severity.medium, nullable=False
    )
    status: Mapped[FindingStatus] = mapped_column(
        SAEnum(FindingStatus, name="finding_status"), default=FindingStatus.open, nullable=False
    )
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Phase 4E: where it came from, and the issue it was raised to.
    answer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assessment_answers.id", ondelete="SET NULL"), nullable=True
    )
    question_key: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    option_value: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    auto_raised: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True, index=True
    )

    assessment: Mapped[Assessment] = relationship(back_populates="findings")
    issue: Mapped["Issue | None"] = relationship("Issue", lazy="selectin", viewonly=True)  # noqa: F821

    @property
    def issue_ref(self) -> dict | None:
        issue = self.issue
        if issue is None or getattr(issue, "deleted", False):
            return None
        return {"id": issue.id, "reference": issue.reference or "", "title": issue.title or "",
                "status": getattr(issue.status, "value", issue.status)}

    @property
    def effective_status(self) -> str:
        """Closed when the finding is closed, or when the issue it was raised to is closed
        (closed or risk accepted): the issue is where the remediation is tracked."""
        own = getattr(self.status, "value", self.status)
        ref = self.issue_ref
        if own == FindingStatus.open.value and ref and ref["status"] in ("closed", "risk_accepted"):
            return FindingStatus.closed.value
        return own


class AssessmentLink(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A respondent-portal link. Only the SHA-256 of the token is stored; the token is
    shown once (and e-mailed) when the link is created."""

    __tablename__ = "assessment_links"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    contact_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    #: initial | manual | resend | reminder
    reason: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AssessmentAccessLog(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Every request made through a respondent-portal link (and every refused one that
    named this organisation)."""

    __tablename__ = "assessment_access_logs"

    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    link_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assessment_links.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: view | save | upload | delete_file | submit | denied
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    detail: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(400), default="", nullable=False)
