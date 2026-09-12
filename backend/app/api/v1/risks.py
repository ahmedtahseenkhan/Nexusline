"""Risk Management API — the reference module.

Covers the full lifecycle: register CRUD, inherent/residual scoring, treatment,
control/asset linkage, a risk-acceptance approval workflow with expiry, and review
scheduling.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.asset import Asset
from app.models.control import Control
from app.models.incident import Incident
from app.models.policy import Policy
from app.models.enums import (
    AcceptanceStatus,
    RiskStatus,
    TreatmentStrategy,
)
from app.models.organization import BusinessUnit, Process
from app.models.risk import Risk, RiskAcceptance, risk_assets
from app.services.risk_query import build_risk_query  # noqa: F401 - re-exported for callers
from app.models.threat import Threat, Vulnerability
from app.schemas.common import Page
from app.schemas.risk import (
    OrphanedRisk,
    OrphanedRiskPage,
    OrphanPurgeRequest,
    OrphanPurgeResult,
    ResidualAcceptance,
    RiskAcceptanceCreate,
    RiskAcceptanceDecision,
    RiskAcceptanceRead,
    RiskAssessment,
    RiskCreate,
    RiskRead,
    RiskUpdate,
    SuggestedResidual,
)
from app.db.data_repairs import RESIDUAL_REVIEW_REASON
from app.services.refs import next_reference
from app.services import audit
from app.services import delete_guard
from app.services import dual_control
from app.services import ref_fields
from app.services import risk_integrity
from app.services.residual_engine import ControlInput, suggest_residual
from app.services.risk_scoring import next_review_date
from app.services.risk_settings import (
    get_matrix_size,
    get_max_score,
    get_or_create_residual_policy,
    policy_spec,
)

router = APIRouter(prefix="/risks", tags=["risks"])

#: The risk's picked fields (phase 1): each key beside the legacy text it keeps in step
#: (``owner_id`` never had one). Reads carry ``<name>_ref``. See services.ref_fields.
RISK_REFS: tuple[ref_fields.RefField, ...] = (
    ref_fields.user("owner_id", None),
    ref_fields.user("treatment_owner_id", "treatment_owner"),
    ref_fields.lookup(Risk, "category_id", "category"),
    ref_fields.WORKFLOW_OWNER,
)


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
    relied on today — a failed audit, an overdue test or an open finding means it cannot.
    """
    from app.models.enums import AuditFindingStatus, TestResult

    out: list[ControlInput] = []
    for control in risk.controls:
        note = ""
        if control.last_audit_result == TestResult.failed:
            note = "its last audit failed"
        elif control.is_audit_overdue:
            note = "its audit is overdue"
        elif any(
            f.status not in (AuditFindingStatus.closed, AuditFindingStatus.risk_accepted)
            for f in control.audit_findings
        ):
            note = "it has an open audit finding"
        out.append(
            ControlInput(
                label=control.reference or control.name,
                effectiveness=control.effectiveness,
                healthy=not note,
                health_note=note,
            )
        )
    return out


# --------------------------------------------------------------------------- CRUD
_RISK_SORTABLE = {
    "reference": Risk.reference,
    "title": Risk.title,
    "category": Risk.category,
    "status": Risk.status,
    "inherent_score": Risk.inherent_score,
    "residual_score": Risk.residual_score,
    "next_review_date": Risk.next_review_date,
    "created_at": Risk.created_at,
}


@router.get("", response_model=Page[RiskRead], dependencies=[Depends(require("risk:read"))])
async def list_risks(
    db: DbSession,
    user: CurrentUser,
    status_filter: Annotated[RiskStatus | None, Query(alias="status")] = None,
    category: str | None = None,
    business_unit_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    treatment_owner_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    needs_review: bool | None = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RiskRead]:
    stmt: Select = build_risk_query(
        status=status_filter,
        category=category,
        business_unit_id=business_unit_id,
        process_id=process_id,
        asset_id=asset_id,
        search=search,
        owner_id=owner_id,
        treatment_owner_id=treatment_owner_id,
        category_id=category_id,
    )
    if needs_review is not None:
        stmt = stmt.where(Risk.needs_review.is_(needs_review))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _RISK_SORTABLE, default=Risk.inherent_score)
    else:
        stmt = stmt.order_by(Risk.inherent_score.desc(), Risk.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    context = {"max_score": await get_max_score(db, user.tenant_id)}
    items = [RiskRead.model_validate(r, context=context) for r in rows]
    await ref_fields.fill_refs(db, list(zip(rows, items)), RISK_REFS)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=RiskRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("risk:write"))],
)
async def create_risk(body: RiskCreate, db: DbSession, user: CurrentUser) -> RiskRead:
    await _check_scale(db, user, body.model_dump())
    _enforce_residual(
        user,
        inherent=(body.inherent_likelihood, body.inherent_impact),
        residual=(body.residual_likelihood, body.residual_impact),
        override_reason=body.residual_override_reason,
    )
    data = body.model_dump(
        exclude={
            "business_unit_ids", "process_ids", "asset_ids", "control_ids",
            "threat_ids", "vulnerability_ids", "policy_ids", "incident_ids",
        }
    )
    await ref_fields.apply_refs(db, Risk, data, RISK_REFS)
    risk = Risk(tenant_id=user.tenant_id, **data)
    risk.reference = await _next_reference(db)
    risk.business_units = await _resolve(db, BusinessUnit, body.business_unit_ids)
    risk.processes = await _resolve(db, Process, body.process_ids)
    risk.assets = await _resolve(db, Asset, body.asset_ids)
    risk.controls = await _resolve(db, Control, body.control_ids)
    risk.threats = await _resolve(db, Threat, body.threat_ids)
    risk.vulnerabilities = await _resolve(db, Vulnerability, body.vulnerability_ids)
    risk.policies = await _resolve(db, Policy, body.policy_ids)
    risk.incidents = await _resolve(db, Incident, body.incident_ids)
    risk.next_review_date = next_review_date(risk.review_frequency)

    db.add(risk)
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="create",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Created risk {risk.reference}: {risk.title}",
    )
    return await _read(db, risk.id, user)


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


@router.patch(
    "/{risk_id}", response_model=RiskRead, dependencies=[Depends(require("risk:write"))]
)
async def update_risk(
    risk_id: uuid.UUID, body: RiskUpdate, db: DbSession, user: CurrentUser
) -> RiskRead:
    risk = await _load_risk(db, risk_id)
    data = body.model_dump(exclude_unset=True)
    await _check_scale(db, user, data)
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

    await ref_fields.apply_refs(db, Risk, data, RISK_REFS, record=risk)

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

    if "review_frequency" in data:
        risk.next_review_date = next_review_date(
            risk.review_frequency, risk.last_review_date
        )
    cleared = risk_integrity.clear_residual_flag(risk, RESIDUAL_REVIEW_REASON)

    await db.flush()
    changes = {k: str(v) for k, v in data.items()}
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
    risk.residual_likelihood = body.residual_likelihood
    risk.residual_impact = body.residual_impact
    if "residual_override_reason" in incoming:
        risk.residual_override_reason = incoming["residual_override_reason"]
    if risk.status == RiskStatus.draft:
        risk.status = RiskStatus.assessed
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
        },
    )
    return await _read(db, risk.id, user)


@router.post(
    "/{risk_id}/review",
    response_model=RiskRead,
    dependencies=[Depends(require("risk:write"))],
    summary="Mark a risk reviewed; reschedules the next review",
)
async def review_risk(risk_id: uuid.UUID, db: DbSession, user: CurrentUser) -> RiskRead:
    risk = await _load_risk(db, risk_id)
    today = date.today()
    risk.last_review_date = today
    risk.next_review_date = next_review_date(risk.review_frequency, today)
    await db.flush()
    await audit.record(
        db,
        actor=user,
        action="review",
        entity_type="risk",
        entity_id=risk.id,
        summary=f"Reviewed risk {risk.reference}",
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
    """
    risk = await _load_risk(db, risk_id)
    policy = await get_or_create_residual_policy(db, user.tenant_id)
    suggestion = suggest_residual(
        risk.inherent_likelihood,
        risk.inherent_impact,
        _control_inputs(risk),
        policy_spec(policy),
    )

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

    # The suggestion never exceeds inherent, but an override can: that needs the reason
    # above *and* the right to accept risk.
    _enforce_residual(
        user,
        inherent=(risk.inherent_likelihood, risk.inherent_impact),
        residual=(likelihood, impact),
        override_reason=body.override_reason if is_override else "",
    )

    risk.residual_likelihood = likelihood
    risk.residual_impact = impact
    risk.suggested_residual_likelihood = suggestion.likelihood
    risk.suggested_residual_impact = suggestion.impact
    risk.suggested_residual_rationale = "\n".join(suggestion.rationale)
    risk.residual_override_reason = body.override_reason.strip() if is_override else ""
    risk.residual_accepted_by = user.id
    risk.residual_accepted_at = date.today()
    if risk.status == RiskStatus.draft:
        risk.status = RiskStatus.assessed
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
            **({"review_reason": "residual corrected; review flag cleared"} if cleared else {}),
        },
    )
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


async def _read(db, risk_id: uuid.UUID, user: CurrentUser) -> RiskRead:
    """Reload a risk with relationships for serialization.

    The tenant's matrix size travels as validation context so severity chips are banded
    on the same scale the heat map uses — a 4x4 register must not be banded as 5x5.
    """
    max_score = await get_max_score(db, user.tenant_id)
    risk = await _load_risk(db, risk_id)
    read = RiskRead.model_validate(risk, context={"max_score": max_score})
    await ref_fields.fill_refs(db, [(risk, read)], RISK_REFS)
    return read
