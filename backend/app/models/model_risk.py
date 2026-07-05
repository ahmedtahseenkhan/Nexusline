"""Model Risk Management & AI Governance — SR 11-7 / ISO 42001 flavoured.

Banks run a growing estate of quantitative and AI/ML models — IFRS 9 ECL, AML
transaction-monitoring scoring, credit / behavioural scoring, capital and stress
models. Supervisors expect a **model inventory** with materiality tiering plus a
**validation lifecycle** (independent validation on a periodic cycle).

* **ModelInventory** — the model register: type, ownership, materiality, regulatory
  relevance, AI/ML flag, methodology and the validation schedule (last / next).
* **ModelValidation** — a single validation exercise against a model (initial,
  periodic or targeted) with its outcome, findings, metrics and recommendations.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, Uuid
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
from app.models.enums import Criticality


# =============================================================== enums (local) ===
class ModelType(str, enum.Enum):
    """The kind of quantitative / AI model held in the inventory."""

    credit_scoring = "credit_scoring"
    ifrs9_ecl = "ifrs9_ecl"
    aml_transaction_monitoring = "aml_transaction_monitoring"
    fraud_detection = "fraud_detection"
    capital = "capital"
    stress_testing = "stress_testing"
    market_risk = "market_risk"
    ai_ml = "ai_ml"
    other = "other"


class ModelStatus(str, enum.Enum):
    """Lifecycle of a model in the inventory."""

    development = "development"
    validated = "validated"
    in_production = "in_production"
    under_review = "under_review"
    retired = "retired"


class ValidationType(str, enum.Enum):
    """The scope of a validation exercise (SR 11-7)."""

    initial = "initial"
    periodic = "periodic"
    targeted = "targeted"


class ValidationOutcome(str, enum.Enum):
    """Overall conclusion of a validation exercise."""

    pass_ = "pass"
    pass_with_findings = "pass_with_findings"
    fail = "fail"
    not_completed = "not_completed"


class ModelValidationStatus(str, enum.Enum):
    """Lifecycle of a validation exercise."""

    planned = "planned"
    in_progress = "in_progress"
    completed = "completed"


# ========================================================== model inventory ===
class ModelInventory(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "model_inventory"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(Text, default="")
    model_type: Mapped[ModelType] = mapped_column(
        SAEnum(ModelType, name="model_type"), default=ModelType.other, nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    developer: Mapped[str] = mapped_column(String(200), default="")
    vendor: Mapped[str] = mapped_column(String(200), default="")
    materiality: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    status: Mapped[ModelStatus] = mapped_column(
        SAEnum(ModelStatus, name="model_status"), default=ModelStatus.development, nullable=False
    )
    regulatory_relevant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_ml: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    methodology: Mapped[str] = mapped_column(Text, default="")
    last_validation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_validation_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    validations: Mapped[list["ModelValidation"]] = relationship(
        back_populates="model", cascade="all, delete-orphan", lazy="selectin",
        order_by="ModelValidation.created_at",
    )

    @property
    def validation_count(self) -> int:
        return len(self.validations)

    @property
    def is_validation_overdue(self) -> bool:
        return (self.status != ModelStatus.retired and self.next_validation_date is not None
                and self.next_validation_date < date.today())


# ========================================================= model validations ===
class ModelValidation(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single independent validation exercise against a model."""

    __tablename__ = "model_validations"

    model_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("model_inventory.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    validation_type: Mapped[ValidationType] = mapped_column(
        SAEnum(ValidationType, name="model_validation_type"),
        default=ValidationType.periodic, nullable=False,
    )
    validator: Mapped[str] = mapped_column(String(200), default="")
    validation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    outcome: Mapped[ValidationOutcome] = mapped_column(
        SAEnum(ValidationOutcome, name="model_validation_outcome"),
        default=ValidationOutcome.not_completed, nullable=False,
    )
    findings: Mapped[str] = mapped_column(Text, default="")
    performance_metrics: Mapped[str] = mapped_column(Text, default="")
    recommendations: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ModelValidationStatus] = mapped_column(
        SAEnum(ModelValidationStatus, name="model_validation_status"),
        default=ModelValidationStatus.planned, nullable=False,
    )

    model: Mapped[ModelInventory] = relationship(back_populates="validations")
