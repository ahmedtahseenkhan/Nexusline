"""Report builder — the subject registry, and the query each subject compiles to.

A report is a question: *which* records (filters), *shown how* (columns, sort), *summed
up how* (breakdowns). Every module used to answer that with one hard-coded export. This
module makes the answer declarative — each **subject** (risks, controls, incidents)
registers its filters, its columns and its summaries, and the UI, the on-screen run,
the PDF and the Excel are all generated from that one declaration. Adding a fourth
subject is adding a fourth entry here, not a fourth page.

Two rules that shape the design:

* **Filters compile to SQL.** Saved filters evaluate conditions in Python per record,
  which is fine for a few hundred rows and useless for a bank's full register. Every
  filter below becomes a ``WHERE`` clause, so a report over 50,000 risks costs one
  query with a ``LIMIT``, not a table scan into Python.
* **Nothing here talks to the database.** Building a ``Select`` is pure; loading rows and
  resolving names is the API's job. That keeps every subject unit-testable by compiling
  the statement and reading the SQL.

Filter values arrive as JSON — strings, lists of strings, or booleans — and are coerced
leniently: an empty value means "not filtered", an unknown key is ignored, so a report
somebody saved before a filter was retired still runs.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.control import Control, control_assets
from app.models.enums import (
    ControlEffectiveness,
    ControlStatus,
    ControlType,
    IncidentStatus,
    RiskStatus,
    Severity,
    TreatmentStrategy,
)
from app.models.identity import User
from app.models.incident import Incident, incident_controls
from app.models.organization import BusinessUnit, Process
from app.models.risk import Risk, risk_assets, risk_controls
from app.services.risk_query import build_risk_query
from app.services.risk_scoring import appetite_status, band_ranges, severity_for_score

# ---------------------------------------------------------------------------
# Context and specs
# ---------------------------------------------------------------------------
@dataclass
class ReportContext:
    """What a subject needs beyond the rows: the tenant's methodology, today's date,
    and the display names the API resolved for id-valued filters and for owners."""

    org_name: str = ""
    appetite: int = 6
    tolerance: int = 12
    max_score: int = 25
    matrix_size: int = 5
    today: date = field(default_factory=date.today)
    #: id (as str) -> display name, for filters that hold ids and for owner columns.
    names: dict[str, str] = field(default_factory=dict)
    #: Per-subject prefetched extras (counts, lookups), keyed by the subject's choice.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FilterSpec:
    key: str
    label: str
    #: select | multiselect | typeahead | date | bool | text
    kind: str
    #: For select/multiselect: [{"value", "label"}].
    options: tuple[dict, ...] = ()
    #: For typeahead: the list endpoint the UI searches ("assets", "users", ...).
    source: str = ""
    help: str = ""


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    #: In the default column set when a report does not choose.
    default: bool
    #: Relative width hint for the PDF; scaled to the page.
    width: int
    #: Value for a row, given the ORM object and the context. Plain str/int/float/None.
    get: Callable[[Any, ReportContext], Any]
    #: SQL expression the column may be sorted by; None means not sortable.
    sort: Any = None


@dataclass
class Subject:
    key: str
    label: str
    model: type
    read_perm: str
    columns: list[ColumnSpec]
    filters: list[FilterSpec]
    apply_filters: Callable[[Select, dict, ReportContext], Select]
    default_sort: str
    default_sort_dir: str
    #: Breakdown counts over the *whole* matching set, e.g. {"By severity": {...}}.
    summarize: Callable[[list, ReportContext], dict[str, dict[str, int]]]
    #: Populate ``ctx.names`` / ``ctx.extra`` for the rows about to be rendered.
    prefetch: Callable[[AsyncSession, list, ReportContext], Awaitable[None]] | None = None
    #: The subject has a per-record detail page the PDF can append.
    has_detail: bool = False

    @property
    def column_map(self) -> dict[str, ColumnSpec]:
        return {c.key: c for c in self.columns}

    @property
    def filter_map(self) -> dict[str, FilterSpec]:
        return {f.key: f for f in self.filters}


# ---------------------------------------------------------------------------
# Coercion — JSON in, typed values out, empties meaning "not filtered"
# ---------------------------------------------------------------------------
def _list(value: Any) -> list[str]:
    if value is None or value == "" or value == []:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)]


def _uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _bool(value: Any) -> bool | None:
    """Tri-state: True / False / "any" (None)."""
    if value in (None, "", "any"):
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _enum_options(enum_cls) -> tuple[dict, ...]:
    return tuple({"value": m.value, "label": m.value.replace("_", " ").title()} for m in enum_cls)


_SEVERITY_OPTIONS = _enum_options(Severity)
_APPETITE_OPTIONS = (
    {"value": "within_appetite", "label": "Within appetite"},
    {"value": "elevated", "label": "Elevated"},
    {"value": "breach", "label": "Breach"},
)
_BOOL_OPTIONS = ({"value": "true", "label": "Yes"}, {"value": "false", "label": "No"})


# ---------------------------------------------------------------------------
# Shared cell helpers
# ---------------------------------------------------------------------------
def _d(value) -> str:
    return value.isoformat() if isinstance(value, date) else ("" if value is None else str(value))


def _names(items, attr: str = "name") -> str:
    return ", ".join(getattr(i, attr, "") or "" for i in (items or []))


def _enum(value) -> str:
    return value.value.replace("_", " ").title() if value is not None else ""


def _money(value) -> str:
    return f"{value:,.2f}" if value not in (None, "") else ""


def _score_bands(score_col, chosen: list[str], max_score: int):
    """OR of ``score BETWEEN low AND high`` for each chosen severity band.

    Bands are derived from the tenant's matrix, so "critical" means 15-25 on a 5x5 and
    57-100 on a 10x10 — the same words the heat map uses.
    """
    wanted = {c for c in chosen}
    clauses = [
        score_col.between(low, high)
        for low, high, sev in band_ranges(max_score)
        if sev.value in wanted
    ]
    return or_(*clauses) if clauses else None


# ===========================================================================
# Subject: risks
# ===========================================================================
_RISK_EFFECTIVE = func.coalesce(Risk.residual_score, Risk.inherent_score)


def _risk_filters(stmt: Select, f: dict, ctx: ReportContext) -> Select:
    # The register's own filter first, so a report and the screen agree by construction.
    stmt = build_risk_query(
        category=_text(f.get("category")) or None,
        business_unit_id=_uuid(f.get("business_unit_id")),
        process_id=_uuid(f.get("process_id")),
        asset_id=_uuid(f.get("asset_id")),
        search=_text(f.get("search")) or None,
    )

    statuses = _list(f.get("status"))
    if statuses:
        stmt = stmt.where(Risk.status.in_([RiskStatus(s) for s in statuses if s in RiskStatus.__members__]))

    strategies = _list(f.get("treatment_strategy"))
    if strategies:
        stmt = stmt.where(Risk.treatment_strategy.in_(
            [TreatmentStrategy(s) for s in strategies if s in TreatmentStrategy.__members__]
        ))

    owner = _uuid(f.get("owner_id"))
    if owner is not None:
        stmt = stmt.where(Risk.owner_id == owner)

    inh = _score_bands(Risk.inherent_score, _list(f.get("inherent_severity")), ctx.max_score)
    if inh is not None:
        stmt = stmt.where(inh)
    res = _score_bands(Risk.residual_score, _list(f.get("residual_severity")), ctx.max_score)
    if res is not None:
        stmt = stmt.where(res)

    appetite = _list(f.get("appetite_status"))
    if appetite:
        clauses = []
        if "within_appetite" in appetite:
            clauses.append(_RISK_EFFECTIVE <= ctx.appetite)
        if "elevated" in appetite:
            clauses.append((_RISK_EFFECTIVE > ctx.appetite) & (_RISK_EFFECTIVE <= ctx.tolerance))
        if "breach" in appetite:
            clauses.append(_RISK_EFFECTIVE > ctx.tolerance)
        if clauses:
            stmt = stmt.where(or_(*clauses))

    created_from, created_to = _date(f.get("created_from")), _date(f.get("created_to"))
    if created_from:
        stmt = stmt.where(func.date(Risk.created_at) >= created_from)
    if created_to:
        stmt = stmt.where(func.date(Risk.created_at) <= created_to)

    review_from, review_to = _date(f.get("review_from")), _date(f.get("review_to"))
    if review_from:
        stmt = stmt.where(Risk.next_review_date >= review_from)
    if review_to:
        stmt = stmt.where(Risk.next_review_date <= review_to)

    overdue = _bool(f.get("review_overdue"))
    if overdue is True:
        stmt = stmt.where(Risk.next_review_date < ctx.today)
    elif overdue is False:
        stmt = stmt.where(or_(Risk.next_review_date.is_(None), Risk.next_review_date >= ctx.today))

    has_controls = _bool(f.get("has_controls"))
    if has_controls is not None:
        linked = select(risk_controls.c.risk_id).where(risk_controls.c.risk_id == Risk.id).exists()
        stmt = stmt.where(linked if has_controls else ~linked)

    return stmt


def _risk_severity(score, ctx: ReportContext) -> str:
    band = severity_for_score(score, ctx.max_score)
    return band.value.title() if band else ""


def _risk_appetite(risk, ctx: ReportContext) -> str:
    eff = risk.residual_score if risk.residual_score is not None else risk.inherent_score
    status = appetite_status(eff, ctx.appetite, ctx.tolerance)
    return {"within_appetite": "Within appetite", "elevated": "Elevated", "breach": "Breach"}.get(status or "", "")


def _owner(obj, ctx: ReportContext) -> str:
    return ctx.names.get(str(obj.owner_id), "") if obj.owner_id else ""


async def _risk_prefetch(db: AsyncSession, rows: list, ctx: ReportContext) -> None:
    ids = {r.owner_id for r in rows if r.owner_id}
    if ids:
        for user in (await db.scalars(select(User).where(User.id.in_(ids)))).all():
            ctx.names[str(user.id)] = user.full_name or user.email


def _risk_summary(rows: list, ctx: ReportContext) -> dict[str, dict[str, int]]:
    by_sev: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_appetite: dict[str, int] = {}
    for r in rows:
        eff = r.residual_score if r.residual_score is not None else r.inherent_score
        sev = _risk_severity(eff, ctx) or "Unscored"
        by_sev[sev] = by_sev.get(sev, 0) + 1
        st = _enum(r.status)
        by_status[st] = by_status.get(st, 0) + 1
        ap = _risk_appetite(r, ctx) or "—"
        by_appetite[ap] = by_appetite.get(ap, 0) + 1
    return {"By severity": by_sev, "By status": by_status, "Against appetite": by_appetite}


RISKS = Subject(
    key="risks",
    label="Risks",
    model=Risk,
    read_perm="risk:read",
    default_sort="inherent",
    default_sort_dir="desc",
    has_detail=True,
    columns=[
        ColumnSpec("reference", "Ref", True, 8, lambda r, c: r.reference, Risk.reference),
        ColumnSpec("title", "Risk", True, 26, lambda r, c: r.title, Risk.title),
        ColumnSpec("category", "Category", True, 12, lambda r, c: r.category, Risk.category),
        ColumnSpec("status", "Status", True, 10, lambda r, c: _enum(r.status), Risk.status),
        ColumnSpec("owner", "Owner", True, 12, _owner),
        ColumnSpec("business_units", "Business units", True, 14, lambda r, c: _names(r.business_units)),
        ColumnSpec("processes", "Processes", False, 14, lambda r, c: _names(r.processes)),
        ColumnSpec("assets", "Assets", False, 16, lambda r, c: _names(r.assets)),
        ColumnSpec("controls", "Controls", False, 16, lambda r, c: _names(r.controls)),
        ColumnSpec("control_count", "Ctrls", False, 5, lambda r, c: len(r.controls or []), None),
        ColumnSpec("inherent", "Inherent", True, 9,
                   lambda r, c: f"{r.inherent_likelihood}x{r.inherent_impact}={r.inherent_score}",
                   Risk.inherent_score),
        ColumnSpec("inherent_severity", "Inh. severity", True, 9,
                   lambda r, c: _risk_severity(r.inherent_score, c), Risk.inherent_score),
        ColumnSpec("residual", "Residual", True, 9,
                   lambda r, c: (f"{r.residual_likelihood}x{r.residual_impact}={r.residual_score}"
                                 if r.residual_score is not None else ""),
                   Risk.residual_score),
        ColumnSpec("residual_severity", "Res. severity", True, 9,
                   lambda r, c: _risk_severity(r.residual_score, c), Risk.residual_score),
        ColumnSpec("appetite", "Appetite", True, 10, _risk_appetite),
        ColumnSpec("treatment_strategy", "Treatment", False, 9, lambda r, c: _enum(r.treatment_strategy),
                   Risk.treatment_strategy),
        ColumnSpec("treatment_owner", "Treatment owner", False, 12, lambda r, c: r.treatment_owner),
        ColumnSpec("treatment_deadline", "Deadline", False, 9, lambda r, c: _d(r.treatment_deadline),
                   Risk.treatment_deadline),
        ColumnSpec("annual_loss_expectancy", "ALE", False, 10, lambda r, c: _money(r.annual_loss_expectancy),
                   Risk.annual_loss_expectancy),
        ColumnSpec("next_review_date", "Next review", True, 9, lambda r, c: _d(r.next_review_date),
                   Risk.next_review_date),
        ColumnSpec("last_review_date", "Last review", False, 9, lambda r, c: _d(r.last_review_date),
                   Risk.last_review_date),
        ColumnSpec("created_at", "Created", False, 9, lambda r, c: _d(r.created_at.date() if r.created_at else None),
                   Risk.created_at),
        ColumnSpec("description", "Description", False, 30, lambda r, c: r.description),
    ],
    filters=[
        FilterSpec("business_unit_id", "Business unit", "typeahead", source="business-units"),
        FilterSpec("process_id", "Process", "typeahead", source="processes"),
        FilterSpec("asset_id", "Asset", "typeahead", source="assets"),
        FilterSpec("owner_id", "Risk owner", "typeahead", source="users"),
        FilterSpec("category", "Category", "text", help="Contains match."),
        FilterSpec("status", "Status", "multiselect", options=_enum_options(RiskStatus)),
        FilterSpec("inherent_severity", "Inherent severity", "multiselect", options=_SEVERITY_OPTIONS,
                   help="Bands follow your matrix."),
        FilterSpec("residual_severity", "Residual severity", "multiselect", options=_SEVERITY_OPTIONS),
        FilterSpec("appetite_status", "Against appetite", "multiselect", options=_APPETITE_OPTIONS,
                   help="Residual where assessed, otherwise inherent."),
        FilterSpec("treatment_strategy", "Treatment strategy", "multiselect",
                   options=_enum_options(TreatmentStrategy)),
        FilterSpec("has_controls", "Has controls", "bool", options=_BOOL_OPTIONS),
        FilterSpec("review_overdue", "Review overdue", "bool", options=_BOOL_OPTIONS),
        FilterSpec("review_from", "Next review from", "date"),
        FilterSpec("review_to", "Next review to", "date"),
        FilterSpec("created_from", "Created from", "date"),
        FilterSpec("created_to", "Created to", "date"),
        FilterSpec("search", "Search", "text", help="Title or reference."),
    ],
    apply_filters=_risk_filters,
    summarize=_risk_summary,
    prefetch=_risk_prefetch,
)


# ===========================================================================
# Subject: controls
# ===========================================================================
def _control_filters(stmt: Select, f: dict, ctx: ReportContext) -> Select:
    statuses = _list(f.get("status"))
    if statuses:
        stmt = stmt.where(Control.status.in_([ControlStatus(s) for s in statuses if s in ControlStatus.__members__]))
    eff = _list(f.get("effectiveness"))
    if eff:
        stmt = stmt.where(Control.effectiveness.in_(
            [ControlEffectiveness(s) for s in eff if s in ControlEffectiveness.__members__]
        ))
    ctype = _text(f.get("control_type"))
    if ctype in ControlType.__members__:
        stmt = stmt.where(Control.control_type == ControlType(ctype))
    owner = _text(f.get("owner"))
    if owner:
        stmt = stmt.where(Control.owner.ilike(f"%{owner}%"))
    classification = _text(f.get("classification"))
    if classification:
        stmt = stmt.where(Control.classification.ilike(f"%{classification}%"))

    risk_id = _uuid(f.get("risk_id"))
    if risk_id is not None:
        stmt = stmt.where(
            select(risk_controls.c.control_id)
            .where(risk_controls.c.control_id == Control.id, risk_controls.c.risk_id == risk_id)
            .exists()
        )
    asset_id = _uuid(f.get("asset_id"))
    if asset_id is not None:
        stmt = stmt.where(
            select(control_assets.c.control_id)
            .where(control_assets.c.control_id == Control.id, control_assets.c.asset_id == asset_id)
            .exists()
        )

    overdue = _bool(f.get("audit_overdue"))
    if overdue is True:
        stmt = stmt.where(Control.next_audit_date < ctx.today)
    elif overdue is False:
        stmt = stmt.where(or_(Control.next_audit_date.is_(None), Control.next_audit_date >= ctx.today))

    audit_from, audit_to = _date(f.get("audit_from")), _date(f.get("audit_to"))
    if audit_from:
        stmt = stmt.where(Control.next_audit_date >= audit_from)
    if audit_to:
        stmt = stmt.where(Control.next_audit_date <= audit_to)

    search = _text(f.get("search"))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Control.name.ilike(like) | Control.reference.ilike(like))
    return stmt


async def _control_prefetch(db: AsyncSession, rows: list, ctx: ReportContext) -> None:
    """How many live risks each control mitigates — the join is write-only on the ORM."""
    ids = [c.id for c in rows]
    if not ids:
        return
    counts = (
        await db.execute(
            select(risk_controls.c.control_id, func.count())
            .join(Risk, Risk.id == risk_controls.c.risk_id)
            .where(risk_controls.c.control_id.in_(ids), Risk.deleted.is_(False))
            .group_by(risk_controls.c.control_id)
        )
    ).all()
    ctx.extra["risk_counts"] = {str(cid): n for cid, n in counts}


def _control_summary(rows: list, ctx: ReportContext) -> dict[str, dict[str, int]]:
    by_eff: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for c in rows:
        e = _enum(c.effectiveness) or "Not assessed"
        by_eff[e] = by_eff.get(e, 0) + 1
        s = _enum(c.status)
        by_status[s] = by_status.get(s, 0) + 1
    return {"By effectiveness": by_eff, "By status": by_status}


CONTROLS = Subject(
    key="controls",
    label="Controls",
    model=Control,
    read_perm="control:read",
    default_sort="reference",
    default_sort_dir="asc",
    columns=[
        ColumnSpec("reference", "Ref", True, 8, lambda c, x: c.reference, Control.reference),
        ColumnSpec("name", "Control", True, 26, lambda c, x: c.name, Control.name),
        ColumnSpec("control_type", "Type", True, 8, lambda c, x: _enum(c.control_type), Control.control_type),
        ColumnSpec("status", "Status", True, 10, lambda c, x: _enum(c.status), Control.status),
        ColumnSpec("effectiveness", "Effectiveness", True, 11, lambda c, x: _enum(c.effectiveness),
                   Control.effectiveness),
        ColumnSpec("owner", "Owner", True, 12, lambda c, x: c.owner, Control.owner),
        ColumnSpec("classification", "Classification", False, 12, lambda c, x: c.classification,
                   Control.classification),
        ColumnSpec("risk_count", "Risks", True, 6,
                   lambda c, x: x.extra.get("risk_counts", {}).get(str(c.id), 0)),
        ColumnSpec("assets", "Protected assets", False, 16, lambda c, x: _names(c.assets)),
        ColumnSpec("policies", "Policies", False, 14, lambda c, x: _names(c.policies, "title")),
        ColumnSpec("audit_frequency", "Test cycle", False, 8, lambda c, x: _enum(c.audit_frequency)),
        ColumnSpec("last_audit_date", "Last tested", True, 9, lambda c, x: _d(c.last_audit_date),
                   Control.last_audit_date),
        ColumnSpec("next_audit_date", "Next test", True, 9, lambda c, x: _d(c.next_audit_date),
                   Control.next_audit_date),
        ColumnSpec("next_maintenance_date", "Next maintenance", False, 9,
                   lambda c, x: _d(c.next_maintenance_date), Control.next_maintenance_date),
        ColumnSpec("opex", "Opex / yr", False, 9, lambda c, x: _money(c.opex), Control.opex),
        ColumnSpec("capex", "Capex", False, 9, lambda c, x: _money(c.capex), Control.capex),
        ColumnSpec("created_at", "Created", False, 9,
                   lambda c, x: _d(c.created_at.date() if c.created_at else None), Control.created_at),
        ColumnSpec("objective", "Objective", False, 30, lambda c, x: c.objective),
    ],
    filters=[
        FilterSpec("status", "Status", "multiselect", options=_enum_options(ControlStatus)),
        FilterSpec("effectiveness", "Effectiveness", "multiselect", options=_enum_options(ControlEffectiveness)),
        FilterSpec("control_type", "Type", "select", options=_enum_options(ControlType)),
        FilterSpec("owner", "Owner", "text", help="Contains match."),
        FilterSpec("classification", "Classification", "text"),
        FilterSpec("risk_id", "Mitigates risk", "typeahead", source="risks"),
        FilterSpec("asset_id", "Protects asset", "typeahead", source="assets"),
        FilterSpec("audit_overdue", "Test overdue", "bool", options=_BOOL_OPTIONS),
        FilterSpec("audit_from", "Next test from", "date"),
        FilterSpec("audit_to", "Next test to", "date"),
        FilterSpec("search", "Search", "text", help="Name or reference."),
    ],
    apply_filters=_control_filters,
    summarize=_control_summary,
    prefetch=_control_prefetch,
)


# ===========================================================================
# Subject: incidents
# ===========================================================================
def _incident_filters(stmt: Select, f: dict, ctx: ReportContext) -> Select:
    statuses = _list(f.get("status"))
    if statuses:
        stmt = stmt.where(Incident.status.in_(
            [IncidentStatus(s) for s in statuses if s in IncidentStatus.__members__]
        ))
    sev = _list(f.get("severity"))
    if sev:
        stmt = stmt.where(Incident.severity.in_([Severity(s) for s in sev if s in Severity.__members__]))
    category = _text(f.get("category"))
    if category:
        stmt = stmt.where(Incident.category.ilike(f"%{category}%"))
    assignee = _text(f.get("assignee"))
    if assignee:
        stmt = stmt.where(Incident.assignee.ilike(f"%{assignee}%"))

    reportable = _bool(f.get("is_reportable"))
    if reportable is not None:
        stmt = stmt.where(Incident.is_reportable.is_(reportable))
    resolved = _bool(f.get("resolved"))
    if resolved is True:
        stmt = stmt.where(Incident.resolved_at.is_not(None))
    elif resolved is False:
        stmt = stmt.where(Incident.resolved_at.is_(None))

    for key, col in (("occurred", Incident.occurred_at), ("detected", Incident.detected_at)):
        lo, hi = _date(f.get(f"{key}_from")), _date(f.get(f"{key}_to"))
        if lo:
            stmt = stmt.where(col >= lo)
        if hi:
            stmt = stmt.where(col <= hi)

    asset_id = _uuid(f.get("asset_id"))
    if asset_id is not None:
        from app.models.asset import assets_incidents

        stmt = stmt.where(
            select(assets_incidents.c.incident_id)
            .where(assets_incidents.c.incident_id == Incident.id, assets_incidents.c.asset_id == asset_id)
            .exists()
        )
    control_id = _uuid(f.get("control_id"))
    if control_id is not None:
        stmt = stmt.where(
            select(incident_controls.c.incident_id)
            .where(incident_controls.c.incident_id == Incident.id, incident_controls.c.control_id == control_id)
            .exists()
        )

    search = _text(f.get("search"))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Incident.title.ilike(like) | Incident.reference.ilike(like))
    return stmt


def _incident_summary(rows: list, ctx: ReportContext) -> dict[str, dict[str, int]]:
    by_sev: dict[str, int] = {}
    by_status: dict[str, int] = {}
    reportable = {"Reportable": 0, "Not reportable": 0}
    for i in rows:
        s = _enum(i.severity)
        by_sev[s] = by_sev.get(s, 0) + 1
        st = _enum(i.status)
        by_status[st] = by_status.get(st, 0) + 1
        reportable["Reportable" if i.is_reportable else "Not reportable"] += 1
    return {"By severity": by_sev, "By status": by_status, "Regulatory": reportable}


INCIDENTS = Subject(
    key="incidents",
    label="Incidents",
    model=Incident,
    read_perm="incident:read",
    default_sort="occurred_at",
    default_sort_dir="desc",
    columns=[
        ColumnSpec("reference", "Ref", True, 8, lambda i, x: i.reference, Incident.reference),
        ColumnSpec("title", "Incident", True, 24, lambda i, x: i.title, Incident.title),
        ColumnSpec("category", "Category", True, 11, lambda i, x: i.category, Incident.category),
        ColumnSpec("severity", "Severity", True, 8, lambda i, x: _enum(i.severity), Incident.severity),
        ColumnSpec("status", "Status", True, 9, lambda i, x: _enum(i.status), Incident.status),
        ColumnSpec("assignee", "Assignee", True, 11, lambda i, x: i.assignee, Incident.assignee),
        ColumnSpec("reported_by", "Reported by", False, 11, lambda i, x: i.reported_by),
        ColumnSpec("occurred_at", "Occurred", True, 9, lambda i, x: _d(i.occurred_at), Incident.occurred_at),
        ColumnSpec("detected_at", "Detected", False, 9, lambda i, x: _d(i.detected_at), Incident.detected_at),
        ColumnSpec("resolved_at", "Resolved", True, 9, lambda i, x: _d(i.resolved_at), Incident.resolved_at),
        ColumnSpec("is_reportable", "Reportable", True, 8, lambda i, x: "Yes" if i.is_reportable else "No",
                   Incident.is_reportable),
        ColumnSpec("regulator", "Regulator", False, 10, lambda i, x: i.regulator),
        ColumnSpec("cost", "Cost", False, 9, lambda i, x: _money(i.cost), Incident.cost),
        ColumnSpec("assets", "Assets", False, 16, lambda i, x: _names(i.assets)),
        ColumnSpec("risks", "Risks", False, 14, lambda i, x: _names(i.risks, "reference")),
        ColumnSpec("controls", "Controls", False, 16, lambda i, x: _names(i.controls)),
        ColumnSpec("root_cause", "Root cause", False, 24, lambda i, x: i.root_cause),
        ColumnSpec("created_at", "Logged", False, 9,
                   lambda i, x: _d(i.created_at.date() if i.created_at else None), Incident.created_at),
    ],
    filters=[
        FilterSpec("status", "Status", "multiselect", options=_enum_options(IncidentStatus)),
        FilterSpec("severity", "Severity", "multiselect", options=_SEVERITY_OPTIONS),
        FilterSpec("category", "Category", "text", help="Contains match."),
        FilterSpec("assignee", "Assignee", "text"),
        FilterSpec("is_reportable", "Regulator-reportable", "bool", options=_BOOL_OPTIONS),
        FilterSpec("resolved", "Resolved", "bool", options=_BOOL_OPTIONS),
        FilterSpec("asset_id", "Affects asset", "typeahead", source="assets"),
        FilterSpec("control_id", "Control that failed", "typeahead", source="controls"),
        FilterSpec("occurred_from", "Occurred from", "date"),
        FilterSpec("occurred_to", "Occurred to", "date"),
        FilterSpec("detected_from", "Detected from", "date"),
        FilterSpec("detected_to", "Detected to", "date"),
        FilterSpec("search", "Search", "text", help="Title or reference."),
    ],
    apply_filters=_incident_filters,
    summarize=_incident_summary,
)


# ===========================================================================
# Registry and the operations every caller shares
# ===========================================================================
SUBJECTS: dict[str, Subject] = {s.key: s for s in (RISKS, CONTROLS, INCIDENTS)}

#: Which model an id-valued filter refers to, for resolving a name on the cover page.
_ID_MODELS: dict[str, type] = {
    "business_unit_id": BusinessUnit,
    "process_id": Process,
    "asset_id": Asset,
    "owner_id": User,
    "risk_id": Risk,
    "control_id": Control,
}


def get_subject(key: str) -> Subject:
    try:
        return SUBJECTS[key]
    except KeyError:
        raise KeyError(f"Unknown report subject '{key}'") from None


def catalog() -> list[dict]:
    """The registry as the UI consumes it — nothing about a subject is hard-coded there."""
    out = []
    for s in SUBJECTS.values():
        out.append({
            "key": s.key,
            "label": s.label,
            "has_detail": s.has_detail,
            "default_sort": s.default_sort,
            "default_sort_dir": s.default_sort_dir,
            "columns": [
                {"key": c.key, "label": c.label, "default": c.default, "sortable": c.sort is not None}
                for c in s.columns
            ],
            "filters": [
                {"key": f.key, "label": f.label, "kind": f.kind, "options": list(f.options),
                 "source": f.source, "help": f.help}
                for f in s.filters
            ],
        })
    return out


def selected_columns(subject: Subject, keys: list[str] | None) -> list[ColumnSpec]:
    """The chosen columns in the order chosen; unknown keys are dropped rather than
    failing, so a report saved before a column was retired still runs. No choice means
    the subject's default set."""
    cmap = subject.column_map
    chosen = [cmap[k] for k in (keys or []) if k in cmap]
    return chosen or [c for c in subject.columns if c.default]


def build_statement(subject: Subject, filters: dict | None, ctx: ReportContext) -> Select:
    model = subject.model
    stmt: Select = select(model)
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    return subject.apply_filters(stmt, filters or {}, ctx)


def apply_sort(subject: Subject, stmt: Select, sort_by: str | None, sort_dir: str | None) -> Select:
    """Sort by a sortable column, falling back to the subject's default rather than
    erroring — a saved report must survive a column losing its sort expression."""
    cmap = subject.column_map
    col = cmap.get(sort_by or "")
    if col is None or col.sort is None:
        col = cmap[subject.default_sort]
        sort_dir = sort_dir or subject.default_sort_dir
    direction = (sort_dir or subject.default_sort_dir).lower()
    expr = col.sort.desc() if direction == "desc" else col.sort.asc()
    return stmt.order_by(expr, subject.model.id)


def render_rows(subject: Subject, columns: list[ColumnSpec], objs: list, ctx: ReportContext) -> list[dict]:
    return [{"id": str(o.id), "cells": {c.key: c.get(o, ctx) for c in columns}} for o in objs]


def id_filter_models(subject: Subject, filters: dict | None) -> list[tuple[str, type, uuid.UUID]]:
    """(filter key, model, id) for every id-valued filter actually set — the API resolves
    these to names so the cover page can say "Internet Banking", not a UUID."""
    out = []
    for key, value in (filters or {}).items():
        model = _ID_MODELS.get(key)
        ident = _uuid(value)
        if model is not None and ident is not None and key in subject.filter_map:
            out.append((key, model, ident))
    return out


def describe_filters(subject: Subject, filters: dict | None, ctx: ReportContext) -> list[tuple[str, str]]:
    """Human-readable (label, value) for every filter that is set, in registry order.

    Printed on the PDF cover and the Excel Parameters sheet: a filtered report that does
    not say how it was filtered is indistinguishable from the whole register.
    """
    out: list[tuple[str, str]] = []
    f = filters or {}
    for spec in subject.filters:
        raw = f.get(spec.key)
        if raw in (None, "", [], "any"):
            continue
        if spec.kind == "typeahead":
            value = ctx.names.get(str(raw), str(raw))
        elif spec.kind in ("select", "multiselect", "bool"):
            labels = {o["value"]: o["label"] for o in spec.options}
            value = ", ".join(labels.get(v, v) for v in _list(raw))
        elif spec.kind == "date":
            value = _d(_date(raw))
        else:
            value = _text(raw)
        if value:
            out.append((spec.label, value))
    return out
