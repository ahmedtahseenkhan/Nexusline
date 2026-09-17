"""Suggested requirements for controls (D-03) — "which clauses does this control meet?"

Scoring lives in :mod:`app.services.clause_suggestions`; this router loads the tenant's
controls, asks for suggestions, and writes the links a person accepts. Suggestions are
read-only (``control:read`` + ``compliance:read``); accepting writes requirement ↔
control links and needs ``control:write``. Every accept is on the audit trail.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.control import Control
from app.schemas.compliance import (
    AcceptSuggestionsBody,
    AcceptSuggestionsResult,
    BulkAcceptBody,
    BulkAcceptResult,
    BulkSuggestBody,
    ControlSuggestionsRead,
    PendingSuggestionsRead,
    RequirementSuggestionRead,
    SuggestionFrameworkCount,
    SuggestionReviewPage,
)
from app.services import audit
from app.services import clause_suggestions as engine

router = APIRouter(tags=["controls"])

_READ = Depends(require("control:read", "compliance:read"))
_WRITE = Depends(require("control:write"))


async def _control(db, control_id: uuid.UUID) -> Control:
    control = await db.scalar(
        select(Control).where(Control.id == control_id, Control.deleted.is_(False))
    )
    if control is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Control not found")
    return control


def _read(s: engine.Suggestion) -> RequirementSuggestionRead:
    return RequirementSuggestionRead(**s.as_dict())


def _label(requirement) -> str:
    fw = requirement.framework.name if getattr(requirement, "framework", None) else ""
    return f"{requirement.reference or requirement.title}" + (f" ({fw})" if fw else "")


async def _record(db, user, control, requirements: list) -> None:
    labels = ", ".join(_label(r) for r in requirements[:8])
    more = f" and {len(requirements) - 8} more" if len(requirements) > 8 else ""
    await audit.record(
        db, actor=user, action="map_requirements", entity_type="control", entity_id=control.id,
        summary=(
            f"Linked {len(requirements)} suggested requirement(s) to "
            f"{control.reference or control.name}: {labels}{more}"
        )[:500],
        changes={"requirement_ids": [str(r.id) for r in requirements]},
    )


@router.get(
    "/controls/{control_id}/suggested-requirements",
    response_model=list[RequirementSuggestionRead],
    dependencies=[_READ],
    summary="Framework clauses this control probably meets",
)
async def suggested_requirements(
    control_id: uuid.UUID,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    min_score: Annotated[float, Query(ge=0, le=1)] = 0.2,
) -> list[RequirementSuggestionRead]:
    """Ranked clauses from the installed compliance frameworks, scored on the control's
    reference, a curated synonym table, keyword overlap, crosswalks and shared risk
    scenarios. Clauses the control already meets are left out; excluded (not
    applicable) clauses are never suggested."""
    control = await _control(db, control_id)
    found = await engine.suggest_for_controls(db, [control], limit=limit, min_score=min_score)
    return [_read(s) for s in found.get(control.id, [])]


@router.post(
    "/controls/{control_id}/suggested-requirements/accept",
    response_model=AcceptSuggestionsResult,
    dependencies=[_WRITE],
    summary="Link accepted suggested requirements to the control",
)
async def accept_suggested_requirements(
    control_id: uuid.UUID, body: AcceptSuggestionsBody, db: DbSession, user: CurrentUser,
) -> AcceptSuggestionsResult:
    control = await _control(db, control_id)
    written = await engine.link(db, [(control.id, rid) for rid in body.requirement_ids])
    if written:
        await _record(db, user, control, [r for _, r in written])
    return AcceptSuggestionsResult(linked=len(written), requirement_ids=[r.id for _, r in written])


@router.post(
    "/controls/suggest-requirements/bulk",
    response_model=list[ControlSuggestionsRead],
    dependencies=[_READ],
    summary="Suggested requirements for many controls at once",
)
async def bulk_suggest(body: BulkSuggestBody, db: DbSession) -> list[ControlSuggestionsRead]:
    ids = list(dict.fromkeys(body.control_ids))
    controls = (
        await db.scalars(select(Control).where(Control.id.in_(ids), Control.deleted.is_(False)))
    ).all()
    order = {cid: i for i, cid in enumerate(ids)}
    controls = sorted(controls, key=lambda c: order[c.id])
    found = await engine.suggest_for_controls(db, controls, limit=body.limit, min_score=body.min_score)
    return [
        ControlSuggestionsRead(
            control_id=c.id, reference=c.reference or "", name=c.name,
            suggestions=[_read(s) for s in found.get(c.id, [])],
        )
        for c in controls
    ]


@router.post(
    "/controls/suggest-requirements/bulk/accept",
    response_model=BulkAcceptResult,
    dependencies=[_WRITE],
    summary="Link accepted (control, requirement) suggestions",
)
async def bulk_accept(body: BulkAcceptBody, db: DbSession, user: CurrentUser) -> BulkAcceptResult:
    written = await engine.link(db, [(p.control_id, p.requirement_id) for p in body.pairs])
    by_control: dict = {}
    for control, requirement in written:
        by_control.setdefault(control.id, (control, []))[1].append(requirement)
    for control, requirements in by_control.values():
        await _record(db, user, control, requirements)
    return BulkAcceptResult(linked=len(written), controls=len(by_control))


# ------------------------------------------------ register-wide review (F-19)
async def _check_framework(db, framework_id: uuid.UUID | None) -> None:
    if framework_id is None:
        return
    from app.models.compliance import Framework

    found = await db.scalar(
        select(Framework.id).where(Framework.id == framework_id, Framework.deleted.is_(False))
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Framework not found")


@router.get(
    "/controls/suggest-requirements/review",
    response_model=SuggestionReviewPage,
    dependencies=[_READ],
    summary="Review suggested clauses across the whole control register, a page at a time",
)
async def review_all_suggestions(
    db: DbSession,
    scope: Annotated[str, Query(pattern="^(unmapped|all)$")] = engine.SCOPE_UNMAPPED,
    framework_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    min_score: Annotated[float, Query(ge=0, le=1)] = 0.5,
    limit: Annotated[int, Query(ge=1, le=25)] = 5,
) -> SuggestionReviewPage:
    """Every control in scope — those with no clause mapped (of ``framework_id`` when
    given) or all of them — in reference order, ``page_size`` at a time. Only controls
    with a suggestion are listed; ``next_offset`` is null on the last page. Nothing is
    linked until the pairs are accepted (``/controls/suggest-requirements/bulk/accept``)."""
    await _check_framework(db, framework_id)
    page = await engine.review_page(
        db, scope=scope, framework_id=framework_id, offset=offset, page_size=page_size,
        min_score=min_score, limit=limit,
    )
    return SuggestionReviewPage(
        **{k: v for k, v in page.items() if k not in ("groups", "frameworks")},
        groups=[
            ControlSuggestionsRead(
                control_id=c.id, reference=c.reference or "", name=c.name,
                suggestions=[_read(s) for s in kept],
            )
            for c, kept in page["groups"]
        ],
        frameworks=[SuggestionFrameworkCount(**row) for row in page["frameworks"]],
    )


@router.get(
    "/controls/suggest-requirements/pending",
    response_model=PendingSuggestionsRead,
    dependencies=[_READ],
    summary="How many unmapped controls have strong clause suggestions waiting",
)
async def pending_suggestions(db: DbSession, framework_id: uuid.UUID | None = None) -> PendingSuggestionsRead:
    await _check_framework(db, framework_id)
    return PendingSuggestionsRead(**await engine.pending_strong(db, framework_id=framework_id))
