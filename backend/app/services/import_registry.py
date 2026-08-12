"""Declarative registry powering the generic CSV import/export engine.

Each importable/exportable resource is described once as a :class:`ResourceIO`:
its model, its Pydantic *Create* schema, the module's existing async create
function ``create_func(body, db, user)``, the read/write permission codes, and a
flat list of :class:`Column` describing every CSV column. Link columns carry a
:class:`LinkSpec` mapping a human reference back to the ``*_ids`` field the
Create schema accepts, and to the relationship attribute used when exporting.

The engine (``app.api.v1.dataio``) reads only from this registry, so adding or
adjusting a resource never touches the module's own model/schema/api files.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.models.access_review import AccessReview
from app.models.asset import Asset
from app.models.bia import BiaAssessment, BiaStatus
from app.models.awareness import AwarenessProgram
from app.models.compliance import Framework, Requirement
from app.models.continuity import ContinuityPlan
from app.models.control import Control
from app.models.evidence import Evidence
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.icfr import IcfrProcess, IcfrProcessStatus
from app.models.incident import Incident
from app.models.internal_audit import AuditEngagement, AuditableUnit
from app.models.issue import Issue, IssueSource, IssueStatus2
from app.models.model_risk import ModelInventory, ModelStatus, ModelType
from app.models.operational_risk import KeyRiskIndicator, LossEvent, RcsaAssessment
from app.models.organization import BusinessUnit, Legal, Process
from app.models.outsourcing import (
    CloudModel,
    OutsourcingArrangement,
    OutsourcingCategory,
    OutsourcingMateriality,
    OutsourcingStatus,
    SbpApprovalStatus,
)
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.regulatory_change import (
    Applicability,
    Obligation,
    ObligationStatus,
    ObligationType,
    RegChangeStatus,
    RegulatoryChange,
)
from app.models.risk import Risk
from app.models.threat import Threat, Vulnerability
from app.models.vendor import Vendor

# --- enums -----------------------------------------------------------------
from app.models.base import WorkflowState
from app.models.enums import (
    AccessReviewStatus,
    AssessmentStatus,
    AssetClass,
    AssetEnvironment,
    AuditEngagementStatus,
    AwarenessStatus,
    BaselEventType,
    ComplianceStatus,
    ComplianceTreatment,
    ContinuityStatus,
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    Criticality,
    DpiaStatus,
    EvidenceStatus,
    EvidenceType,
    ExceptionType,
    GoalStatus,
    IncidentStatus,
    KriDirection,
    LawfulBasis,
    LossEventStatus,
    PolicyDocType,
    PolicyStatus,
    ProjectStatus,
    RcsaStatus,
    ReviewFrequency,
    RiskStatus,
    RopaStatus,
    Severity,
    TreatmentStrategy,
    VendorStatus,
    WorkflowStatus,
)

# --- Create schemas --------------------------------------------------------
from app.schemas.access_review import ReviewCreate
from app.schemas.asset import AssetCreate
from app.schemas.awareness import ProgramCreate
from app.schemas.bia import BiaCreate
from app.schemas.compliance import RequirementCreate
from app.schemas.continuity import PlanCreate
from app.schemas.control import ControlCreate
from app.schemas.evidence import EvidenceCreate
from app.schemas.exception import ExceptionCreate
from app.schemas.goal import GoalCreate
from app.schemas.icfr import IcfrProcessCreate
from app.schemas.incident import IncidentCreate
from app.schemas.internal_audit import EngagementCreate
from app.schemas.issue import IssueCreate
from app.schemas.model_risk import ModelCreate
from app.schemas.operational_risk import KriCreate, LossEventCreate, RcsaCreate
from app.schemas.organization import BusinessUnitCreate, LegalCreate, ProcessCreate
from app.schemas.outsourcing import OutsourcingArrangementCreate
from app.schemas.policy import PolicyCreate
from app.schemas.privacy import RopaCreate
from app.schemas.project import ProjectCreate
from app.schemas.regulatory_change import ObligationCreate, RegulatoryChangeCreate
from app.schemas.risk import RiskCreate
from app.schemas.threat import ThreatCreate, VulnerabilityCreate
from app.schemas.vendor import VendorCreate

# --- existing module create functions --------------------------------------
from app.api.v1.access_reviews import create_review
from app.api.v1.awareness import create_program
from app.api.v1.bia import create_bia
from app.api.v1.compliance import create_requirement
from app.api.v1.continuity import create_plan
from app.api.v1.controls import create_control
from app.api.v1.evidence import create_evidence
from app.api.v1.exceptions import create_exception
from app.api.v1.goals import create_goal
from app.api.v1.icfr import create_process as create_icfr_process
from app.api.v1.incidents import create_incident
from app.api.v1.internal_audit import create_engagement
from app.api.v1.issues import create_issue
from app.api.v1.model_risk import create_model
from app.api.v1.operational_risk import create_kri, create_loss_event, create_rcsa
from app.api.v1.outsourcing import create_arrangement
from app.api.v1.assets import create_asset
from app.api.v1.organization import (
    create_business_unit,
    create_legal,
    create_process,
)
from app.api.v1.policies import create_policy
from app.api.v1.privacy import create_ropa
from app.api.v1.projects import create_project
from app.api.v1.regulatory_change import create_change, create_obligation
from app.api.v1.risks import create_risk
from app.api.v1.threats import create_threat, create_vulnerability
from app.api.v1.vendors import create_vendor


# ---------------------------------------------------------------------------
# Spec dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LinkSpec:
    """How a reference column resolves to ids on import and renders on export.

    ``target_model``  SQLAlchemy model the reference points at.
    ``match_field``   primary lookup attribute (we always try ``reference``
                      first when the target has one, then this field).
    ``multi``         True if the column accepts several comma/semicolon tokens.
    ``create_field``  the exact ``*_ids`` (or scalar ``*_id``) field on the
                      Create schema this column feeds.
    ``export_attr``   relationship attribute on the main model holding the linked
                      object(s) for export rendering.
    ``exportable``    False when the main model exposes no real ORM relationship
                      for this link (the link is write-only via a join table that
                      the create function manages). The column is still emitted on
                      export for round-trip symmetry, but renders blank.
    """

    target_model: type
    match_field: str
    multi: bool
    create_field: str
    export_attr: str
    exportable: bool = True


@dataclass(frozen=True)
class Column:
    header: str
    field: str
    required: bool = False
    kind: str = "text"  # text|int|float|bool|date|enum|link
    enum_values: list[str] | None = None
    help: str = ""
    link: LinkSpec | None = None


@dataclass(frozen=True)
class ResourceIO:
    """One CSV-addressable register.

    ``fixed`` stamps discriminator fields onto every imported row and filters the
    export to matching rows. It exists for registers that share one table behind a
    discriminator column — IT vs Information assets — so each resource round-trips
    only its own records and an import can never land rows in the wrong register.
    Fixed fields are deliberately *not* CSV columns: they are the identity of the
    resource, not per-row data.
    """

    resource: str
    label: str
    model: type
    create_schema: type
    create_func: Callable[..., Awaitable[Any]]
    read_perm: str
    write_perm: str
    importable: bool
    columns: list[Column] = field(default_factory=list)
    fixed: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Column-builder helpers
# ---------------------------------------------------------------------------
def _enum_vals(enum_cls: type[Enum]) -> list[str]:
    return [e.value for e in enum_cls]


def text(field: str, header: str | None = None, *, required: bool = False, help: str = "") -> Column:
    return Column(header=header or field, field=field, required=required, kind="text", help=help)


def integer(field: str, header: str | None = None, *, help: str = "") -> Column:
    return Column(header=header or field, field=field, kind="int", help=help)


def number(field: str, header: str | None = None, *, help: str = "") -> Column:
    return Column(header=header or field, field=field, kind="float", help=help)


def boolean(field: str, header: str | None = None, *, help: str = "") -> Column:
    return Column(header=header or field, field=field, kind="bool", help=help)


def date_col(field: str, header: str | None = None, *, help: str = "") -> Column:
    return Column(header=header or field, field=field, kind="date", help=help)


def enum_col(field: str, enum_cls: type[Enum], header: str | None = None, *, help: str = "") -> Column:
    return Column(
        header=header or field, field=field, kind="enum",
        enum_values=_enum_vals(enum_cls), help=help,
    )


def link_col(
    header: str,
    create_field: str,
    target_model: type,
    export_attr: str,
    *,
    match_field: str = "name",
    multi: bool = True,
    exportable: bool = True,
    help: str = "",
) -> Column:
    return Column(
        header=header,
        field=create_field,
        kind="link",
        help=help or f"Comma-separated reference or {match_field} of {target_model.__name__} records",
        link=LinkSpec(
            target_model=target_model,
            match_field=match_field,
            multi=multi,
            create_field=create_field,
            export_attr=export_attr,
            exportable=exportable,
        ),
    )


# ---------------------------------------------------------------------------
# REGISTRY
# ---------------------------------------------------------------------------
REGISTRY: dict[str, ResourceIO] = {}


def _register(res: ResourceIO) -> None:
    REGISTRY[res.resource] = res


# ----- policies ------------------------------------------------------------
_register(ResourceIO(
    resource="policies", label="Policies", model=Policy,
    create_schema=PolicyCreate, create_func=create_policy,
    read_perm="policy:read", write_perm="policy:write", importable=True,
    columns=[
        text("title", required=True),
        text("summary"),
        text("body"),
        text("url"),
        text("category"),
        enum_col("document_type", PolicyDocType),
        text("version"),
        enum_col("status", PolicyStatus),
        text("owner"),
        enum_col("review_frequency", ReviewFrequency),
        enum_col("workflow_status", WorkflowState),
        # NB: PolicyCreate has no workflow_owner field (unlike most modules), so it is omitted.
        link_col("controls", "controls_ids", Control, "controls", match_field="name"),
        link_col("requirements", "requirements_ids", Requirement, "requirements", match_field="title"),
        link_col("risks", "risks_ids", Risk, "risks", match_field="title"),
        link_col("related_policies", "related_ids", Policy, "related", match_field="title"),
    ],
))

# ----- risks ---------------------------------------------------------------
_register(ResourceIO(
    resource="risks", label="Risks", model=Risk,
    create_schema=RiskCreate, create_func=create_risk,
    read_perm="risk:read", write_perm="risk:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        text("category"),
        enum_col("status", RiskStatus),
        integer("inherent_likelihood", help="1-5"),
        integer("inherent_impact", help="1-5"),
        integer("residual_likelihood", help="1-5 (optional)"),
        integer("residual_impact", help="1-5 (optional)"),
        enum_col("treatment_strategy", TreatmentStrategy),
        text("treatment_description"),
        text("treatment_owner"),
        date_col("treatment_deadline"),
        number("treatment_cost"),
        number("annual_loss_frequency", help="FAIR: events per year"),
        number("single_loss_expectancy", help="FAIR: $ per event"),
        enum_col("review_frequency", ReviewFrequency),
        enum_col("workflow_status", WorkflowState),
        text("workflow_owner"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("threats", "threat_ids", Threat, "threats", match_field="name"),
        link_col("vulnerabilities", "vulnerability_ids", Vulnerability, "vulnerabilities", match_field="name"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
        link_col("incidents", "incident_ids", Incident, "incidents", match_field="title"),
    ],
))

# ----- controls ------------------------------------------------------------
_register(ResourceIO(
    resource="controls", label="Controls", model=Control,
    create_schema=ControlCreate, create_func=create_control,
    read_perm="control:read", write_perm="control:write", importable=True,
    columns=[
        text("name", required=True),
        # Control.reference is a real, user-supplied column here (not auto-generated).
        text("reference", help="External control reference, e.g. A.5.1 / AC-2"),
        text("description"),
        text("objective"),
        text("owner"),
        enum_col("control_type", ControlType),
        text("classification"),
        text("documentation_url"),
        enum_col("status", ControlStatus),
        enum_col("effectiveness", ControlEffectiveness),
        enum_col("workflow_status", WorkflowState),
        number("opex"),
        number("capex"),
        integer("resource_utilization", help="0-100"),
        enum_col("audit_frequency", ReviewFrequency),
        text("audit_metric"),
        text("audit_success_criteria"),
        enum_col("maintenance_frequency", ReviewFrequency),
        date_col("next_audit_date"),
        date_col("next_maintenance_date"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
        link_col("requirements", "requirement_ids", Requirement, "requirements", match_field="title"),
        # Control has no ORM `risks` relationship (write-only via risk_controls join) -> import-only link.
        link_col("risks", "risk_ids", Risk, "risks", match_field="title", exportable=False),
    ],
))

# ----- assets --------------------------------------------------------------
# The single asset table backs two registers (ISO 27005 primary/supporting split),
# discriminated by `asset_class`. Each gets its own resource so the CSV headers match
# the register the user is loading, and so `fixed` stamps the class on every imported
# row — otherwise every import silently lands as information_asset (the column default).
_ASSET_SHARED_COLUMNS = [
    text("name", required=True),
    text("description"),
    enum_col("confidentiality", Criticality),
    enum_col("integrity", Criticality),
    enum_col("availability", Criticality),
    enum_col("criticality", Criticality),
    text("potential_liabilities"),
    text("location"),
    integer("rto_hours", help="Recovery time objective, hours"),
    integer("rpo_hours", help="Recovery point objective, hours"),
    enum_col("review_frequency", ReviewFrequency),
    date_col("next_review_date"),
    enum_col("workflow_status", WorkflowStatus),
]

_ASSET_SHARED_LINKS = [
    link_col("processes", "process_ids", Process, "processes", match_field="name"),
    link_col("legals", "legal_ids", Legal, "legals", match_field="name"),
    link_col("requirements", "requirement_ids", Requirement, "requirements", match_field="title"),
    link_col("incidents", "incident_ids", Incident, "incidents", match_field="title"),
    link_col("exceptions", "exception_ids", ExceptionRecord, "exceptions", match_field="title"),
    link_col("related_assets", "related_ids", Asset, "related_assets", match_field="name"),
    link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
]

_register(ResourceIO(
    resource="information-assets", label="Information Assets", model=Asset,
    create_schema=AssetCreate, create_func=create_asset,
    read_perm="asset:read", write_perm="asset:write", importable=True,
    fixed={"asset_class": AssetClass.information_asset},
    columns=[
        *_ASSET_SHARED_COLUMNS,
        # Primary-asset attributes: what the data is worth and who owns it.
        enum_col("business_value", Criticality),
        text("information_owner"),
        text("data_categories"),
        text("records_volume"),
        boolean("self_assessed"),
        text("assessed_by"),
        date_col("assessed_date"),
        *_ASSET_SHARED_LINKS,
    ],
))

_register(ResourceIO(
    resource="it-assets", label="IT Assets", model=Asset,
    create_schema=AssetCreate, create_func=create_asset,
    read_perm="asset:read", write_perm="asset:write", importable=True,
    fixed={"asset_class": AssetClass.it_asset},
    columns=[
        *_ASSET_SHARED_COLUMNS,
        # Supporting-asset attributes: the physical/technical inventory fields a bank
        # loads from its CMDB or discovery tool.
        enum_col("environment", AssetEnvironment),
        text("hostname"),
        text("ip_address"),
        text("serial_number"),
        text("manufacturer"),
        text("model_number"),
        text("os_version"),
        number("replacement_cost"),
        text("currency"),
        text("external_id", help="Identifier in the source CMDB / discovery tool"),
        *_ASSET_SHARED_LINKS,
    ],
))

# ----- vendors -------------------------------------------------------------
_register(ResourceIO(
    resource="vendors", label="Vendors", model=Vendor,
    create_schema=VendorCreate, create_func=create_vendor,
    read_perm="vendor:read", write_perm="vendor:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("category"),
        text("contact_name"),
        text("contact_email"),
        text("contact_phone"),
        text("website"),
        text("location"),
        enum_col("criticality", Criticality),
        enum_col("status", VendorStatus),
        enum_col("risk_rating", Severity),
        boolean("shares_data"),
        enum_col("assessment_status", AssessmentStatus),
        date_col("last_assessed_at"),
        date_col("onboarded_at"),
        date_col("offboarded_at"),
        enum_col("review_frequency", ReviewFrequency),
        date_col("next_review_date"),
        enum_col("workflow_status", WorkflowState),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
    ],
))

# ----- incidents -----------------------------------------------------------
_register(ResourceIO(
    resource="incidents", label="Incidents", model=Incident,
    create_schema=IncidentCreate, create_func=create_incident,
    read_perm="incident:read", write_perm="incident:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        text("category"),
        text("classification"),
        enum_col("severity", Severity),
        enum_col("status", IncidentStatus),
        enum_col("workflow_status", WorkflowState),
        text("assignee"),
        text("reported_by"),
        text("impact"),
        text("root_cause"),
        text("lessons_learned"),
        number("cost"),
        date_col("detected_at"),
        date_col("occurred_at"),
        date_col("resolved_at"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("vendors", "vendor_ids", Vendor, "vendors", match_field="name"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
    ],
))

# ----- exceptions ----------------------------------------------------------
_register(ResourceIO(
    resource="exceptions", label="Exceptions", model=ExceptionRecord,
    create_schema=ExceptionCreate, create_func=create_exception,
    read_perm="exception:read", write_perm="exception:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        enum_col("exception_type", ExceptionType),
        text("classification"),
        text("rationale"),
        text("compensating_controls"),
        text("business_owner"),
        enum_col("workflow_status", WorkflowState),
        date_col("start_date"),
        date_col("expires_at"),
        date_col("closure_date"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
        link_col("requirements", "requirement_ids", Requirement, "requirements", match_field="title"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
    ],
))

# ----- legal ---------------------------------------------------------------
_register(ResourceIO(
    resource="legal", label="Legal & Regulatory", model=Legal,
    create_schema=LegalCreate, create_func=create_legal,
    read_perm="org:read", write_perm="org:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("category"),
        text("jurisdiction"),
        # Legal.reference is a real user-supplied column (regulatory reference).
        text("reference", help="Regulatory reference / citation"),
        text("countries", help="Comma-separated list of applicable countries"),
        number("risk_magnifier", help="Amplifies linked risk scores (default 1.0)"),
        enum_col("workflow_status", WorkflowState),
        text("workflow_owner"),
        link_col("business_units", "business_unit_ids", BusinessUnit, "business_units", match_field="name"),
        # Legal has no ORM `assets` relationship (write-only via assets_legals join) -> import-only link.
        link_col("assets", "asset_ids", Asset, "assets", match_field="name", exportable=False),
    ],
))

# ----- business-units ------------------------------------------------------
_register(ResourceIO(
    resource="business-units", label="Business Units", model=BusinessUnit,
    create_schema=BusinessUnitCreate, create_func=create_business_unit,
    read_perm="org:read", write_perm="org:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("manager"),
        text("email"),
        text("location"),
        enum_col("workflow_status", WorkflowState),
        text("workflow_owner"),
        # BusinessUnit exposes parent only as parent_id FK (no `parent` ORM attr) -> import-only link.
        link_col("parent", "parent_id", BusinessUnit, "parent", match_field="name", multi=False,
                 exportable=False, help="Parent business unit name (single value)"),
        link_col("legals", "legal_ids", Legal, "legals", match_field="name"),
    ],
))

# ----- processes -----------------------------------------------------------
_register(ResourceIO(
    resource="processes", label="Processes", model=Process,
    create_schema=ProcessCreate, create_func=create_process,
    read_perm="org:read", write_perm="org:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("owner"),
        enum_col("criticality", Criticality),
        integer("rto_hours", help="Recovery Time Objective (hours)"),
        integer("rpo_hours", help="Recovery Point Objective (hours)"),
        integer("rpd_hours", help="Max tolerable downtime (hours)"),
        enum_col("workflow_status", WorkflowState),
        text("workflow_owner"),
        link_col("business_unit", "business_unit_id", BusinessUnit, "business_unit", match_field="name", multi=False,
                 help="Owning business unit name (single value)"),
        # Process has no ORM `assets` relationship (write-only via assets_processes join) -> import-only link.
        link_col("assets", "asset_ids", Asset, "assets", match_field="name", exportable=False),
    ],
))

# ----- threats -------------------------------------------------------------
_register(ResourceIO(
    resource="threats", label="Threats", model=Threat,
    create_schema=ThreatCreate, create_func=create_threat,
    read_perm="risk:read", write_perm="risk:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("category"),
    ],
))

# ----- vulnerabilities -----------------------------------------------------
_register(ResourceIO(
    resource="vulnerabilities", label="Vulnerabilities", model=Vulnerability,
    create_schema=VulnerabilityCreate, create_func=create_vulnerability,
    read_perm="risk:read", write_perm="risk:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("category"),
    ],
))

# ----- goals ---------------------------------------------------------------
_register(ResourceIO(
    resource="goals", label="Goals", model=Goal,
    create_schema=GoalCreate, create_func=create_goal,
    read_perm="goal:read", write_perm="goal:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("owner"),
        enum_col("status", GoalStatus),
        text("audit_metric"),
        text("success_criteria"),
        enum_col("audit_frequency", ReviewFrequency),
        enum_col("workflow_status", WorkflowState),
        text("workflow_owner"),
        date_col("next_audit_date"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("projects", "project_ids", Project, "projects", match_field="title"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
    ],
))

# ----- processing-activities (privacy / ROPA) ------------------------------
_register(ResourceIO(
    resource="processing-activities", label="Processing Activities (ROPA)",
    model=ProcessingActivity, create_schema=RopaCreate, create_func=create_ropa,
    read_perm="privacy:read", write_perm="privacy:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("purpose"),
        enum_col("status", RopaStatus),
        enum_col("workflow_status", WorkflowState),
        enum_col("lawful_basis", LawfulBasis),
        text("data_subjects"),
        text("data_categories"),
        text("data_types"),
        text("collection_methods"),
        text("volume"),
        boolean("special_category"),
        text("retention_period"),
        text("archiving_driver"),
        text("recipients"),
        text("security_measures"),
        text("accuracy"),
        text("controller"),
        text("processor"),
        text("dpo"),
        boolean("cross_border_transfer"),
        text("origin"),
        text("transfer_destinations"),
        text("transfer_safeguard"),
        boolean("dpia_required"),
        enum_col("dpia_status", DpiaStatus),
        enum_col("review_frequency", ReviewFrequency),
        date_col("review_date"),
        link_col("business_unit", "business_unit_id", BusinessUnit, "business_unit", match_field="name", multi=False,
                 help="Owning business unit name (single value)"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("processes", "process_ids", Process, "processes", match_field="name"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
    ],
))

# ----- continuity-plans ----------------------------------------------------
_register(ResourceIO(
    resource="continuity-plans", label="Continuity Plans", model=ContinuityPlan,
    create_schema=PlanCreate, create_func=create_plan,
    read_perm="bcp:read", write_perm="bcp:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("bia", help="Business Impact Analysis"),
        text("invocation", help="Invocation criteria/procedure"),
        enum_col("status", ContinuityStatus),
        enum_col("workflow_status", WorkflowState),
        text("owner"),
        integer("max_tolerable_downtime_hours"),
        integer("rto_hours", help="Recovery Time Objective (hours)"),
        integer("rpo_hours", help="Recovery Point Objective (hours)"),
        enum_col("criticality", Criticality),
        enum_col("test_frequency", ReviewFrequency),
        link_col("business_unit", "business_unit_id", BusinessUnit, "business_unit", match_field="name", multi=False,
                 help="Owning business unit name (single value)"),
        link_col("process", "process_id", Process, "process", match_field="name", multi=False,
                 help="Related process name (single value)"),
    ],
))

# ----- projects ------------------------------------------------------------
_register(ResourceIO(
    resource="projects", label="Projects", model=Project,
    create_schema=ProjectCreate, create_func=create_project,
    read_perm="project:read", write_perm="project:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        enum_col("status", ProjectStatus),
        text("owner"),
        date_col("start_date"),
        date_col("deadline"),
        number("budget"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
    ],
))

# ----- requirements (compliance) -------------------------------------------
# create_requirement takes framework_id as a PATH parameter, so an import carries
# the framework as a reference column and this adapter routes it into the real
# create function. RequirementImport = RequirementCreate + a resolved framework_id.
class RequirementImport(RequirementCreate):
    framework_id: uuid.UUID


async def _create_requirement_import(body: RequirementImport, db, user):
    inner = RequirementCreate(**body.model_dump(exclude={"framework_id"}))
    return await create_requirement(
        framework_id=body.framework_id, body=inner, db=db, user=user
    )


_register(ResourceIO(
    resource="requirements", label="Compliance Requirements", model=Requirement,
    create_schema=RequirementImport, create_func=_create_requirement_import,
    read_perm="compliance:read", write_perm="compliance:write", importable=True,
    columns=[
        link_col("framework", "framework_id", Framework, "framework", match_field="name",
                 multi=False, help="Framework this requirement belongs to (required)"),
        text("title", required=True),
        text("reference", help="Requirement reference, e.g. A.5.1 / CC6.1"),
        text("domain"),
        text("description"),
        text("implementation", help="How we comply"),
        text("audit_questionnaire", help="How to test compliance"),
        enum_col("status", ComplianceStatus),
        enum_col("treatment", ComplianceTreatment),
        integer("efficacy", help="0-100 %"),
        text("owner"),
        enum_col("workflow_status", WorkflowState),
        link_col("legal", "legal_id", Legal, "legal", match_field="name", multi=False,
                 help="Legal obligation this requirement discharges (single value)"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
    ],
))

# ----- evidence ------------------------------------------------------------
_register(ResourceIO(
    resource="evidence", label="Evidence", model=Evidence,
    create_schema=EvidenceCreate, create_func=create_evidence,
    read_perm="control:read", write_perm="control:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        enum_col("evidence_type", EvidenceType),
        text("reference", help="URL or storage location"),
        enum_col("status", EvidenceStatus),
        date_col("collected_at"),
        date_col("valid_until"),
        # control_id is required on EvidenceCreate -> a blank cell fails the row.
        link_col("control", "control_id", Control, "control", match_field="name", multi=False,
                 help="Control this evidence supports (single value, required)"),
    ],
))

# ----- awareness-programs --------------------------------------------------
_register(ResourceIO(
    resource="awareness-programs", label="Awareness Programs", model=AwarenessProgram,
    create_schema=ProgramCreate, create_func=create_program,
    read_perm="awareness:read", write_perm="awareness:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("content", help="Training material / URL"),
        enum_col("status", AwarenessStatus),
        integer("passing_score", help="0-100 %"),
        enum_col("frequency", ReviewFrequency),
        date_col("due_date"),
    ],
))

# ----- access-reviews ------------------------------------------------------
_register(ResourceIO(
    resource="access-reviews", label="Access Reviews", model=AccessReview,
    create_schema=ReviewCreate, create_func=create_review,
    read_perm="review:read", write_perm="review:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        enum_col("status", AccessReviewStatus),
        text("reviewer"),
        text("system_name", help="System / application under review"),
        date_col("due_date"),
        enum_col("frequency", ReviewFrequency),
        link_col("asset", "asset_id", Asset, "asset", match_field="name", multi=False,
                 help="Asset the reviewed system maps to (single value)"),
    ],
))


# ===========================================================================
# Banking modules
#
# A bank arrives with these registers already populated in spreadsheets, so bulk
# load is what makes onboarding a day rather than a month. Link columns resolve by
# the target's human reference/title, exactly as the core registers do — an RCSA
# line can name the enterprise risk it belongs to, a finding can name the controls
# it failed.
# ===========================================================================

# ----- issues & actions (CAPA) ---------------------------------------------
_register(ResourceIO(
    resource="issues", label="Issues & Actions", model=Issue,
    create_schema=IssueCreate, create_func=create_issue,
    read_perm="issue:read", write_perm="issue:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        enum_col("source_type", IssueSource),
        text("source_reference", help="Reference of the finding/audit that raised this"),
        text("category"),
        enum_col("severity", Severity),
        enum_col("status", IssueStatus2),
        text("owner"),
        text("business_unit"),
        date_col("identified_date"),
        date_col("due_date"),
        date_col("closed_date"),
        text("root_cause"),
        text("management_response"),
        boolean("repeat_finding"),
        boolean("regulator_related"),
        enum_col("workflow_status", WorkflowState),
    ],
))

# ----- operational risk: RCSA ----------------------------------------------
_register(ResourceIO(
    resource="rcsa-assessments", label="RCSA Assessments", model=RcsaAssessment,
    create_schema=RcsaCreate, create_func=create_rcsa,
    read_perm="oprisk:read", write_perm="oprisk:write", importable=True,
    columns=[
        text("title", required=True),
        text("business_unit"),
        text("process"),
        text("assessor"),
        enum_col("status", RcsaStatus),
        text("period", help="e.g. FY2026-Q1"),
        date_col("due_date"),
        date_col("completed_date"),
        enum_col("workflow_status", WorkflowState),
    ],
))

# ----- operational risk: KRIs ----------------------------------------------
_register(ResourceIO(
    resource="kris", label="Key Risk Indicators", model=KeyRiskIndicator,
    create_schema=KriCreate, create_func=create_kri,
    read_perm="oprisk:read", write_perm="oprisk:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("category"),
        text("business_area"),
        text("owner"),
        text("unit", help="Unit of measure, e.g. %, count, PKR"),
        enum_col("frequency", ReviewFrequency),
        enum_col("direction", KriDirection),
        number("warning_threshold"),
        number("limit_threshold"),
        number("current_value"),
        date_col("last_measured_date"),
        enum_col("workflow_status", WorkflowState),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
    ],
))

# ----- operational risk: Basel loss events ---------------------------------
_register(ResourceIO(
    resource="loss-events", label="Loss Events", model=LossEvent,
    create_schema=LossEventCreate, create_func=create_loss_event,
    read_perm="oprisk:read", write_perm="oprisk:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        enum_col("basel_event_type", BaselEventType),
        text("business_line"),
        number("gross_loss"),
        number("recovery"),
        text("currency"),
        enum_col("status", LossEventStatus),
        date_col("occurrence_date"),
        date_col("discovery_date"),
        date_col("accounting_date"),
        text("root_cause"),
        text("action_owner"),
        enum_col("workflow_status", WorkflowState),
        link_col("incident", "incident_id", Incident, "incident", match_field="title", multi=False),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
    ],
))

# ----- regulatory change ----------------------------------------------------
_register(ResourceIO(
    resource="regulatory-changes", label="Regulatory Changes", model=RegulatoryChange,
    create_schema=RegulatoryChangeCreate, create_func=create_change,
    read_perm="regchange:read", write_perm="regchange:write", importable=True,
    columns=[
        text("title", required=True),
        text("regulator", help="e.g. SBP, SECP"),
        text("circular_ref", help="e.g. BPRD Circular No. 03 of 2026"),
        text("source_url"),
        date_col("issued_date"),
        date_col("effective_date"),
        text("summary"),
        enum_col("applicability", Applicability),
        text("impact_assessment"),
        enum_col("status", RegChangeStatus),
        text("owner"),
        enum_col("priority", Criticality),
        text("department"),
        enum_col("workflow_status", WorkflowState),
    ],
))

# ----- obligations ----------------------------------------------------------
_register(ResourceIO(
    resource="obligations", label="Obligations", model=Obligation,
    create_schema=ObligationCreate, create_func=create_obligation,
    read_perm="regchange:read", write_perm="regchange:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        enum_col("obligation_type", ObligationType),
        text("owner"),
        text("business_unit"),
        enum_col("status", ObligationStatus),
        date_col("due_date"),
        link_col("regulatory_change", "regulatory_change_id", RegulatoryChange,
                 "regulatory_change", match_field="title", multi=False),
        link_col("requirements", "requirement_ids", Requirement, "requirements", match_field="title"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
    ],
))

# ----- internal audit: engagements ------------------------------------------
_register(ResourceIO(
    resource="audit-engagements", label="Audit Engagements", model=AuditEngagement,
    create_schema=EngagementCreate, create_func=create_engagement,
    read_perm="internal_audit:read", write_perm="internal_audit:write", importable=True,
    columns=[
        text("title", required=True),
        text("scope"),
        text("objectives"),
        text("lead_auditor"),
        text("audit_team"),
        enum_col("status", AuditEngagementStatus),
        date_col("period_start"),
        date_col("period_end"),
        date_col("planned_start"),
        date_col("planned_end"),
        date_col("actual_start"),
        date_col("actual_end"),
        text("conclusion"),
        enum_col("rating", Severity),
        enum_col("workflow_status", WorkflowState),
        link_col("auditable_unit", "auditable_unit_id", AuditableUnit, "auditable_unit",
                 match_field="name", multi=False),
    ],
))

# ----- ICFR processes -------------------------------------------------------
_register(ResourceIO(
    resource="icfr-processes", label="ICFR Processes", model=IcfrProcess,
    create_schema=IcfrProcessCreate, create_func=create_icfr_process,
    read_perm="icfr:read", write_perm="icfr:write", importable=True,
    columns=[
        text("name", required=True),
        text("cycle", help="e.g. Revenue, Procure-to-Pay, Treasury"),
        text("business_unit"),
        text("owner"),
        text("description"),
        boolean("key_process"),
        enum_col("status", IcfrProcessStatus),
        enum_col("workflow_status", WorkflowState),
    ],
))

# ----- model risk -----------------------------------------------------------
_register(ResourceIO(
    resource="models", label="Model Inventory", model=ModelInventory,
    create_schema=ModelCreate, create_func=create_model,
    read_perm="modelrisk:read", write_perm="modelrisk:write", importable=True,
    columns=[
        text("name", required=True),
        text("purpose"),
        enum_col("model_type", ModelType),
        text("owner"),
        text("developer"),
        text("vendor"),
        enum_col("materiality", Criticality),
        enum_col("status", ModelStatus),
        boolean("regulatory_relevant"),
        boolean("ai_ml"),
        text("methodology"),
        date_col("last_validation_date"),
        date_col("next_validation_date"),
        enum_col("workflow_status", WorkflowState),
    ],
))

# ----- outsourcing ----------------------------------------------------------
_register(ResourceIO(
    resource="outsourcing-arrangements", label="Outsourcing Arrangements",
    model=OutsourcingArrangement,
    create_schema=OutsourcingArrangementCreate, create_func=create_arrangement,
    read_perm="outsourcing:read", write_perm="outsourcing:write", importable=True,
    columns=[
        text("title", required=True),
        text("service_provider"),
        text("service_description"),
        enum_col("category", OutsourcingCategory),
        enum_col("materiality", OutsourcingMateriality),
        text("materiality_assessment"),
        boolean("is_cloud"),
        enum_col("cloud_model", CloudModel),
        boolean("data_offshored"),
        text("country"),
        boolean("sbp_approval_required"),
        enum_col("sbp_approval_status", SbpApprovalStatus),
        text("sbp_approval_ref"),
        date_col("contract_start"),
        date_col("contract_end"),
        text("exit_plan"),
        boolean("exit_plan_tested"),
        text("concentration_note"),
        enum_col("status", OutsourcingStatus),
        text("owner"),
        enum_col("workflow_status", WorkflowState),
        # OutsourcingArrangement holds vendor_id but exposes no ORM relationship, so the
        # column imports the link and stays blank on export (round-trip symmetry).
        link_col("vendor", "vendor_id", Vendor, "vendor", match_field="name", multi=False,
                 exportable=False),
    ],
))

# ----- business impact analysis ---------------------------------------------
_register(ResourceIO(
    resource="bia-assessments", label="Business Impact Analyses", model=BiaAssessment,
    create_schema=BiaCreate, create_func=create_bia,
    read_perm="bia:read", write_perm="bia:write", importable=True,
    columns=[
        text("process_name", required=True),
        text("business_unit"),
        text("owner"),
        text("description"),
        enum_col("criticality", Criticality),
        integer("rto_hours"),
        integer("rpo_hours"),
        integer("mtpd_hours"),
        text("peak_periods"),
        number("financial_impact_24h"),
        number("financial_impact_1week"),
        text("currency"),
        text("operational_impact"),
        text("reputational_impact"),
        text("regulatory_impact"),
        text("legal_impact"),
        text("minimum_resources"),
        text("recovery_strategy"),
        text("workaround"),
        enum_col("status", BiaStatus),
        date_col("assessment_date"),
        date_col("next_review_date"),
        enum_col("workflow_status", WorkflowState),
        link_col("process", "process_id", Process, "process", match_field="name", multi=False),
    ],
))
