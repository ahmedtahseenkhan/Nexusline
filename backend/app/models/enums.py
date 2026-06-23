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
