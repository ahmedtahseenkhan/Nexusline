"""Domain enumerations shared across models and schemas."""
from __future__ import annotations

import enum


class RiskStatus(str, enum.Enum):
    draft = "draft"
    assessed = "assessed"
    treatment_planned = "treatment_planned"
    treatment_in_progress = "treatment_in_progress"
    accepted = "accepted"
    closed = "closed"


class TreatmentStrategy(str, enum.Enum):
    mitigate = "mitigate"
    accept = "accept"
    transfer = "transfer"
    avoid = "avoid"


class Criticality(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AssetType(str, enum.Enum):
    information = "information"
    software = "software"
    hardware = "hardware"
    service = "service"
    people = "people"
    facility = "facility"
    process = "process"


class AssetClass(str, enum.Enum):
    """The ISO 27005 primary/supporting split.

    * ``information_asset`` — a *primary* asset (data / application). Its criticality
      reflects **business value**, attested by the business owner. Classification &
      handling labels live here (ISO 27001:2022 A.5.9 / A.5.12 / A.5.13).
    * ``it_asset`` — a *supporting* asset (hardware / software / network / facility).
      Judged by **intrinsic** cost + availability, PLUS **derived** criticality
      inherited from the information assets it hosts (the "backup server" rule).
    """

    it_asset = "it_asset"
    information_asset = "information_asset"


class AssetEnvironment(str, enum.Enum):
    """Operational environment tag for IT (supporting) assets."""

    production = "production"
    dr = "dr"
    uat = "uat"
    staging = "staging"
    development = "development"
    not_applicable = "not_applicable"


class AssetDependencyType(str, enum.Enum):
    """How an information asset relates to the IT asset that carries it."""

    hosts = "hosts"
    stores = "stores"
    processes = "processes"
    transmits = "transmits"
    backs_up = "backs_up"


class DiscoverySource(str, enum.Enum):
    """Where an asset record originated — manual today, automated discovery later (CAASM)."""

    manual = "manual"
    active_directory = "active_directory"
    intune_mdm = "intune_mdm"
    cmdb = "cmdb"
    network_scan = "network_scan"
    cloud_connector = "cloud_connector"
    edr = "edr"
    import_csv = "import_csv"


class ControlStatus(str, enum.Enum):
    planned = "planned"
    implemented = "implemented"
    operational = "operational"
    retired = "retired"


class ControlType(str, enum.Enum):
    """eramba security_service_type — is the control a design artefact or in production?"""

    design = "design"
    production = "production"


class ControlEffectiveness(str, enum.Enum):
    not_assessed = "not_assessed"
    ineffective = "ineffective"
    partially_effective = "partially_effective"
    effective = "effective"


class ReviewFrequency(str, enum.Enum):
    none = "none"
    monthly = "monthly"
    quarterly = "quarterly"
    semiannual = "semiannual"
    annual = "annual"


class AcceptanceStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class Severity(str, enum.Enum):
    """Derived from a 1-25 risk score (5x5 matrix)."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ComplianceTreatment(str, enum.Enum):
    """eramba compliance_treatment_strategy — how a requirement gap is treated."""

    implement = "implement"
    improve = "improve"
    accept = "accept"
    transfer = "transfer"
    not_applicable = "not_applicable"


class ComplianceStatus(str, enum.Enum):
    not_assessed = "not_assessed"
    non_compliant = "non_compliant"
    partially_compliant = "partially_compliant"
    compliant = "compliant"
    not_applicable = "not_applicable"


class IncidentStatus(str, enum.Enum):
    open = "open"
    triage = "triage"
    investigating = "investigating"
    contained = "contained"
    resolved = "resolved"
    closed = "closed"


class PolicyDocType(str, enum.Enum):
    """eramba security_policy_document_type."""

    policy = "policy"
    standard = "standard"
    procedure = "procedure"
    guideline = "guideline"


class PolicyStatus(str, enum.Enum):
    draft = "draft"
    under_review = "under_review"
    approved = "approved"
    published = "published"
    retired = "retired"


class VendorStatus(str, enum.Enum):
    prospective = "prospective"
    active = "active"
    suspended = "suspended"
    offboarded = "offboarded"


class AssessmentStatus(str, enum.Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    completed = "completed"


class EvidenceType(str, enum.Enum):
    document = "document"
    screenshot = "screenshot"
    log = "log"
    link = "link"
    configuration = "configuration"
    other = "other"


class EvidenceStatus(str, enum.Enum):
    pending = "pending"
    valid = "valid"
    expired = "expired"


class ExceptionType(str, enum.Enum):
    risk = "risk"
    policy = "policy"
    compliance = "compliance"
    other = "other"


class ExceptionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    closed = "closed"


class ProjectStatus(str, enum.Enum):
    planned = "planned"
    ongoing = "ongoing"
    on_hold = "on_hold"
    completed = "completed"
    cancelled = "cancelled"


class GoalStatus(str, enum.Enum):
    not_started = "not_started"
    on_track = "on_track"
    at_risk = "at_risk"
    off_track = "off_track"
    achieved = "achieved"


class GoalAuditResult(str, enum.Enum):
    not_assessed = "not_assessed"
    passed = "passed"
    failed = "failed"


class TestResult(str, enum.Enum):
    """Generic pass/fail result for control audits and maintenances."""

    not_assessed = "not_assessed"
    passed = "passed"
    failed = "failed"


class VendorAssessmentStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    in_progress = "in_progress"
    submitted = "submitted"
    reviewed = "reviewed"


class FindingStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class ContinuityStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    under_review = "under_review"
    retired = "retired"


class LawfulBasis(str, enum.Enum):
    consent = "consent"
    contract = "contract"
    legal_obligation = "legal_obligation"
    vital_interests = "vital_interests"
    public_task = "public_task"
    legitimate_interests = "legitimate_interests"


class RopaStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    under_review = "under_review"
    retired = "retired"


class DpiaStatus(str, enum.Enum):
    not_required = "not_required"
    required = "required"
    in_progress = "in_progress"
    completed = "completed"


class AccessReviewStatus(str, enum.Enum):
    draft = "draft"
    in_progress = "in_progress"
    completed = "completed"


class AccessDecision(str, enum.Enum):
    pending = "pending"
    keep = "keep"
    revoke = "revoke"


class AwarenessStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    closed = "closed"


class TrainingStatus(str, enum.Enum):
    assigned = "assigned"
    completed = "completed"


class StageStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"


class NotificationCategory(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class CustomFieldType(str, enum.Enum):
    text = "text"
    textarea = "textarea"
    number = "number"
    date = "date"
    select = "select"
    checkbox = "checkbox"


class WorkflowStatus(str, enum.Enum):
    """eramba workflow_status — the approval lifecycle on most records."""

    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    retired = "retired"


class AssetReviewStatus(str, enum.Enum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    expired = "expired"


class AuditEngagementStatus(str, enum.Enum):
    """Lifecycle of an internal-audit engagement."""

    planned = "planned"
    fieldwork = "fieldwork"
    reporting = "reporting"
    closed = "closed"
    cancelled = "cancelled"


class AuditProcedureResult(str, enum.Enum):
    """Outcome of an audit test/procedure (workpaper)."""

    pending = "pending"
    passed = "passed"
    failed = "failed"
    not_applicable = "not_applicable"


class AuditFindingStatus(str, enum.Enum):
    """Lifecycle of an audit finding through remediation follow-up."""

    open = "open"
    in_progress = "in_progress"
    closed = "closed"
    risk_accepted = "risk_accepted"


class ShariahMode(str, enum.Enum):
    """Islamic modes of finance / contract types."""

    murabaha = "murabaha"
    ijarah = "ijarah"
    musharakah = "musharakah"
    diminishing_musharakah = "diminishing_musharakah"
    mudarabah = "mudarabah"
    salam = "salam"
    istisna = "istisna"
    wakala = "wakala"
    tawarruq = "tawarruq"
    qard = "qard"
    other = "other"


class ShariahRulingStatus(str, enum.Enum):
    """Lifecycle of a Shariah Board ruling / fatwa / resolution."""

    draft = "draft"
    under_review = "under_review"
    approved = "approved"
    superseded = "superseded"


class IslamicProductStatus(str, enum.Enum):
    in_development = "in_development"
    approved = "approved"
    active = "active"
    suspended = "suspended"
    withdrawn = "withdrawn"


class ShariahReviewStatus(str, enum.Enum):
    planned = "planned"
    in_progress = "in_progress"
    completed = "completed"


class ShariahFindingStatus(str, enum.Enum):
    """Lifecycle of a Shariah Non-Compliance (SNC) finding."""

    open = "open"
    in_progress = "in_progress"
    remediated = "remediated"
    closed = "closed"


class CharityStatus(str, enum.Enum):
    """Purification / charity disbursement of Shariah non-compliant income."""

    pending = "pending"
    approved = "approved"
    disbursed = "disbursed"


class RcsaStatus(str, enum.Enum):
    """Risk & Control Self-Assessment campaign lifecycle."""

    planned = "planned"
    in_progress = "in_progress"
    completed = "completed"


class KriStatus(str, enum.Enum):
    """Key Risk Indicator RAG status (computed from value vs thresholds)."""

    green = "green"
    amber = "amber"
    red = "red"
    no_data = "no_data"


class KriDirection(str, enum.Enum):
    """Which direction breaches a KRI threshold."""

    higher_is_worse = "higher_is_worse"
    lower_is_worse = "lower_is_worse"


class BaselEventType(str, enum.Enum):
    """Basel II operational-risk loss event categories (level 1)."""

    internal_fraud = "internal_fraud"
    external_fraud = "external_fraud"
    employment_practices = "employment_practices"
    clients_products_business_practices = "clients_products_business_practices"
    damage_to_physical_assets = "damage_to_physical_assets"
    business_disruption_system_failure = "business_disruption_system_failure"
    execution_delivery_process_management = "execution_delivery_process_management"


class LossEventStatus(str, enum.Enum):
    open = "open"
    under_investigation = "under_investigation"
    recovered = "recovered"
    closed = "closed"


class RegulatoryReportType(str, enum.Enum):
    """Regulator submission types (e.g. SBP incident-reporting stages)."""

    initial_notification = "initial_notification"
    interim_update = "interim_update"
    final_report = "final_report"
    closure = "closure"


class RegulatoryReportStatus(str, enum.Enum):
    pending = "pending"
    submitted = "submitted"
    acknowledged = "acknowledged"


class ScreeningType(str, enum.Enum):
    """AML/CFT screening scope."""

    sanctions = "sanctions"
    pep = "pep"
    adverse_media = "adverse_media"
    comprehensive = "comprehensive"


class ScreeningMatchStatus(str, enum.Enum):
    no_match = "no_match"
    potential_match = "potential_match"
    confirmed_match = "confirmed_match"
    false_positive = "false_positive"


class ScreeningCaseStatus(str, enum.Enum):
    open = "open"
    under_review = "under_review"
    cleared = "cleared"
    escalated = "escalated"


class SarStatus(str, enum.Enum):
    """Suspicious Transaction/Activity Report lifecycle (filed with the FMU)."""

    draft = "draft"
    under_review = "under_review"
    filed = "filed"
    closed = "closed"


class AmlScope(str, enum.Enum):
    customer = "customer"
    product = "product"
    geography = "geography"
    channel = "channel"
    enterprise = "enterprise"
