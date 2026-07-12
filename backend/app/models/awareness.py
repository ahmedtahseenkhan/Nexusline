"""Awareness Training — recurring security-awareness programs with a quiz and
per-participant completion / compliance tracking."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkflowMixin,
)
from app.models.enums import AwarenessStatus, ReviewFrequency, TrainingStatus


class AwarenessProgram(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "awareness_programs"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")  # training material / URL
    status: Mapped[AwarenessStatus] = mapped_column(
        SAEnum(AwarenessStatus, name="awareness_status"),
        default=AwarenessStatus.draft,
        nullable=False,
    )
    passing_score: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual,
        nullable=False,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    questions: Mapped[list["AwarenessQuestion"]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AwarenessQuestion.order_index",
    )
    participants: Mapped[list["TrainingRecord"]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="TrainingRecord.participant_name",
    )

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def participant_count(self) -> int:
        return len(self.participants)

    @property
    def completed_count(self) -> int:
        return sum(1 for p in self.participants if p.status == TrainingStatus.completed)

    @property
    def compliant_count(self) -> int:
        return sum(
            1
            for p in self.participants
            if p.status == TrainingStatus.completed
            and p.score is not None
            and p.score >= self.passing_score
        )

    @property
    def completion_pct(self) -> float:
        return round(100 * self.completed_count / self.participant_count, 1) if self.participant_count else 0.0

    @property
    def compliance_pct(self) -> float:
        return round(100 * self.compliant_count / self.participant_count, 1) if self.participant_count else 0.0


class AwarenessQuestion(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "awareness_questions"

    program_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("awareness_programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    program: Mapped[AwarenessProgram] = relationship(back_populates="questions")
    options: Mapped[list["AwarenessOption"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AwarenessOption.order_index",
    )


class AwarenessOption(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "awareness_options"

    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("awareness_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    question: Mapped[AwarenessQuestion] = relationship(back_populates="options")


class TrainingRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "training_records"

    program_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("awareness_programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    participant_email: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[TrainingStatus] = mapped_column(
        SAEnum(TrainingStatus, name="training_status"),
        default=TrainingStatus.assigned,
        nullable=False,
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    program: Mapped[AwarenessProgram] = relationship(back_populates="participants")
