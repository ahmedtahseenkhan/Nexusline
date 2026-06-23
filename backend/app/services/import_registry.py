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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.models.asset import Asset
from app.models.compliance import Requirement
from app.models.continuity import ContinuityPlan
from app.models.control import Control
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.incident import Incident
from app.models.organization import BusinessUnit, Legal, Process
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.risk import Risk
from app.models.threat import Threat, Vulnerability
from app.models.vendor import Vendor

# --- enums -----------------------------------------------------------------
from app.models.base import WorkflowState
from app.models.enums import (
    AssessmentStatus,
    ContinuityStatus,
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    Criticality,
    DpiaStatus,
    ExceptionType,
    GoalStatus,
    IncidentStatus,
    LawfulBasis,
    PolicyDocType,
    PolicyStatus,
    ProjectStatus,
    ReviewFrequency,
    RiskStatus,
    RopaStatus,
    Severity,
    TreatmentStrategy,
    VendorStatus,
    WorkflowStatus,
)

# --- Create schemas --------------------------------------------------------
from app.schemas.asset import AssetCreate
from app.schemas.continuity import PlanCreate
from app.schemas.control import ControlCreate
from app.schemas.exception import ExceptionCreate
from app.schemas.goal import GoalCreate
from app.schemas.incident import IncidentCreate
from app.schemas.organization import BusinessUnitCreate, LegalCreate, ProcessCreate
from app.schemas.policy import PolicyCreate
from app.schemas.privacy import RopaCreate
from app.schemas.project import ProjectCreate
from app.schemas.risk import RiskCreate
from app.schemas.threat import ThreatCreate, VulnerabilityCreate
from app.schemas.vendor import VendorCreate

# --- existing module create functions --------------------------------------
from app.api.v1.continuity import create_plan
from app.api.v1.controls import create_control
from app.api.v1.exceptions import create_exception
from app.api.v1.goals import create_goal
from app.api.v1.incidents import create_incident
from app.api.v1.assets import create_asset
from app.api.v1.organization import (
    create_business_unit,
    create_legal,
    create_process,
)
from app.api.v1.policies import create_policy
from app.api.v1.privacy import create_ropa
from app.api.v1.projects import create_project
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
    resource: str
    label: str
    model: type
    create_schema: type
    create_func: Callable[..., Awaitable[Any]]
    read_perm: str
    write_perm: str
    importable: bool
    columns: list[Column] = field(default_factory=list)


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
_register(ResourceIO(
    resource="assets", label="Assets", model=Asset,
    create_schema=AssetCreate, create_func=create_asset,
    read_perm="asset:read", write_perm="asset:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        enum_col("confidentiality", Criticality),
        enum_col("integrity", Criticality),
        enum_col("availability", Criticality),
        enum_col("criticality", Criticality),
        text("potential_liabilities"),
        enum_col("review_frequency", ReviewFrequency),
        date_col("next_review_date"),
        enum_col("workflow_status", WorkflowStatus),
        link_col("processes", "process_ids", Process, "processes", match_field="name"),
        link_col("legals", "legal_ids", Legal, "legals", match_field="name"),
        link_col("requirements", "requirement_ids", Requirement, "requirements", match_field="title"),
        link_col("incidents", "incident_ids", Incident, "incidents", match_field="title"),
        link_col("exceptions", "exception_ids", ExceptionRecord, "exceptions", match_field="title"),
        link_col("related_assets", "related_ids", Asset, "related_assets", match_field="name"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
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
