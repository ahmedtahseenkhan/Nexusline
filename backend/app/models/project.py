"""Project Management — remediation projects with tasks/milestones, budget & expenses,
and links to the risks/controls/policies they address."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, Table, Text, Uuid
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
from app.models.enums import ProjectStatus

project_risks = Table(
    "project_risks",
    Base.metadata,
    Column("project_id", Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)
project_controls = Table(
    "project_controls",
    Base.metadata,
    Column("project_id", Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("control_id", Uuid, ForeignKey("controls.id", ondelete="CASCADE"), primary_key=True),
)
project_policies = Table(
    "project_policies",
    Base.metadata,
    Column("project_id", Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)


class Project(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "projects"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus, name="project_status"), default=ProjectStatus.planned, nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)

    tasks: Mapped[list["ProjectTask"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProjectTask.order_index",
    )
    expenses: Mapped[list["ProjectExpense"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    risks: Mapped[list["Risk"]] = relationship(secondary=project_risks, lazy="selectin",
        secondaryjoin="and_(project_risks.c.risk_id == Risk.id, Risk.deleted == False)",
    )  # noqa: F821
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        secondary=project_controls, lazy="selectin",
        secondaryjoin="and_(project_controls.c.control_id == Control.id, Control.deleted == False)",
    )
    policies: Mapped[list["Policy"]] = relationship(  # noqa: F821
        secondary=project_policies, lazy="selectin",
        secondaryjoin="and_(project_policies.c.policy_id == Policy.id, Policy.deleted == False)",
    )

    @property
    def spent(self) -> float:
        return round(sum(e.amount for e in self.expenses), 2)

    @property
    def over_budget(self) -> bool:
        return self.budget is not None and self.spent > self.budget

    @property
    def progress(self) -> int:
        if self.tasks:
            return round(sum(t.completion for t in self.tasks) / len(self.tasks))
        return 100 if self.status == ProjectStatus.completed else 0

    @property
    def open_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.completion < 100)

    @property
    def is_overdue(self) -> bool:
        return (
            self.deadline is not None
            and self.deadline < date.today()
            and self.status != ProjectStatus.completed
        )


class ProjectTask(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A task / milestone (eramba 'achievement') with a % completion."""

    __tablename__ = "project_tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completion: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assignee: Mapped[str] = mapped_column(String(200), default="")

    project: Mapped[Project] = relationship(back_populates="tasks")

    @property
    def is_overdue(self) -> bool:
        return (
            self.due_date is not None
            and self.due_date < date.today()
            and self.completion < 100
        )


class ProjectExpense(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "project_expenses"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    expense_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    project: Mapped[Project] = relationship(back_populates="expenses")
