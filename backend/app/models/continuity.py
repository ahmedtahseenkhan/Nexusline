"""Business Continuity Management — continuity plans (BCP) with a 5W playbook of tasks
and a recurring pass/fail test/exercise calendar."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, Uuid
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
from app.models.enums import ContinuityStatus, Criticality, ReviewFrequency, TestResult


class ContinuityPlan(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "continuity_plans"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")  # objective / scope
    bia: Mapped[str] = mapped_column(Text, default="")  # business impact analysis
    invocation: Mapped[str] = mapped_column(Text, default="")  # invocation criteria/procedure
    status: Mapped[ContinuityStatus] = mapped_column(
        SAEnum(ContinuityStatus, name="continuity_status"),
        default=ContinuityStatus.draft,
        nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("processes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    max_tolerable_downtime_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rto_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpo_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criticality: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.high, nullable=False
    )

    test_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual,
        nullable=False,
    )
    next_test_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_test_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    business_unit: Mapped["BusinessUnit | None"] = relationship(  # noqa: F821
        "BusinessUnit", lazy="selectin"
    )
    process: Mapped["Process | None"] = relationship("Process", lazy="selectin")  # noqa: F821
    tasks: Mapped[list["ContinuityTask"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ContinuityTask.step",
    )
    tests: Mapped[list["ContinuityTest"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ContinuityTest.created_at.desc()",
    )

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @property
    def test_count(self) -> int:
        return len(self.tests)

    @property
    def last_test_result(self) -> TestResult | None:
        assessed = [t for t in self.tests if t.result != TestResult.not_assessed]
        return assessed[0].result if assessed else None

    @property
    def is_test_overdue(self) -> bool:
        return self.next_test_date is not None and self.next_test_date < date.today()


class ContinuityTask(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A recovery playbook step (5W: action/actor/timing/location/method)."""

    __tablename__ = "continuity_tasks"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # what is done
    actor: Mapped[str] = mapped_column(String(200), default="")  # who
    timing: Mapped[str] = mapped_column(String(200), default="")  # when
    location: Mapped[str] = mapped_column(String(200), default="")  # where
    method: Mapped[str] = mapped_column(Text, default="")  # how

    plan: Mapped[ContinuityPlan] = relationship(back_populates="tasks")


class ContinuityTest(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "continuity_tests"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("continuity_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    conducted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[TestResult] = mapped_column(
        SAEnum(TestResult, name="test_result"), default=TestResult.not_assessed, nullable=False
    )
    result_description: Mapped[str] = mapped_column(Text, default="")
    tester: Mapped[str] = mapped_column(String(200), default="")

    plan: Mapped[ContinuityPlan] = relationship(back_populates="tests")
