"""AML/CFT — Anti-Money Laundering & Countering the Financing of Terrorism.

Board-level for Pakistani banks given the FATF context. Three registers:
* **ScreeningCase** — sanctions / PEP / adverse-media screening of parties, with match
  disposition.
* **SuspiciousActivityReport** — STR/SAR filings with the FMU, tracked to a filing
  deadline.
* **AmlRiskAssessment** — customer/product/geography/enterprise AML risk assessments
  (inherent → controls → residual).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkflowMixin,
)
from app.models.enums import (
    AmlScope,
    Criticality,
    ReviewFrequency,
    SarStatus,
    ScreeningCaseStatus,
    ScreeningMatchStatus,
    ScreeningType,
)


class ScreeningCase(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A sanctions / PEP / adverse-media screening result and its disposition."""

    __tablename__ = "screening_cases"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(64), default="customer")  # customer|counterparty|employee|vendor
    screening_type: Mapped[ScreeningType] = mapped_column(
        SAEnum(ScreeningType, name="screening_type"), default=ScreeningType.sanctions, nullable=False
    )
    lists_checked: Mapped[str] = mapped_column(Text, default="")  # UN, OFAC, EU, local…
    match_status: Mapped[ScreeningMatchStatus] = mapped_column(
        SAEnum(ScreeningMatchStatus, name="screening_match_status"),
        default=ScreeningMatchStatus.no_match, nullable=False,
    )
    risk_rating: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.low, nullable=False
    )
    screened_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    disposition: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[ScreeningCaseStatus] = mapped_column(
        SAEnum(ScreeningCaseStatus, name="screening_case_status"),
        default=ScreeningCaseStatus.open, nullable=False,
    )


class SuspiciousActivityReport(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A Suspicious Transaction/Activity Report (STR/SAR) filed with the FMU."""

    __tablename__ = "suspicious_activity_reports"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    activity_description: Mapped[str] = mapped_column(Text, default="")
    suspicion_reason: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    analyst: Mapped[str] = mapped_column(String(200), default="")
    priority: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    detected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)  # FMU filing deadline
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fmu_reference: Mapped[str] = mapped_column(String(120), default="")  # FMU acknowledgement
    status: Mapped[SarStatus] = mapped_column(
        SAEnum(SarStatus, name="sar_status"), default=SarStatus.draft, nullable=False
    )

    @property
    def is_overdue(self) -> bool:
        return (
            self.status not in (SarStatus.filed, SarStatus.closed)
            and self.deadline is not None
            and self.deadline < date.today()
        )


class AmlRiskAssessment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """An AML/CFT risk assessment (customer / product / geography / enterprise)."""

    __tablename__ = "aml_risk_assessments"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scope: Mapped[AmlScope] = mapped_column(
        SAEnum(AmlScope, name="aml_scope"), default=AmlScope.customer, nullable=False
    )
    subject: Mapped[str] = mapped_column(String(255), default="")
    inherent_risk: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    mitigating_controls: Mapped[str] = mapped_column(Text, default="")
    residual_risk: Mapped[Criticality] = mapped_column(
        SAEnum(Criticality, name="criticality"), default=Criticality.medium, nullable=False
    )
    assessor: Mapped[str] = mapped_column(String(200), default="")
    assessment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.annual, nullable=False,
    )
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def is_review_overdue(self) -> bool:
        return self.next_review_date is not None and self.next_review_date < date.today()
