"""Integrations & Continuous Controls Monitoring (CCM) — the 2026 defining trend.

A **connector registry** plus **automated control tests** that run against connected
sources and record pass/fail over time. Runtime execution is stubbed/manual for now;
the schema + UI are the deliverable — a control tester records the outcome of a run
and the platform keeps the pass/fail history and the control's rolling pass-rate.

* **Connector** — a registered integration into a source of truth the bank already
  runs (Active Directory, Azure AD / O365, SIEM, EDR, CMDB, core banking, cloud,
  webhook / CSV feed / generic API). Holds endpoint, auth method, sync frequency and
  a computed *stale* flag when it has not synced recently.
* **AutomatedControlTest** — a continuous control test bound (optionally) to a
  connector, expressing its logic in plain language (e.g. "all privileged accounts
  have MFA enabled"), with the latest result and a rolling pass-rate.
* **ControlTestRun** — a single recorded execution of a test: date, result, findings,
  an evidence reference and the pass-rate observed on that run.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, timedelta

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, Uuid
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
from app.models.enums import ReviewFrequency

# Number of days after which a connector's last sync is considered stale.
STALE_AFTER_DAYS = 35


# =============================================================== enums (local) ===
class ConnectorType(str, enum.Enum):
    """The kind of source a connector integrates with."""

    active_directory = "active_directory"
    azure_ad = "azure_ad"
    o365 = "o365"
    siem = "siem"
    edr_crowdstrike = "edr_crowdstrike"
    cmdb = "cmdb"
    core_banking = "core_banking"
    cloud_aws = "cloud_aws"
    cloud_azure = "cloud_azure"
    webhook = "webhook"
    csv_feed = "csv_feed"
    api = "api"


class ConnectorStatus(str, enum.Enum):
    """Lifecycle / health of a connector."""

    configured = "configured"
    active = "active"
    error = "error"
    disabled = "disabled"


class CcmResult(str, enum.Enum):
    """Outcome of an automated control test / run."""

    passed = "passed"
    failed = "failed"
    error = "error"
    not_run = "not_run"


class CcmStatus(str, enum.Enum):
    """Whether an automated control test is actively monitored."""

    active = "active"
    paused = "paused"


# ================================================================ connectors ===
class Connector(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "connectors"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    connector_type: Mapped[ConnectorType] = mapped_column(
        SAEnum(ConnectorType, name="connector_type"),
        default=ConnectorType.api, nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, default="")
    endpoint_url: Mapped[str] = mapped_column(String(500), default="")
    auth_method: Mapped[str] = mapped_column(String(120), default="")
    sync_frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.monthly, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    config_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ConnectorStatus] = mapped_column(
        SAEnum(ConnectorStatus, name="connector_status"),
        default=ConnectorStatus.configured, nullable=False,
    )
    last_sync: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def is_stale(self) -> bool:
        return self.last_sync is None or self.last_sync < (date.today() - timedelta(days=STALE_AFTER_DAYS))


# =============================================== automated control tests (CCM) ===
class AutomatedControlTest(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "automated_control_tests"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    control_ref: Mapped[str] = mapped_column(String(120), default="")
    connector_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str] = mapped_column(Text, default="")
    test_logic: Mapped[str] = mapped_column(Text, default="")
    frequency: Mapped[ReviewFrequency] = mapped_column(
        SAEnum(ReviewFrequency, name="review_frequency"),
        default=ReviewFrequency.monthly, nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(200), default="")
    last_run: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_result: Mapped[CcmResult] = mapped_column(
        SAEnum(CcmResult, name="ccm_result"),
        default=CcmResult.not_run, nullable=False,
    )
    pass_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    status: Mapped[CcmStatus] = mapped_column(
        SAEnum(CcmStatus, name="ccm_status"),
        default=CcmStatus.active, nullable=False,
    )

    runs: Mapped[list["ControlTestRun"]] = relationship(
        back_populates="test", cascade="all, delete-orphan", lazy="selectin",
        order_by="ControlTestRun.created_at",
    )

    @property
    def run_count(self) -> int:
        return len(self.runs)


# ============================================================ control test runs ===
class ControlTestRun(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A single recorded execution of an automated control test."""

    __tablename__ = "control_test_runs"

    test_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("automated_control_tests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[CcmResult] = mapped_column(
        SAEnum(CcmResult, name="ccm_result"),
        default=CcmResult.not_run, nullable=False,
    )
    findings: Mapped[str] = mapped_column(Text, default="")
    evidence_ref: Mapped[str] = mapped_column(String(500), default="")
    pass_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)

    test: Mapped[AutomatedControlTest] = relationship(back_populates="runs")
