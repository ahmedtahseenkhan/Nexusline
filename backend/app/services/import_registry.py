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

from app.services.lifecycle_gates import (  # noqa: F401 - StateRule re-exported
    ACCESS_REVIEW_STATUS,
    DPIA_STATUS,
    ISSUE_STATUS,
    MODEL_STATUS,
    POLICY_STATUS,
    RISK_STATUS,
    StateRule,
)

from app.models.access_review import AccessReview
from app.models.asset import Asset, AssetClassification, AssetLabel, AssetMediaType, AssetTag
from app.models.bia import BiaAssessment, BiaStatus
from app.models.awareness import AwarenessProgram
from app.models.compliance import Framework, Requirement
from app.models.continuity import ContinuityPlan
from app.models.data_protection import (
    ConsentRecord,
    ConsentStatus,
    Dpia,
    DpiaWorkflowStatus,
    Dsar,
    DsarStatus,
    DsarType,
)
from app.models.control import Control
from app.models.evidence import Evidence
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.icfr import IcfrProcess, IcfrProcessStatus
from app.models.incident import Incident
from app.models.internal_audit import AuditEngagement, AuditFinding, AuditableUnit
from app.models.issue import Issue, IssueSource, IssueStatus2
from app.models.model_risk import ModelInventory, ModelStatus, ModelType
from app.models.operational_risk import BASEL_EVENT_TYPES_L2, KeyRiskIndicator, LossEvent, RcsaAssessment
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
from app.models.governance import Committee  # policies: approving authority
from app.models.identity import Role, User  # policies: roles; KRIs: data provider
from app.models.lookup import Lookup  # picked list values (countries, impact dimensions…)
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
from app.models.risk_scenario import RiskScenarioTemplate
from app.models.threat import Threat, Vulnerability
from app.models.vendor import Vendor, VendorType

# --- enums -----------------------------------------------------------------
from app.models.base import WorkflowState
from app.models.enums import (
    AccessReviewStatus,
    AssessmentStatus,
    AssetClass,
    AssetEnvironment,
    AuditEngagementStatus,
    AuditFindingStatus,
    AuditType,
    AwarenessStatus,
    BaselEventType,
    ComplianceStatus,
    ComplianceTreatment,
    ContinuityStatus,
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    Criticality,
    DiscoverySource,
    PciScope,
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
from app.schemas.asset import MAX_ASSET_TIER, AssetCreate, AssetDependencyCreate
from app.schemas.awareness import ProgramCreate
from app.schemas.bia import BiaCreate
from app.schemas.compliance import RequirementCreate
from app.schemas.continuity import PlanCreate
from app.schemas.data_protection import ConsentRecordCreate, DpiaCreate, DsarCreate
from app.schemas.control import ControlCreate
from app.schemas.evidence import EvidenceCreate
from app.schemas.exception import ExceptionCreate
from app.schemas.goal import GoalCreate
from app.schemas.icfr import IcfrProcessCreate
from app.schemas.incident import IncidentCreate
from app.schemas.internal_audit import EngagementCreate, FindingCreate
from app.schemas.issue import IssueImport
from app.schemas.model_risk import ModelCreate
from app.schemas.operational_risk import KriCreate, LossEventCreate, RcsaCreate
from app.schemas.organization import BusinessUnitCreate, LegalCreate, ProcessCreate
from app.schemas.outsourcing import OutsourcingArrangementCreate
from app.schemas.policy import PolicyCreate
from app.schemas.privacy import RopaCreate
from app.schemas.project import ProjectCreate
from app.schemas.regulatory_change import ObligationCreate, RegulatoryChangeCreate
from app.schemas.risk import RISK_SOURCES, RISK_TYPES, RISK_VELOCITIES, RiskCreate
from app.schemas.risk_scenario import ScenarioCreate
from app.schemas.threat import ThreatCreate, VulnerabilityCreate
from app.schemas.vendor import VendorCreate

# --- existing module create functions --------------------------------------
from app.api.v1.access_reviews import create_review
from app.api.v1.awareness import create_program
from app.api.v1.bia import create_bia
from app.api.v1.compliance import create_requirement
from app.api.v1.continuity import create_plan
from app.api.v1.data_protection import create_consent_record, create_dpia, create_dsar
from app.api.v1.controls import create_control
from app.api.v1.evidence import create_evidence
from app.api.v1.exceptions import create_exception
from app.api.v1.goals import create_goal
from app.api.v1.icfr import create_process as create_icfr_process
from app.api.v1.incidents import create_incident
from app.api.v1.internal_audit import create_engagement, create_finding
from app.api.v1.issues import import_issue
from app.api.v1.model_risk import create_model
from app.api.v1.operational_risk import create_kri, create_loss_event, create_rcsa
from app.api.v1.outsourcing import create_arrangement
from app.api.v1.assets import create_asset, create_dependency
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
from app.api.v1.risk_scenarios import create_scenario
from app.api.v1.threats import create_threat, create_vulnerability
from app.api.v1.vendors import create_vendor


# ---------------------------------------------------------------------------
# Spec dataclasses
# ---------------------------------------------------------------------------
#: How an export reads a link (``LinkSpec.via``).
VIA_RELATIONSHIP = "relationship"  # the ORM relationship ``export_attr`` on the model
VIA_COLUMN = "column"  # the model's own foreign-key column (``create_field``), no relationship
VIA_JOIN = "join"  # the join table behind the target's relationship back to the model


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
                      object(s) for export rendering. A dotted path follows one more
                      relationship per step (``hosted_dependencies.information_asset``).
    ``via``           where the export reads the link from. Every link column exports:
                      what the product exports must re-import to the same record.
                      ``relationship`` (default) reads ``export_attr``; ``column`` reads
                      the model's own foreign key (``create_field``) where the model has
                      no relationship for it (``BusinessUnit.parent_id``); ``join`` reads
                      the join table behind the *target's* relationship back to this
                      model (``Asset.legals`` gives ``Legal``'s assets).
    ``also_match``    further target attributes a cell may name (a user's full name
                      besides the email the export writes; a lookup's stored value
                      besides its label).
    ``scope``         ``(attribute, value)`` pairs every candidate must satisfy — one
                      lookup list out of the shared ``lookups`` table.
    ``label``         renders one target for export when neither its reference nor
                      ``match_field`` is unique on its own (an asset classification is
                      "Integrity: High", not "High"); the rendered text is indexed too.
    ``lenient``       an unmatched token is dropped with a row warning instead of
                      failing the row. For optional people pickers with no free-text
                      twin (a risk's owner): a legacy register's "Head of Ops (vacant)"
                      should not block the rest of the row.
    """

    target_model: type
    match_field: str
    multi: bool
    create_field: str
    export_attr: str
    via: str = VIA_RELATIONSHIP
    also_match: tuple[str, ...] = ()
    scope: tuple[tuple[str, Any], ...] = ()
    label: Callable[[Any], str] | None = None
    lenient: bool = False

    @property
    def exportable(self) -> bool:
        """True when the link renders through the ORM relationship ``export_attr``.

        Historical name, kept for the registry invariants: a ``column`` / ``join`` link
        has no relationship to check and renders through ``via`` instead."""
        return self.via == VIA_RELATIONSHIP


@dataclass(frozen=True)
class Column:
    """One spreadsheet column.

    ``export_value`` renders the cell from the record where the value is not a plain
    attribute (a dict, a derived timestamp). ``parse`` turns the cell text into the
    value the Create schema takes (``kind`` stays ``text``); it is given the link index
    when the column also carries a ``link`` used only to resolve names inside the cell.
    ``match_on_field`` False keeps the column-mapping wizard from matching a client's
    heading against the bare field name — a register's "Consequence" or "Level" column
    is a score, not our risk statement or hierarchy level — so only the header (and
    its synonyms) match.
    """

    header: str
    field: str
    required: bool = False
    kind: str = "text"  # text|int|float|bool|date|enum|link
    enum_values: list[str] | None = None
    help: str = ""
    link: LinkSpec | None = None
    export_value: Callable[[Any], Any] | None = None
    #: Async ``(db, records) -> {record id: cell}`` for a value that needs a query of
    #: its own (a risk's per-dimension impact scores); one call per export.
    export_batch: Callable[[Any, list[Any]], Awaitable[dict[Any, Any]]] | None = None
    parse: Callable[..., Any] | None = None
    match_on_field: bool = True


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
    #: Columns whose export is computed (``Column.export_value``) because the value is
    #: not an attribute of the model — an incident's notification time lives on its
    #: initial regulatory report. Importable like any other column; kept apart so the
    #: attribute columns above stay plain ``getattr`` reads.
    derived: list[Column] = field(default_factory=list)
    #: Extra export criteria, called at export time. Rows the importer could never take
    #: back (a finding of an archived audit) are left out rather than exported to fail.
    export_where: Callable[[], list[Any]] | None = None
    #: The register's own list filters, from the export request's query string
    #: (``{name: value}``) — so "export" exports the rows the user filtered to.
    export_filters: Callable[[dict[str, str]], list[Any]] | None = None
    #: Per-row adjustment of the import payload, before validation, for values the
    #: product derives and an export carries (a control's tested effectiveness). Returns
    #: the row warnings to report; runs in preview and import alike.
    prepare: Callable[[dict[str, Any]], list[str]] | None = None
    #: Status fields whose later values only a workflow action reaches (see StateRule).
    #: ``workflow_status`` gets its rule automatically (``_with_workflow_rule``).
    state_rules: tuple[StateRule, ...] = ()

    @property
    def all_columns(self) -> list[Column]:
        """Every spreadsheet column, attribute columns first."""
        return [*self.columns, *self.derived]


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
    via: str = VIA_RELATIONSHIP,
    also_match: tuple[str, ...] = (),
    scope: tuple[tuple[str, Any], ...] = (),
    label: Callable[[Any], str] | None = None,
    lenient: bool = False,
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
            via=via,
            also_match=also_match,
            scope=scope,
            label=label,
            lenient=lenient,
        ),
    )


def user_col(
    header: str,
    create_field: str,
    export_attr: str = "",
    *,
    via: str = VIA_COLUMN,
    lenient: bool = True,
    help: str = "",
) -> Column:
    """A person picked by id with no free-text twin (a risk's owner, a control's operator).

    Exports the user's email — unique, so it always resolves back — and accepts the
    email or full name on import. Lenient by default: an unmatched name is a row warning
    and the field stays empty, as for the text-backed people fields."""
    return link_col(
        header, create_field, User, export_attr or header, match_field="email", multi=False,
        via=via, also_match=("full_name",), lenient=lenient,
        help=help or "Email or full name of a user; unmatched text is skipped with a warning",
    )


def lookup_col(
    header: str,
    create_field: str,
    list_key: str,
    export_attr: str = "",
    *,
    multi: bool = False,
    via: str = VIA_COLUMN,
    help: str = "",
) -> Column:
    """A value picked from one list of the shared ``lookups`` table (countries, data
    classifications…). Exports the label; accepts the label or the stored value."""
    return link_col(
        header, create_field, Lookup, export_attr or header, match_field="label", multi=multi,
        via=via, also_match=("value",), scope=(("key", list_key),),
        help=help or f"Label from the {list_key.replace('_', ' ')} list"
        + ("; comma-separated" if multi else ""),
    )


# ---------------------------------------------------------------------------
# Cell renderers / parsers for values that are not a single scalar
# ---------------------------------------------------------------------------
def _iso_attributes_cell(control: Any) -> str:
    """``{"control_type": ["preventive"], …}`` as ``control_type: preventive; …``."""
    attrs = getattr(control, "iso27002_attributes", None) or {}
    return "; ".join(f"{key}: {' '.join(values)}" for key, values in attrs.items() if values)


def _parse_iso_attributes(text: str) -> dict[str, str]:
    """The reverse of :func:`_iso_attributes_cell`. Values stay a string per attribute:
    the Create schema normalises them (``#Asset_management`` and commas included) and
    names the first unknown attribute or value."""
    out: dict[str, str] = {}
    for part in text.split(";"):
        if not part.strip():
            continue
        key, sep, values = part.partition(":")
        if not sep:
            raise ValueError(
                f"iso27002_attributes: '{part.strip()}' needs the form 'attribute: value value'"
            )
        out[key.strip()] = values.strip()
    return out


def _ignore_derived_effectiveness(payload: dict[str, Any]) -> list[str]:
    """A control's effectiveness is derived from its reviewed tests; an export carries it.

    On import it is a manual override only when the row says why
    (``effectiveness_override_reason``). Without a reason the value is the source
    record's test result, which a new control does not have, so it is dropped (the
    control starts as not assessed) with a row warning rather than failing the row."""
    value = payload.get("effectiveness")
    if value is None or str(payload.get("effectiveness_override_reason") or "").strip():
        return []
    del payload["effectiveness"]
    if str(value) == ControlEffectiveness.not_assessed.value:
        return []
    return [
        f"effectiveness: '{value}' comes from reviewed tests, so the new control starts as "
        "not assessed. Give effectiveness_override_reason to set it by hand."
    ]


_BASES = ("inherent", "residual", "target")


def _dimension_scores_decide_impact(payload: dict[str, Any]) -> list[str]:
    """Where a row scores a basis per dimension, that basis' overall impact is derived
    from the dimension scores (the organisation's impact mode), so the row's own
    ``<basis>_impact`` is left out rather than contradicting them — a stored impact that
    has drifted from its dimensions would otherwise fail the row. The column's help says so; no per-row warning, as an exported file carries
    both on every such row."""
    bases = {d.get("basis") for d in payload.get("impact_dimensions") or ()}
    for basis in _BASES:
        if basis in bases:
            payload.pop(f"{basis}_impact", None)
    return []


#: What a risk takes from its assets and the rating computed from it: exported as
#: evidence, never imported — the asset register holds the value and tier, and the
#: platform multiplies.
_RISK_ASSET_COLUMNS = (
    "asset_value", "asset_tier", "inherent_business_impact", "inherent_business_rating",
    "residual_business_impact", "residual_business_rating",
)


def _risk_import_prepare(payload: dict[str, Any]) -> list[str]:
    for key in _RISK_ASSET_COLUMNS:
        payload.pop(key, None)
    return _dimension_scores_decide_impact(payload)


async def _risk_asset_table(db: Any, risks: list[Any]) -> dict[Any, dict[str, Any]]:
    """``risk id -> {column: cell}`` for :data:`_RISK_ASSET_COLUMNS`, computed once per
    export (the six columns share it through the session's ``info``)."""
    from sqlalchemy import select

    from app.models.risk import RiskSetting
    from app.services.risk_scoring import business_impact, is_scored
    from app.services.risk_settings import business_scale_for, load_asset_facts

    key = ("risk_asset_table", tuple(r.id for r in risks))
    cached = db.info.get("risk_asset_table")
    if cached is not None and cached[0] == key:
        return cached[1]
    facts = await load_asset_facts(db, [r.id for r in risks])
    settings = await db.scalar(select(RiskSetting))
    scale = business_scale_for(settings) if settings is not None else None
    table: dict[Any, dict[str, Any]] = {}
    for risk in risks:
        fact = facts.get(risk.id)
        row: dict[str, Any] = {
            "asset_value": fact.asset_value if fact else None,
            "asset_tier": fact.tier if fact else None,
        }
        if scale is not None and fact is not None and is_scored(risk.status, risk.last_assessed_at):
            for basis in ("inherent", "residual"):
                value = business_impact(getattr(risk, f"{basis}_score"), fact.asset_value)
                rating = scale.for_value(value)
                row[f"{basis}_business_impact"] = value
                row[f"{basis}_business_rating"] = rating.value if rating else None
        table[risk.id] = row
    db.info["risk_asset_table"] = (key, table)
    return table


def _risk_asset_column(name: str, help: str) -> Column:
    async def cells(db: Any, risks: list[Any]) -> dict[Any, Any]:
        table = await _risk_asset_table(db, risks)
        return {rid: ("" if row.get(name) is None else row[name]) for rid, row in table.items()}

    # Read-only, so it answers to its own heading only: a register's "Risk Value" is its
    # score, not a column to guess onto "asset_value" on a shared word.
    return Column(header=name, field=name, export_batch=cells, match_on_field=False,
                  help=f"{help} Computed by the platform (read-only): ignored on import.")


async def _impact_dimension_cells(db: Any, risks: list[Any]) -> dict[Any, str]:
    """``risk id -> "inherent: Financial=4, Reputational=3; residual: Financial=2"``."""
    from sqlalchemy import select

    from app.models.risk import RiskImpactDimension

    ids = [r.id for r in risks]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(RiskImpactDimension.risk_id, RiskImpactDimension.basis,
                   RiskImpactDimension.score, Lookup.label)
            .join(Lookup, Lookup.id == RiskImpactDimension.dimension_id)
            .where(RiskImpactDimension.risk_id.in_(ids))
            .order_by(Lookup.sort_order, Lookup.label)
        )
    ).all()
    grouped: dict[Any, dict[str, list[str]]] = {}
    for risk_id, basis, score, label in rows:
        grouped.setdefault(risk_id, {}).setdefault(basis, []).append(f"{label}={score}")
    return {
        risk_id: "; ".join(f"{b}: {', '.join(by_basis[b])}" for b in _BASES if b in by_basis)
        for risk_id, by_basis in grouped.items()
    }


def _parse_impact_dimensions(text: str, resolve: Callable[[str], Any]) -> list[dict[str, Any]]:
    """The reverse of :func:`_impact_dimension_cells`; ``resolve`` turns a dimension's
    label or value into its id (raising ``ValueError`` naming an unknown one)."""
    out: list[dict[str, Any]] = []
    for part in text.split(";"):
        if not part.strip():
            continue
        basis, sep, pairs = part.partition(":")
        basis = basis.strip().lower()
        if not sep or basis not in _BASES:
            raise ValueError(
                f"impact_dimensions: '{part.strip()}' should start with inherent:, residual: or target:"
            )
        for pair in pairs.split(","):
            if not pair.strip():
                continue
            name, eq, score = pair.rpartition("=")
            try:
                value = int(score.strip())
            except ValueError:
                value = None
            if not eq or not name.strip() or value is None:
                raise ValueError(f"impact_dimensions: '{pair.strip()}' should read Dimension=score")
            out.append({"dimension_id": resolve(name.strip()), "basis": basis, "score": value})
    return out


# ---------------------------------------------------------------------------
# REGISTRY
# ---------------------------------------------------------------------------
REGISTRY: dict[str, ResourceIO] = {}


def _register(res: ResourceIO) -> None:
    REGISTRY[res.resource] = _importing_workflow_status(_with_workflow_rule(_with_workflow_column(res)))


WORKFLOW_RULE = StateRule(
    field="workflow_status",
    later=frozenset({"in_review", "approved", "retired"}),
    initial="draft",
    how="Submit it for review after the import; an approver decides it here.",
    routed=True,
    always=frozenset({"in_review"}),
)


def _with_workflow_rule(res: ResourceIO) -> ResourceIO:
    """Every register with an approval lifecycle gates its imported ``workflow_status``."""
    if not any(c.field == "workflow_status" for c in res.all_columns):
        return res
    if any(r.field == "workflow_status" for r in res.state_rules):
        return res
    from dataclasses import replace

    return replace(res, state_rules=(*res.state_rules, WORKFLOW_RULE))


@dataclass(frozen=True)
class ImportGate:
    """The state rules of one resource, resolved for one importer (see StateRule).

    Built once per preview / import by :func:`import_gate`; :meth:`apply` is pure, so
    preview and import take exactly the same decision for every row."""

    decisions: tuple[tuple[StateRule, str], ...] = ()  # (rule, "" = may carry | why not)
    #: (live-only rule, the value a new record starts with) — lifecycle_gates.APPROVED_FIRST.
    approved_first: tuple[tuple[Any, str], ...] = ()

    def apply(self, payload: dict[str, Any]) -> list[str]:
        warnings = self._apply_decisions(payload)
        # Operational states that need the approval to exist (an outsourced service
        # "active", a model "in production"): judged after the row's own approval state
        # is settled above, exactly as an edit would be.
        approved = str(getattr(payload.get("workflow_status"), "value", payload.get("workflow_status")) or "")
        if approved != "approved":
            for rule, start in self.approved_first:
                raw = payload.get(rule.field)
                value = str(getattr(raw, "value", raw) or "")
                if value in rule.values:
                    payload[rule.field] = start
                    warnings.append(
                        f"{rule.field}: imported as '{start}', not '{value}' — {_a_noun(rule.noun)} "
                        f"can't be {value.replace('_', ' ')} before {rule.approval}."
                    )
        return warnings

    def _apply_decisions(self, payload: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for rule, blocked in self.decisions:
            raw = payload.get(rule.field)
            value = str(getattr(raw, "value", raw) or "")
            if value not in rule.later:
                continue
            if value in rule.always:
                reason = "an import cannot put a record into an approval route"
            elif blocked:
                reason = blocked
            else:
                continue
            payload[rule.field] = rule.initial
            dropped = [f for f in rule.clears if payload.pop(f, None) is not None]
            note = f" ({', '.join(dropped)} left blank)" if dropped else ""
            warnings.append(
                f"{rule.field}: imported as '{rule.initial}', not '{value}'{note} — {reason}. {rule.how}"
            )
        return warnings


async def import_gate(db: Any, res: ResourceIO, user: Any) -> ImportGate:
    """Resolve ``res.state_rules`` for ``user``: may they bring a record in past its
    initial state, i.e. could they have taken that decision alone in the app?"""
    from app.services import dual_control, record_workflow, workflow_engine
    from app.services.lifecycle_gates import APPROVED_FIRST
    from app.services.record_registry import entity_type_for_model

    entity_type = entity_type_for_model(res.model) or res.resource
    approved_first = tuple(
        (rule, _start_value(res, rule.field)) for rule in APPROVED_FIRST.get(entity_type, ())
    )
    if not res.state_rules:
        return ImportGate(approved_first=approved_first)
    held = set(getattr(user, "permission_codes", []) or [])
    decisions: list[tuple[StateRule, str]] = []
    for rule in res.state_rules:
        module = rule.module or entity_type
        needed = rule.permissions or record_workflow.required_permissions(module, "approve")
        blocked = ""
        if not set(needed) <= held:
            blocked = f"that takes approval rights ({', '.join(needed)})"
        if not blocked:
            for action in rule.four_eyes:
                required, _ = await dual_control.dual_control_required(db, module, action)
                if required:
                    blocked = (
                        "maker-checker applies, so the person importing a record cannot "
                        "also be the one who approves it"
                    )
                    break
        if not blocked and rule.routed and await workflow_engine.definition_for(db, entity_type):
            blocked = "these records go through a configured approval route"
        decisions.append((rule, blocked))
    return ImportGate(tuple(decisions), approved_first)


def _start_value(res: ResourceIO, field_name: str) -> str:
    """The value a record created through the form starts with (its Create default)."""
    default = res.create_schema.model_fields[field_name].default
    return str(getattr(default, "value", default) or "")


def _a_noun(noun: str) -> str:
    return f"an {noun}" if noun[:1].lower() in "aeiou" else f"a {noun}"


def _with_workflow_column(res: ResourceIO) -> ResourceIO:
    """Give every register with an approval lifecycle a ``workflow_status`` import column.

    The phase-1 registers dropped it when the state left their forms; a round-tripped
    export and a migration from a legacy tool still carry it (see
    :func:`_importing_workflow_status`, and :class:`StateRule` for who may import a
    record past Draft)."""
    column = res.model.__table__.c.get("workflow_status")
    enum_cls = getattr(getattr(column, "type", None), "enum_class", None)
    if enum_cls is None or any(c.field == "workflow_status" for c in res.columns):
        return res
    from dataclasses import replace

    return replace(res, columns=[*res.columns, enum_col("workflow_status", enum_cls)])


IMPORT_STATE_REFUSAL = (
    "Importing a record as '{state}' needs approval rights ({perms}). Import it as draft, "
    "or have someone who can approve {what} run the import."
)


def import_state_refusal(state: str, needed: tuple[str, ...], held: set[str], what: str) -> str | None:
    """Why this importer may not bring a record in at ``state``, or None. Pure.

    Draft is always fine. Anything past it is a claim that somebody approved the record;
    only a person who could approve it in the app may make that claim in bulk."""
    if state in ("", "draft") or set(needed).issubset(held):
        return None
    return IMPORT_STATE_REFUSAL.format(state=state, perms=", ".join(needed), what=what)


def _importing_workflow_status(res: ResourceIO) -> ResourceIO:
    """Keep ``workflow_status`` importable once it leaves the module's Create schema.

    The lifecycle state is no longer a form field (``services/record_workflow.py`` is
    the only thing that moves it), so Create schemas are dropping it. A CSV import is
    different: the column carries the state an export wrote, or a legacy tool's. Which
    states may come in is decided before this wrapper runs, by the resource's
    :class:`ImportGate` (``WORKFLOW_RULE``): past Draft only when the importer could have
    approved the record alone in the app — approval rights, no four-eyes rule and no
    approval route for the record type — which is how a single-operator installation
    migrates its approved records. Otherwise the row arrives as a draft with a warning.
    On *create* only, the row is validated against the Create schema plus
    ``workflow_status``, created through the module's own create function (all its rules
    apply), and a carried state is then written in an explicit
    ``record_workflow.system_write()`` block with an ``import_state`` audit entry. The
    approval-rights check below stays as a second line of defence for callers that
    bypass the gate. A resource whose Create schema still carries the field is left
    untouched.
    """
    if not any(c.field == "workflow_status" for c in res.columns):
        return res
    if "workflow_status" in res.create_schema.model_fields:
        return res
    column = res.model.__table__.c.get("workflow_status")
    enum_cls = getattr(getattr(column, "type", None), "enum_class", None)
    if enum_cls is None:
        return res

    from dataclasses import replace

    from pydantic import create_model

    base_schema, base_func, model = res.create_schema, res.create_func, res.model
    schema = create_model(
        f"{base_schema.__name__}Import",
        __base__=base_schema,
        workflow_status=(enum_cls | None, None),
    )

    async def create_func(*, body, db, user):
        state = getattr(body, "workflow_status", None)
        fields = {name: getattr(body, name) for name in base_schema.model_fields}
        base_body = base_schema.model_construct(
            _fields_set=set(body.model_fields_set) - {"workflow_status"}, **fields
        )
        from app.services import audit, record_workflow
        from app.services.record_registry import entity_type_for_model

        state_value = getattr(state, "value", state) or ""
        entity_type = entity_type_for_model(model)
        if state_value not in ("", "draft"):
            needed = (
                record_workflow.required_permissions(entity_type, "approve")
                if entity_type else ("workflow:approve",)
            )
            refusal = import_state_refusal(
                state_value, needed, set(getattr(user, "permission_codes", []) or []),
                (entity_type or "these records").replace("_", " ") + "s",
            )
            if refusal:
                raise ValueError(refusal)
        created = await base_func(body=base_body, db=db, user=user)
        if state is not None and state_value != "draft":
            record = await db.get(model, getattr(created, "id", None))
            if record is not None and state_value == "approved" and entity_type:
                # An approval carried in is still an approval: where the delegation-of-
                # authority matrix governs the record type, the importer's own mandate
                # must cover its amount, or the row stays a draft to be approved here.
                from app.services import authority_limits, ref_fields

                subject = await authority_limits.subject_for(db, entity_type, record)
                verdict = await authority_limits.verdict(db, subject, user) if subject else None
                if verdict is not None and not verdict.allowed:
                    ref_fields._warn(f"workflow_status: imported as 'draft', not 'approved' — {verdict.reason}")
                    return created
            if record is not None:
                # The business status that records the same decision follows (an
                # exception imported approved is approved, not pending).
                await record_workflow.carry_state(db, record, state_value)
                await audit.record(
                    db, actor=user, action="import_state", entity_type=entity_type or res.resource,
                    entity_id=record.id,
                    summary=f"Imported as {state_value} (state carried over from the source system)",
                )
        return created

    return replace(res, create_schema=schema, create_func=create_func)


# Phase 1 picked fields (risks, controls, policies, org registers, goals): the text
# column is matched onto the new key by the module's own create function
# (services.ref_fields) — exactly as the start-up backfill matches. Unmatched text is kept
# on the record as a note ("nothing typed is lost") and reported as a row warning rather
# than failing the row. ``workflow_owner`` is picked only (no text input), so it is not
# an import column.
_PERSON_HELP = "Email or full name of an active user; unmatched text is kept as a note"


def _pick_help(list_name: str) -> str:
    return f"Value or label from the {list_name} list; unmatched text is kept as a note"


# Issues, incidents, KRIs, loss events, RCSA and vendors resolve the same way through
# services.ref_fields, and also report each unmatched value as a row warning.
_UNIT_HELP = "Name of a business unit; unmatched text is kept as a note"
_CURRENCY_HELP = "ISO 4217 three-letter code such as PKR or USD"


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
        text("category", help=_pick_help("policy category")),
        enum_col("document_type", PolicyDocType),
        text("version"),
        enum_col("status", PolicyStatus),
        text("owner", help=_PERSON_HELP),
        enum_col("review_frequency", ReviewFrequency),
        # workflow_owner is picked only (workflow_owner_id), so it is not a column here.
        # workflow_status is appended by _with_workflow_column: importable on create,
        # past Draft only for a user who can approve (see _importing_workflow_status).
        link_col("controls", "controls_ids", Control, "controls", match_field="name"),
        link_col("requirements", "requirements_ids", Requirement, "requirements", match_field="title"),
        link_col("risks", "risks_ids", Risk, "risks", match_field="title"),
        link_col("related_policies", "related_ids", Policy, "related", match_field="title"),
        # Phase 2: governance and applicability.
        link_col("approving_authority", "approving_authority_id", Committee, "approving_authority",
                 match_field="name", multi=False, help="Reference or name of a committee (Governance)"),
        date_col("effective_date", help="Can't precede approval; empty = the publication date"),
        link_col("supersedes", "supersedes_id", Policy, "supersedes", match_field="title", multi=False,
                 help="Reference or title of the policy this one replaces (retired when this is published)"),
        link_col("business_units", "business_unit_ids", BusinessUnit, "business_units", match_field="name"),
        link_col("roles", "role_ids", Role, "roles", match_field="name",
                 help="Comma-separated role names; their members are asked to acknowledge the policy"),
        link_col("classification_label", "label_id", AssetLabel, "label", match_field="name", multi=False,
                 help="Information classification label, e.g. Internal or Confidential"),
        boolean("use_attachments", help="true when the policy text is an attached document"),
    ],
    # One rule for the form, the edit and the import (services.lifecycle_gates).
    state_rules=(POLICY_STATUS,),
))

# ----- risks ---------------------------------------------------------------
_register(ResourceIO(
    resource="risks", label="Risks", model=Risk,
    create_schema=RiskCreate, create_func=create_risk,
    read_perm="risk:read", write_perm="risk:write", importable=True,
    columns=[
        # A migrated register keeps its own identifiers; the parent_risk column matches them.
        text("reference", help="Your own risk ID; blank takes the next R-number. "
             "A reference a risk already carries is refused"),
        # Blank titles are composed from event / cause / consequence.
        text("title", help="Optional when event is given: composed from event and cause"),
        text("description"),
        text("cause", help="Risk statement: what could cause the event"),
        text("event", help="Risk statement: what could happen"),
        # In bank registers a "Consequence" heading is usually the impact score
        # (likelihood x consequence), so the statement column carries a heading of its own
        # and is never matched on its bare field name: the scores keep going to impact.
        Column(header="consequence_statement", field="consequence", match_on_field=False,
               help="Risk statement: what the event would lead to"),
        text("category", help=_pick_help("risk category")),
        Column(header="risk_type", field="risk_type", kind="enum", enum_values=list(RISK_TYPES)),
        Column(header="velocity", field="velocity", kind="enum", enum_values=list(RISK_VELOCITIES),
               help="How fast the impact is felt once the event happens"),
        Column(header="source", field="source", kind="enum", enum_values=list(RISK_SOURCES),
               help="Where the risk was identified"),
        date_col("identified_date"),
        user_col("identified_by", "identified_by_id",
                 help="Email or full name of the user who identified it; blank = the importer"),
        # The accountable owner. A risk leaves Draft only with one (services.risk_integrity).
        # Headed risk_owner, not owner: a register's "Process Owner" is not the risk owner.
        user_col("risk_owner", "owner_id", "owner", help="Email or full name of the risk owner (a user). "
                 "Needed for any status beyond draft; unmatched text is skipped with a warning"),
        enum_col("status", RiskStatus,
                 help="Any status beyond draft needs both inherent scores and an assessment_rationale"),
        # The scale is per-tenant (3x3 up to 10x10), so the help names the range the
        # organisation actually configured rather than a hard-coded 1-5.
        integer("inherent_likelihood", help="1 to your configured matrix size"),
        integer("inherent_impact", help="1 to your configured matrix size"),
        integer("residual_likelihood", help="1 to your configured matrix size (optional)"),
        integer("residual_impact", help="1 to your configured matrix size (optional)"),
        integer("target_likelihood", help="Where treatment should take it (optional; not above residual)"),
        integer("target_impact", help="Where treatment should take it (optional; not above residual)"),
        text("assessment_rationale", help="Why the scores are what they are"),
        text("residual_override_reason",
             help="Why the residual score is above the inherent (required in that case)"),
        enum_col("treatment_strategy", TreatmentStrategy),
        text("treatment_description"),
        text("treatment_owner", help=_PERSON_HELP),
        date_col("treatment_deadline"),
        number("treatment_cost"),
        number("annual_loss_frequency", help="FAIR: events per year"),
        number("single_loss_expectancy", help="FAIR: loss per event, in your organisation's currency"),
        enum_col("review_frequency", ReviewFrequency),
        # Phase 3 hierarchy: enterprise (1) > category (2) > scenario (3).
        link_col("parent_risk", "parent_id", Risk, "parent", match_field="title", multi=False,
                 via=VIA_COLUMN, help="Reference or title of the risk above this one"),
        Column(header="hierarchy_level", field="level", kind="int", match_on_field=False,
               help="1 enterprise, 2 category, 3 scenario; blank = one below the parent risk"),
        # Segment scoping. A bank's existing register almost always has a department or
        # process column already, so importing it should land the segment too rather
        # than making someone re-tag several hundred rows by hand.
        link_col("business_units", "business_unit_ids", BusinessUnit, "business_units",
                 match_field="name"),
        link_col("processes", "process_ids", Process, "processes", match_field="name"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("threats", "threat_ids", Threat, "threats", match_field="name"),
        link_col("vulnerabilities", "vulnerability_ids", Vulnerability, "vulnerabilities", match_field="name"),
        link_col("policies", "policy_ids", Policy, "policies", match_field="title"),
        link_col("incidents", "incident_ids", Incident, "incidents", match_field="title"),
    ],
    derived=[
        Column(header="impact_dimensions", field="impact_dimensions", parse=_parse_impact_dimensions,
               export_batch=_impact_dimension_cells,
               link=LinkSpec(target_model=Lookup, match_field="label", multi=False,
                             create_field="impact_dimensions", export_attr="impact_dimensions",
                             via=VIA_COLUMN, also_match=("value",), scope=(("key", "impact_dimension"),)),
               help="Impact per dimension as 'basis: Dimension=score, …; …', e.g. "
               "inherent: Financial=4, Reputational=3; residual: Financial=2. A basis scored "
               "here takes its overall impact from these scores (the impact column is ignored)"),
        _risk_asset_column("asset_value", "Highest value among the linked assets, 1 (low) to 4 (critical)."),
        _risk_asset_column("asset_tier", "Most critical service tier among the linked assets."),
        _risk_asset_column("inherent_business_impact", "Inherent score x asset value (asset-based rating)."),
        _risk_asset_column("inherent_business_rating", "Band of the inherent business impact."),
        _risk_asset_column("residual_business_impact", "Residual score x asset value (asset-based rating)."),
        _risk_asset_column("residual_business_rating", "Band of the residual business impact."),
    ],
    prepare=_risk_import_prepare,
    # Accepting a risk is a decision (request, then a holder of risk:accept decides).
    state_rules=(RISK_STATUS,),
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
        text("owner", help=_PERSON_HELP),
        user_col("operator", "operator_id", help="Email or full name of the user who performs "
                 "the control day to day; unmatched text is skipped with a warning"),
        enum_col("control_type", ControlType),
        text("classification", help=_pick_help("control classification")),
        text("documentation_url"),
        enum_col("status", ControlStatus),
        # Phase 2 attributes.
        Column(header="nature", field="nature", kind="enum",
               enum_values=["preventive", "detective", "corrective", "directive"]),
        Column(header="automation", field="automation", kind="enum",
               enum_values=["manual", "it_dependent_manual", "automated"]),
        boolean("is_key", help="Key control (true/false)"),
        Column(header="operating_frequency", field="operating_frequency", kind="enum",
               enum_values=["continuous", "daily", "weekly", "monthly", "quarterly", "semiannual",
                            "annual", "per_event", "ad_hoc"]),
        text("test_procedure"),
        text("evidence_expected"),
        Column(header="iso27002_attributes", field="iso27002_attributes",
               export_value=_iso_attributes_cell, parse=_parse_iso_attributes,
               help="ISO/IEC 27002:2022 attributes as 'attribute: value value; …', e.g. "
               "control_type: preventive; security_properties: confidentiality integrity"),
        # The export carries the rating the tests produced. Without an override reason it
        # is ignored on import — a new control has no reviewed tests, so it starts as not
        # assessed (see _ignore_derived_effectiveness) — rather than failing the row.
        enum_col("effectiveness", ControlEffectiveness,
                 help="Derived from reviewed tests and ignored on import unless "
                 "effectiveness_override_reason says why it is set by hand"),
        text("effectiveness_override_reason", help="Why the effectiveness is set by hand"),
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
        # Control has no `risks` relationship: exported from the risk_controls join table.
        link_col("risks", "risk_ids", Risk, "risks", match_field="title", via=VIA_JOIN),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("business_units", "business_unit_ids", BusinessUnit, "business_units", match_field="name"),
        link_col("processes", "process_ids", Process, "processes", match_field="name"),
    ],
    prepare=_ignore_derived_effectiveness,
))

# ----- assets --------------------------------------------------------------
# The single asset table backs two registers (ISO 27005 primary/supporting split),
# discriminated by `asset_class`. Each gets its own resource so the CSV headers match
# the register the user is loading, and so `fixed` stamps the class on every imported
# row — otherwise every import silently lands as information_asset (the column default).
def _asset_export_filters(params: dict[str, str]) -> list[Any]:
    """The register's list filters, from the export request's query string (the same
    names ``GET /assets`` takes), so an export carries exactly the rows on screen. A
    value that isn't one of the choices is refused rather than ignored."""
    from fastapi import HTTPException

    from app.api.v1.assets import asset_filters
    from app.models.enums import WorkflowStatus as _WS

    def choice(key: str, enum_cls: type[Enum]):
        raw = (params.get(key) or "").strip()
        if not raw:
            return None
        try:
            return enum_cls(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail=(
                f"'{raw}' is not a {key.replace('_', ' ')}. Use one of: {', '.join(_enum_vals(enum_cls))}."
            )) from None

    overdue = (params.get("review_overdue") or "").strip().lower()
    return asset_filters(
        search=(params.get("search") or "").strip() or None,
        review_overdue=overdue in ("1", "true", "yes"),
        environment=choice("environment", AssetEnvironment),
        effective_criticality=choice("effective_criticality", Criticality),
        workflow_status=choice("workflow_status", _WS),
        tier=_parse_tier(params["tier"]) if (params.get("tier") or "").strip() else None,
        pci_scope=choice("pci_scope", PciScope),
    )


def _parse_tier(text: str) -> int:
    """A tier cell as registers write it: ``1``, ``Tier 1``, ``T1``."""
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits or not 1 <= int(digits) <= MAX_ASSET_TIER:
        raise ValueError(f"tier: '{text.strip()}' is not a tier from 1 to {MAX_ASSET_TIER}")
    return int(digits)


_PCI_SCOPE_WORDS: dict[str, PciScope] = {
    "in_scope": PciScope.in_scope, "in scope": PciScope.in_scope, "yes": PciScope.in_scope,
    "y": PciScope.in_scope, "cde": PciScope.in_scope, "true": PciScope.in_scope,
    "connected": PciScope.connected, "connected to": PciScope.connected,
    "connected-to": PciScope.connected, "connected system": PciScope.connected,
    "out_of_scope": PciScope.out_of_scope, "out of scope": PciScope.out_of_scope,
    "no": PciScope.out_of_scope, "n": PciScope.out_of_scope, "false": PciScope.out_of_scope,
}


def _parse_pci_scope(text: str) -> PciScope | None:
    """A PCI scope cell: one of the three values, or the Yes / No a tracker usually holds.
    ``N/A`` and ``not assessed`` leave the asset unscoped."""
    word = " ".join(text.strip().lower().replace("-", " ").split())
    if word in ("n/a", "na", "not assessed", "tbd", "unknown"):
        return None
    scope = _PCI_SCOPE_WORDS.get(word) or _PCI_SCOPE_WORDS.get(word.replace(" ", "_"))
    if scope is None:
        raise ValueError(
            f"pci_scope: '{text.strip()}' is not one of {', '.join(_enum_vals(PciScope))} (or Yes / No)"
        )
    return scope


_ASSET_SHARED_COLUMNS = [
    text("name", required=True),
    text("description"),
    enum_col("confidentiality", Criticality),
    enum_col("integrity", Criticality),
    enum_col("availability", Criticality),
    text("potential_liabilities"),
    text("location"),
    Column(header="tier", field="tier", kind="int", parse=_parse_tier,
           help=f"Service tier, 1 (most critical) to {MAX_ASSET_TIER}; 'Tier 1' is read as 1"),
    Column(header="pci_scope", field="pci_scope", kind="enum", enum_values=_enum_vals(PciScope),
           parse=_parse_pci_scope,
           help="PCI DSS scope: in_scope (in the cardholder data environment), connected or "
           "out_of_scope; Yes / No are read as in_scope / out_of_scope; blank = not assessed"),
    integer("rto_hours", help="Recovery time objective, hours"),
    integer("rpo_hours", help="Recovery point objective, hours"),
    enum_col("review_frequency", ReviewFrequency),
    date_col("next_review_date"),
    enum_col("workflow_status", WorkflowStatus),
]

def _crit_cell(attr: str) -> Callable[[Any], str]:
    def cell(asset: Any) -> str:
        value = getattr(asset, attr, None)
        return str(getattr(value, "value", value) or "")
    return cell


#: The criticality the register shows, exported as evidence and never imported: it is
#: computed (an information asset's business value; an IT asset's cost band,
#: availability and hosted data), so a file cannot set it. The stored ``criticality``
#: column it replaces was an input no form set, and a workbook handed to an auditor
#: showed it in place of what the screen calls criticality.
_EFFECTIVE_CRITICALITY = Column(
    header="effective_criticality", field="effective_criticality",
    export_value=_crit_cell("effective_criticality"), match_on_field=False,
    help="Computed by the platform (read-only): ignored on import.",
)
_IT_CRITICALITY_INPUTS = [
    Column(header="intrinsic_criticality", field="intrinsic_criticality",
           export_value=_crit_cell("intrinsic_criticality"), match_on_field=False,
           help="Computed from replacement cost and availability (read-only): ignored on import."),
    Column(header="derived_criticality", field="derived_criticality",
           export_value=_crit_cell("derived_criticality"), match_on_field=False,
           help="Inherited from the information assets it hosts (read-only): ignored on import."),
]
_COMPUTED_CRITICALITY = ("effective_criticality", "intrinsic_criticality", "derived_criticality")


def _ignore_computed_criticality(payload: dict[str, Any]) -> list[str]:
    """Drop the exported, computed criticality columns from an import row: the platform
    derives them. An exported file carries them on every row, so no warning."""
    for key in _COMPUTED_CRITICALITY:
        payload.pop(key, None)
    return []


def _classification_label(value: Any) -> str:
    kind = getattr(getattr(value, "type", None), "name", "") or ""
    return f"{kind}: {value.name}" if kind else value.name


_ASSET_SHARED_LINKS = [
    link_col("media_type", "media_type_id", AssetMediaType, "media_type", multi=False,
             help="Asset type, e.g. Hardware, Software, Data Asset"),
    # RACI business units (owner / guardian / user), as on the form.
    link_col("owner_business_unit", "owner_id", BusinessUnit, "owner", multi=False,
             help="Business unit that owns the asset"),
    link_col("guardian_business_unit", "guardian_id", BusinessUnit, "guardian", multi=False,
             help="Business unit that looks after the asset"),
    link_col("user_business_unit", "user_id", BusinessUnit, "user", multi=False,
             help="Business unit that uses the asset"),
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
    derived=[_EFFECTIVE_CRITICALITY],
    prepare=_ignore_computed_criticality,
    export_filters=_asset_export_filters,
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
        link_col("classification_label", "label_id", AssetLabel, "label", multi=False,
                 help="Handling label, e.g. Internal, Confidential, Restricted"),
        link_col("classifications", "classification_ids", AssetClassification, "classifications",
                 label=_classification_label,
                 help="Comma-separated 'Axis: Value' pairs, e.g. Confidentiality: Restricted"),
        *_ASSET_SHARED_LINKS,
    ],
))

class ItAssetImport(AssetCreate):
    """AssetCreate plus the information assets the IT asset hosts — links the form makes
    one at a time through ``POST /assets/dependencies`` after the asset exists."""

    hosted_information_asset_ids: list[uuid.UUID] = []


async def _create_it_asset_import(body: ItAssetImport, db, user):
    created = await create_asset(
        body=AssetCreate.model_validate(body.model_dump(exclude={"hosted_information_asset_ids"})),
        db=db, user=user,
    )
    for info_id in dict.fromkeys(body.hosted_information_asset_ids):
        await create_dependency(
            AssetDependencyCreate(information_asset_id=info_id, it_asset_id=created.id),
            db=db, user=user,
        )
    return created


_register(ResourceIO(
    resource="it-assets", label="IT Assets", model=Asset,
    create_schema=ItAssetImport, create_func=_create_it_asset_import,
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
        text("currency", help=_CURRENCY_HELP),
        enum_col("discovery_source", DiscoverySource, help="Where the record came from"),
        text("external_id", help="Identifier in the source CMDB / discovery tool"),
        boolean("auto_discovered", help="true when a discovery tool found the asset"),
        date_col("last_seen", help="When the discovery tool last saw the asset"),
        link_col("tags", "tag_ids", AssetTag, "tags", help="Comma-separated operational tags"),
        *_ASSET_SHARED_LINKS,
    ],
    derived=[
        # An IT asset carries information assets (criticality inherits from the data).
        link_col("hosted_information_assets", "hosted_information_asset_ids", Asset,
                 "hosted_dependencies.information_asset",
                 scope=(("asset_class", AssetClass.information_asset),),
                 help="Comma-separated names of the information assets this asset hosts"),
        _EFFECTIVE_CRITICALITY,
        *_IT_CRITICALITY_INPUTS,
    ],
    prepare=_ignore_computed_criticality,
    export_filters=_asset_export_filters,
))

# ----- vendors -------------------------------------------------------------
_register(ResourceIO(
    resource="vendors", label="Vendors", model=Vendor,
    create_schema=VendorCreate, create_func=create_vendor,
    read_perm="vendor:read", write_perm="vendor:write", importable=True,
    columns=[
        text("name", required=True),
        text("description"),
        text("category", help=_pick_help("third-party category")),
        link_col("type", "type_id", VendorType, "type", multi=False,
                 help="Third-party type, e.g. Cloud Provider, Processor, Supplier"),
        text("legal_name", help="Registered legal name, if different from the trading name"),
        text("registration_number", help="SECP / company registration number"),
        number("annual_spend"),
        text("spend_currency", help="ISO 4217 code such as PKR or USD; blank means the organisation's currency"),
        text("contact_name"),
        text("contact_email"),
        text("contact_phone"),
        text("website"),
        # City or address, free text; the country is picked from the country list.
        text("location", help="City or street address (free text)"),
        lookup_col("country", "country_id", "country"),
        lookup_col("data_classification", "data_classification_id", "data_classification",
                   help="Highest classification of bank data the third party accesses"),
        user_col("relationship_owner", "relationship_owner_id",
                 help="Email or full name of the bank's accountable owner of the relationship"),
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
        # workflow_status: appended by _with_workflow_column (see policies).
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("requirements", "requirement_ids", Requirement, "requirements", match_field="title"),
        link_col("processes", "process_ids", Process, "processes", match_field="name",
                 help="Business processes this third party supports"),
        link_col("subcontractors", "subcontractor_ids", Vendor, "subcontractors", match_field="name",
                 help="The third party's own sub-contractors (fourth parties), from the vendor register"),
        lookup_col("data_residency_countries", "data_residency_country_ids", "country",
                   "data_residency_countries", multi=True, via=VIA_RELATIONSHIP,
                   help="Countries where the third party stores or processes our data; comma-separated"),
    ],
))

# ----- incidents -----------------------------------------------------------
_INCIDENT_TS_HELP = (
    "YYYY-MM-DD (taken as 00:00 in the organisation's timezone) or an ISO date-time, "
    "e.g. 2026-09-01T14:30 or 2026-09-01T14:30:00+05:00"
)


def _notification_clock(incident: Any) -> Any:
    """The regulator-notification position, for a reportable incident only: the import
    records a notification on the initial report, which only a reportable incident has."""
    from app.services import incident_clock

    if not getattr(incident, "is_reportable", False):
        return None
    return incident_clock.notification_clock(incident.regulatory_reports)


def _incident_notified_at(incident: Any) -> Any:
    clock = _notification_clock(incident)
    return clock.notified_at if clock else None


def _incident_regulator_reference(incident: Any) -> str:
    clock = _notification_clock(incident)
    return (clock.regulator_reference or "") if clock else ""

_register(ResourceIO(
    resource="incidents", label="Incidents", model=Incident,
    create_schema=IncidentCreate, create_func=create_incident,
    read_perm="incident:read", write_perm="incident:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        text("category", help=_pick_help("incident type")),
        text("classification", help=_pick_help("incident classification")),
        enum_col("severity", Severity),
        enum_col("status", IncidentStatus),
        text("assignee", help=_PERSON_HELP),
        text("reported_by", help=_PERSON_HELP),
        text("impact"),
        text("root_cause"),
        text("lessons_learned"),
        number("cost"),
        # Phase 2: timestamps. Text columns so a full ISO date-time reaches the schema
        # intact; a bare date is 00:00 in the organisation's timezone (api.v1.incidents).
        text("occurred_at", help=_INCIDENT_TS_HELP),
        text("detected_at", help=_INCIDENT_TS_HELP),
        text("contained_at", help=_INCIDENT_TS_HELP),
        text("resolved_at", help=_INCIDENT_TS_HELP),
        integer("customers_affected"),
        integer("records_affected"),
        boolean("near_miss", help="true when nothing was lost (leave cost blank)"),
        boolean("personal_data_breach", help="true opens a linked data-breach record"),
        boolean("is_reportable", help="true creates the regulator's initial and final reports"),
        text("regulator", help=_pick_help("regulator")),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("vendors", "vendor_ids", Vendor, "vendors", match_field="name"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
    ],
    # Stored on the incident's initial regulatory report, not the incident itself.
    derived=[
        Column(header="notified_at", field="notified_at", export_value=_incident_notified_at,
               help="When the regulator was notified (marks the initial report submitted). "
               + _INCIDENT_TS_HELP),
        Column(header="regulator_reference", field="regulator_reference",
               export_value=_incident_regulator_reference,
               help="The regulator's acknowledgement reference"),
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
        number("exposure_amount", help="Exposure the exception leaves uncovered (checked against "
               "the approver's delegation-of-authority mandate)"),
        text("exposure_currency", help=_CURRENCY_HELP + "; blank = the organisation's reporting currency"),
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
        text("category", help=_pick_help("legal category")),
        text("jurisdiction"),
        # Legal.reference is a real user-supplied column (regulatory reference).
        text("reference", help="Regulatory reference / citation"),
        text("countries", help="Comma-separated list of applicable countries"),
        number("risk_magnifier", help="Amplifies linked risk scores (default 1.0)"),
        link_col("business_units", "business_unit_ids", BusinessUnit, "business_units", match_field="name"),
        # Legal has no `assets` relationship: exported from the assets_legals join table.
        link_col("assets", "asset_ids", Asset, "assets", match_field="name", via=VIA_JOIN),
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
        text("manager", help=_PERSON_HELP),
        text("email"),
        text("location"),
        # BusinessUnit exposes its parent only as the parent_id foreign key.
        link_col("parent", "parent_id", BusinessUnit, "parent", match_field="name", multi=False,
                 via=VIA_COLUMN, help="Parent business unit name (single value)"),
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
        text("owner", help=_PERSON_HELP),
        enum_col("criticality", Criticality),
        integer("rto_hours", help="Recovery Time Objective (hours)"),
        integer("rpo_hours", help="Recovery Point Objective (hours)"),
        integer("rpd_hours", help="Max tolerable downtime (hours)"),
        link_col("business_unit", "business_unit_id", BusinessUnit, "business_unit", match_field="name", multi=False,
                 help="Owning business unit name (single value)"),
        # Process has no `assets` relationship: exported from the assets_processes join table.
        link_col("assets", "asset_ids", Asset, "assets", match_field="name", via=VIA_JOIN),
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
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
    ],
))

# ----- audit findings -------------------------------------------------------
# An external firm or a regulator hands over a finding list; this loads it into the same
# remediation pipeline internal findings already run through.
_register(ResourceIO(
    resource="audit-findings", label="Audit Findings", model=AuditFinding,
    create_schema=FindingCreate, create_func=create_finding,
    read_perm="internal_audit:read", write_perm="internal_audit:write", importable=True,
    columns=[
        Column(header="engagement", field="engagement_id", required=True, kind="link",
               help="Reference or title of the audit this finding belongs to",
               link=LinkSpec(target_model=AuditEngagement, match_field="title", multi=False,
                             create_field="engagement_id", export_attr="engagement")),
        text("title", required=True),
        text("description"),
        enum_col("rating", Severity),
        text("risk_implication"),
        text("recommendation"),
        text("management_response"),
        text("action_owner"),
        date_col("due_date"),
        enum_col("status", AuditFindingStatus),
        date_col("closed_date"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("requirements", "requirement_ids", Requirement, "requirements", match_field="title"),
    ],
    # A finding of an archived audit cannot be imported (its engagement no longer
    # resolves), so it is not exported either; archiving the audit archived its findings.
    export_where=lambda: [AuditFinding.engagement.has(AuditEngagement.deleted.is_(False))],
))

# ----- risk scenario library ------------------------------------------------
_register(ResourceIO(
    resource="risk-scenarios", label="Risk Scenarios", model=RiskScenarioTemplate,
    create_schema=ScenarioCreate, create_func=create_scenario,
    read_perm="risk:read", write_perm="risk:write", importable=True,
    columns=[
        text("reference", help="Blank to auto-number (RS-001, RS-002, ...)"),
        text("title", required=True, help="Use {asset} where the asset name should appear"),
        text("description"),
        text("category"),
        text("asset_classes", help="information_asset and/or it_asset, comma-separated; blank = all assets"),
        text("asset_kinds", help="Comma-separated asset kinds the scenario applies to "
             "(GET /risk-scenarios/asset-kinds); blank = every kind"),
        text("threat"),
        text("vulnerability"),
        integer("likelihood", help="1-5 base likelihood; rescaled to your matrix"),
        text("impact_rule", help="from_criticality | from_business_value | from_cia_max | from_property | fixed"),
        text("impact_property", help="confidentiality | integrity | availability (with impact_rule=from_property)"),
        integer("fixed_impact", help="1-5, only with impact_rule=fixed"),
        text("treatment_hint"),
        text("control_references", help="Comma-separated control references that treat the scenario"),
        boolean("enabled"),
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
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
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
        text("owner", help=_PERSON_HELP),
        enum_col("status", GoalStatus),
        text("audit_metric"),
        text("success_criteria"),
        enum_col("audit_frequency", ReviewFrequency),
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
        # Data-subject rights: how each is honoured for this activity.
        text("right_to_be_informed"),
        text("right_to_access"),
        text("right_to_rectification"),
        text("right_to_erasure"),
        text("right_to_object"),
        text("right_to_portability"),
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

# ----- data protection: DPIAs, DSARs, consent ledger -------------------------
# The DPO's operational registers (Pakistan PDPA readiness). Each goes through the
# module's own create: references are numbered, a DSAR without a due date gets the
# statutory 30 days from receipt.
_register(ResourceIO(
    resource="dpias", label="Data Protection Impact Assessments", model=Dpia,
    create_schema=DpiaCreate, create_func=create_dpia,
    read_perm="dpo:read", write_perm="dpo:write", importable=True,
    state_rules=(DPIA_STATUS,),
    columns=[
        text("title", required=True),
        text("processing_activity", help="Name of the processing activity assessed"),
        text("description"),
        text("necessity_justification"),
        text("risks_identified"),
        text("mitigations"),
        enum_col("residual_risk", Criticality),
        enum_col("status", DpiaWorkflowStatus),
        text("owner"),
        text("dpo_reviewer"),
        date_col("review_date"),
        # workflow_status: appended by _with_workflow_column (see policies).
    ],
))

_register(ResourceIO(
    resource="dsars", label="Data Subject Requests", model=Dsar,
    create_schema=DsarCreate, create_func=create_dsar,
    read_perm="dpo:read", write_perm="dpo:write", importable=True,
    columns=[
        text("subject_name"),
        text("subject_contact"),
        enum_col("request_type", DsarType),
        date_col("received_date", help="Starts the response clock"),
        date_col("due_date", help="Blank = the statutory deadline from the received date"),
        date_col("response_date"),
        text("handler"),
        text("notes"),
        enum_col("status", DsarStatus),
    ],
))

_register(ResourceIO(
    resource="consent-records", label="Consent Records", model=ConsentRecord,
    create_schema=ConsentRecordCreate, create_func=create_consent_record,
    read_perm="dpo:read", write_perm="dpo:write", importable=True,
    columns=[
        text("subject_name"),
        text("purpose"),
        boolean("consent_given"),
        date_col("consent_date"),
        date_col("withdrawal_date"),
        text("channel", help="Where consent was captured, e.g. branch form, mobile app"),
        enum_col("lawful_basis", LawfulBasis),
        enum_col("status", ConsentStatus),
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
        link_col("business_impact_analysis", "bia_id", BiaAssessment, "bia_assessment",
                 match_field="process_name", multi=False,
                 help="Reference or process name of the BIA this plan answers"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
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
        Column(header="framework", field="framework_id", required=True, kind="link",
               help="Name of the framework this requirement belongs to",
               link=LinkSpec(target_model=Framework, match_field="name", multi=False,
                             create_field="framework_id", export_attr="framework")),
        text("title", required=True),
        text("reference", help="Requirement reference, e.g. A.5.1 / CC6.1"),
        text("domain"),
        text("description"),
        text("implementation", help="How we comply"),
        text("audit_questionnaire", help="How to test compliance"),
        enum_col("status", ComplianceStatus),
        enum_col("treatment", ComplianceTreatment),
        text("applicability_justification", help="Why the requirement is (not) applicable"),
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
        Column(header="control", field="control_id", required=True, kind="link",
               help="Reference or name of the control this evidence supports",
               link=LinkSpec(target_model=Control, match_field="name", multi=False,
                             create_field="control_id", export_attr="control")),
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
    # A completed review is the sign-off on decisions an import does not bring.
    state_rules=(ACCESS_REVIEW_STATUS,),
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
    create_schema=IssueImport, create_func=import_issue,
    read_perm="issue:read", write_perm="issue:write", importable=True,
    columns=[
        text("title", required=True),
        text("description"),
        enum_col("source_type", IssueSource),
        text("source_reference", help="Reference of the finding/audit that raised this"),
        text("category", help=_pick_help("issue category")),
        enum_col("severity", Severity),
        enum_col("status", IssueStatus2),
        text("owner", help=_PERSON_HELP),
        text("business_unit", help=_UNIT_HELP),
        date_col("identified_date"),
        date_col("due_date"),
        # Import only: a closed row keeps its closed date (needs approval rights, see
        # api.v1.issues.import_issue); in the app the server sets it on Close.
        date_col("closed_date", help="Only for rows imported closed; set by the server otherwise"),
        text("root_cause"),
        lookup_col("root_cause_category", "root_cause_category_id", "root_cause_category"),
        text("management_response"),
        boolean("repeat_finding"),
        boolean("regulator_related"),
        link_col("risks", "risk_ids", Risk, "risks", match_field="title"),
        link_col("controls", "control_ids", Control, "controls", match_field="name"),
        link_col("requirements", "requirement_ids", Requirement, "requirements", match_field="title"),
        link_col("assets", "asset_ids", Asset, "assets", match_field="name"),
        link_col("third_parties", "vendor_ids", Vendor, "vendors", match_field="name"),
    ],
    state_rules=(ISSUE_STATUS,),
))

# ----- operational risk: RCSA ----------------------------------------------
_register(ResourceIO(
    resource="rcsa-assessments", label="RCSA Assessments", model=RcsaAssessment,
    create_schema=RcsaCreate, create_func=create_rcsa,
    read_perm="oprisk:read", write_perm="oprisk:write", importable=True,
    columns=[
        text("title", required=True),
        text("business_unit", help=_UNIT_HELP),
        text("process", help="Name of a process; unmatched text is kept as a note"),
        text("assessor", help=_PERSON_HELP),
        enum_col("status", RcsaStatus),
        text("period", help="e.g. FY2026-Q1"),
        date_col("due_date"),
        date_col("completed_date"),
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
        text("category", help=_pick_help("KRI category")),
        text("business_area", help=_UNIT_HELP),
        text("owner", help=_PERSON_HELP),
        text("unit", help="Unit of measure, e.g. %, count, PKR"),
        enum_col("frequency", ReviewFrequency),
        enum_col("direction", KriDirection),
        number("warning_threshold", help="Amber; below the limit when higher is worse, above it when lower is worse; empty for within_range"),
        number("limit_threshold", help="Red; for within_range, the tolerance beyond the range"),
        # Phase 2 (F-14): definition, lineage and the within-range band.
        number("lower_bound", help="within_range only: lowest acceptable value"),
        number("upper_bound", help="within_range only: highest acceptable value"),
        number("current_value"),
        date_col("last_measured_date"),
        text("definition"),
        text("numerator"),
        text("denominator"),
        text("data_source"),
        link_col("data_provider", "data_provider_id", User, "data_provider", match_field="email",
                 multi=False, help="Email of the user who supplies the value"),
        Column(header="indicator_type", field="indicator_type", kind="enum",
               enum_values=["leading", "lagging"]),
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
        Column(header="basel_event_type_l2", field="basel_event_type_l2", kind="enum",
               enum_values=[k for k, *_ in BASEL_EVENT_TYPES_L2],
               help="Basel II level-2 category; must belong to basel_event_type. Blank = not categorised"),
        text("business_line", help=_UNIT_HELP),
        number("gross_loss"),
        number("recovery"),
        text("currency", help="ISO 4217 code such as USD; blank = the organisation's reporting currency"),
        enum_col("status", LossEventStatus),
        date_col("occurrence_date"),
        date_col("discovery_date"),
        date_col("accounting_date"),
        text("root_cause"),
        text("action_owner", help=_PERSON_HELP),
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
        enum_col("audit_type", AuditType, help="Who performed the audit"),
        text("auditor_firm", help="Audit firm or regulator"),
        text("report_reference"),
        date_col("report_date"),
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
    state_rules=(MODEL_STATUS,),
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
        number("contract_value", help="Total contract value, in contract_currency"),
        text("contract_currency", help="ISO 4217 code such as USD; blank = the organisation's reporting currency"),
        text("exit_plan"),
        boolean("exit_plan_tested"),
        text("concentration_note"),
        text("substitutability", help="easy / moderate / difficult / none. Required with the materiality "
             "assessment and exit plan before a material arrangement can be active"),
        text("concentration_level", help="low / medium / high"),
        enum_col("status", OutsourcingStatus),
        text("owner"),
        enum_col("workflow_status", WorkflowState),
        # OutsourcingArrangement holds vendor_id with no relationship: read off the column.
        link_col("vendor", "vendor_id", Vendor, "vendor", match_field="name", multi=False,
                 via=VIA_COLUMN),
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
        text("currency", help=_CURRENCY_HELP),
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


# ----- decision 4: exchange rates into the reporting currency ------------------
# Banks keep rates in a treasury spreadsheet (or copy the SBP weighted-average customer
# rates); importing the same file again updates the rates in place (upsert on currency +
# effective date) instead of failing row by row.
from app.api.v1.fx_rates import upsert_rate  # noqa: E402
from app.models.fx import FxRate  # noqa: E402
from app.schemas.fx import FxRateCreate  # noqa: E402

_register(ResourceIO(
    resource="fx-rates", label="Exchange Rates", model=FxRate,
    create_schema=FxRateCreate, create_func=upsert_rate,
    read_perm="settings:manage", write_perm="settings:manage", importable=True,
    columns=[
        text("currency", required=True, help="ISO 4217 code of the foreign currency, e.g. USD"),
        Column(header="rate", field="rate_to_reporting", required=True, kind="float",
               help="Units of the reporting currency for 1 unit of the currency, e.g. 278.45"),
        Column(header="effective_date", field="effective_date", required=True, kind="date",
               help="YYYY-MM-DD; the rate applies to amounts dated on or after it"),
        text("source", help="e.g. SBP weighted-average customer rate"),
    ],
))
