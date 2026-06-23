"""Vendor Assessments — reusable questionnaires (questions + scored options) sent to
third parties; answers are weighted-scored and gaps become findings."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FindingStatus, Severity, VendorAssessmentStatus


# ----------------------------------------------------------- questionnaire template
class Questionnaire(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "questionnaires"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")

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
    def max_score(self) -> float:
        return round(
            sum(max((o.score for o in q.options), default=0.0) for q in self.questions), 2
        )


class Question(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "questions"

    questionnaire_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    guidance: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    questionnaire: Mapped[Questionnaire] = relationship(back_populates="questions")
    options: Mapped[list["QuestionOption"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="QuestionOption.order_index",
    )

    @property
    def max_score(self) -> float:
        return max((o.score for o in self.options), default=0.0)


class QuestionOption(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "question_options"

    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    question: Mapped[Question] = relationship(back_populates="options")


# -------------------------------------------------------------- assessment campaign
class Assessment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "assessments"

    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    questionnaire_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questionnaires.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[VendorAssessmentStatus] = mapped_column(
        SAEnum(VendorAssessmentStatus, name="vendor_assessment_status"),
        default=VendorAssessmentStatus.draft,
        nullable=False,
    )
    access_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    submitted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_notes: Mapped[str] = mapped_column(Text, default="")

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

    @property
    def question_count(self) -> int:
        return self.questionnaire.question_count if self.questionnaire else 0

    @property
    def answered_count(self) -> int:
        return sum(1 for a in self.answers if a.option_id is not None)

    @property
    def max_score(self) -> float:
        return self.questionnaire.max_score if self.questionnaire else 0.0

    @property
    def total_score(self) -> float:
        return round(sum(a.option.score for a in self.answers if a.option), 2)

    @property
    def score_pct(self) -> float:
        return round(100 * self.total_score / self.max_score, 1) if self.max_score else 0.0

    @property
    def open_findings(self) -> int:
        return sum(1 for f in self.findings if f.status == FindingStatus.open)


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

    assessment: Mapped[Assessment] = relationship(back_populates="findings")
