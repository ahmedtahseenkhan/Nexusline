"""Strategy & Goals — strategic goals with a recurring pass/fail audit cycle,
linked to the risks, projects and policies that support them."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Column, Date, ForeignKey, String, Table, Text, Uuid
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
from app.models.enums import GoalAuditResult, GoalStatus, ReviewFrequency

goal_risks = Table(
    "goal_risks",
    Base.metadata,
    Column("goal_id", Uuid, ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True),
    Column("risk_id", Uuid, ForeignKey("risks.id", ondelete="CASCADE"), primary_key=True),
)
goal_projects = Table(
    "goal_projects",
    Base.metadata,
    Column("goal_id", Uuid, ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True),
    Column("project_id", Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
)
goal_policies = Table(
    "goal_policies",
    Base.metadata,
    Column("goal_id", Uuid, ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True),
    Column("policy_id", Uuid, ForeignKey("policies.id", ondelete="CASCADE"), primary_key=True),
)


class Goal(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "goals"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[GoalStatus] = mapped_column(
        SAEnum(GoalStatus, name="goal_status"), default=GoalStatus.not_started, nullable=False
    )
    audit_metric: Mapped[str] = mapped_column(Text, default="")
    success_criteria: Mapped[str] = mapped_column(Text, default="")
    audit_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual,
        nullable=False,
    )
    next_audit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_audit_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    audits: Mapped[list["GoalAudit"]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="GoalAudit.created_at.desc()",
    )
    risks: Mapped[list["Risk"]] = relationship(secondary=goal_risks, lazy="selectin",
        secondaryjoin="and_(goal_risks.c.risk_id == Risk.id, Risk.deleted == False)",
    )  # noqa: F821
    projects: Mapped[list["Project"]] = relationship(  # noqa: F821
        secondary=goal_projects, lazy="selectin",
        secondaryjoin="and_(goal_projects.c.project_id == Project.id, Project.deleted == False)",
    )
    policies: Mapped[list["Policy"]] = relationship(  # noqa: F821
        secondary=goal_policies, lazy="selectin",
        secondaryjoin="and_(goal_policies.c.policy_id == Policy.id, Policy.deleted == False)",
    )

    @property
    def audit_count(self) -> int:
        return len(self.audits)

    @property
    def last_result(self) -> GoalAuditResult | None:
        assessed = [a for a in self.audits if a.result != GoalAuditResult.not_assessed]
        return assessed[0].result if assessed else None

    @property
    def is_audit_overdue(self) -> bool:
        return self.next_audit_date is not None and self.next_audit_date < date.today()


class GoalAudit(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "goal_audits"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    conducted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[GoalAuditResult] = mapped_column(
        SAEnum(GoalAuditResult, name="goal_audit_result"),
        default=GoalAuditResult.not_assessed,
        nullable=False,
    )
    metric_description: Mapped[str] = mapped_column(Text, default="")
    success_criteria: Mapped[str] = mapped_column(Text, default="")
    result_description: Mapped[str] = mapped_column(Text, default="")
    auditor: Mapped[str] = mapped_column(String(200), default="")

    goal: Mapped[Goal] = relationship(back_populates="audits")
