"""Integrations & Continuous Controls Monitoring (CCM) — the 2026 defining trend.

A **connector registry** plus **automated control tests** that run against connected
sources and record pass/fail over time. Phase 4: tests are executable — a test names a
``check_type`` with JSON ``parameters`` and a threshold, the scheduler runs the ones that
are due (``services/ccm_runner.py``), and each run keeps its population, exceptions,
duration and the evidence it wrote. Connector secrets are encrypted at rest
(``services/ccm_checks/secrets.py``) and never returned by the API. Runs may still be
recorded by hand or pushed by a monitoring tool (the phase 3 feed).

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
from datetime import date, datetime, timedelta

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
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
#: Runs a test read carries (newest first); older ones are on the run-history endpoint.
RECENT_RUNS = 30


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
    #: Phase 4: scanner exports (Nessus, Qualys, OpenVAS) read from an import folder or uploaded.
    vuln_scanner = "vuln_scanner"


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
    # Phase 3: SHA-256 of the token a monitoring tool uses to push evidence and test
    # results for this connector; never the token itself.
    ingest_token_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # Phase 4: how to reach the source. ``config`` holds the non-secret settings for the
    # connector type (host, port, base DN, URL, auth kind…); ``secrets_encrypted`` the
    # Fernet token of the secret ones (bind password, API token), and ``secret_keys`` the
    # names that are set, so a form can say "set" without decrypting anything.
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    secrets_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    secret_keys: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

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

    @property
    def has_ingest_token(self) -> bool:
        """Whether a monitoring-feed token is live (the token itself is never stored)."""
        return bool(self.ingest_token_hash)

    @property
    def kind(self) -> str:
        """ldap | http | file | push — how the connector is reached."""
        from app.services.ccm_checks import kind_of

        return kind_of(getattr(self.connector_type, "value", self.connector_type)).kind

    @property
    def secrets_set(self) -> list[str]:
        """Names of the secrets on file (never their values)."""
        return sorted(str(k) for k in (self.secret_keys or []))


# =============================================== automated control tests (CCM) ===
class AutomatedControlTest(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    __tablename__ = "automated_control_tests"
    # Phase 4: an executable definition. ``control_id`` is the monitored control
    # (``control_ref`` stays as the fallback and the push feed's key); ``check_type`` one
    # of ``services.ccm_checks.CHECKS`` ("manual" = recorded by hand or pushed);
    # ``parameters`` its settings; the threshold says how many exceptions a pass allows.
    control_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("controls.id", ondelete="SET NULL"), nullable=True, index=True
    )
    check_type: Mapped[str] = mapped_column(String(48), default="manual", nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    threshold_max_failures: Mapped[int | None] = mapped_column(Integer, nullable=True)
    threshold_max_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    population_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pass_criterion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # A KRI each run posts a reading to, and which number of the run it posts.
    kri_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("key_risk_indicators.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kri_metric: Mapped[str] = mapped_column(String(24), default="exceptions", nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The first day of the current unbroken run of failures; cleared by a pass.
    failing_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: The issue this test's failures are tracked on while it is open (one per test).
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True, index=True
    )

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

    @property
    def is_executable(self) -> bool:
        from app.services import ccm_runner

        return ccm_runner.is_executable(self)

    @property
    def is_overdue(self) -> bool:
        from datetime import timezone

        from app.services import ccm_runner

        return ccm_runner.is_overdue(self, datetime.now(timezone.utc))

    @property
    def recent_runs(self) -> list["ControlTestRun"]:
        """The newest runs first, capped: what a read carries (the full log is paged)."""
        return sorted(self.runs, key=lambda r: (r.run_date or date.min, r.created_at or datetime.min),
                      reverse=True)[:RECENT_RUNS]


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
    # Phase 4: what an executed run observed.
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)  # manual|scheduled|run_now|upload|push
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    population_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exceptions_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Up to ``ccm_checks.SAMPLE_CAP`` exception rows, each a small JSON object.
    exceptions_sample: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kri_measurement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("kri_measurements.id", ondelete="SET NULL"), nullable=True, index=True
    )

    test: Mapped[AutomatedControlTest] = relationship(back_populates="runs")
