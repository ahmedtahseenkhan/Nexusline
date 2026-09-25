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

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, Uuid, and_, select
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, backref, foreign, mapped_column, relationship

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
    # The enterprise control this RCM line relies on, and the reverse
    # ``Control.icfr_controls`` so the control's page lists the ICFR lines that depend on
    # it. Not loaded by default in this direction: a Control arrives with a dozen eager
    # relationships of its own, and an RCM needs only its id, reference and name — the
    # ICFR API asks for exactly those (``api/v1/icfr.py::_with_control``). The reverse is
    # eager (a control page shows it) and filtered to live processes.
    control: Mapped["Control | None"] = relationship(  # noqa: F821
        "Control", lazy="noload", viewonly=True,
        backref=backref(
            "icfr_controls", lazy="selectin", viewonly=True,
            primaryjoin=lambda: _live_rcm_join(), order_by="IcfrControl.reference",
        ),
    )

    @property
    def test_count(self) -> int:
        return len(self.tests)

    @property
    def latest_result(self) -> IcfrTestResult | None:
        return self.tests[-1].result if self.tests else None


def _live_rcm_join():
    """Control ↔ its RCM lines, leaving out lines of an archived ICFR process (the
    register does not show them either)."""
    from app.models.control import Control

    live = select(IcfrProcess.id).where(IcfrProcess.deleted.is_(False))
    return and_(Control.id == foreign(IcfrControl.control_id), IcfrControl.process_id.in_(live))


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


# ===================================================== effectiveness from tests ===
#: Test results that conclude a test, and the rating each one gives the control.
RESULT_RATING: dict[IcfrTestResult, ControlEffectiveness] = {
    IcfrTestResult.passed: ControlEffectiveness.effective,
    IcfrTestResult.passed_with_exceptions: ControlEffectiveness.partially_effective,
    IcfrTestResult.failed: ControlEffectiveness.ineffective,
}


def _plain(value):
    return getattr(value, "value", value)


def latest_conclusive(tests, test_type: IcfrTestType):
    """The newest test of ``test_type`` with a conclusive result (by test date, then
    when it was recorded), or None. Works on ORM rows and read models alike."""
    wanted = _plain(test_type)
    done = [t for t in tests if _plain(t.test_type) == wanted
            and _plain(t.result) in {_plain(r) for r in RESULT_RATING}]
    if not done:
        return None
    return max(done, key=lambda t: (t.test_date or date.min, str(t.created_at or "")))


def derive_effectiveness(tests, design_manual, operating_manual):
    """``(design, operating, design_basis, operating_basis)`` for an RCM control.

    SOX / SBP ICFR practice (PCAOB AS 2201 ¶42-44; COSO 2013): a control's design and
    operating effectiveness are the conclusions of its latest design and operating tests
    — passed → effective, passed with exceptions → partially effective, failed →
    ineffective. A control that is not designed effectively cannot operate effectively,
    so an ineffective design caps the operating rating at ineffective. Without a
    conclusive test of a kind the rating entered by hand stands (basis "manual")."""
    design_test = latest_conclusive(tests, IcfrTestType.design)
    operating_test = latest_conclusive(tests, IcfrTestType.operating)
    design = (RESULT_RATING[IcfrTestResult(_plain(design_test.result))] if design_test
              else ControlEffectiveness(_plain(design_manual)))
    operating = (RESULT_RATING[IcfrTestResult(_plain(operating_test.result))] if operating_test
                 else ControlEffectiveness(_plain(operating_manual)))
    operating_basis = "tests" if operating_test else "manual"
    if design == ControlEffectiveness.ineffective and operating != ControlEffectiveness.not_assessed:
        if operating != ControlEffectiveness.ineffective:
            operating_basis = "design"
        operating = ControlEffectiveness.ineffective
    return design, operating, ("tests" if design_test else "manual"), operating_basis


def figures_problem(sample_size: int, exceptions_found: int, result) -> str | None:
    """Why a test's figures do not hang together, or None."""
    if exceptions_found > sample_size:
        return (f"exceptions_found: {exceptions_found} exceptions cannot come from a sample of "
                f"{sample_size}. Record the sample size tested.")
    if exceptions_found > 0 and _plain(result) == IcfrTestResult.passed.value:
        return ("result: a test that found exceptions did not simply pass. Record it as "
                "passed with exceptions or failed.")
    return None
