"""User-defined multi-stage approval routing.

Every major record already has a fixed lifecycle (draft → in review → approved →
retired) and a maker-checker approval inbox. What banks ask for on top is *their own*
route: "risk acceptance goes Owner → Department Head → CRO → Risk Committee, two of
three". That is what these tables describe.

Two design rules make this safe to add to a running system:

* **Each stage materialises a real** :class:`~app.models.approval.ApprovalRequest`.
  Nothing here re-implements approving. The inbox, N-eyes counting, segregation of
  duties, overdue chasing and the audit trail keep working because they are the same
  code paths a single-stage approval already uses.
* **No definition means no change.** An entity type with no enabled definition keeps the
  behaviour it has today, so switching the feature on for one record type cannot disturb
  any other.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ApproverMode(str, enum.Enum):
    """Who decides a stage.

    ``role`` and ``named_user`` are explicit. ``record_owner`` and ``line_manager``
    resolve at runtime, which is what lets one definition serve every record of a type
    instead of needing a copy per department.
    """

    role = "role"
    named_user = "named_user"
    record_owner = "record_owner"
    line_manager = "line_manager"


class TimeoutAction(str, enum.Enum):
    """What happens when a stage passes its own deadline."""

    escalate = "escalate"        # notify, keep waiting — the default
    auto_approve = "auto_approve"
    block = "block"              # freeze the whole instance until someone acts


class WorkflowInstanceStatus(str, enum.Enum):
    in_progress = "in_progress"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class StageStatus2(str, enum.Enum):
    """Named to avoid clashing with the incident ``StageStatus`` elsewhere."""

    pending = "pending"
    in_progress = "in_progress"
    approved = "approved"
    rejected = "rejected"
    skipped = "skipped"


class WorkflowDefinition(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One routing definition for one record type."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "name", name="uq_workflow_def_name"),
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    #: Only one definition per entity type may be enabled — otherwise a record has two
    #: routes and no defensible answer to "which one applied?".
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    stages: Mapped[list["WorkflowStage"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", lazy="selectin",
        order_by="WorkflowStage.order_index",
    )

    @property
    def stage_count(self) -> int:
        return len(self.stages)


class WorkflowStage(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "workflow_stages"
    __table_args__ = (
        CheckConstraint("required_approvals BETWEEN 1 AND 10", name="ck_workflow_stage_approvals"),
    )

    definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    approver_mode: Mapped[ApproverMode] = mapped_column(
        SAEnum(ApproverMode, name="approver_mode"),
        default=ApproverMode.role, nullable=False,
    )
    #: Role name or user email, depending on ``approver_mode``.
    approver_ref: Mapped[str] = mapped_column(String(200), default="")
    #: N-eyes for this stage on its own — "two of the three committee members".
    required_approvals: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sla_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 = none
    on_timeout: Mapped[TimeoutAction] = mapped_column(
        SAEnum(TimeoutAction, name="workflow_timeout_action"),
        default=TimeoutAction.escalate, nullable=False,
    )

    definition: Mapped[WorkflowDefinition] = relationship(back_populates="stages")


class WorkflowInstance(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One record's journey through one definition."""

    __tablename__ = "workflow_instances"

    definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    entity_label: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[WorkflowInstanceStatus] = mapped_column(
        SAEnum(WorkflowInstanceStatus, name="workflow_instance_status"),
        default=WorkflowInstanceStatus.in_progress, nullable=False, index=True,
    )
    started_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    started_by_email: Mapped[str] = mapped_column(String(255), default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["WorkflowInstanceStage"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", lazy="selectin",
        order_by="WorkflowInstanceStage.order_index",
    )

    @property
    def current_step(self) -> "WorkflowInstanceStage | None":
        for step in self.steps:
            if step.status in (StageStatus2.pending, StageStatus2.in_progress):
                return step
        return None

    @property
    def total_stages(self) -> int:
        return len(self.steps)

    @property
    def completed_stages(self) -> int:
        return sum(1 for s in self.steps if s.status == StageStatus2.approved)


class WorkflowInstanceStage(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "workflow_instance_stages"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_instances.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_stages.id", ondelete="SET NULL"), nullable=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(160), default="")
    approver_label: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[StageStatus2] = mapped_column(
        SAEnum(StageStatus2, name="workflow_stage_status"),
        default=StageStatus2.pending, nullable=False,
    )
    #: The approval this stage raised — the link that keeps N-eyes, SoD and the inbox
    #: working without any of it being reimplemented here.
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[str] = mapped_column(Text, default="")

    instance: Mapped[WorkflowInstance] = relationship(back_populates="steps")
