"""Internal Control over Financial Reporting (ICFR) — the SBP-mandated annual cycle.

* **IcfrProcess** — the financial-reporting process universe (e.g. Revenue,
  Procure-to-Pay, Financial Close); the anchor for a Risk-Control Matrix (RCM).
* **IcfrControl** — an RCM line: a control mapped to a financial-statement
  assertion, with design and operating effectiveness conclusions.
* **IcfrTest** — a control test (design or operating effectiveness) with sample
  size, exceptions found and a pass/fail conclusion.
* **IcfrDeficiency** — the deficiency register, evaluated as a control
  deficiency, a significant deficiency, or a material weakness.
"""
from __future__ import annotations

import enum
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
from app.models.enums import ControlEffectiveness, ReviewFrequency


# ============================================================= local enums ===
class IcfrProcessStatus(str, enum.Enum):
    """Lifecycle of a financial-reporting process in the ICFR universe."""

    active = "active"
    retired = "retired"


class FinancialAssertion(str, enum.Enum):
    """Financial-statement assertions a control addresses."""

    existence_occurrence = "existence_occurrence"
    completeness = "completeness"
    accuracy = "accuracy"
    valuation_allocation = "valuation_allocation"
    rights_obligations = "rights_obligations"
    presentation_disclosure = "presentation_disclosure"
    cutoff = "cutoff"


class IcfrControlType(str, enum.Enum):
    """Whether the control prevents or detects a misstatement."""

    preventive = "preventive"
    detective = "detective"


class ControlNature(str, enum.Enum):
    """How the control operates."""

    manual = "manual"
    automated = "automated"
    it_dependent_manual = "it_dependent_manual"


class IcfrTestType(str, enum.Enum):
    """Design vs operating effectiveness testing."""

    design = "design"
    operating = "operating"


class IcfrTestResult(str, enum.Enum):
    not_tested = "not_tested"
    passed = "passed"
    failed = "failed"
    passed_with_exceptions = "passed_with_exceptions"


class IcfrTestStatus(str, enum.Enum):
    planned = "planned"
    in_progress = "in_progress"
    completed = "completed"


class DeficiencySeverity(str, enum.Enum):
    """SOX/SBP deficiency evaluation severity."""

    deficiency = "deficiency"
    significant_deficiency = "significant_deficiency"
    material_weakness = "material_weakness"


class DeficiencyStatus(str, enum.Enum):
    open = "open"
    remediating = "remediating"
    remediated = "remediated"
    closed = "closed"


# =============================================================== processes ===
class IcfrProcess(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "icfr_processes"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    cycle: Mapped[str] = mapped_column(String(120), default="")
    business_unit: Mapped[str] = mapped_column(String(200), default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    key_process: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[IcfrProcessStatus] = mapped_column(
        SAEnum(IcfrProcessStatus, name="icfr_process_status"),
        default=IcfrProcessStatus.active, nullable=False,
    )

    controls: Mapped[list["IcfrControl"]] = relationship(
        back_populates="process", cascade="all, delete-orphan", lazy="selectin",
        order_by="IcfrControl.created_at",
    )

    @property
    def control_count(self) -> int:
        return len(self.controls)

    @property
    def key_control_count(self) -> int:
        return sum(1 for c in self.controls if c.is_key)


# ============================================================ RCM controls ===
class IcfrControl(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single Risk-Control Matrix line inside an ICFR process."""

    __tablename__ = "icfr_controls"

    process_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("icfr_processes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    control_objective: Mapped[str] = mapped_column(Text, default="")
    risk_description: Mapped[str] = mapped_column(Text, default="")
    # Bridge the ICFR RCM line to the enterprise control register (avoids a parallel universe).
    control_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("controls.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assertion: Mapped[FinancialAssertion] = mapped_column(
        SAEnum(FinancialAssertion, name="icfr_assertion"),
        default=FinancialAssertion.accuracy, nullable=False,
    )
    control_type: Mapped[IcfrControlType] = mapped_column(
        SAEnum(IcfrControlType, name="icfr_control_type"),
        default=IcfrControlType.preventive, nullable=False,
    )
    nature: Mapped[ControlNature] = mapped_column(
        SAEnum(ControlNature, name="icfr_control_nature"),
        default=ControlNature.manual, nullable=False,
    )
    frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.monthly, nullable=False,
    )
    is_key: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    owner: Mapped[str] = mapped_column(String(200), default="")
    design_effectiveness: Mapped[ControlEffectiveness] = mapped_column(
        SAEnum(ControlEffectiveness, name="control_effectiveness"),
        default=ControlEffectiveness.not_assessed, nullable=False,
    )
    operating_effectiveness: Mapped[ControlEffectiveness] = mapped_column(
        SAEnum(ControlEffectiveness, name="control_effectiveness"),
        default=ControlEffectiveness.not_assessed, nullable=False,
    )

    process: Mapped[IcfrProcess] = relationship(back_populates="controls")
    tests: Mapped[list["IcfrTest"]] = relationship(
        back_populates="control", cascade="all, delete-orphan", lazy="selectin",
        order_by="IcfrTest.created_at",
    )

    @property
    def test_count(self) -> int:
        return len(self.tests)

    @property
    def latest_result(self) -> IcfrTestResult | None:
        return self.tests[-1].result if self.tests else None


# ============================================================ control tests ===
class IcfrTest(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A design or operating-effectiveness test executed against an RCM control."""

    __tablename__ = "icfr_tests"

    control_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("icfr_controls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    test_type: Mapped[IcfrTestType] = mapped_column(
        SAEnum(IcfrTestType, name="icfr_test_type"),
        default=IcfrTestType.operating, nullable=False,
    )
    period: Mapped[str] = mapped_column(String(64), default="")
    tester: Mapped[str] = mapped_column(String(200), default="")
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exceptions_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    test_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[IcfrTestResult] = mapped_column(
        SAEnum(IcfrTestResult, name="icfr_test_result"),
        default=IcfrTestResult.not_tested, nullable=False,
    )
    conclusion: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[IcfrTestStatus] = mapped_column(
        SAEnum(IcfrTestStatus, name="icfr_test_status"),
        default=IcfrTestStatus.planned, nullable=False,
    )

    control: Mapped[IcfrControl] = relationship(back_populates="tests")


# =========================================================== deficiencies ===
class IcfrDeficiency(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin, Base):
    """A control deficiency identified during ICFR testing, evaluated by severity."""

    __tablename__ = "icfr_deficiencies"

    control_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("icfr_controls.id", ondelete="SET NULL"), nullable=True, index=True
    )
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("icfr_processes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[DeficiencySeverity] = mapped_column(
        SAEnum(DeficiencySeverity, name="icfr_deficiency_severity"),
        default=DeficiencySeverity.deficiency, nullable=False,
    )
    status: Mapped[DeficiencyStatus] = mapped_column(
        SAEnum(DeficiencyStatus, name="icfr_deficiency_status"),
        default=DeficiencyStatus.open, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    identified_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remediation_plan: Mapped[str] = mapped_column(Text, default="")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remediated_date: Mapped[date | None] = mapped_column(Date, nullable=True)
