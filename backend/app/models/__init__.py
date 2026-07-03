"""SQLAlchemy models. Import all here so metadata is fully populated."""
from app.models.base import Base
from app.models.tenant import Tenant
from app.models.identity import Permission, Role, User, role_permissions, user_roles
from app.models.audit import AuditLog
from app.models.access_review import AccessReview, AccessReviewItem
from app.models.approval import ApprovalAction, ApprovalRequest
from app.models.attestation import Attestation
from app.models.asset import (
    Asset,
    AssetClassification,
    AssetClassificationType,
    AssetLabel,
    AssetMediaType,
    AssetReview,
    asset_classification_links,
    assets_exceptions,
    assets_incidents,
    assets_legals,
    assets_processes,
    assets_related,
    assets_requirements,
)
from app.models.awareness import (
    AwarenessOption,
    AwarenessProgram,
    AwarenessQuestion,
    TrainingRecord,
)
from app.models.assessment import (
    Assessment,
    AssessmentAnswer,
    AssessmentFinding,
    Question,
    QuestionOption,
    Questionnaire,
)
from app.models.collab import Attachment, Comment, EntityTag, StoredFile, Tag
from app.models.continuity import ContinuityPlan, ContinuityTask, ContinuityTest
from app.models.control import Control, ControlAudit, ControlMaintenance, control_policies
from app.models.custom_field import CustomField, CustomFieldValue
from app.models.risk import (
    Risk,
    RiskAcceptance,
    RiskSetting,
    risk_assets,
    risk_controls,
    risk_incidents,
    risk_policies,
)
from app.models.threat import (
    Threat,
    Vulnerability,
    risk_threats,
    risk_vulnerabilities,
)
from app.models.compliance import (
    ComplianceFinding,
    Framework,
    Requirement,
    requirement_controls,
    requirement_crosswalks,
    requirement_policies,
    requirement_risks,
)
from app.models.evidence import Evidence
from app.models.exception import (
    ExceptionRecord,
    exception_controls,
    exception_policies,
    exception_requirements,
    exception_risks,
)
from app.models.goal import Goal, GoalAudit, goal_policies, goal_projects, goal_risks
from app.models.internal_audit import (
    AuditableUnit,
    AuditEngagement,
    AuditFinding,
    AuditProcedure,
)
from app.models.shariah import (
    CharityDisbursement,
    IslamicProduct,
    ShariahFinding,
    ShariahReview,
    ShariahRuling,
)
from app.models.operational_risk import (
    KeyRiskIndicator,
    KriMeasurement,
    LossEvent,
    RcsaAssessment,
    RcsaRisk,
)
from app.models.aml import (
    AmlRiskAssessment,
    ScreeningCase,
    SuspiciousActivityReport,
)
from app.models.incident import (
    Incident,
    IncidentStage,
    RegulatoryReport,
    incident_controls,
    incident_vendors,
)
from app.models.notification import Notification, NotificationView
from app.models.organization import (
    BusinessUnit,
    Legal,
    Process,
    business_units_legals,
)
from app.models.privacy import (
    ProcessingActivity,
    ropa_assets,
    ropa_policies,
    ropa_processes,
    ropa_risks,
)
from app.models.project import (
    Project,
    ProjectExpense,
    ProjectTask,
    project_controls,
    project_policies,
    project_risks,
)
from app.models.policy import Policy, PolicyAcknowledgment, PolicyReview, policies_related
from app.models.vendor import ServiceContract, Vendor, VendorType, vendor_assets, vendor_risks
from app.models.saved_filter import SavedFilter
from app.models.sso import SsoConfig
from app.models.ldap_config import LdapConfig
from app.models.status_rule import StatusRule
from app.models.version import RecordVersion
from app.models.webhook import Webhook, WebhookDelivery
from app.models.widget import DashboardWidget

__all__ = [
    "Base",
    "Tenant",
    "User",
    "Role",
    "Permission",
    "role_permissions",
    "user_roles",
    "AuditLog",
    "Asset",
    "AssetLabel",
    "AssetMediaType",
    "AssetClassificationType",
    "AssetClassification",
    "AssetReview",
    "Control",
    "ControlAudit",
    "ControlMaintenance",
    "Risk",
    "RiskAcceptance",
    "RiskSetting",
    "risk_assets",
    "risk_controls",
    "risk_incidents",
    "risk_policies",
    "Threat",
    "Vulnerability",
    "risk_threats",
    "risk_vulnerabilities",
    "Framework",
    "Requirement",
    "ComplianceFinding",
    "requirement_controls",
    "requirement_risks",
    "requirement_policies",
    "requirement_crosswalks",
    "Evidence",
    "Incident",
    "IncidentStage",
    "RegulatoryReport",
    "BusinessUnit",
    "Process",
    "Legal",
    "Policy",
    "PolicyAcknowledgment",
    "PolicyReview",
    "policies_related",
    "Vendor",
    "VendorType",
    "ServiceContract",
    "vendor_risks",
    "vendor_assets",
    "ExceptionRecord",
    "exception_risks",
    "exception_controls",
    "exception_policies",
    "exception_requirements",
    "Project",
    "ProjectTask",
    "ProjectExpense",
    "project_risks",
    "project_controls",
    "project_policies",
    "Goal",
    "GoalAudit",
    "goal_risks",
    "goal_projects",
    "goal_policies",
    "Questionnaire",
    "Question",
    "QuestionOption",
    "Assessment",
    "AssessmentAnswer",
    "AssessmentFinding",
    "ContinuityPlan",
    "ContinuityTask",
    "ContinuityTest",
    "ProcessingActivity",
    "ropa_assets",
    "ropa_risks",
    "ropa_processes",
    "ropa_policies",
    "AccessReview",
    "AccessReviewItem",
    "AwarenessProgram",
    "AwarenessQuestion",
    "AwarenessOption",
    "TrainingRecord",
    "Notification",
    "NotificationView",
    "ApprovalRequest",
    "ApprovalAction",
    "AuditableUnit",
    "AuditEngagement",
    "AuditProcedure",
    "AuditFinding",
    "ShariahRuling",
    "IslamicProduct",
    "ShariahReview",
    "ShariahFinding",
    "CharityDisbursement",
    "RcsaAssessment",
    "RcsaRisk",
    "KeyRiskIndicator",
    "KriMeasurement",
    "LossEvent",
    "ScreeningCase",
    "SuspiciousActivityReport",
    "AmlRiskAssessment",
    "CustomField",
    "CustomFieldValue",
    "DashboardWidget",
    "Comment",
    "Tag",
    "EntityTag",
    "Attachment",
    "StoredFile",
    "RecordVersion",
    "Webhook",
    "WebhookDelivery",
    "StatusRule",
    "Attestation",
    "SavedFilter",
    "SsoConfig",
    "LdapConfig",
]
