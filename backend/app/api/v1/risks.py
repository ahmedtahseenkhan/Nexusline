"""Risk Management API — the reference module.

Covers the full lifecycle: register CRUD, inherent/residual scoring, treatment,
control/asset linkage, a risk-acceptance approval workflow with expiry, and review
scheduling.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import aliased

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.asset import Asset
from app.models.control import Control, ControlAudit
from app.models.incident import Incident
from app.models.issue import Issue, IssueStatus2, issue_controls
from app.models.policy import Policy
from app.models.enums import (
    AcceptanceStatus,
    RiskStatus,
    TreatmentStrategy,
)
from app.models.organization import BusinessUnit, Process
from app.models.risk import (
    Risk,
    RiskAcceptance,
    RiskImpactDimension,
    RiskTreatmentAction,
    risk_assets,
)
from app.services.risk_query import UNPLACED, build_risk_query  # noqa: F401 - re-exported for callers
from app.models.threat import Threat, Vulnerability
from app.schemas.common import GraphRef, Page
from app.schemas.control import ControlAssuranceRef
from app.schemas.risk import (
    OrphanedRisk,
    OrphanedRiskPage,
    OrphanPurgeRequest,
    OrphanPurgeResult,
    ResidualAcceptance,
    RiskAcceptanceCreate,
    RiskAcceptanceDecision,
    RiskAcceptanceRead,
    ImpactDimensionRead,
    RiskAssessment,
    RiskCreate,
    RiskHierarchy,
    RiskHierarchyNode,
    RiskRead,
    RiskRollup,
    RiskUpdate,
    SuggestedResidual,
    TreatmentActionCreate,
    TreatmentActionRead,
    TreatmentActionUpdate,
    TreatmentProgress,
    UNTESTED_CREDIT_NOTE_NEEDED,
)
from app.db.data_repairs import RESIDUAL_REVIEW_REASON
from app.services.refs import next_reference
from app.services import audit
from app.services import control_assurance
from app.services import delete_guard
from app.services import master_data
from app.services import dual_control
from app.services import ref_fields
from app.services import risk_hierarchy
from app.services import risk_integrity
from app.services.residual_engine import ControlInput, suggest_residual
from app.services import notifications
from app.services.risk_scoring import (
    SeverityScale,
    current_severity,
    effective_review_frequency,
    next_review_date,
    rescheduled_review,
)
from app.services.risk_settings import (
    get_matrix_size,
    get_max_score,  # noqa: F401 - kept for callers that import it from here
    get_or_create_residual_policy,
    get_or_create_settings,
    load_appetite_book,
    policy_spec,
    scale_for,
)

router = APIRouter(prefix="/risks", tags=["risks"])

#: The risk's picked fields (phase 1): each key beside the legacy text it keeps in step
#: (``owner_id`` never had one). Reads carry ``<name>_ref``. See services.ref_fields.
RISK_REFS: tuple[ref_fields.RefField, ...] = (
    ref_fields.user("owner_id", None),
    ref_fields.user("treatment_owner_id", "treatment_owner"),
    ref_fields.lookup(Risk, "category_id", "category"),
    ref_fields.WORKFLOW_OWNER,
    # Phase 2. ``last_assessed_by_id`` is never in a request (the server stamps it);
    # it is declared so reads carry ``last_assessed_by_ref``.
    ref_fields.user("identified_by_id", None),
    ref_fields.user("last_assessed_by_id", None),
)

#: A treatment action's owner — picked, validated, read as ``owner_ref``.
ACTION_REFS: tuple[ref_fields.RefField, ...] = (ref_fields.user("owner_id", None),)

_DIMENSION_LIST = "impact_dimension"


# --------------------------------------------------------------------------- helpers
async def _load_risk(db, risk_id: uuid.UUID) -> Risk:
    risk = await db.scalar(
        select(Risk).where(Risk.id == risk_id, Risk.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if risk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    return risk


async def _resolve(db, model, ids: Sequence[uuid.UUID]) -> list:
    if not ids:
        return []
    stmt = select(model).where(model.id.in_(ids))
    if hasattr(model, "deleted"):
        stmt = stmt.where(model.deleted.is_(False))
    rows = (await db.scalars(stmt)).all()
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown {model.__name__.lower()} id(s): {sorted(map(str, missing))}",
        )
    return list(rows)


async def _next_reference(db) -> str:
    return await next_reference(db, Risk, "R")




async def _check_scale(db, user: CurrentUser, values: dict[str, object]) -> None:
    """Reject scores outside the tenant's configured matrix.

    The schema only bounds scores to the widest scale any tenant may choose
    (``MAX_MATRIX_SIZE``) and the database check constraint does the same, because
    neither can vary per tenant.
    This is where the tenant's own ``matrix_size`` is enforced — without it, a 4x4
    organisation could store a 5 that its own heat map has no cell for.
    """
    size = await get_matrix_size(db, user.tenant_id)
    for name in (
        "inherent_likelihood", "inherent_impact", "residual_likelihood", "residual_impact",
        "target_likelihood", "target_impact",
    ):
        value = values.get(name)
        if isinstance(value, int) and value > size:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{name.replace('_', ' ')} {value} is outside this organisation's "
                    f"{size}x{size} risk matrix (1-{size})"
                ),
            )
    for row in values.get("impact_dimensions") or ():
        score = row.get("score") if isinstance(row, dict) else getattr(row, "score", None)
        if isinstance(score, int) and score > size:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"impact_dimensions: score {score} is outside this organisation's "
                    f"{size}x{size} risk matrix (1-{size})"
                ),
            )


def _enforce_target(values: dict[str, object]) -> None:
    """Target <= residual <= inherent (422). ``values`` is the resulting state."""
    detail = risk_integrity.target_rule_violation(
        inherent=(values.get("inherent_likelihood"), values.get("inherent_impact")),
        residual=(values.get("residual_likelihood"), values.get("residual_impact")),
        target=(values.get("target_likelihood"), values.get("target_impact")),
    )
    if detail:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _status_value(value) -> str | None:
    return getattr(value, "value", value)


async def _stored_dimensions(db, risk_id: uuid.UUID) -> list[RiskImpactDimension]:
    return list(
        (
            await db.scalars(
                select(RiskImpactDimension).where(RiskImpactDimension.risk_id == risk_id)
            )
        ).all()
    )


async def _apply_dimensions(
    db,
    user: CurrentUser,
    rows: list[dict],
    data: dict[str, object],
    stored: Sequence[RiskImpactDimension] = (),
) -> None:
    """Validate the dimension rows and write each basis' derived impact into ``data``.

    A dimension already scored on the risk is not re-checked, so a risk scored on a
    dimension that has since been deactivated can still be saved.
    """
    known = {(r.dimension_id, r.basis) for r in stored}
    for row in rows:
        if (row["dimension_id"], row["basis"]) not in known:
            await master_data.check_lookup(db, row["dimension_id"], _DIMENSION_LIST, "impact_dimensions")
    settings = await get_or_create_settings(db, user.tenant_id)
    data.update(
        risk_integrity.derive_dimension_impacts(rows, data, settings.impact_mode or "max")
    )


def _dimension_rows(risk: Risk, rows: list[dict], tenant_id) -> list[RiskImpactDimension]:
    return [
        RiskImpactDimension(
            tenant_id=tenant_id, risk_id=risk.id, dimension_id=r["dimension_id"],
            basis=r["basis"], score=r["score"], rationale=(r.get("rationale") or "").strip(),
        )
        for r in rows
    ]


def _scoring_changed(risk: Risk | None, incoming: dict[str, object]) -> bool:
    """Whether the request actually changes a score or the override reason.

    The register form sends every field on each save, so presence in the payload is not
    a change; only a different value is.
    """
    for name in risk_integrity.SCORING_FIELDS:
        if name not in incoming:
            continue
        new, old = incoming[name], (getattr(risk, name) if risk is not None else None)
        if name == "residual_override_reason":
            if (new or "").strip() != (old or "").strip():
                return True
        elif new != old:
            return True
    return False


def _enforce_residual(
    user: CurrentUser,
    *,
    inherent: tuple[int | None, int | None],
    residual: tuple[int | None, int | None],
    override_reason: str | None,
    changes_scoring: bool = True,
) -> None:
    """Residual may not exceed inherent without a reason from someone who can accept
    risk. 422 without a reason, 403 without ``risk:accept``. See ``risk_integrity``."""
    risk_integrity.enforce_residual_rule(
        inherent_likelihood=inherent[0],
        inherent_impact=inherent[1],
        residual_likelihood=residual[0],
        residual_impact=residual[1],
        override_reason=override_reason,
        can_accept=risk_integrity.can_accept_risk(user),
        changes_scoring=changes_scoring,
    )


def _control_inputs(risk: Risk) -> list[ControlInput]:
    """Describe each linked control to the residual engine, including whether it can be
    relied on today — its latest reviewed test failed, its test is overdue or an audit
    finding is open. The rule is ``control_assurance.reliance_note``, the same one the
    risk page's assurance fields (B2) and the health rollups read.
    """
    out: list[ControlInput] = []
    for control in risk.controls:
        note = control_assurance.reliance_note(control, getattr(control, "audits", None) or ())
        out.append(
            ControlInput(
                label=control.reference or control.name,
                effectiveness=control.effectiveness,
                healthy=not note,
                health_note=note,
                key=control.id,
            )
        )
    return out


# ------------------------------------------------------- control assurance (B2, B6)
# What a risk page needs to judge how far each mitigating control's rating can be
# trusted — and what accepting residual credit leans on. Only tests that decide a rating
# count (conclusive, and reviewed or recorded before reviews existed): a test awaiting
# review is the tester's claim, not assurance (``services.control_assurance``).

#: Bases of a rating no reviewed test stands behind.
HAND_RATED_BASES: tuple[str, ...] = (control_assurance.BASIS_MANUAL, control_assurance.BASIS_OVERRIDE)
_OPEN_ISSUE_EXCLUDED = tuple(IssueStatus2(s) for s in control_assurance.CLOSED_ISSUE_STATES)


def control_assurance_ref(
    control,
    tests=(),
    open_issue_count: int | None = 0,
    today: date | None = None,
    *,
    assurance: bool = True,
) -> ControlAssuranceRef:
    """A linked control with its rating, the rating's basis and its test record (B2).

    ``tests`` are the control's test rows in any review state; only those that decide a
    rating are counted, and the last result and date are the newest of those
    (``control_assurance.latest_counting_test`` — what the residual engine reads too).
    ``pending_review_count`` says how many more await a reviewer; ``open_finding_count``
    is the open audit findings the engine also withholds credit for. The next test date
    is the control's clock, which a planned or retired control does not carry.

    ``assurance=False`` (a viewer without ``control:read``) gives identity only;
    ``open_issue_count=None`` (a viewer without ``issue:read``) leaves the issue count
    out. The page reads a missing field as "not shown here". Pure.
    """
    if not assurance:
        return ControlAssuranceRef(id=control.id, name=control.name, reference=control.reference or "")
    tests = list(tests)
    counting = [t for t in tests if control_assurance.counts_towards_rating(t)]
    latest = control_assurance.latest_counting_test(tests)
    clock = control_assurance.carries_test_clock(control.status)
    return ControlAssuranceRef(
        id=control.id,
        name=control.name,
        reference=control.reference or "",
        effectiveness=control.effectiveness,
        effectiveness_basis=control_assurance.effectiveness_basis(
            tests, control.effectiveness_override_reason or "", control.effectiveness
        ),
        audit_count=len(counting),
        last_audit_result=latest.result if latest is not None else None,
        last_audit_date=control_assurance.performed_on(latest) if latest is not None else None,
        next_audit_date=control.next_audit_date if clock else None,
        is_audit_overdue=control_assurance.is_cycle_overdue(control.status, control.next_audit_date, today),
        pending_review_count=control_assurance.pending_review_count(tests),
        open_finding_count=control_assurance.open_finding_count(control),
        open_issue_count=open_issue_count,
    )


def rests_on_untested_rating(ref: ControlAssuranceRef) -> bool:
    """A rating set by hand or by override, or with no reviewed test on file (B6). The
    rule is ``control_assurance.rests_on_untested_rating``, which control health reads too."""
    return control_assurance.rests_on_untested_rating(ref.effectiveness_basis, ref.audit_count)


async def _control_health(db, risks: Sequence[Risk]) -> dict[uuid.UUID, str]:
    """Each risk's control health with open issues counted (``Risk.control_health``
    cannot see them): ``issues`` > ``untested`` > ``ok``, ``none`` without controls. Two
    queries for every control on the page (``_assurance_inputs``)."""
    controls = {c.id: c for r in risks for c in (getattr(r, "controls", None) or [])}
    if not controls:
        return {r.id: control_assurance.HEALTH_NONE for r in risks}
    tests, issues = await _assurance_inputs(db, list(controls), issues=True)
    today = date.today()
    state = {
        cid: control_assurance.health_of_control(c, tests.get(cid, ()), issues.get(cid, 0), today)
        for cid, c in controls.items()
    }
    return {
        r.id: control_assurance.rollup_health(state[c.id] for c in (getattr(r, "controls", None) or []))
        for r in risks
    }


async def _assurance_inputs(db, control_ids, *, issues: bool = True) -> tuple[dict, dict]:
    """``({control id: [test rows]}, {control id: open issue count})`` for these
    controls — one query for the tests and one for the issues, whatever their number."""
    ids = list(dict.fromkeys(control_ids))
    if not ids:
        return {}, {}
    tests: dict = {}
    for row in (
        await db.execute(
            select(
                ControlAudit.control_id, ControlAudit.result, ControlAudit.review_status,
                ControlAudit.test_type, ControlAudit.conducted_date, ControlAudit.created_at,
            ).where(ControlAudit.control_id.in_(ids))
        )
    ).all():
        tests.setdefault(row.control_id, []).append(row)
    if not issues:
        return tests, {}
    open_issues = {
        control_id: int(n)
        for control_id, n in (
            await db.execute(
                select(issue_controls.c.control_id, func.count())
                .join(Issue, Issue.id == issue_controls.c.issue_id)
                .where(
                    issue_controls.c.control_id.in_(ids),
                    Issue.deleted.is_(False),
                    Issue.status.notin_(_OPEN_ISSUE_EXCLUDED),
                )
                .group_by(issue_controls.c.control_id)
            )
        ).all()
    }
    return tests, open_issues


def _holds(user, code: str) -> bool:
    return code in set(getattr(user, "permission_codes", None) or [])


async def _assured_controls(db, controls, user=None) -> list[ControlAssuranceRef]:
    """The risk's controls with their assurance (B2), in the order given.

    Test results and dates are control-testing records: only a viewer who holds
    ``control:read`` gets them, and the open-issue count only with ``issue:read`` too —
    as an asset reader without ``risk:read`` gets no risk scores (B8). ``user=None`` is
    an internal caller and gets everything."""
    controls = list(controls)
    can_controls = user is None or _holds(user, "control:read")
    can_issues = can_controls and (user is None or _holds(user, "issue:read"))
    if not can_controls:
        return [control_assurance_ref(c, assurance=False) for c in controls]
    tests, issues = await _assurance_inputs(db, [c.id for c in controls], issues=can_issues)
    today = date.today()
    return [
        control_assurance_ref(c, tests.get(c.id, ()), issues.get(c.id, 0) if can_issues else None, today)
        for c in controls
    ]


async def _untested_credit(db, risk: Risk, suggestion) -> list[ControlAssuranceRef]:
    """The controls a suggestion takes credit from whose rating no reviewed test
    supports (B6). Empty when the suggestion takes no credit."""
    credited = set(getattr(suggestion, "credited", ()) or ())
    controls = [c for c in (getattr(risk, "controls", None) or []) if c.id in credited]
    if not controls:
        return []
    tests, _ = await _assurance_inputs(db, [c.id for c in controls], issues=False)
    refs = [control_assurance_ref(c, tests.get(c.id, ())) for c in controls]
    return [r for r in refs if rests_on_untested_rating(r)]


# --------------------------------------------------------------------------- CRUD
_RISK_SORTABLE = {
    "reference": Risk.reference,
    "title": Risk.title,
    "category": Risk.category,
    "status": Risk.status,
    "inherent_score": Risk.inherent_score,
    "residual_score": Risk.residual_score,
    # Unset targets sort as 0, so a descending sort starts with real targets.
    "target_score": func.coalesce(Risk.target_likelihood * Risk.target_impact, 0),
    "treatment_deadline": Risk.treatment_deadline,
    "risk_type": Risk.risk_type,
    "source": Risk.source,
    "next_review_date": Risk.next_review_date,
    "created_at": Risk.created_at,
    # Phase 3: unplaced risks sort after level 3 ascending.
    "level": func.coalesce(Risk.level, 9),
}


class RiskListFilters:
    """Every filter the register's list takes, as one FastAPI dependency.

    ``GET /risks`` and the register PDF (``GET /reports/pdf/risk-register``) both declare
    ``filters: Annotated[RiskListFilters, Depends()]``, so a filter added here reaches the
    export the same day it reaches the screen — the PDF cannot quietly drift from the list
    it was launched from. :meth:`statement` builds the query; :meth:`active` names what is
    set, for the PDF cover.
    """

    def __init__(
        self,
        status_filter: Annotated[RiskStatus | None, Query(alias="status")] = None,
        category: str | None = None,
        business_unit_id: uuid.UUID | None = None,
        process_id: uuid.UUID | None = None,
        asset_id: uuid.UUID | None = None,
        owner_id: uuid.UUID | None = None,
        treatment_owner_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        needs_review: bool | None = None,
        risk_type: str | None = None,
        source: str | None = None,
        search: str | None = None,
        # Phase 3: hierarchy ("none" = not placed) and the dashboard's drill-through
        # filters, defined in services.risk_query exactly as the dashboard counts them.
        level: Annotated[str | None, Query(pattern="^(1|2|3|none)$")] = None,
        max_level: Annotated[int | None, Query(ge=1, le=3)] = None,
        parent_id: uuid.UUID | None = None,
        roots_only: bool | None = None,
        review: Annotated[str | None, Query(pattern="^(overdue|due_30d)$")] = None,
        appetite: Annotated[str | None, Query(pattern="^(within|within_appetite|elevated|breach)$")] = None,
        has_controls: bool | None = None,
        treatment_overdue: bool | None = None,
        # F-21: drafts the dashboard's figures leave out ("N risks pending validation").
        pending_validation: bool | None = None,
    ) -> None:
        self.status_filter = status_filter
        self.category = category
        self.business_unit_id = business_unit_id
        self.process_id = process_id
        self.asset_id = asset_id
        self.owner_id = owner_id
        self.treatment_owner_id = treatment_owner_id
        self.category_id = category_id
        self.needs_review = needs_review
        self.risk_type = risk_type
        self.source = source
        self.search = search
        self.level = level
        self.max_level = max_level
        self.parent_id = parent_id
        self.roots_only = roots_only
        self.review = review
        self.appetite = appetite
        self.has_controls = has_controls
        self.treatment_overdue = treatment_overdue
        self.pending_validation = pending_validation

    def statement(self, appetite_book) -> Select:
        """Live risks matching every set filter (``services.risk_query`` plus the
        register-only columns)."""
        stmt: Select = build_risk_query(
            status=self.status_filter,
            category=self.category,
            business_unit_id=self.business_unit_id,
            process_id=self.process_id,
            asset_id=self.asset_id,
            search=self.search,
            owner_id=self.owner_id,
            treatment_owner_id=self.treatment_owner_id,
            category_id=self.category_id,
            level=(UNPLACED if self.level == "none" else int(self.level)) if self.level else None,
            max_level=self.max_level,
            parent_id=self.parent_id,
            roots_only=self.roots_only,
            review=self.review,
            appetite=self.appetite,
            appetite_book=appetite_book,
            has_controls=self.has_controls,
            treatment_overdue=self.treatment_overdue,
            pending_validation=self.pending_validation,
        )
        if self.needs_review is not None:
            stmt = stmt.where(Risk.needs_review.is_(self.needs_review))
        if self.risk_type:
            stmt = stmt.where(Risk.risk_type == self.risk_type)
        if self.source:
            stmt = stmt.where(Risk.source == self.source)
        return stmt

    #: Filter name -> how the PDF cover labels it. Ids are resolved to names by the caller.
    LABELS: dict[str, str] = {
        "status_filter": "Status", "category": "Category", "business_unit_id": "Business unit",
        "process_id": "Process", "asset_id": "Asset", "owner_id": "Owner",
        "treatment_owner_id": "Treatment owner", "category_id": "Risk category",
        "needs_review": "Flagged for review", "risk_type": "Risk type", "source": "Source",
        "search": "Matching", "level": "Level", "max_level": "Level up to", "parent_id": "Below",
        "roots_only": "Top of the tree only", "review": "Review", "appetite": "Appetite",
        "has_controls": "Has controls", "treatment_overdue": "Treatment overdue",
        "pending_validation": "Pending validation",
    }

    def active(self) -> dict[str, object]:
        """The filters that are set, in :attr:`LABELS` order."""
        return {k: getattr(self, k) for k in self.LABELS if getattr(self, k) not in (None, "")}


@router.get("", response_model=Page[RiskRead], dependencies=[Depends(require("risk:read"))])
async def list_risks(
    db: DbSession,
    user: CurrentUser,
    filters: Annotated[RiskListFilters, Depends()],
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RiskRead]:
    context = await _read_context(db, user)
    stmt = filters.statement(context["appetite"])

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=filters.search)
        stmt = apply_sort(stmt, params, _RISK_SORTABLE, default=Risk.inherent_score)
    else:
        stmt = stmt.order_by(Risk.inherent_score.desc(), Risk.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    items = [RiskRead.model_validate(r, context=context) for r in rows]
    await ref_fields.fill_refs(db, list(zip(rows, items)), RISK_REFS)
    await _fill_hierarchy(db, list(zip(rows, items)))
    today = date.today()
    actions = await _actions_by_risk(db, [r.id for r in rows])
    health = await _control_health(db, rows)
    for row, item in zip(rows, items):
        item.treatment_progress = TreatmentProgress(
            **risk_integrity.treatment_progress(actions.get(row.id, []), today)
        )
        item.control_health = health.get(row.id, item.control_health)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=RiskRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("risk:write"))],
)
async def create_risk(body: RiskCreate, db: DbSession, user: CurrentUser) -> RiskRead:
    """Create a risk.

    Phase 2 rules (``services.risk_integrity``): a blank title is composed from the
    statement; dimension scores decide their basis' impact; target <= residual <=
    inherent; scores given on create stamp the assessment trail, and a risk created
    beyond draft needs chosen inherent scores and an ``assessment_rationale``.
    """
    await _check_scale(db, user, body.model_dump())
    data = body.model_dump(
        exclude={
            "business_unit_ids", "process_ids", "asset_ids", "control_ids",
            "threat_ids", "vulnerability_ids", "policy_ids", "incident_ids",
            "impact_dimensions",
        }
    )
    dimension_rows = [d.model_dump() for d in body.impact_dimensions]
    if dimension_rows:
        await _apply_dimensions(db, user, dimension_rows, data)
    # Phase 3: a parent must be live and above the risk; the level defaults from it.
    if data.get("parent_id") is not None or data.get("level") is not None:
        data["level"] = await _place(
            db, risk_id=None, parent_id=data.get("parent_id"), level=data.get("level"),
            level_given="level" in body.model_fields_set, current_level=None,
        )
    sends_inherent = data.get("inherent_likelihood") is not None and data.get("inherent_impact") is not None
    # Scores not chosen yet are stored as 1 (the columns are NOT NULL) and the risk
    # cannot leave draft until someone scores it.
    inherent = (data.get("inherent_likelihood") or 1, data.get("inherent_impact") or 1)
    _enforce_residual(
        user,
        inherent=inherent,
        residual=(data.get("residual_likelihood"), data.get("residual_impact")),
        override_reason=body.residual_override_reason,
    )
    _enforce_target({**data, "inherent_likelihood": inherent[0], "inherent_impact": inherent[1]})
    decision = risk_integrity.assessment_decision(
        creating=True,
        changed=bool(risk_integrity.changed_scores(None, data)),
        sends_inherent=sends_inherent,
        rationale=data.get("assessment_rationale"),
        stored_rationale="",
        status_before=None,
        status_after=_status_value(data.get("status") or RiskStatus.draft),
        previously_assessed=False,
        has_owner=data.get("owner_id") is not None,
        has_business_unit=bool(body.business_unit_ids),
    )
    data["inherent_likelihood"], data["inherent_impact"] = inherent
    data["assessment_rationale"] = decision.rationale or ""
    for name in ("cause", "event", "consequence"):
        data[name] = (data.get(name) or "").strip()
    data["title"] = (data.get("title") or "").strip() or risk_integrity.compose_title(
        data["cause"], data["event"], data["consequence"]
    )
    if not data["title"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=risk_integrity.TITLE_NEEDS_STATEMENT_DETAIL,
        )

    await ref_fields.apply_refs(db, Risk, data, RISK_REFS)
    risk = Risk(tenant_id=user.tenant_id, **data)
    if risk.identified_by_id is None:
        risk.identified_by_id = user.id
    if decision.stamp:
        risk.last_assessed_at = datetime.now(timezone.utc)
        risk.last_assessed_by_id = user.id
    risk.reference = await _next_reference(db)
    risk.business_units = await _resolve(db, BusinessUnit, body.business_unit_ids)
    risk.processes = await _resolve(db, Process, body.process_ids)
    risk.assets = await _resolve(db, Asset, body.asset_ids)
    risk.controls = await _resolve(db, Control, body.control_ids)
    risk.threats = await _resolve(db, Threat, body.threat_ids)
    risk.vulnerabilities = await _resolve(db, Vulnerability, body.vulnerability_ids)
    risk.policies = await _resolve(db, Policy, body.policy_ids)
    risk.incidents = await _resolve(db, Incident, body.incident_ids)
    # The review clock runs on the effective cycle: the rating may require a shorter one.
    policy = await _review_policy(db, user)
    risk.next_review_date = next_review_date(_effective_frequency(risk, policy))

    db.add(risk)
    await db.flush()
    for row in _dimension_rows(risk, dimension_rows, user.tenant_id):
        db.add(row)
    if dimension_rows:
        await db.flush()
    # A generated-style title that names an asset the risk doesn't link needs a look.
    await _reconcile_title_flag(db, user, risk)
    await audit.record(
        db,
        actor=user,
        action="create",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Created risk {risk.reference}: {risk.title}",
        changes={
            "scores": f"{risk.inherent_likelihood}x{risk.inherent_impact}" if sends_inherent else "not scored",
            **({"assessment_rationale": risk.assessment_rationale} if risk.assessment_rationale else {}),
            **({"impact_dimensions": len(dimension_rows)} if dimension_rows else {}),
        },
    )
    await _refresh_alerts(db, user, risk)
    return await _read(db, risk.id, user)


# ----------------------------------------------------------------- hierarchy (phase 3)
# 1 enterprise → 2 category → 3 scenario. The placement rules live in
# services.risk_hierarchy (pure); these helpers load the facts they need.
async def _hierarchy_node(db, risk_id: uuid.UUID) -> risk_hierarchy.Node | None:
    row = (
        await db.execute(
            select(Risk.id, Risk.reference, Risk.level, Risk.deleted).where(Risk.id == risk_id)
        )
    ).first()
    if row is None:
        return None
    return risk_hierarchy.Node(row.id, row.reference or "", row.level, bool(row.deleted))


async def _ancestor_ids(db, risk_id: uuid.UUID) -> list[uuid.UUID]:
    """``risk_id`` and every risk above it, archived ones included (a loop through an
    archived risk would come back on restore). UNION, not UNION ALL, so a loop already
    in the data ends the walk instead of hanging it."""
    above = aliased(Risk)
    walk = select(Risk.id, Risk.parent_id).where(Risk.id == risk_id).cte("risk_ancestors", recursive=True)
    walk = walk.union(select(above.id, above.parent_id).where(above.id == walk.c.parent_id))
    return list((await db.scalars(select(walk.c.id))).all())


async def _child_nodes(db, risk_id: uuid.UUID) -> list[risk_hierarchy.Node]:
    rows = (
        await db.execute(
            select(Risk.id, Risk.reference, Risk.level)
            .where(Risk.parent_id == risk_id, Risk.deleted.is_(False))
            .order_by(Risk.reference)
        )
    ).all()
    return [risk_hierarchy.Node(r.id, r.reference or "", r.level) for r in rows]


async def _place(
    db,
    *,
    risk_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
    level: int | None,
    level_given: bool,
    current_level: int | None,
) -> int | None:
    """Apply the hierarchy rules (422 with the rule's sentence) and return the level."""
    parent = await _hierarchy_node(db, parent_id) if parent_id is not None else None
    ancestors = (
        await _ancestor_ids(db, parent_id)
        if parent_id is not None and parent is not None and risk_id is not None
        else []
    )
    children = await _child_nodes(db, risk_id) if risk_id is not None else []
    try:
        return risk_hierarchy.place(
            risk_id=risk_id, parent_id=parent_id, parent=parent, level=level,
            level_given=level_given, current_level=current_level,
            ancestors_of_parent=ancestors, children=children,
        )
    except risk_hierarchy.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


async def _place_on_update(db, risk: Risk, data: dict[str, object]) -> None:
    """Check a PATCH's ``parent_id``/``level`` against the rules, in place.

    The form sends every field on each save, so an unchanged parent and level are
    dropped rather than re-checked — a risk whose parent was later archived can still
    have its title edited.
    """
    stored_parent, stored_level = getattr(risk, "parent_id", None), getattr(risk, "level", None)
    parent_changed = "parent_id" in data and data["parent_id"] != stored_parent
    level_changed = "level" in data and data["level"] != stored_level
    if not (parent_changed or level_changed):
        data.pop("parent_id", None)
        data.pop("level", None)
        return
    parent_id = data["parent_id"] if "parent_id" in data else stored_parent
    data["level"] = await _place(
        db, risk_id=risk.id, parent_id=parent_id, level=data.get("level"),
        level_given="level" in data, current_level=stored_level,
    )
    if "parent_id" not in data:
        data["parent_id"] = parent_id


async def _fill_hierarchy(db, pairs: Sequence[tuple[Risk, RiskRead]]) -> None:
    """Set ``parent`` (live parents only) and ``children_count`` on read models — two
    queries for the whole page."""
    if not pairs:
        return
    parent_ids = {getattr(r, "parent_id", None) for r, _ in pairs} - {None}
    parents: dict[uuid.UUID, GraphRef] = {}
    if parent_ids:
        for row in (
            await db.execute(
                select(Risk.id, Risk.reference, Risk.title)
                .where(Risk.id.in_(parent_ids), Risk.deleted.is_(False))
            )
        ).all():
            parents[row.id] = GraphRef(id=row.id, reference=row.reference or "", title=row.title or "")
    counts = dict(
        (
            await db.execute(
                select(Risk.parent_id, func.count())
                .where(Risk.parent_id.in_([r.id for r, _ in pairs]), Risk.deleted.is_(False))
                .group_by(Risk.parent_id)
            )
        ).all()
    )
    for risk, read in pairs:
        read.parent = parents.get(getattr(risk, "parent_id", None))
        read.children_count = int(counts.get(risk.id, 0))


async def _hierarchy_facts(db) -> list[risk_hierarchy.RiskFacts]:
    """Every live risk that is placed or has a parent — the population of the tree."""
    rows = (
        await db.execute(
            select(
                Risk.id, Risk.parent_id, Risk.level, Risk.reference, Risk.title, Risk.status,
                Risk.category_id, Risk.inherent_likelihood, Risk.inherent_impact,
                Risk.residual_likelihood, Risk.residual_impact, Risk.last_assessed_at,
            ).where(Risk.deleted.is_(False), or_(Risk.parent_id.is_not(None), Risk.level.is_not(None)))
        )
    ).all()
    return [_facts_of(r) for r in rows]


def _facts_of(row) -> risk_hierarchy.RiskFacts:
    return risk_hierarchy.RiskFacts(
        id=row.id, parent_id=row.parent_id, level=row.level, reference=row.reference or "",
        title=row.title or "", status=_status_value(row.status) or "", category_id=row.category_id,
        inherent_likelihood=row.inherent_likelihood, inherent_impact=row.inherent_impact,
        residual_likelihood=row.residual_likelihood, residual_impact=row.residual_impact,
        last_assessed_at=getattr(row, "last_assessed_at", None),
    )


@router.get(
    "/hierarchy",
    response_model=RiskHierarchy,
    dependencies=[Depends(require("risk:read"))],
    summary="Board view: levels 1..max_level as a tree, with the worst exposure below each node",
)
async def get_risk_hierarchy(
    db: DbSession,
    user: CurrentUser,
    max_level: Annotated[int, Query(ge=1, le=3)] = 2,
) -> RiskHierarchy:
    """The enterprise → category (→ scenario) tree. Each node carries its direct child
    count, how many live risks sit anywhere below it, the worst exposure among them
    (residual when assessed, else inherent — at any level, so a category shows its worst
    scenario even when the tree stops at categories) and their severity counts.

    Worst exposure, severity counts and breaches read the board register only (scored,
    out of Draft, not accepted or closed) so a node never disagrees with the dashboard;
    drafts and settled risks stay in the tree marked ``in_figures=false`` and each node's
    ``not_in_figures`` says how many below it were left out."""
    context = await _read_context(db, user)
    facts = await _hierarchy_facts(db)
    tree = risk_hierarchy.build_tree(
        facts, max_level=max_level, scale=context["scale"], book=context["appetite"]
    )
    by_level = dict(
        (
            await db.execute(
                select(Risk.level, func.count())
                .where(Risk.deleted.is_(False), Risk.level.is_not(None))
                .group_by(Risk.level)
            )
        ).all()
    )
    unplaced = await db.scalar(
        select(func.count()).select_from(Risk).where(Risk.deleted.is_(False), Risk.level.is_(None))
    ) or 0
    return RiskHierarchy(
        max_level=max_level,
        roots=[RiskHierarchyNode.model_validate(node, from_attributes=True) for node in tree],
        unplaced=int(unplaced),
        by_level={str(k): int(v) for k, v in sorted(by_level.items())},
    )


# ------------------------------------------------------------------ orphan cleanup
# A risk is offered for archiving only when it was written against assets that are all
# deleted *and* nothing else live links to it — no control, business unit, process,
# policy, incident, threat, requirement, KRI, issue and so on (``risk_integrity``).
# The review dialog lists the survivors with their live-link counts; nothing is archived
# until a person ticks rows, writes a reason and presses the button.
@router.get(
    "/orphaned",
    response_model=OrphanedRiskPage,
    dependencies=[Depends(require("risk:read"))],
    summary="Risks with no live links — their assets were deleted and nothing else links",
)
async def list_orphaned_risks(db: DbSession) -> OrphanedRiskPage:
    scan = await risk_integrity.scan_orphans(db)
    ids = scan.orphaned
    if not ids:
        return OrphanedRiskPage(items=[], total=0, kept_with_links=len(scan.kept))

    rows = (
        await db.scalars(
            select(Risk).where(Risk.id.in_(ids)).order_by(Risk.reference)
        )
    ).all()
    # Which deleted assets each risk pointed at, so the reviewer can see why it
    # is on this list before archiving anything.
    names: dict[uuid.UUID, list[str]] = {}
    for rid, name in (
        await db.execute(
            select(risk_assets.c.risk_id, Asset.name)
            .join(Asset, Asset.id == risk_assets.c.asset_id)
            .where(risk_assets.c.risk_id.in_(ids), Asset.deleted.is_(True))
        )
    ).all():
        names.setdefault(rid, []).append(name)
    items = []
    for r in rows:
        counts = scan.counts.get(r.id, risk_integrity.empty_link_counts())
        items.append(
            OrphanedRisk(
                id=r.id,
                reference=r.reference,
                title=r.title,
                category=r.category,
                status=r.status.value,
                inherent_score=r.inherent_score,
                deleted_asset_names=sorted(names.get(r.id, [])),
                live_links=counts,
                live_link_total=sum(counts.values()),
            )
        )
    return OrphanedRiskPage(items=items, total=len(items), kept_with_links=len(scan.kept))


BULK_ARCHIVE_UNDER_DUAL_CONTROL = (
    "Archiving risks in bulk is under dual control, and one person cannot be both the "
    "maker and the checker of a bulk archive. Archive the risks one at a time from the "
    "register, or ask an administrator to add a dual-control rule for "
    "risk / bulk_archive that lets this action through."
)


@router.post(
    "/orphaned/purge",
    response_model=OrphanPurgeResult,
    dependencies=[Depends(require("risk:delete"))],
    summary="Archive chosen risks that have no live links (soft delete, audit-logged)",
)
async def purge_orphaned_risks(
    body: OrphanPurgeRequest, db: DbSession, user: CurrentUser
) -> OrphanPurgeResult:
    """Archive exactly the ticked risks, and only those still without a live link.

    **Dual control.** The dual-control model gates a checker deciding a maker's request;
    a bulk archive is carried out at once by one person, who is both, so there is no
    second person to route it to. The action is therefore gated on the
    ``risk / bulk_archive`` DualControlRule: when dual control applies (an active rule
    requiring it, or — with no rule — the global ``enforce_segregation_of_duties``
    switch, on by default) the bulk archive is refused with 403. An administrator
    enables it with a rule that sets ``requires_dual_control = false``, or with a
    ``threshold_amount``: the amount compared is the archived risks' total annual loss
    expectancy (0 when none has one), the same measure ``risk / accept`` uses.
    """
    from datetime import datetime, timezone

    scan = await risk_integrity.scan_orphans(db)
    requested = set(body.risk_ids)
    targets = requested & set(scan.orphaned)
    skipped = len(requested - targets)
    if not targets:
        return OrphanPurgeResult(archived=0, references=[], skipped=skipped)

    rows = (
        await db.scalars(select(Risk).where(Risk.id.in_(targets)).order_by(Risk.reference))
    ).all()
    exposure = sum(float(r.annual_loss_expectancy or 0) for r in rows)
    required, _rule = await dual_control.dual_control_required(
        db, "risk", "bulk_archive", amount=exposure
    )
    if required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=BULK_ARCHIVE_UNDER_DUAL_CONTROL
        )

    now = datetime.now(timezone.utc)
    for risk in rows:
        risk.deleted = True
        risk.deleted_date = now
    refs = [r.reference for r in rows]
    await db.flush()
    # One row per risk, so each risk's own history says who archived it and why.
    for risk in rows:
        await audit.record(
            db,
            actor=user,
            action="delete",
            entity_type="risk",
            entity_id=risk.id,
            summary=f"Archived risk {risk.reference} (no live links). Reason: {body.reason}",
            changes={"reason": body.reason, "via": "bulk archive of risks with no live links"},
        )
    await audit.record(
        db,
        actor=user,
        action="bulk_archive",
        entity_type="risk",
        entity_id=None,
        summary=f"Archived {len(rows)} risk(s) with no live links. Reason: {body.reason}",
        changes={
            "reason": body.reason,
            "archived": len(rows),
            "skipped": skipped,
            "references": ", ".join(refs[:50]) + (" …" if len(refs) > 50 else ""),
        },
    )
    return OrphanPurgeResult(archived=len(rows), references=refs, skipped=skipped)


@router.get("/{risk_id}", response_model=RiskRead, dependencies=[Depends(require("risk:read"))])
async def get_risk(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> RiskRead:
    return await _read(db, risk_id, user)


@router.get(
    "/{risk_id}/rollup",
    response_model=RiskRollup,
    dependencies=[Depends(require("risk:read"))],
    summary="Children and descendants with their scores, the worst residual below, counts by severity",
)
async def get_risk_rollup(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> RiskRollup:
    risk = await _load_risk(db, risk_id)
    context = await _read_context(db, user)
    index = risk_hierarchy.children_index(await _hierarchy_facts(db))
    result = risk_hierarchy.rollup(_facts_of(risk), index, context["scale"], context["appetite"])
    return RiskRollup.model_validate(result, from_attributes=True)


@router.patch(
    "/{risk_id}", response_model=RiskRead, dependencies=[Depends(require("risk:write"))]
)
async def update_risk(
    risk_id: uuid.UUID, body: RiskUpdate, db: DbSession, user: CurrentUser
) -> RiskRead:
    risk = await _load_risk(db, risk_id)
    data = body.model_dump(exclude_unset=True)
    # A null inherent score means "not chosen": the stored value stands (NOT NULL).
    for name in ("inherent_likelihood", "inherent_impact"):
        if name in data and data[name] is None:
            data.pop(name)
    await _check_scale(db, user, data)
    dimension_rows = data.pop("impact_dimensions", None)
    stored_dims: list[RiskImpactDimension] = []
    if dimension_rows is not None:
        stored_dims = await _stored_dimensions(db, risk.id)
        await _apply_dimensions(db, user, dimension_rows, data, stored_dims)
    else:
        # An impact whose basis is scored by dimension moves only with its dimensions.
        moved = [
            b for b in ("inherent", "residual", "target")
            if f"{b}_impact" in data and data[f"{b}_impact"] != getattr(risk, f"{b}_impact", None)
        ]
        if moved:
            scored = {r.basis for r in await _stored_dimensions(db, risk.id)}
            clash = [b for b in moved if b in scored]
            if clash:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"The {clash[0]} impact is derived from its dimension scores; "
                        "change the dimension scores instead."
                    ),
                )
    if "residual_override_reason" in data:
        data["residual_override_reason"] = (data["residual_override_reason"] or "").strip()
    # The rule is checked on the state the update would leave behind: a PATCH that only
    # lowers inherent can push an untouched residual above it.
    merged = {name: data.get(name, getattr(risk, name)) for name in risk_integrity.SCORING_FIELDS}
    _enforce_residual(
        user,
        inherent=(merged["inherent_likelihood"], merged["inherent_impact"]),
        residual=(merged["residual_likelihood"], merged["residual_impact"]),
        override_reason=merged["residual_override_reason"],
        changes_scoring=_scoring_changed(risk, data),
    )
    _enforce_target({
        **merged,
        "target_likelihood": data.get("target_likelihood", getattr(risk, "target_likelihood", None)),
        "target_impact": data.get("target_impact", getattr(risk, "target_impact", None)),
    })
    stored_scores = {name: getattr(risk, name) for name in risk_integrity.SCORE_FIELDS}
    changed = risk_integrity.changed_scores(stored_scores, data)
    # Owner and business units as the write would leave them (F-21: both are needed to
    # leave Draft).
    units_after = (
        data["business_unit_ids"] if data.get("business_unit_ids") is not None
        else getattr(risk, "business_units", None) or []
    )
    decision = risk_integrity.assessment_decision(
        creating=False,
        changed=bool(changed),
        sends_inherent="inherent_likelihood" in data and "inherent_impact" in data,
        rationale=data.pop("assessment_rationale", None),
        stored_rationale=getattr(risk, "assessment_rationale", ""),
        status_before=_status_value(getattr(risk, "status", None)),
        status_after=_status_value(data.get("status", getattr(risk, "status", None))),
        previously_assessed=getattr(risk, "last_assessed_at", None) is not None,
        has_owner=data.get("owner_id", getattr(risk, "owner_id", None)) is not None,
        has_business_unit=bool(units_after),
    )
    if "treatment_deadline" in data and data["treatment_deadline"] != getattr(risk, "treatment_deadline", None):
        if await _action_count(db, risk.id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "The treatment deadline follows the treatment actions (the latest open "
                    "action's due date); change an action's due date instead."
                ),
            )
    for name in ("cause", "event", "consequence"):
        if name in data:
            data[name] = (data[name] or "").strip()
    await _place_on_update(db, risk, data)

    await ref_fields.apply_refs(db, Risk, data, RISK_REFS, record=risk)
    policy = await _review_policy(db, user)
    effective_before = _effective_frequency(risk, policy)
    frequency_changed = "review_frequency" in data and _status_value(data["review_frequency"]) != _status_value(
        getattr(risk, "review_frequency", None)
    )
    status_before = _status_value(getattr(risk, "status", None))
    # What a breach alert reads besides the scores: the status and the tolerance's category.
    category_before = getattr(risk, "category_id", None)

    business_unit_ids = data.pop("business_unit_ids", None)
    process_ids = data.pop("process_ids", None)
    asset_ids = data.pop("asset_ids", None)
    control_ids = data.pop("control_ids", None)
    threat_ids = data.pop("threat_ids", None)
    vulnerability_ids = data.pop("vulnerability_ids", None)
    policy_ids = data.pop("policy_ids", None)
    incident_ids = data.pop("incident_ids", None)
    if business_unit_ids is not None:
        risk.business_units = await _resolve(db, BusinessUnit, business_unit_ids)
    if process_ids is not None:
        risk.processes = await _resolve(db, Process, process_ids)
    if asset_ids is not None:
        risk.assets = await _resolve(db, Asset, asset_ids)
    if control_ids is not None:
        risk.controls = await _resolve(db, Control, control_ids)
    if threat_ids is not None:
        risk.threats = await _resolve(db, Threat, threat_ids)
    if vulnerability_ids is not None:
        risk.vulnerabilities = await _resolve(db, Vulnerability, vulnerability_ids)
    if policy_ids is not None:
        risk.policies = await _resolve(db, Policy, policy_ids)
    if incident_ids is not None:
        risk.incidents = await _resolve(db, Incident, incident_ids)

    for field, value in data.items():
        setattr(risk, field, value)
    if decision.rationale is not None:
        risk.assessment_rationale = decision.rationale
    if decision.stamp:
        risk.last_assessed_at = datetime.now(timezone.utc)
        risk.last_assessed_by_id = user.id

    if dimension_rows is not None:
        for row in stored_dims:
            await db.delete(row)
        await db.flush()
        for row in _dimension_rows(risk, dimension_rows, user.tenant_id):
            db.add(row)

    # F-22: the review date moves only when the cycle does — the owner changed it, or a
    # re-score tightened the cycle the rating requires. Re-saving the form never moves it.
    review_before = getattr(risk, "next_review_date", None)
    _reschedule(risk, effective_before, policy, frequency_changed=frequency_changed)
    cleared = risk_integrity.clear_residual_flag(risk, RESIDUAL_REVIEW_REASON)

    await db.flush()
    if asset_ids is not None or "title" in data:
        await _reconcile_title_flag(db, user, risk)
    changes = {k: str(v) for k, v in data.items()}
    if getattr(risk, "next_review_date", None) != review_before:
        changes["next_review_date"] = f"{review_before} -> {risk.next_review_date}"
    if decision.rationale:
        changes["assessment_rationale"] = decision.rationale
    if decision.stamp:
        changes["assessed"] = ", ".join(changed) or "scores confirmed"
    if dimension_rows is not None:
        changes["impact_dimensions"] = "; ".join(
            f"{r['basis']} {r['dimension_id']}={r['score']}" for r in dimension_rows
        ) or "cleared"
    if cleared:
        changes["review_reason"] = "residual corrected; review flag cleared"
    await audit.record(
        db,
        actor=user,
        action="update",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Updated risk {risk.reference}",
        changes=changes,
    )
    if (
        changed
        or status_before != _status_value(getattr(risk, "status", None))
        or category_before != getattr(risk, "category_id", None)
    ):
        await _refresh_alerts(db, user, risk)
    return await _read(db, risk.id, user)


@router.delete(
    "/{risk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("risk:delete"))],
)
async def delete_risk(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Archive a risk (soft delete, audit-logged).

    **Dual control** ``risk / delete``: while segregation of duties applies, whoever
    entered the risk (``dual_control.maker_of``) cannot also archive it — 403. The ALE is
    the amount a rule's threshold compares, as for ``risk / accept``.
    """
    from datetime import datetime, timezone

    risk = await _load_risk(db, risk_id)
    await delete_guard.enforce(
        db, entity_type="risk", record=risk, user=user, label="risk",
        amount=float(risk.annual_loss_expectancy) if risk.annual_loss_expectancy else None,
    )
    ref = risk.reference
    risk.deleted = True
    risk.deleted_date = datetime.now(timezone.utc)
    await audit.record(
        db,
        actor=user,
        action="delete",
        entity_type="risk",
        entity_id=risk_id,
        summary=f"Archived risk {ref}",
    )


# --------------------------------------------------------------------------- workflow
@router.post(
    "/{risk_id}/assess",
    response_model=RiskRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Record residual scoring after controls",
)
async def assess_risk(
    risk_id: uuid.UUID, body: RiskAssessment, db: DbSession, user: CurrentUser
) -> RiskRead:
    risk = await _load_risk(db, risk_id)
    incoming = body.model_dump(exclude_none=True)
    await _check_scale(db, user, incoming)
    policy = await _review_policy(db, user)
    effective_before = _effective_frequency(risk, policy)
    if "residual_override_reason" in incoming:
        incoming["residual_override_reason"] = incoming["residual_override_reason"].strip()
    reason = incoming.get("residual_override_reason", risk.residual_override_reason)
    _enforce_residual(
        user,
        inherent=(risk.inherent_likelihood, risk.inherent_impact),
        residual=(body.residual_likelihood, body.residual_impact),
        override_reason=reason,
        changes_scoring=_scoring_changed(risk, incoming),
    )
    _enforce_target({
        "inherent_likelihood": risk.inherent_likelihood, "inherent_impact": risk.inherent_impact,
        "residual_likelihood": body.residual_likelihood, "residual_impact": body.residual_impact,
        "target_likelihood": getattr(risk, "target_likelihood", None),
        "target_impact": getattr(risk, "target_impact", None),
    })
    decision, advance = _residual_assessment(
        risk,
        {"residual_likelihood": body.residual_likelihood, "residual_impact": body.residual_impact},
        body.assessment_rationale,
    )
    risk.residual_likelihood = body.residual_likelihood
    risk.residual_impact = body.residual_impact
    if "residual_override_reason" in incoming:
        risk.residual_override_reason = incoming["residual_override_reason"]
    _record_assessment(risk, decision, user)
    if advance:
        risk.status = RiskStatus.assessed
    _reschedule(risk, effective_before, policy, frequency_changed=False)
    cleared = risk_integrity.clear_residual_flag(risk, RESIDUAL_REVIEW_REASON)
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="assess",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Assessed residual risk for {risk.reference}"
        + ("; review flag cleared" if cleared else ""),
        changes={
            "residual_likelihood": body.residual_likelihood,
            "residual_impact": body.residual_impact,
            "override_reason": risk.residual_override_reason,
            **({"assessment_rationale": decision.rationale} if decision.rationale else {}),
        },
    )
    await _refresh_alerts(db, user, risk)
    return await _read(db, risk.id, user)


def _residual_assessment(
    risk: Risk, incoming: dict[str, object], rationale: str | None
) -> tuple[risk_integrity.Assessment, bool]:
    """The assessment-trail decision for a residual-only write (assess, accept-residual).

    A draft moves to assessed only when the assessment is complete — inherent scores
    recorded by an earlier assessment and a rationale; otherwise the residual is kept as
    a provisional draft score and the risk stays draft. Returns ``(decision, advance)``.
    """
    stored_scores = {name: getattr(risk, name) for name in risk_integrity.SCORE_FIELDS}
    common = dict(
        creating=False,
        changed=bool(risk_integrity.changed_scores(stored_scores, incoming)),
        sends_inherent=False,
        rationale=rationale,
        stored_rationale=getattr(risk, "assessment_rationale", ""),
        status_before=_status_value(getattr(risk, "status", None)),
        previously_assessed=getattr(risk, "last_assessed_at", None) is not None,
    )
    if getattr(risk, "status", None) == RiskStatus.draft:
        # A draft advances only when it could leave Draft by an edit too: scores and a
        # rationale, an owner and a business unit (F-21). Otherwise it stays a draft.
        common_leaving = dict(
            common,
            has_owner=getattr(risk, "owner_id", None) is not None,
            has_business_unit=bool(getattr(risk, "business_units", None)),
        )
        try:
            return risk_integrity.assessment_decision(status_after="assessed", **common_leaving), True
        except HTTPException:
            return risk_integrity.assessment_decision(status_after="draft", **common), False
    return risk_integrity.assessment_decision(
        status_after=_status_value(getattr(risk, "status", None)), **common
    ), False


def _record_assessment(risk: Risk, decision: risk_integrity.Assessment, user: CurrentUser) -> None:
    if decision.rationale is not None:
        risk.assessment_rationale = decision.rationale
    if decision.stamp:
        risk.last_assessed_at = datetime.now(timezone.utc)
        risk.last_assessed_by_id = user.id


@router.post(
    "/{risk_id}/review",
    response_model=RiskRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Mark a risk reviewed; reschedules the next review",
)
async def review_risk(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> RiskRead:
    """Record the periodic review of a risk — as an attestation (D-05b, one clock).

    A risk's review and its attestation are the same act, so this runs the attest call's
    own gates (independent of the owner, not a draft, approval complete — decision 6 —
    and four-eyes) and writes the attestation through
    ``attestations.record_attestation``, which alone moves ``last_review_date`` /
    ``next_review_date`` on the risk's effective cycle. One audit row, action ``review``.
    """
    from app.api.v1 import attestations
    from app.services import entity_types

    risk = await _load_risk(db, risk_id)
    found = entity_types.spec("risk")
    await attestations.enforce_attestable(db, user, "risk", risk.id, risk, found)
    await attestations.record_attestation(
        db, user, "risk", risk.id, risk,
        comment="Recorded from the risk review.",
        audit_action="review",
        audit_summary=f"Reviewed risk {risk.reference}",
    )
    return await _read(db, risk.id, user)


RESIDUAL_STILL_ABOVE_INHERENT = (
    "Residual risk is still higher than inherent risk. Lower the residual, or record an "
    "override reason, before marking this risk reviewed."
)


@router.post(
    "/{risk_id}/mark-reviewed",
    response_model=RiskRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Clear the needs-review flag once a person has looked at the risk",
)
async def mark_risk_reviewed(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> RiskRead:
    """Clear ``needs_review`` and its reasons. Refused (409) while the residual is above
    inherent with no override reason: that contradiction has to be fixed, not waved
    through. Separate from ``/review``, which reschedules the periodic review."""
    risk = await _load_risk(db, risk_id)
    if not risk.needs_review and not risk.review_reason:
        return await _read(db, risk.id, user)
    if risk_integrity.residual_exceeds_inherent(
        risk.inherent_likelihood, risk.inherent_impact,
        risk.residual_likelihood, risk.residual_impact,
    ) and not (risk.residual_override_reason or "").strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=RESIDUAL_STILL_ABOVE_INHERENT
        )
    previous = risk.review_reason
    risk.needs_review = False
    risk.review_reason = ""
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="mark_reviewed",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Marked risk {risk.reference} reviewed and cleared its review flag",
        changes={"review_reason": previous},
    )
    return await _read(db, risk.id, user)


# ------------------------------------------------------------- residual suggestion
@router.get(
    "/{risk_id}/suggested-residual",
    response_model=SuggestedResidual,
    dependencies=[Depends(require("risk:read"))],
    summary="Residual score proposed from the linked controls' effectiveness",
)
async def get_suggested_residual(
    risk_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> SuggestedResidual:
    """Compute — but never store — a residual proposal, with its reasoning.

    Read-only and always recomputed, so it reflects control effectiveness *as of now*:
    when a mitigating control's audit fails, the proposal rises again on the next read
    without anyone re-running anything.
    """
    risk = await _load_risk(db, risk_id)
    policy = await get_or_create_residual_policy(db, user.tenant_id)
    suggestion = suggest_residual(
        risk.inherent_likelihood,
        risk.inherent_impact,
        _control_inputs(risk),
        policy_spec(policy),
    )
    # The band the suggested score would fall in, judged as the recorded score is (B12).
    book = await load_appetite_book(db, user.tenant_id)
    # What accepting it relies on, and whether that needs the owner's note (B6).
    untested = await _untested_credit(db, risk, suggestion)
    return SuggestedResidual(
        likelihood=suggestion.likelihood,
        impact=suggestion.impact,
        score=suggestion.score,
        reduction=suggestion.reduction,
        rationale=suggestion.rationale,
        inherent_score=risk.inherent_score,
        current_residual_score=risk.residual_score,
        matches_current=(
            risk.residual_likelihood == suggestion.likelihood
            and risk.residual_impact == suggestion.impact
        ),
        appetite_status=book.status(suggestion.score, getattr(risk, "category_id", None)),
        credited_control_ids=list(suggestion.credited),
        note_required=bool(untested),
    )


@router.post(
    "/{risk_id}/accept-residual",
    response_model=RiskRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Adopt the suggested residual, or record a different judgement with a reason",
)
async def accept_residual(
    risk_id: uuid.UUID, body: ResidualAcceptance, db: DbSession, user: CurrentUser
) -> RiskRead:
    """Sign off the residual score.

    Sending no scores accepts the suggestion as it stands. Sending different scores is
    an override and **requires a reason** — that sentence is what an auditor reads when
    they ask why the recorded residual is lower than the control evidence supports.

    Accepting a suggestion that takes credit from a control rated by hand or by
    override, or with no reviewed test on file, **requires a note** (422 otherwise): the
    owner says why they rely on that rating. A note is appended to the stored rationale
    ("; owner's note: …") and recorded in the activity trail.
    """
    risk = await _load_risk(db, risk_id)
    policy = await get_or_create_residual_policy(db, user.tenant_id)
    suggestion = suggest_residual(
        risk.inherent_likelihood,
        risk.inherent_impact,
        _control_inputs(risk),
        policy_spec(policy),
    )
    review_policy = await _review_policy(db, user)
    effective_before = _effective_frequency(risk, review_policy)

    likelihood = body.likelihood if body.likelihood is not None else suggestion.likelihood
    impact = body.impact if body.impact is not None else suggestion.impact
    await _check_scale(
        db, user, {"residual_likelihood": likelihood, "residual_impact": impact}
    )

    is_override = (likelihood, impact) != (suggestion.likelihood, suggestion.impact)
    if is_override and not body.override_reason.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Recording {likelihood}x{impact} instead of the suggested "
                f"{suggestion.likelihood}x{suggestion.impact} needs a written reason"
            ),
        )
    # An override is the owner's own judgement and carries its own reason; accepting the
    # suggestion is relying on the credited controls' ratings, so an untested one needs
    # the owner's word on why (B6).
    note = (body.note or "").strip()
    untested = [] if is_override else await _untested_credit(db, risk, suggestion)
    if untested and not note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=UNTESTED_CREDIT_NOTE_NEEDED)

    # The suggestion never exceeds inherent, but an override can: that needs the reason
    # above *and* the right to accept risk.
    _enforce_residual(
        user,
        inherent=(risk.inherent_likelihood, risk.inherent_impact),
        residual=(likelihood, impact),
        override_reason=body.override_reason if is_override else "",
    )

    _enforce_target({
        "inherent_likelihood": risk.inherent_likelihood, "inherent_impact": risk.inherent_impact,
        "residual_likelihood": likelihood, "residual_impact": impact,
        "target_likelihood": getattr(risk, "target_likelihood", None),
        "target_impact": getattr(risk, "target_impact", None),
    })
    # The sign-off is the rationale: the owner's reason for an override, else the
    # engine's reasoning they accepted.
    rationale = (
        f"Residual {likelihood}x{impact} recorded instead of the suggested "
        f"{suggestion.likelihood}x{suggestion.impact}: {body.override_reason.strip()}"
        if is_override
        else f"Accepted the suggested residual {likelihood}x{impact}: "
        + "; ".join(str(line) for line in suggestion.rationale)
    )
    if note:
        rationale += f"; owner's note: {note}"
    decision, advance = _residual_assessment(
        risk, {"residual_likelihood": likelihood, "residual_impact": impact}, rationale
    )
    risk.residual_likelihood = likelihood
    risk.residual_impact = impact
    risk.suggested_residual_likelihood = suggestion.likelihood
    risk.suggested_residual_impact = suggestion.impact
    risk.suggested_residual_rationale = "\n".join(suggestion.rationale)
    risk.residual_override_reason = body.override_reason.strip() if is_override else ""
    risk.residual_accepted_by = user.id
    risk.residual_accepted_at = date.today()
    _record_assessment(risk, decision, user)
    if advance:
        risk.status = RiskStatus.assessed
    _reschedule(risk, effective_before, review_policy, frequency_changed=False)
    cleared = risk_integrity.clear_residual_flag(risk, RESIDUAL_REVIEW_REASON)

    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="assess",
        entity_type="risk",
        entity_id=risk.id,
        summary=(
            f"{'Overrode' if is_override else 'Accepted'} suggested residual for "
            f"{risk.reference}: {likelihood}x{impact}"
        ),
        changes={
            "residual_likelihood": likelihood,
            "residual_impact": impact,
            "suggested": f"{suggestion.likelihood}x{suggestion.impact}",
            "override_reason": risk.residual_override_reason,
            **({"note": note} if note else {}),
            **({"untested_credit": [c.reference or c.name for c in untested]} if untested else {}),
            **({"review_reason": "residual corrected; review flag cleared"} if cleared else {}),
        },
    )
    await _refresh_alerts(db, user, risk)
    return await _read(db, risk.id, user)


@router.post(
    "/{risk_id}/acceptances",
    response_model=RiskAcceptanceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("risk:write"))],
    summary="Request formal acceptance of a risk",
)
async def request_acceptance(
    risk_id: uuid.UUID, body: RiskAcceptanceCreate, db: DbSession, user: CurrentUser
) -> RiskAcceptanceRead:
    risk = await _load_risk(db, risk_id)
    refusal = risk_integrity.acceptance_refusal(
        risk.status, risk.last_assessed_at, risk.assessment_rationale
    )
    if refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refusal)
    acceptance = RiskAcceptance(
        tenant_id=user.tenant_id,
        risk_id=risk.id,
        requested_by=user.id,
        rationale=body.rationale,
        expires_at=body.expires_at,
        status=AcceptanceStatus.pending,
    )
    db.add(acceptance)
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="request_acceptance",
        entity_type="risk_acceptance",
        entity_id=acceptance.id,
        summary=f"Requested acceptance for risk {risk.reference}",
    )
    await db.refresh(acceptance)
    return RiskAcceptanceRead.model_validate(acceptance)


@router.post(
    "/{risk_id}/acceptances/{acceptance_id}/decision",
    response_model=RiskAcceptanceRead,
    dependencies=[Depends(require("risk:accept"))],
    summary="Approve or reject a pending risk acceptance",
)
async def decide_acceptance(
    risk_id: uuid.UUID,
    acceptance_id: uuid.UUID,
    body: RiskAcceptanceDecision,
    db: DbSession,
    user: CurrentUser,
) -> RiskAcceptanceRead:
    acceptance = await db.scalar(
        select(RiskAcceptance).where(
            RiskAcceptance.id == acceptance_id, RiskAcceptance.risk_id == risk_id
        )
    )
    if acceptance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Acceptance not found"
        )
    if acceptance.status != AcceptanceStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Acceptance already {acceptance.status.value}",
        )

    # Maker-checker: accepting a risk is a four-eyes control — the person who requested
    # the acceptance can never approve it. Gated by the risk's exposure (ALE) so a
    # DualControlRule threshold can scope it to material risks.
    risk = await _load_risk(db, risk_id)
    await dual_control.enforce_maker_checker(
        db,
        module="risk",
        action="accept",
        maker_id=acceptance.requested_by,
        checker_id=user.id,
        amount=float(risk.annual_loss_expectancy) if risk.annual_loss_expectancy else None,
        subject="risk acceptance",
    )

    if body.approve:
        refusal = risk_integrity.acceptance_refusal(
            risk.status, risk.last_assessed_at, risk.assessment_rationale
        )
        if refusal:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refusal)
    acceptance.approver_id = user.id
    acceptance.decided_at = date.today()
    if body.approve:
        acceptance.status = AcceptanceStatus.approved
        risk.status = RiskStatus.accepted
        risk.treatment_strategy = TreatmentStrategy.accept
        action, verb = "approve_acceptance", "Approved"
    else:
        acceptance.status = AcceptanceStatus.rejected
        action, verb = "reject_acceptance", "Rejected"

    await db.flush()
    await audit.record(
        db,
        actor=user,
        action=action,
        entity_type="risk_acceptance",
        entity_id=acceptance.id,
        summary=f"{verb} acceptance for risk {risk_id}",
        changes={"note": body.note} if body.note else {},
    )
    await db.refresh(acceptance)
    return RiskAcceptanceRead.model_validate(acceptance)


async def _read_context(db, user: CurrentUser) -> dict:
    """Validation context for ``RiskRead``: the tenant's banding (configured bands and
    cell overrides) and per-category appetite, loaded once per request."""
    settings = await get_or_create_settings(db, user.tenant_id)
    scale = scale_for(settings)
    return {
        "max_score": scale.max_score,
        "scale": scale,
        "appetite": await load_appetite_book(db, user.tenant_id, settings),
        "cadence": dict(getattr(settings, "review_cadence", None) or {}),
    }


# ------------------------------------------------------------- review cadence (F-22)
ReviewPolicy = tuple[SeverityScale, dict]


async def _review_policy(db, user: CurrentUser) -> ReviewPolicy:
    """The tenant's banding and rating-driven review cadence, for the review clock."""
    settings = await get_or_create_settings(db, user.tenant_id)
    return scale_for(settings), dict(getattr(settings, "review_cadence", None) or {})


def _effective_frequency(risk, policy: ReviewPolicy):
    """The cycle the risk's review clock runs on: the stricter of its chosen cycle and
    the longest its current rating allows (``risk_scoring.effective_review_frequency``)."""
    scale, cadence = policy
    return effective_review_frequency(
        getattr(risk, "review_frequency", None), current_severity(risk, scale), cadence
    )[0]


def _reschedule(risk, effective_before, policy: ReviewPolicy, *, frequency_changed: bool) -> None:
    """Move ``next_review_date`` as ``risk_scoring.rescheduled_review`` says, in place."""
    risk.next_review_date = rescheduled_review(
        current=getattr(risk, "next_review_date", None),
        last_review=getattr(risk, "last_review_date", None),
        effective_before=effective_before,
        effective_after=_effective_frequency(risk, policy),
        frequency_changed=frequency_changed,
    )


async def _refresh_alerts(db, user: CurrentUser, risk) -> None:
    """Bring this risk's breach and review alerts up to date now, rather than at the
    next scan: a re-score that ends a breach resolves its alert on save (F-22)."""
    await db.flush()
    await notifications.refresh_risk_alerts(db, user.tenant_id, risk.id)


async def _reconcile_title_flag(db, user: CurrentUser, risk) -> None:
    """Flag (or clear) a generated-style title that names an asset this risk doesn't link."""
    await risk_integrity.reconcile_generated_title_flags(db, [risk.id])


async def _actions_by_risk(db, risk_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[RiskTreatmentAction]]:
    out: dict[uuid.UUID, list[RiskTreatmentAction]] = {rid: [] for rid in risk_ids}
    if not risk_ids:
        return out
    rows = (
        await db.scalars(
            select(RiskTreatmentAction)
            .where(RiskTreatmentAction.risk_id.in_(list(risk_ids)))
            .order_by(
                RiskTreatmentAction.due_date.asc().nulls_last(), RiskTreatmentAction.created_at
            )
        )
    ).all()
    for row in rows:
        out.setdefault(row.risk_id, []).append(row)
    return out


async def _action_count(db, risk_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(RiskTreatmentAction)
            .where(RiskTreatmentAction.risk_id == risk_id)
        )
        or 0
    )


async def _action_reads(db, actions: Sequence[RiskTreatmentAction]) -> list[TreatmentActionRead]:
    today = date.today()
    reads = []
    for a in actions:
        read = TreatmentActionRead.model_validate(a)
        read.overdue = risk_integrity.action_is_overdue(a, today)
        reads.append(read)
    await ref_fields.fill_refs(db, list(zip(actions, reads)), ACTION_REFS)
    return reads


async def _read(db, risk_id: uuid.UUID, user: CurrentUser) -> RiskRead:
    """Reload a risk with relationships for serialization.

    The tenant's banding travels as validation context so severity chips are banded on
    the same scale (and with the same cell overrides) the heat map uses — a 4x4 register
    must not be banded as 5x5 — and each risk carries its category's appetite. The
    record read also carries its impact dimensions and treatment actions.
    """
    context = await _read_context(db, user)
    risk = await _load_risk(db, risk_id)
    read = RiskRead.model_validate(risk, context=context)
    await ref_fields.fill_refs(db, [(risk, read)], RISK_REFS)
    await _fill_hierarchy(db, [(risk, read)])
    # Each control's rating, basis and test record (B2): two queries for all of them.
    read.controls = await _assured_controls(db, risk.controls, user)
    read.control_health = (await _control_health(db, [risk]))[risk.id]
    actions = (await _actions_by_risk(db, [risk.id]))[risk.id]
    read.treatment_actions = await _action_reads(db, actions)
    read.treatment_progress = TreatmentProgress(
        **risk_integrity.treatment_progress(actions, date.today())
    )
    dims = await _stored_dimensions(db, risk.id)
    labels = await master_data.lookups_by_id(db, [d.dimension_id for d in dims])
    order = {"inherent": 0, "residual": 1, "target": 2}
    read.impact_dimensions = [
        ImpactDimensionRead(
            id=d.id, dimension_id=d.dimension_id, dimension_ref=labels.get(d.dimension_id),
            basis=d.basis, score=d.score, rationale=d.rationale or "",
        )
        for d in sorted(dims, key=lambda d: (order.get(d.basis, 9), str(d.dimension_id)))
    ]
    return read


# ------------------------------------------------------------ treatment actions
# A treatment plan as actions with owners and dates. ``treatment_description`` stays as
# the plan's summary; ``treatment_deadline`` follows the actions once there are any (the
# latest open action's due date), and the overdue alert fires per action.
async def _load_action(db, risk_id: uuid.UUID, action_id: uuid.UUID) -> RiskTreatmentAction:
    action = await db.scalar(
        select(RiskTreatmentAction).where(
            RiskTreatmentAction.id == action_id, RiskTreatmentAction.risk_id == risk_id
        )
    )
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Treatment action not found")
    return action


async def _sync_deadline(db, risk: Risk) -> date | None:
    """Re-derive the risk's treatment deadline from its actions; returns the new value."""
    actions = (await _actions_by_risk(db, [risk.id]))[risk.id]
    if actions:
        risk.treatment_deadline = risk_integrity.derive_treatment_deadline(actions)
    return risk.treatment_deadline


@router.get(
    "/{risk_id}/treatment-actions",
    response_model=list[TreatmentActionRead],
    dependencies=[Depends(require("risk:read"))],
    summary="The risk's treatment actions, earliest due first",
)
async def list_treatment_actions(risk_id: uuid.UUID, db: DbSession) -> list[TreatmentActionRead]:
    risk = await _load_risk(db, risk_id)
    return await _action_reads(db, (await _actions_by_risk(db, [risk.id]))[risk.id])


@router.post(
    "/{risk_id}/treatment-actions",
    response_model=TreatmentActionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("risk:write"))],
    summary="Add a treatment action (owner, due date, status, percent complete)",
)
async def create_treatment_action(
    risk_id: uuid.UUID, body: TreatmentActionCreate, db: DbSession, user: CurrentUser
) -> TreatmentActionRead:
    risk = await _load_risk(db, risk_id)
    data = body.model_dump()
    await ref_fields.apply_refs(db, RiskTreatmentAction, data, ACTION_REFS)
    status_value, percent = data.pop("status"), data.pop("percent_complete")
    action = RiskTreatmentAction(tenant_id=user.tenant_id, risk_id=risk.id, **data)
    action.title = action.title.strip()
    action.completed_at = None
    risk_integrity.apply_action_status(
        action, status=status_value, percent=percent, now=datetime.now(timezone.utc)
    )
    db.add(action)
    await db.flush()
    deadline = await _sync_deadline(db, risk)
    await db.flush()
    await audit.record(
        db, actor=user, action="add_treatment_action", entity_type="risk", entity_id=risk.id,
        summary=f"Added treatment action to {risk.reference}: {action.title}",
        changes={
            "action_id": str(action.id), "title": action.title, "status": action.status,
            "due_date": str(action.due_date or ""), "owner_id": str(action.owner_id or ""),
            "treatment_deadline": str(deadline or ""),
        },
    )
    return (await _action_reads(db, [action]))[0]


@router.patch(
    "/{risk_id}/treatment-actions/{action_id}",
    response_model=TreatmentActionRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Update a treatment action; done stamps completed_at",
)
async def update_treatment_action(
    risk_id: uuid.UUID,
    action_id: uuid.UUID,
    body: TreatmentActionUpdate,
    db: DbSession,
    user: CurrentUser,
) -> TreatmentActionRead:
    risk = await _load_risk(db, risk_id)
    action = await _load_action(db, risk.id, action_id)
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is None:
        data.pop("title")
    await ref_fields.apply_refs(db, RiskTreatmentAction, data, ACTION_REFS, record=action)
    status_value, percent = data.pop("status", None), data.pop("percent_complete", None)
    before = {"status": action.status, "due_date": action.due_date, "percent_complete": action.percent_complete}
    for field, value in data.items():
        setattr(action, field, value.strip() if field == "title" else value)
    risk_integrity.apply_action_status(
        action, status=status_value, percent=percent, now=datetime.now(timezone.utc)
    )
    await db.flush()
    deadline = await _sync_deadline(db, risk)
    await db.flush()
    changes = {k: str(v) for k, v in data.items()}
    for key, old in before.items():
        new = getattr(action, key)
        if new != old:
            changes[key] = f"{old} -> {new}"
    changes["treatment_deadline"] = str(deadline or "")
    await audit.record(
        db, actor=user, action="update_treatment_action", entity_type="risk", entity_id=risk.id,
        summary=f"Updated treatment action on {risk.reference}: {action.title}",
        changes={"action_id": str(action.id), **changes},
    )
    return (await _action_reads(db, [action]))[0]


@router.delete(
    "/{risk_id}/treatment-actions/{action_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("risk:write"))],
    summary="Remove a treatment action (audit-logged; cancel it instead to keep it on the plan)",
)
async def delete_treatment_action(
    risk_id: uuid.UUID, action_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> None:
    risk = await _load_risk(db, risk_id)
    action = await _load_action(db, risk.id, action_id)
    snapshot = {
        "action_id": str(action.id), "title": action.title, "status": action.status,
        "due_date": str(action.due_date or ""), "percent_complete": action.percent_complete,
    }
    await db.delete(action)
    await db.flush()
    deadline = await _sync_deadline(db, risk)
    await db.flush()
    await audit.record(
        db, actor=user, action="delete_treatment_action", entity_type="risk", entity_id=risk.id,
        summary=f"Removed treatment action from {risk.reference}: {snapshot['title']}",
        changes={**snapshot, "treatment_deadline": str(deadline or "")},
    )
